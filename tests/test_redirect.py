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

    # On the context, so tabs the page opens are covered too.
    context.route(COURSE_SITE + "**", course_finder)
    context.route(REFERRER + "**", referrer)
    yield page
    context.close()


def launch(page, base_url, query):
    page.goto(f"{base_url}?{query}")
    page.wait_for_url(COURSE_SITE)
    assert len(page.posts) == 1
    return page.posts[0]


def test_launch_skips_the_builder_scripts(page, base_url):
    """A visitor passing through downloads the page and nothing else."""
    requested = []
    page.on("request", lambda r: requested.append(r.url))
    launch(page, base_url, "kw=digital")
    assert requested == [f"{base_url}?kw=digital", COURSE_SITE]


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


def decode_qr(png_path):
    """The text in a QR code image. OpenCV sometimes misses a clean code at full size
    (it depends on the content, and so on the test server's random port), so a miss
    is retried on a smaller copy."""
    import cv2
    image = cv2.imread(str(png_path))
    detector = cv2.QRCodeDetector()
    text = detector.detectAndDecode(image)[0]
    for side in (600, 300):
        if text:
            break
        small = cv2.resize(image, (side, side), interpolation=cv2.INTER_NEAREST)
        text = detector.detectAndDecode(small)[0]
    return text


@pytest.mark.parametrize("size,colour", [("400", "#000000"), ("2000", "#2A0E42")])
def test_qr_png_download_scans_to_link(page, base_url, tmp_path, size, colour):
    page.goto(base_url)
    page.fill("#kw", "AI for Productivity")
    page.select_option("#qrSize", size)
    page.select_option("#qrColour", colour)
    link = page.input_value("#outUrl")
    assert link == f"{base_url}?kw=AI+for+Productivity"

    with page.expect_download() as info:
        page.click("#qrDownload")
    download = info.value
    assert download.suggested_filename == "ocsw-courses-ai-for-productivity.png"
    png = tmp_path / download.suggested_filename
    download.save_as(png)

    import cv2
    height, width = cv2.imread(str(png)).shape[:2]
    assert width == height and int(size) * 0.85 <= width <= int(size)
    assert decode_qr(png) == link


def test_qr_preview_follows_the_link(page, base_url):
    page.goto(base_url)
    before = page.evaluate("document.getElementById('qrCanvas').toDataURL()")
    page.fill("#kw", "Coding")
    after = page.evaluate("document.getElementById('qrCanvas').toDataURL()")
    assert before != after


def test_preset_fills_keyword(page, base_url):
    page.goto(base_url)
    assert page.is_visible("#preset")
    page.select_option("#preset", "AI for Productivity")
    assert page.input_value("#kw") == "AI for Productivity"
    assert page.input_value("#outUrl") == f"{base_url}?kw=AI+for+Productivity"
    # Typing a keyword of your own clears the preset; typing a preset's keyword selects it again.
    page.fill("#kw", "excel")
    assert page.input_value("#preset") == ""
    page.fill("#kw", "Digital Tools")
    assert page.input_value("#preset") == "Digital Tools"


def test_link_too_long_for_a_qr_code(page, base_url):
    page.goto(base_url)
    page.fill("#kw", "x" * 3000)
    assert page.input_value("#outUrl").endswith("x" * 3000)  # the link itself still works
    assert page.is_visible("#qrNote") and page.is_hidden("#qrCanvas")
    assert page.is_disabled("#qrDownload")
    page.fill("#kw", "english")
    assert page.is_visible("#qrCanvas") and page.is_hidden("#qrNote")
    assert page.is_enabled("#qrDownload")


def test_builder_works_without_the_qr_library(page, base_url):
    page.route("**/vendor/qrcode.js", lambda route: route.abort())
    page.goto(base_url)
    page.fill("#kw", "english")
    assert page.input_value("#outUrl") == f"{base_url}?kw=english"
    assert page.is_visible("#preset") and page.is_visible("#qrNote")


# ---------- hostile input ----------
# Everything a person can type or put in a link, tried as markup and as script addresses.

MARKUP = [
    '"><img src=x onerror="window.__xss=1">',
    "</pre><script>window.__xss=1</script>",
    "'><svg onload=window.__xss=1>",
    "</button></form><iframe srcdoc='<script>parent.__xss=1</script>'></iframe>",
    "&lt;img src=x onerror=window.__xss=1&gt;",
]
SCRIPT_ADDRESSES = [
    "javascript:window.__xss=1//",
    "JaVaScRiPt:window.__xss=1//",
    " javascript:window.__xss=1//",
    "java\tscript:window.__xss=1//",
    "data:text/html,<script>opener.__xss=1</script>",
    "vbscript:msgbox(1)",
    "//evil.test/x",
    "https:javascript:window.__xss=1",
    'https://ok.test/"onmouseover="window.__xss=1',
]


def assert_no_script_ran(page):
    assert page.evaluate("window.__xss") is None
    # Nothing clickable or submittable on the page points anywhere but a web address or this page.
    bad = page.evaluate("""() => [...document.querySelectorAll('a[href], form[action], [formaction], iframe, img, svg')]
        .map(e => e.tagName + ' ' + (e.href || e.action || e.formAction || e.src || ''))
        .filter(t => !/^(A|FORM) https?:\\/\\//.test(t))""")
    assert bad == []


@pytest.fixture
def no_dialogs(page):
    seen = []
    page.on("dialog", lambda d: (seen.append(d.message), d.dismiss()))
    yield
    assert seen == []


@pytest.mark.parametrize("text", MARKUP)
def test_typed_markup_stays_text(page, base_url, no_dialogs, text):
    page.goto(base_url)
    page.fill("#kw", text)
    page.fill("#label", text)
    assert_no_script_ran(page)
    # The preview button and the code box show the text as typed.
    assert page.text_content("#preview button") == text
    assert page.locator("#preview *").count() == 2 + 3 + 7  # form + button + its hidden fields
    assert page.locator("#outCode *").count() == 0
    # The button code, pasted into a page, is one form that sends the keyword unchanged.
    parsed = page.evaluate("""() => {
        const d = new DOMParser().parseFromString(document.getElementById('outCode').textContent, 'text/html');
        return { tags: [...d.body.querySelectorAll('*')].map(e => e.tagName).join(','),
                 kw: d.querySelector('[name="options.KeyWord"]').value,
                 label: d.querySelector('button').textContent,
                 action: d.querySelector('form').action };
    }""")
    assert parsed == {"tags": "FORM," + "INPUT," * 10 + "BUTTON", "kw": text, "label": text, "action": COURSE_SITE}
    # The link carries the keyword back intact.
    link = page.input_value("#outUrl")
    assert launch(page, link.split("?")[0], link.split("?", 1)[1]) == expected_body(kw=text)


@pytest.mark.parametrize("text", MARKUP)
def test_markup_in_a_link_is_sent_as_text(page, base_url, no_dialogs, text):
    from urllib.parse import quote
    body = launch(page, base_url, f"kw={quote(text)}&venue={quote(text)}&sort={quote(text)}&days={quote(text)}")
    assert body == expected_body(kw=text)


@pytest.mark.parametrize("text", MARKUP)
def test_markup_in_a_link_never_reaches_the_page(page, base_url, no_dialogs, text):
    """The redirect page, held still (its form submit is stubbed) so what it built can be inspected."""
    from urllib.parse import quote
    page.add_init_script("HTMLFormElement.prototype.submit = function () { window.__held = true; }")
    page.goto(f"{base_url}?kw={quote(text)}&venue={quote(text)}&sort={quote(text)}&days={quote(text)}")
    page.wait_for_function("window.__held")
    page.wait_for_timeout(200)  # time for an injected image or frame to fire
    assert_no_script_ran(page)
    tags = page.evaluate("[...document.querySelectorAll('#launch *')].map(e => e.tagName).join(',')")
    assert tags == "FORM,H1,P,BUTTON" + ",INPUT" * 10
    assert page.input_value("#launchForm [name='options.KeyWord']") == text


@pytest.mark.parametrize("address", SCRIPT_ADDRESSES)
def test_link_address_cannot_run_script(page, base_url, no_dialogs, address):
    page.goto(base_url)
    page.fill("#base", address)
    page.fill("#kw", "english")
    link = page.input_value("#outUrl")
    assert link.startswith(("http://", "https://"))
    if link.startswith(base_url):                      # not a web address: ignored
        assert link == f"{base_url}?kw=english"
        with page.expect_popup() as popup:
            page.click("#openUrl")
        assert popup.value.url.startswith(base_url) or popup.value.url == COURSE_SITE
    else:                                              # another web address: copy only
        assert page.is_disabled("#openUrl") and page.is_visible("#openNote")
    page.click("#searchNow")
    assert_no_script_ran(page)


def test_open_link_opens_the_link(page, base_url):
    opened = []
    page.context.on("request", lambda r: opened.append(r.url))
    page.goto(base_url)
    page.fill("#kw", "AI for Productivity")
    page.select_option("#venue", "1177")
    page.check("#days input[value='2']")
    page.check("#days input[value='4']")
    opened.clear()
    with page.expect_popup() as popup:
        page.click("#openUrl")
    popup.value.wait_for_url(COURSE_SITE)
    assert opened[0] == f"{base_url}?kw=AI+for+Productivity&venue=1177&days=2%2C4"
    assert popup.value.evaluate("window.opener") is None
    assert page.locator("form[method=get]").count() == 0   # the helper form is gone again


def test_link_address_must_be_a_web_address(page, base_url):
    page.goto(base_url)
    page.fill("#base", "javascript:alert(1)//")
    assert page.input_value("#outUrl") == f"{base_url}?kw="
    assert page.is_enabled("#openUrl") and page.is_hidden("#openNote")
    page.fill("#base", "https://www.oncoursesouthwest.co.uk/course-search?old=1")
    assert page.input_value("#outUrl") == "https://www.oncoursesouthwest.co.uk/course-search?kw="
    assert page.is_disabled("#openUrl") and page.is_visible("#openNote")
