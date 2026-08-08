import httpx
import pytest

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


def make_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_is_allowed_url_accepts_libretexts_https():
    assert is_allowed_url("https://eng.libretexts.org/a")
    assert is_allowed_url("https://chem.libretexts.org/b")


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
    first = cache.get("https://eng.libretexts.org/a")
    second = cache.get("https://eng.libretexts.org/a")

    assert len(calls) == 1
    assert first.blocks == second.blocks


def test_get_rejects_disallowed_url(tmp_path):
    cache = PageCache(tmp_path, make_client(lambda request: httpx.Response(200, text=HTML)))
    with pytest.raises(FetchError, match="not an allowed"):
        cache.get("https://evil.example.com/a")


def test_get_retries_on_server_error_then_succeeds(tmp_path):
    responses = [httpx.Response(503), httpx.Response(200, text=HTML)]

    def handler(request):
        return responses.pop(0)

    cache = PageCache(tmp_path, make_client(handler))
    page = cache.get("https://eng.libretexts.org/a")
    assert page.blocks
    assert responses == []


def test_get_raises_on_persistent_server_error(tmp_path):
    cache = PageCache(tmp_path, make_client(lambda request: httpx.Response(503)))
    with pytest.raises(FetchError, match="503"):
        cache.get("https://eng.libretexts.org/a")


def test_get_raises_on_not_found(tmp_path):
    cache = PageCache(tmp_path, make_client(lambda request: httpx.Response(404)))
    with pytest.raises(FetchError, match="404"):
        cache.get("https://eng.libretexts.org/a")


def test_get_enforces_size_cap(tmp_path):
    big = "<html><body><p>" + ("x" * 5000) + "</p></body></html>"
    cache = PageCache(
        tmp_path, make_client(lambda request: httpx.Response(200, text=big)), max_bytes=1000
    )
    with pytest.raises(FetchError, match="too large"):
        cache.get("https://eng.libretexts.org/a")


def test_get_follows_allowed_redirect(tmp_path):
    """Redirect to another allowed libretexts.org host succeeds."""
    def handler(request):
        if request.url == "https://eng.libretexts.org/a":
            return httpx.Response(302, headers={"location": "https://chem.libretexts.org/b"})
        return httpx.Response(200, text=HTML)

    cache = PageCache(tmp_path, make_client(handler))
    page = cache.get("https://eng.libretexts.org/a")
    assert page.blocks


def test_get_rejects_redirect_to_disallowed_host(tmp_path):
    """Redirect to a disallowed host is rejected."""
    def handler(request):
        return httpx.Response(302, headers={"location": "https://evil.example.com/x"})

    cache = PageCache(tmp_path, make_client(handler))
    with pytest.raises(FetchError, match="not allowed"):
        cache.get("https://eng.libretexts.org/a")


def test_get_rejects_redirect_to_http(tmp_path):
    """Redirect to http (non-https) is rejected."""
    def handler(request):
        return httpx.Response(302, headers={"location": "http://eng.libretexts.org/a"})

    cache = PageCache(tmp_path, make_client(handler))
    with pytest.raises(FetchError, match="not allowed"):
        cache.get("https://eng.libretexts.org/a")


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
        cache.get("https://eng.libretexts.org/a")


def test_get_rejects_redirect_without_location(tmp_path):
    """3xx response without Location header is rejected."""
    cache = PageCache(tmp_path, make_client(lambda request: httpx.Response(302)))
    with pytest.raises(FetchError, match="without Location"):
        cache.get("https://eng.libretexts.org/a")


def test_get_retries_on_transport_error_then_succeeds(tmp_path):
    """Transport errors (ConnectError, etc.) are retried and succeed on later attempt."""
    calls = []

    def handler(request):
        calls.append(request.url)
        if len(calls) < 2:
            raise httpx.ConnectError("connection failed")
        return httpx.Response(200, text=HTML)

    cache = PageCache(tmp_path, make_client(handler))
    page = cache.get("https://eng.libretexts.org/a")
    assert page.blocks
    assert len(calls) == 2


def test_get_raises_on_persistent_transport_error(tmp_path):
    """Transport errors that persist after all retries raise FetchError."""
    calls = []

    def handler(request):
        calls.append(request.url)
        raise httpx.ConnectError("connection failed")

    cache = PageCache(tmp_path, make_client(handler))
    with pytest.raises(FetchError, match="transport error"):
        cache.get("https://eng.libretexts.org/a")
    assert len(calls) == 3
