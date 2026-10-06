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

## How it works

- `site/index.html` is the whole site in one file. With a search in the address it shows
  "Taking you to our course search…" and submits the form straight away. Without one it shows the demo.
- If the visitor presses Back on the results, the page sends them back to where they came from,
  so they don't get stuck in a re-submit loop.
- If JavaScript is off, the visitor gets the demo page instead of a redirect.

## Repo layout

```
site/index.html                     the redirect + demo page (published to GitHub Pages)
site/vendor/qrcode.js               QR code library (qrcode-generator 1.4.4, Kazuhiko Arase, MIT licence)
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
