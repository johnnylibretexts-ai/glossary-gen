import httpx
import pytest

from glossary_gen.scan.toc import TOC_HEADERS, TocError, discover

BOOK = "https://eng.libretexts.org/Bookshelves/CS/Python_Programming_(OpenStax)"

_TOC = {
    "toc": {
        "structured": {
            "title": "Python Programming (OpenStax)",
            "url": BOOK,
            "@id": "117469",
            "subdomain": "eng",
            "subpages": [
                {
                    "title": "1: Basics",
                    "url": f"{BOOK}/01",
                    "subpages": [{"title": "1.1: Comments", "url": f"{BOOK}/01/1.01"}],
                },
                {"title": "2: Careers", "url": f"{BOOK}/02"},
            ],
        }
    }
}


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_discover_returns_only_leaf_pages():
    def handler(request):
        return httpx.Response(200, json=_TOC)

    _, urls = discover(BOOK, _client(handler))

    assert urls == (f"{BOOK}/01/1.01", f"{BOOK}/02")


def test_discover_builds_a_complete_book_block():
    def handler(request):
        return httpx.Response(200, json=_TOC)

    book, _ = discover(BOOK, _client(handler))

    assert book.library == "eng"
    assert book.cover_id == "117469"
    assert book.book_id == "python-programming-openstax"
    assert book.title == "Python Programming (OpenStax)"
    assert book.index_url == BOOK


def test_discover_sends_all_three_required_headers():
    seen = {}

    def handler(request):
        seen.update(request.headers)
        return httpx.Response(200, json=_TOC)

    discover(BOOK, _client(handler))

    for header, value in TOC_HEADERS.items():
        assert seen[header.lower()] == value


def test_discover_explains_a_403_as_a_header_problem():
    def handler(request):
        return httpx.Response(403, text="Forbidden")

    with pytest.raises(TocError, match="Origin/Accept/User-Agent"):
        discover(BOOK, _client(handler))


def test_discover_rejects_a_non_libretexts_host():
    def handler(request):  # pragma: no cover - must never be called
        raise AssertionError("no request should be made")

    with pytest.raises(TocError, match="libretexts.org"):
        discover("https://example.com/book", _client(handler))


def test_discover_fails_when_the_toc_is_empty():
    def handler(request):
        return httpx.Response(200, json={"toc": {}})

    with pytest.raises(TocError, match="no TOC"):
        discover(BOOK, _client(handler))
