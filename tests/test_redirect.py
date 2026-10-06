"""End-to-end tests for the course search redirect (site/index.html).

The live course finder is never contacted: Playwright intercepts requests to it,
records the form POST and answers with a stand-in results page.

Run with:  python -m pytest -v
Set CHROMIUM_PATH to use a browser that Playwright did not install itself.
"""
import functools
import http.server
import os
import threading
from pathlib import Path
from urllib.parse import parse_qsl

import pytest
from playwright.sync_api import sync_playwright

SITE_DIR = Path(__file__).resolve().parent.parent / "site"
COURSE_SITE = "https://coursesocsw.cognisoft.cloud/"
REFERRER = "https://referrer.test/"


def expected_body(kw="", venue="0", sort="StartDate", days=()):
    """What the course finder's own form sends, in the same field order."""
    fields = [("options.Venue", venue), ("options.KeyWord", kw), ("options.SortBy", sort)]
    for d in range(1, 8):
        if d in days:
            fields.append(("days", str(d)))
        fields.append(("days", "false"))
    return fields


@pytest.fixture(scope="session")
def base_url():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(SITE_DIR))
    handler.log_message = lambda *a: None
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/"
    server.shutdown()


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.environ.get("CHROMIUM_PATH") or None)
        yield browser
        browser.close()


@pytest.fixture
def page(browser):
    """A page whose requests to the course finder are captured, not sent."""
    context = browser.new_context()
    page = context.new_page()
    page.posts = []

    def course_finder(route, request):
        if request.method == "POST":
            page.posts.append(parse_qsl(request.post_data or "", keep_blank_values=True))
        route.fulfill(status=200, content_type="text/html",
                      body="<title>Results</title><h1>Search our Courses</h1>")

    def referrer(route, request):
        route.fulfill(status=200, content_type="text/html",
                      body='<title>Instagram</title><a id="go" href="about:blank">go</a>')

    page.route(COURSE_SITE + "**", course_finder)
    page.route(REFERRER + "**", referrer)
    yield page
    context.close()


def launch(page, base_url, query):
    page.goto(f"{base_url}?{query}")
    page.wait_for_url(COURSE_SITE)
    assert len(page.posts) == 1
    return page.posts[0]


def test_keyword_search_matches_real_form(page, base_url):
    assert launch(page, base_url, "kw=security") == expected_body(kw="security")


def test_all_parameters(page, base_url):
    body = launch(page, base_url, "kw=excel&venue=961&sort=CourseTitle&days=4,2")
    assert body == expected_body(kw="excel", venue="961", sort="CourseTitle", days=(2, 4))


def test_empty_keyword_means_all_courses(page, base_url):
    assert launch(page, base_url, "kw=") == expected_body()


def test_bad_values_fall_back_to_defaults(page, base_url):
    body = launch(page, base_url, "venue=abc&sort=Nope&days=0,9,3,3")
    assert body == expected_body(days=(3,))


def test_relevance_needs_a_keyword(page, base_url):
    assert launch(page, base_url, "sort=Relevance&venue=1177") == expected_body(venue="1177")
    page.posts.clear()
    assert launch(page, base_url, "kw=maths&sort=Relevance") == expected_body(kw="maths", sort="Relevance")


def test_back_returns_to_referrer(page, base_url):
    page.goto(REFERRER)
    page.evaluate("url => { document.getElementById('go').href = url }", f"{base_url}?kw=digital")
    page.click("#go")
    page.wait_for_url(COURSE_SITE)
    page.go_back()
    page.wait_for_url(REFERRER)
    assert len(page.posts) == 1  # Back did not re-submit the search


def test_no_parameters_shows_demo(page, base_url):
    page.goto(base_url)
    assert page.is_visible("text=Build your own link")
    assert page.posts == []
    # Tiles and the link builder point back at this page.
    assert page.get_attribute(".tile >> nth=0", "href") == f"{base_url}?kw=digital"
    page.fill("#kw", "english")
    page.select_option("#venue", "1177")
    assert page.input_value("#outUrl") == f"{base_url}?kw=english&venue=1177"
