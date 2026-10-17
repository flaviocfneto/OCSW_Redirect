"""Build the course presets for the link builder (site/presets.js).

A preset is a course name phrase that the course finder's keyword search matches.
The finder matches the phrase against course titles, so a name like
"AI for Productivity" finds every upcoming run of that course, at every level,
and a single word like "digital" finds far more than the course you meant.

Where the names come from:
  1. every course run linked from the On Course South West website (all pages in its sitemap);
  2. every course run the course finder lists right now (an empty keyword search).

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
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_JS = ROOT / "site" / "presets.js"
OUT_REPORT = ROOT / "tools" / "presets_report.md"

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
    "copy-of-health-social-care": "Health and social care",
    "healthandsocialcare": "Health and social care",
    "counselling": "Counselling",
    "creativecourses": "Creative",
    "e-learningqualifications": "Online qualifications",
    "employability": "Employability",
    "family-learning": "Family learning",
    "gcses": "English and maths",
    "languages": "Languages",
    "sendprogrammes": "SEND programmes",
    "skillsbootcamps": "Skills bootcamps",
    "wellbeing": "Wellbeing and life skills",
}
# Course code prefix -> area, for courses the website doesn't link to.
CODE_AREAS = {
    "DC": "Digital and creative",
    "HC": "Health and social care",
    "EM": "English and maths",
    "FL": "Family learning",
    "PH": "Community courses",
}
OTHER = "Other courses"

# Run code at the start of a title: "DC26T22A ", "PH26F23B-2 ", "FL26W22J - ".
CODE_RX = re.compile(r"^([A-Z]{2})\d{2}[A-Z]\d{2}[A-Z](?:-\d+)?\s*(?:-\s*)?")
# Topic prefixes OCSW puts before the course name: "Digital - ", "Family Fun: ".
TOPIC_RX = re.compile(r"^(?:Digital|Wellbeing|Employability|Life Skills|Creative Crafts|Cook it Up|"
                      r"Family [Ff]un)\s*[-:]\s*")
# Level and run markers at the end: " Beginners", " Part 2", " (Bespoke)", " L2", " Level 3 Certificate".
TAIL_RX = re.compile(r"(?:\s+(?:Beginners|Improvers|Advanced|Part\s*\d+|L\d|Level\s*\d+(?:\s+Certificate)?|"
                     r"Saltash)|\s*\([^)]*\))+\s*$", re.I)
# Qualification titles: keep the subject, so "L2 Certificate in X" and "Level 2 Certificate in X" both match.
QUAL_RX = re.compile(r"^(?:\(HCE\)\s*)?(?:AAT\s+)?(?:L(?:evel)?\s*\d\s+)?(?:Award|Certificate|Diploma)\s+in\s+", re.I)

_ctx = ssl.create_default_context()


def get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60, context=_ctx) as r:
        return r.read().decode("utf-8", "replace")


def search(kw):
    """Course titles the course finder returns for a keyword, as its own form sends it."""
    fields = [("options.Venue", "0"), ("options.KeyWord", kw), ("options.SortBy", "StartDate")]
    fields += [("days", "false")] * 7
    req = urllib.request.Request(COURSE_SITE, data=urllib.parse.urlencode(fields).encode(), headers=UA)
    with urllib.request.urlopen(req, timeout=60, context=_ctx) as r:
        page = r.read().decode("utf-8", "replace")
    return [html.unescape(t).strip() for t in re.findall(r"<h3>([^<]+)</h3>", page)]


def course_name(title):
    """'DC26T22B AI for Productivity Improvers' -> 'AI for Productivity'."""
    t = re.sub(r"\s+", " ", CODE_RX.sub("", title.strip()))
    t = TOPIC_RX.sub("", t)
    t = TAIL_RX.sub("", t)
    t = re.sub(r"\(HCE\)\s*", "", t)
    t = QUAL_RX.sub("", t)
    t = TAIL_RX.sub("", t)
    return t.strip(" -:")


def bare_title(title):
    """'DC26A11E Introduction to Customer Service Level 1' -> 'Introduction to Customer Service Level 1'."""
    return re.sub(r"\s+", " ", CODE_RX.sub("", title.strip())).strip(" -:")


def best_keyword(name, titles, first_hits):
    """Pick the keyword that finds the most runs of this course, then the fewest other courses."""
    def score(hits):
        on = [t for t in hits if course_name(t).lower() == name.lower()]
        return len(on), -(len(hits) - len(on))
    best = (score(first_hits), name, first_hits)
    if best[0][1] < 0:  # the name also matched other courses: try the full titles
        for kw in sorted({bare_title(t) for t in titles} - {name}):
            hits = _safe(search, kw) or []
            if score(hits) > best[0]:
                best = (score(hits), kw, hits)
    (on, off), kw, hits = best
    return kw, hits, on, -off


def code_area(title):
    m = CODE_RX.match(title.strip())
    return CODE_AREAS.get(m.group(1), OTHER) if m else OTHER


def site_titles():
    """{course title: website area} for every course run the OCSW website links to."""
    sitemap = get(OCSW_SITE + "sitemap.xml")
    pages = []
    for sm in re.findall(r"<loc>([^<]+)</loc>", sitemap):
        pages += [u for u in re.findall(r"<loc>([^<]+)</loc>", get(sm)) if not u.endswith(".xml")]
    links = {}
    with ThreadPoolExecutor(8) as pool:
        for url, body in zip(pages, pool.map(lambda u: _safe(get, u), pages)):
            slug = url.replace(OCSW_SITE, "").strip("/")
            for cid in re.findall(r"coursesocsw\.cognisoft\.cloud/Course/Details/(\d+)", body or ""):
                links.setdefault(cid, PAGE_AREAS.get(slug))
    titles = {}
    with ThreadPoolExecutor(8) as pool:
        ids = list(links)
        for cid, body in zip(ids, pool.map(lambda c: _safe(get, COURSE_SITE + "Course/Details/" + c), ids)):
            heads = re.findall(r"<h[12][^>]*>\s*([^<]+?)\s*<", body or "")
            # Runs that have gone redirect to the search page; skip them.
            if len(heads) > 1 and heads[0] == "Course Details":
                titles.setdefault(html.unescape(heads[1]), links[cid])
    return titles, len(pages)


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

    # course name -> (area, source titles)
    names = {}
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
    with ThreadPoolExecutor(6) as pool:
        results = dict(zip(keys, pool.map(lambda k: _safe(search, names[k][0]) or [], keys)))

    presets, dropped = [], []
    for k in keys:
        name, area, source, titles = names[k]
        if not results[k]:
            dropped.append((name, area, source))
            continue
        kw, hits, on, off = best_keyword(name, titles, results[k])
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
