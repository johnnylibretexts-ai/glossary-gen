import httpx
import pytest

from glossary_gen.cli import build_http_client
from glossary_gen.fetch import FetchError, PageCache, is_allowed_url, parse_page

HTML = """
<html><body>
<h2>Recursion</h2>
<p>Recursion is a technique.</p>
<p>   </p>
<script>ignored()</script>
<p>Second paragraph.</p>
</body></html>
"""


def get_page(cache, url):
    """Fetch then parse, as both entry points' `collect_pages` do.

    `PageCache` serves HTML and nothing else — it deliberately has no method that returns
    a parsed `Page`, because that would be a second route to the same bytes that skips
    narrowing the document to its article (see `PageCache.get_html`).
    """
    return parse_page(url, cache.get_html(url))


def make_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_is_allowed_url_accepts_libretexts_https():
    assert is_allowed_url("https://eng.libretexts.org/a")
    assert is_allowed_url("https://chem.libretexts.org/b")


def test_is_allowed_url_accepts_the_named_pressbooks_network():
    """One Pressbooks network was allowed by name (see
    `docs/research/2026-08-17-platform-discovery-probes.md`). Pressbooks is thousands
    of independent installs, so the entry is a host, never the platform.
    """
    assert is_allowed_url("https://ecampusontario.pressbooks.pub/languagefoundationshandbook/")


def test_is_allowed_url_rejects_hosts_that_merely_end_in_the_allowed_one():
    """The libretexts entry is a suffix because every library is a subdomain of it.
    The Pressbooks entry is one host on a network of thousands, so reusing the suffix
    mechanism hands the allowlist to anyone who registers a name ending in it —
    `notecampusontario.pressbooks.pub` — and to every other install on the network.
    """
    assert not is_allowed_url("https://notecampusontario.pressbooks.pub/a")
    assert not is_allowed_url("https://opentextbc.pressbooks.pub/a")
    assert not is_allowed_url("https://ecampusontario.pressbooks.pub.evil.com/a")


def test_is_allowed_url_rejects_other_hosts_and_schemes():
    assert not is_allowed_url("https://evil.example.com/a")
    assert not is_allowed_url("http://eng.libretexts.org/a")
    assert not is_allowed_url("file:///etc/passwd")
    assert not is_allowed_url("https://libretexts.org.evil.com/a")


def test_parse_page_keeps_headings_and_nonblank_paragraphs():
    page = parse_page("https://eng.libretexts.org/a", HTML)
    assert [(b.kind, b.text) for b in page.blocks] == [
        ("heading", "Recursion"),
        ("paragraph", "Recursion is a technique."),
        ("paragraph", "Second paragraph."),
    ]


def test_get_fetches_then_serves_from_cache(tmp_path):
    calls = []

    def handler(request):
        calls.append(request.url)
        return httpx.Response(200, text=HTML)

    cache = PageCache(tmp_path, make_client(handler))
    first = get_page(cache, "https://eng.libretexts.org/a")
    second = get_page(cache, "https://eng.libretexts.org/a")

    assert len(calls) == 1
    assert first.blocks == second.blocks


def test_get_rejects_disallowed_url(tmp_path):
    cache = PageCache(tmp_path, make_client(lambda request: httpx.Response(200, text=HTML)))
    with pytest.raises(FetchError, match="not an allowed"):
        get_page(cache, "https://evil.example.com/a")


def test_refusal_message_names_the_hosts_that_are_actually_allowed(tmp_path):
    """The refusal is the only place an operator learns what the guard permits.
    Hard-coded as "*.libretexts.org only" it stopped being true the moment a second
    host was allowed, and then described neither of them.
    """
    cache = PageCache(tmp_path, make_client(lambda request: httpx.Response(200, text=HTML)))
    with pytest.raises(FetchError, match="ecampusontario.pressbooks.pub"):
        get_page(cache, "https://evil.example.com/a")


def test_get_retries_on_server_error_then_succeeds(tmp_path):
    responses = [httpx.Response(503), httpx.Response(200, text=HTML)]

    def handler(request):
        return responses.pop(0)

    cache = PageCache(tmp_path, make_client(handler))
    page = get_page(cache, "https://eng.libretexts.org/a")
    assert page.blocks
    assert responses == []


def test_get_raises_on_persistent_server_error(tmp_path):
    cache = PageCache(tmp_path, make_client(lambda request: httpx.Response(503)))
    with pytest.raises(FetchError, match="503"):
        get_page(cache, "https://eng.libretexts.org/a")


def test_get_raises_on_not_found(tmp_path):
    cache = PageCache(tmp_path, make_client(lambda request: httpx.Response(404)))
    with pytest.raises(FetchError, match="404"):
        get_page(cache, "https://eng.libretexts.org/a")


def test_get_enforces_size_cap(tmp_path):
    big = "<html><body><p>" + ("x" * 5000) + "</p></body></html>"
    cache = PageCache(
        tmp_path, make_client(lambda request: httpx.Response(200, text=big)), max_bytes=1000
    )
    with pytest.raises(FetchError, match="too large"):
        get_page(cache, "https://eng.libretexts.org/a")


def test_get_follows_allowed_redirect(tmp_path):
    """Redirect to another allowed libretexts.org host succeeds."""

    def handler(request):
        if request.url == "https://eng.libretexts.org/a":
            return httpx.Response(302, headers={"location": "https://chem.libretexts.org/b"})
        return httpx.Response(200, text=HTML)

    cache = PageCache(tmp_path, make_client(handler))
    page = get_page(cache, "https://eng.libretexts.org/a")
    assert page.blocks


def test_get_rejects_redirect_to_disallowed_host(tmp_path):
    """Redirect to a disallowed host is rejected."""

    def handler(request):
        return httpx.Response(302, headers={"location": "https://evil.example.com/x"})

    cache = PageCache(tmp_path, make_client(handler))
    with pytest.raises(FetchError, match="not allowed"):
        get_page(cache, "https://eng.libretexts.org/a")


def test_get_rejects_redirect_to_http(tmp_path):
    """Redirect to http (non-https) is rejected."""

    def handler(request):
        return httpx.Response(302, headers={"location": "http://eng.libretexts.org/a"})

    cache = PageCache(tmp_path, make_client(handler))
    with pytest.raises(FetchError, match="not allowed"):
        get_page(cache, "https://eng.libretexts.org/a")


def test_get_rejects_redirect_chain_exceeding_limit(tmp_path):
    """Redirect chain exceeding 3 hops is rejected."""

    def handler(request):
        url = str(request.url)
        if "a" in url:
            return httpx.Response(302, headers={"location": "https://eng.libretexts.org/b"})
        if "b" in url:
            return httpx.Response(302, headers={"location": "https://chem.libretexts.org/c"})
        if "c" in url:
            return httpx.Response(302, headers={"location": "https://eng.libretexts.org/d"})
        if "d" in url:
            return httpx.Response(302, headers={"location": "https://chem.libretexts.org/e"})
        return httpx.Response(200, text=HTML)

    cache = PageCache(tmp_path, make_client(handler))
    with pytest.raises(FetchError, match="exceeded.*hops"):
        get_page(cache, "https://eng.libretexts.org/a")


def test_get_rejects_redirect_without_location(tmp_path):
    """3xx response without Location header is rejected."""
    cache = PageCache(tmp_path, make_client(lambda request: httpx.Response(302)))
    with pytest.raises(FetchError, match="without Location"):
        get_page(cache, "https://eng.libretexts.org/a")


def test_get_retries_on_transport_error_then_succeeds(tmp_path):
    """Transport errors (ConnectError, etc.) are retried and succeed on later attempt."""
    calls = []

    def handler(request):
        calls.append(request.url)
        if len(calls) < 2:
            raise httpx.ConnectError("connection failed")
        return httpx.Response(200, text=HTML)

    cache = PageCache(tmp_path, make_client(handler))
    page = get_page(cache, "https://eng.libretexts.org/a")
    assert page.blocks
    assert len(calls) == 2


def test_get_handles_non_utf8_body_without_raising(tmp_path):
    """A regression guard from the Task-4 streaming rewrite: `response.text` used to
    apply charset detection, but the manual `body.decode("utf-8")` decoded strictly
    and raised UnicodeDecodeError on any page with a Latin-1 byte, which propagated
    out of `run()` as an unhandled traceback and killed an otherwise long unattended
    run over one bad page. A non-UTF-8 body must decode (with replacement characters
    for the bad bytes) instead of raising.
    """
    # "Café" encoded as Latin-1: the 0xe9 byte is not valid standalone UTF-8.
    bad_bytes = b"<html><body><h2>Term</h2><p>Caf\xe9 is not valid UTF-8.</p></body></html>"

    def handler(request):
        return httpx.Response(200, content=bad_bytes)

    cache = PageCache(tmp_path, make_client(handler))
    page = get_page(cache, "https://eng.libretexts.org/a")

    assert page.blocks
    assert page.blocks[0].kind == "heading"
    assert page.blocks[0].text == "Term"
    paragraph_text = next(b.text for b in page.blocks if b.kind == "paragraph")
    assert "Caf" in paragraph_text
    assert "is not valid UTF-8." in paragraph_text


def test_get_serves_non_utf8_body_from_cache_without_raising(tmp_path):
    """The cache read path (`Path.read_text`) must tolerate the same bad bytes as the
    live fetch path, since the cache stores exactly what the live path decoded.
    """
    bad_bytes = b"<html><body><p>Caf\xe9 again.</p></body></html>"

    def handler(request):
        return httpx.Response(200, content=bad_bytes)

    cache = PageCache(tmp_path, make_client(handler))
    first = get_page(cache, "https://eng.libretexts.org/a")
    second = get_page(cache, "https://eng.libretexts.org/a")  # served from the on-disk cache
    assert first.blocks == second.blocks


def test_parse_page_only_ever_emits_heading_or_paragraph_kinds():
    """Guards a live hazard in excerpt.py: it gives rank-0 (top) status to any
    non-heading block following a matching heading. If parse_page ever grew a third
    kind (e.g. a future `find_all([..., "li"])` promoting list items), excerpt.py
    would silently treat list items as paragraphs and could rank them as the top
    grounding excerpt.
    """
    html = """
    <html><body>
    <h1>Title</h1>
    <h3>Subheading</h3>
    <p>A paragraph.</p>
    <ul><li>A list item that must not become a block kind of its own.</li></ul>
    <div>A div that is not extracted at all.</div>
    </body></html>
    """
    page = parse_page("https://eng.libretexts.org/a", html)
    assert page.blocks
    assert {b.kind for b in page.blocks} <= {"heading", "paragraph"}
    assert not any("list item" in b.text for b in page.blocks)


def test_get_html_returns_raw_html_and_get_still_returns_the_same_page(tmp_path):
    """`get_html` is additive: it must not change what `get()` returns."""
    cache = PageCache(tmp_path, make_client(lambda request: httpx.Response(200, text=HTML)))

    html = cache.get_html("https://eng.libretexts.org/a")
    page = get_page(cache, "https://eng.libretexts.org/a")

    assert html == HTML
    assert page.blocks == parse_page("https://eng.libretexts.org/a", HTML).blocks


def test_a_second_read_of_one_url_is_served_from_disk(tmp_path):
    """One cache file per URL: the second read must not hit the network again."""
    calls = []

    def handler(request):
        calls.append(request.url)
        return httpx.Response(200, text=HTML)

    cache = PageCache(tmp_path, make_client(handler))
    html = cache.get_html("https://eng.libretexts.org/a")
    again = cache.get_html("https://eng.libretexts.org/a")

    assert len(calls) == 1
    assert html == again == HTML


def test_get_raises_on_persistent_transport_error(tmp_path):
    """Transport errors that persist after all retries raise FetchError."""
    calls = []

    def handler(request):
        calls.append(request.url)
        raise httpx.ConnectError("connection failed")

    cache = PageCache(tmp_path, make_client(handler))
    with pytest.raises(FetchError, match="transport error"):
        get_page(cache, "https://eng.libretexts.org/a")
    assert len(calls) == 3


def test_user_agent_is_browser_shaped_and_still_names_the_tool():
    """A bare `glossary-gen/0.1 (+url)` is refused 403 by the filter in front of
    several Pressbooks installs — measured on ecampusontario and saskoer, which both
    return 200 the moment the string starts `Mozilla/5.0`. The prefix is what those
    filters look for, so the long-standing bot convention
    `Mozilla/5.0 (compatible; <name>; +<url>)` passes them while still saying who is
    asking and where to complain. Claiming outright to be Chrome buys nothing more.
    """
    ua = build_http_client().headers["User-Agent"]

    assert ua.startswith("Mozilla/5.0 (compatible;")
    assert "glossary-gen" in ua
    assert "github.com/johnnylibretexts-ai/glossary-gen" in ua


def test_the_host_a_run_was_pointed_at_is_allowed_for_that_run():
    """A person pasting a book URL is the authorisation; a link discovered mid-crawl
    is not. The standing allowlist cannot name every Pressbooks install — there are
    thousands, independently run — so a run carries the one host it was pointed at,
    and only that one.
    """
    assert is_allowed_url("https://www.saskoer.ca/basicelectricity/", host="www.saskoer.ca")


def test_a_run_scoped_host_does_not_open_the_rest_of_the_web():
    """The guard exists so a scan cannot wander off following links. Naming one host
    must widen the run by exactly that host — otherwise `--book` becomes a way to
    turn the guard off, and the first off-site link is fetched.
    """
    assert not is_allowed_url("https://evil.example.com/a", host="www.saskoer.ca")
    assert not is_allowed_url("http://www.saskoer.ca/a", host="www.saskoer.ca")
    assert not is_allowed_url("https://www.saskoer.ca.evil.com/a", host="www.saskoer.ca")
    assert not is_allowed_url("https://evil.www.saskoer.ca/a", host="www.saskoer.ca")


def test_cache_fetches_the_host_its_run_was_pointed_at(tmp_path):
    """The whole point of the run-scoped host: paste a Pressbooks book URL from an
    install nobody hardcoded, and the pages come back.
    """
    cache = PageCache(
        tmp_path,
        make_client(lambda request: httpx.Response(200, text=HTML)),
        source_host="www.saskoer.ca",
    )

    assert cache.get_html("https://www.saskoer.ca/basicelectricity/")


def test_a_run_scoped_host_still_refuses_a_redirect_off_that_host(tmp_path):
    """A run widened to one host must not follow a redirect out of it. Checking the
    URL a person typed and then trusting whatever it redirects to is the same hole
    as no guard at all.
    """

    def handler(request):
        return httpx.Response(302, headers={"location": "https://evil.example.com/x"})

    cache = PageCache(tmp_path, make_client(handler), source_host="www.saskoer.ca")
    with pytest.raises(FetchError, match="not allowed"):
        get_page(cache, "https://www.saskoer.ca/basicelectricity/")
