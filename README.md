# OCSW course search links

The [On Course South West course finder](https://coursesocsw.cognisoft.cloud/) only runs a search
when its form is submitted (an HTTP POST). Anything in the address bar is ignored, so a normal link
can't open a filtered list.

This repo hosts a small page that fixes that. A link carries the search in its address. The page
turns it into the same POST the course finder's own form sends, and the visitor lands on the results.
That means you can post these links on Instagram, in emails or as QR codes.

**Live site:** <https://flaviocfneto.github.io/OCSW_Redirect/>

## Link format

```
https://flaviocfneto.github.io/OCSW_Redirect/?kw=digital&venue=1177
```

| Parameter | Meaning | Example |
|-----------|---------|---------|
| `kw`    | Keyword. `kw=` on its own shows every course | `kw=excel` |
| `venue` | Venue ID from the course finder | `venue=961` (Cobourg House), `venue=1177` (Online Delivery) |
| `sort`  | `StartDate` (default), `Venue`, `Qualification`, `CourseTitle`, `Relevance` (needs `kw`) | `sort=CourseTitle` |
| `days`  | Comma list, 1 = Sunday … 7 = Saturday | `days=2,4` (Mon and Wed) |

All parameters are optional, but a link needs at least one to redirect. Bad values fall back to the
defaults rather than breaking the search.

Open the site with no parameters to get the demo page and **link builder**. It makes links,
paste-in button code and a **QR code PNG** (three sizes, black or OCSW purple) for you.

## Course presets

The link builder has a **Course preset** list: about 140 course names, grouped by subject, each one
tested on the live course finder. Pick one and it fills in the keyword.

Search with the course name, not a single word. The finder matches the keyword against titles
*and* descriptions, so `kw=digital` brings back far more than the course you meant, while
`kw=AI for Productivity` brings back every upcoming run of that course at every level (Beginners
and Improvers) and nothing else. A keyword in quotes finds nothing, so there is no exact-phrase search.

The presets come from `tools/build_presets.py`. It reads every course linked from the OCSW website
and every course the finder lists. It then cuts each title down to the course name, without the
run code, level or part number. Each name is searched on the finder. When a name also finds other
courses, the script tries the full titles and keeps the keyword that finds the most runs of the
right course. Refresh the presets each term:

```bash
python tools/build_presets.py     # needs internet access; standard library only
```

It rewrites `site/presets.js` and `tools/presets_report.md`. The report lists what each keyword
matched, the few that still find other courses, and the names it dropped because they have no
upcoming runs.

## How it works

- `site/index.html` is the whole site in one file. With a search in the address it shows
  "Taking you to our course search…" and submits the form straight away. Without one it shows the demo.
- If the visitor presses Back on the results, the page sends them back to where they came from,
  so they don't get stuck in a re-submit loop.
- If JavaScript is off, the visitor gets the demo page instead of a redirect.

## Design

The page follows the OCSW Moodle theme at its default level, 3 · balanced
(`moodle-ocsw/moodle-platform/theme/levels/ocsw_boost_bs5_3_balanced.scss`). It uses the same hex values
in the same roles:

- a deep purple (`#2A0E42`) hero and footer, each with a 3px gold (`#FCB813`) rule;
- charcoal body text, purple (`#6E268C`) links, focus rings and filled buttons that turn white on hover;
- Lexend for headings and buttons, Atkinson Hyperlegible Next for body text, Atkinson Hyperlegible Mono for code;
- 6px corners, 44px touch targets, and a gold focus ring on the purple bands.

Like Moodle, it is light only. The fonts come from Google Fonts on the demo page only. A visitor following
a search link never loads them. If the theme's palette changes, update the `:root` block in `site/index.html`.

## Repo layout

```
site/index.html                     the redirect + demo page (published to GitHub Pages)
site/vendor/qrcode.js               QR code library (qrcode-generator 1.4.4, Kazuhiko Arase, MIT licence)
site/presets.js                     course presets for the link builder (generated)
tools/build_presets.py              finds course names and tests them on the live course finder
tools/presets_report.md             what each preset matched when it was last tested (generated)
extras/wix-course-search-snippet.html  same redirect as Wix custom code, for an oncoursesouthwest.co.uk address
tests/test_redirect.py              browser tests (Playwright + pytest)
.github/workflows/pages.yml         runs the tests, then deploys site/ from the default branch
```

## One-time setup

1. In the repo on GitHub go to **Settings → Pages** and set **Source** to **GitHub Actions**.
2. Push to the default branch (or run the workflow from the **Actions** tab). The site goes live at
   the address above after a minute or two.

GitHub Pages on a free account needs the repo to be public. The page holds no secrets.

## Running the tests

```bash
pip install -r requirements-dev.txt
python -m playwright install chromium
python -m pytest -v
```

The tests never contact the live course finder. Playwright intercepts the request, checks the form
body field by field and returns a stand-in results page.

## Limits

- The course finder could change its form field names at any time, and these links would then stop
  filtering. The proper long-term fix is for Cognisoft to accept search terms in the URL.
- Single courses already have their own address, such as
  `https://coursesocsw.cognisoft.cloud/Course/Details/16256`. Link to those directly.
