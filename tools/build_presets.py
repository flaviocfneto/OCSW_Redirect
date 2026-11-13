"""Build the course presets for the link builder (site/presets.js).

A preset is a course name phrase that the course finder's keyword search matches.
The finder matches the phrase against course titles, so a name like
"AI for Productivity" finds every upcoming run of that course, at every level,
and a single word like "digital" finds far more than the course you meant.

Where the names come from:
  1. the course guide (tools/course_guide.json), which also gives each course its pathway;
  2. every course run linked from the On Course South West website (all pages in its sitemap);
  3. every course run the course finder lists right now (an empty keyword search).

Each title is cut down to its course name (no run code, level suffix or part number),
then searched on the live course finder. The finder also searches course descriptions,
so a name can pull in other courses ("Bookkeeping" also finds Business Administration).
When that happens the script also tries each full title as the keyword and keeps the one
that finds the most runs of this course, then the fewest others.

Names with at least one upcoming run become presets; tools/presets_report.md lists what
each keyword matched, which ones still pull in other courses, and what was dropped.

Run from the repo root (needs internet access, standard library only):
    python tools/build_presets.py
"""
import html
import json
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_JS = ROOT / "site" / "presets.js"
OUT_REPORT = ROOT / "tools" / "presets_report.md"
GUIDE = ROOT / "tools" / "course_guide.json"

OCSW_SITE = "https://www.oncoursesouthwest.co.uk/"
COURSE_SITE = "https://coursesocsw.cognisoft.cloud/"
UA = {"User-Agent": "Mozilla/5.0 (OCSW_Redirect preset builder)"}

# OCSW website page -> subject area shown in the link builder.
PAGE_AREAS = {
    "digital": "Digital (community)",
    "digitaltraining": "Digital and creative",
    "accountancy": "Accountancy and bookkeeping",
    "businessandcustomerservice": "Business and customer service",
    "childcareandeducation": "Childcare and education",
    "healthandsocialcare": "Health and social care",
    "counselling": "Counselling",
    "creativecourses": "Creative",
    "e-learningqualifications": "Online qualifications",
    "employability": "Employability",
    "family-learning": "Family learning",
    "gcses": "English and maths",
    "general-4": "Cookery",
    "languages": "Languages",
    "sendprogrammes": "SEND programmes",
    "skillsbootcamps": "Skills bootcamps",
    "volunteering": "Employability",
    "wellbeing": "Wellbeing and life skills",
}
# A page that lists courses from every subject. A course also linked from a subject page takes that subject.
GENERAL_PAGES = {"e-learningqualifications"}
# Words in a course name -> area, for courses the website doesn't link to. First match wins.
NAME_AREAS = [
    (r"Skills Bootcamp", "Skills bootcamps"),
    (r"\bAAT\b|Accounting|Bookkeeping", "Accountancy and bookkeeping"),
    (r"Functional Skills|\bGCSE", "English and maths"),
    (r"Counselling", "Counselling"),
    (r"Child ?[Cc]are|Children|Schools|Teaching", "Childcare and education"),
]
# Course code prefix -> area, for courses the website doesn't link to.
CODE_AREAS = {
    "DC": "Digital and creative",
    "HC": "Health and social care",
    "EM": "English and maths",
    "FL": "Family learning",
    "PH": "Community courses",
}
OTHER = "Other courses"

# Run code at the start of a title: "DC26T22A ", "PH26F23B-2 ", "FL26W22J - ", then any "(C) " marker.
CODE_RX = re.compile(r"^(?:([A-Z]{2})\d{2}[A-Z]\d{2}[A-Z](?:-\d+)?\s*(?:-\s*)?)?(?:\([A-Z]\)\s*)?")
# Slips in the course finder's titles: a first word typed twice ("3D 3D Modelling"), and the
# programme added after the name ("Christmas Craft - Family Learning").
DOUBLED_RX = re.compile(r"^(\w+)\s+\1\b")
PROGRAMME_RX = re.compile(r" ?- ?Family Learning$", re.I)  # runs on titles with single spaces, already trimmed
# Topic prefixes OCSW puts before the course name: "Digital - ", "Family Fun: ".
TOPIC_RX = re.compile(r"^(?:Digital|Wellbeing|Employability|Life Skills|Creative Crafts|Cook it Up|"
                      r"Family [Ff]un)\s*[-:]\s*")
# Level and run markers at the end: " Beginners", " Part 2", " (Bespoke)", " L2", " Level 3 Certificate".
TAIL_RX = re.compile(r"(?:\s+(?:Beginners|Improvers|Advanced|Part\s*\d+|L\d|Level\s*\d+(?:\s+Certificate)?|"
                     r"Saltash)|\s*\([^)]*\))+\s*$", re.I)
# Qualification titles: keep the subject, so "L2 Certificate in X" and "Level 2 Certificate in X" both match.
# The awarding body and "the" go too: "NCFE Level 2 Certificate in the Principles of X" is "Principles of X".
QUAL_RX = re.compile(r"^(?:\(HCE\)\s*)?(?:(?:AAT|NCFE)\s+)?(?:L(?:evel)?\s*\d\s+)?(?:Award|Certificate|Diploma)\s+in\s+"
                     r"(?:the\s+)?", re.I)

_ctx = ssl.create_default_context()


TRIES = 3  # per request; a network blip or a busy server gets another go


def fetch(url, data=None):
    """The page at url as text. Retries timeouts, dropped connections and server errors."""
    for attempt in range(1, TRIES + 1):
        try:
            req = urllib.request.Request(url, data=data, headers=UA)
            with urllib.request.urlopen(req, timeout=60, context=_ctx) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if attempt == TRIES or (e.code < 500 and e.code != 429):  # a 404 stays a 404
                raise
        except OSError:  # URLError, timeouts, resets
            if attempt == TRIES:
                raise
        time.sleep(2 ** attempt)


def get(url):
    return fetch(url)


@lru_cache(maxsize=None)
def _search(kw):
    fields = [("options.Venue", "0"), ("options.KeyWord", kw), ("options.SortBy", "StartDate")]
    fields += [("days", "false")] * 7
    page = fetch(COURSE_SITE, urllib.parse.urlencode(fields).encode())
    return tuple(html.unescape(t).strip() for t in re.findall(r"<h3>([^<]+)</h3>", page))


def search(kw):
    """Course titles the course finder returns for a keyword, as its own form sends it.

    Each keyword is asked for once per build: full titles are often tried for several courses.
    """
    return list(_search(kw))


def course_name(title):
    """'DC26T22B AI for Productivity Improvers' -> 'AI for Productivity'."""
    t = bare_title(title)
    t = PROGRAMME_RX.sub("", t)
    t = TOPIC_RX.sub("", t)
    t = TAIL_RX.sub("", t)
    t = re.sub(r"\(HCE\)\s*", "", t)
    t = QUAL_RX.sub("", t)
    t = TAIL_RX.sub("", t)
    return t.strip(" -:")


def bare_title(title):
    """'DC26A11E Introduction to Customer Service Level 1' -> 'Introduction to Customer Service Level 1'."""
    return DOUBLED_RX.sub(r"\1", re.sub(r"\s+", " ", CODE_RX.sub("", title.strip())).strip(" -:"))


def best_keyword(name, titles, first_hits):
    """Pick the keyword that finds the most runs of this course, then the fewest other courses."""
    def score(hits):
        on = [t for t in hits if course_name(t).lower() == name.lower()]
        return len(on), -(len(hits) - len(on))
    best = (score(first_hits), name, first_hits)
    if best[0][1] < 0:  # the name also matched other courses: try the full titles
        for kw in sorted({bare_title(t) for t in titles} - {name}):
            hits = _safe(search, kw)
            if hits and score(hits) > best[0]:
                best = (score(hits), kw, hits)
    (on, off), kw, hits = best
    return kw, hits, on, -off


def code_area(title):
    """Area for a course the website doesn't link to: from words in its name, else from its run code."""
    for pattern, area in NAME_AREAS:
        if re.search(pattern, title):
            return area
    return CODE_AREAS.get(CODE_RX.match(title.strip()).group(1), OTHER)


def page_area(slugs, linked):
    """Area for a course linked from these website pages; linked[slug] = how many courses that page links to.

    A subject page beats a general list, then the page with the fewest courses (the most specific) wins.
    """
    known = [s for s in slugs if s in PAGE_AREAS]
    if not known:
        return None
    return PAGE_AREAS[min(known, key=lambda s: (s in GENERAL_PAGES, linked[s], known.index(s)))]


def site_titles():
    """{course title: website area} for every course run the OCSW website links to."""
    sitemap = get(OCSW_SITE + "sitemap.xml")
    pages = []
    for sm in re.findall(r"<loc>([^<]+)</loc>", sitemap):
        pages += [u for u in re.findall(r"<loc>([^<]+)</loc>", get(sm)) if not u.endswith(".xml")]
    links = {}  # course id -> the pages that link to it
    with ThreadPoolExecutor(8) as pool:
        for url, body in zip(pages, pool.map(lambda u: _safe(get, u), pages)):
            slug = url.replace(OCSW_SITE, "").strip("/")
            for cid in set(re.findall(r"coursesocsw\.cognisoft\.cloud/Course/Details/(\d+)", body or "")):
                links.setdefault(cid, []).append(slug)
    live = {}  # course id -> title, for runs that are still on the course finder
    with ThreadPoolExecutor(8) as pool:
        ids = list(links)
        for cid, body in zip(ids, pool.map(lambda c: _safe(get, COURSE_SITE + "Course/Details/" + c), ids)):
            # Linear-time pattern (no overlapping \s* and [^<]+); the trimming is done by strip().
            heads = [h.strip() for h in re.findall(r"<h[12][^<>]*>([^<]+)<", body or "")]
            # Runs that have gone redirect to the search page; skip them.
            if len(heads) > 1 and heads[0] == "Course Details":
                live[cid] = html.unescape(heads[1])
    linked = {}
    for cid in live:
        for slug in links[cid]:
            linked[slug] = linked.get(slug, 0) + 1
    titles = {}
    for cid, title in live.items():
        titles.setdefault(title, page_area(links[cid], linked))
    return titles, len(pages)


def guide_titles():
    """{course title: pathway} from the course guide, or {} if there is no guide file."""
    if not GUIDE.exists():
        return {}
    guide = json.loads(GUIDE.read_text(encoding="utf-8"))
    return {title: pathway for pathway, titles in guide["pathways"].items() for title in titles}


def _safe(fn, arg):
    try:
        return fn(arg)
    except Exception as e:  # one bad page shouldn't stop the build
        print(f"  skipped {arg}: {e}", file=sys.stderr)
        return None


def main():
    print("Reading the OCSW website...")
    from_site, n_pages = site_titles()
    print(f"  {n_pages} pages, {len(from_site)} linked course runs still live")
    print("Reading the course finder's full list...")
    listed = search("")
    print(f"  {len(listed)} upcoming runs")

    from_guide = guide_titles()
    print(f"  {len(from_guide)} courses in the course guide")

    # course name -> (area, source titles). The guide goes first, so its pathway is the course's area.
    names = {}
    for title, pathway in from_guide.items():
        n = course_name(title)
        if n:
            names.setdefault(n.lower(), [n, pathway, "course guide", set()])[3].add(title)
    for title, area in from_site.items():
        n = course_name(title)
        if n:
            names.setdefault(n.lower(), [n, area or code_area(title), "website", set()])[3].add(title)
    for title in listed:
        n = course_name(title)
        if n:
            names.setdefault(n.lower(), [n, code_area(title), "course finder", set()])[3].add(title)

    print(f"Testing {len(names)} course names on the course finder...")
    keys = sorted(names)
    def test(k):
        """None if the search failed, [] if the name finds nothing, else the best keyword for it."""
        hits = _safe(search, names[k][0])
        return hits and best_keyword(names[k][0], names[k][3], hits)

    with ThreadPoolExecutor(6) as pool:
        results = dict(zip(keys, pool.map(test, keys)))

    # A search that failed is not a course with no runs. Stop before the presets shrink by mistake.
    failed = [names[k][0] for k in keys if results[k] is None]
    if failed:
        sys.exit(f"{len(failed)} course names could not be tested ({', '.join(failed[:5])}"
                 f"{', ...' if len(failed) > 5 else ''}). Nothing was written; run the build again.")

    presets, dropped = [], []
    for k in keys:
        name, area, source, titles = names[k]
        if not results[k]:
            dropped.append((name, area, source))
            continue
        kw, hits, on, off = results[k]
        if source == "course guide" and not on:
            # In the guide but not on the course finder yet: the hits are other courses that mention it.
            dropped.append((name, area, source))
            continue
        presets.append({"name": name, "kw": kw, "area": area, "runs": on or len(hits), "others": off,
                        "matches": sorted(set(hits))})

    presets.sort(key=lambda p: (p["area"], p["name"].lower()))
    today = date.today().isoformat()
    data = [{k: p[k] for k in ("name", "kw", "area", "runs", "others")} for p in presets]
    OUT_JS.write_text(
        "// Course presets for the link builder. Generated by tools/build_presets.py; don't edit by hand.\n"
        f"// Each kw was tested on the live course finder on {today}: runs = upcoming runs of this course it\n"
        "// found then, others = runs of other courses it also found (the finder searches descriptions too).\n"
        f"window.OCSW_PRESETS = {{ tested: {json.dumps(today)}, presets: "
        + json.dumps(data, indent=1, ensure_ascii=False) + " };\n",
        encoding="utf-8")

    noisy = [p for p in presets if p["others"]]
    lines = [f"# Course presets report ({today})", "",
             f"Generated by `tools/build_presets.py`. {len(presets)} presets kept, {len(dropped)} names dropped, "
             f"{len(noisy)} keywords still also find other courses.", "",
             "The course finder searches course descriptions as well as titles, and has no exact-phrase",
             "search (a keyword in quotes finds nothing). So some keywords below also find other courses.", "",
             "## Kept: keyword, upcoming runs, and the titles it matched", ""]
    for p in presets:
        extra = f", also finds {p['others']} other" if p["others"] else ""
        named = "" if p["kw"] == p["name"] else f" for {p['name']}"
        lines.append(f"- **{p['kw']}**{named} ({p['area']}, {p['runs']} runs{extra}): " + "; ".join(p["matches"]))
    lines += ["", "## Dropped: no upcoming runs found for this name", ""]
    lines += [f"- {n} ({a}, from the {s})" for n, a, s in dropped]
    OUT_REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"Wrote {len(presets)} presets to {OUT_JS.relative_to(ROOT)}; "
          f"{len(dropped)} dropped, see {OUT_REPORT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
