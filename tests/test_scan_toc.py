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


def test_discover_refuses_to_fetch_anything_that_is_not_https():
    """This test used to assert that any non-LibreTexts host was refused outright.
    That rule went when Pressbooks books became readable, and it was doing two jobs:
    routing, and keeping `discover` from fetching arbitrary URLs. Routing moved to
    `discover`; the second job is this. `discover` is the one place a URL a person
    typed is fetched before `PageCache`'s guard sees it, so the scheme is checked
    here or nowhere.
    """

    def handler(request):  # pragma: no cover - must never be called
        raise AssertionError("no request should be made")

    with pytest.raises(TocError, match="https"):
        discover("http://example.com/book", _client(handler))
    with pytest.raises(TocError, match="https"):
        discover("file:///etc/passwd", _client(handler))


def test_discover_fails_when_the_toc_is_empty():
    def handler(request):
        return httpx.Response(200, json={"toc": {}})

    with pytest.raises(TocError, match="no TOC"):
        discover(BOOK, _client(handler))


# --- Pressbooks -------------------------------------------------------------

PB_BOOK = "https://ecampusontario.pressbooks.pub/academicresilience/"
PB_FRONT_PAGE = """
<h1 class="section__title book-header__title">
  <span class="screen-reader-text">Book Title: </span>Academic Resilience		</h1>
<nav class="toc">
  <a href="https://ecampusontario.pressbooks.pub/academicresilience/front-matter/welcome/">Welcome</a>
  <a href="https://ecampusontario.pressbooks.pub/academicresilience/chapter/introduction/">Introduction</a>
  <a href="https://ecampusontario.pressbooks.pub/academicresilience/chapter/arriving/">Arriving</a>
  <a href="https://ecampusontario.pressbooks.pub/academicresilience/back-matter/credits/">Credits</a>
</nav>
"""


def test_pressbooks_pages_come_back_in_reading_order():
    """Pressbooks has no TOC API this tool may use — its `/wp-json/` tree is disallowed
    by the platform's default robots.txt — so the book's own front page is the table of
    contents. Order is the order the links appear, which is the order the book is read
    in, and that is what makes "the first page to define a term" mean anything.
    """
    client = _client(lambda request: httpx.Response(200, text=PB_FRONT_PAGE))

    _, urls = discover(PB_BOOK, client)

    assert urls == (
        f"{PB_BOOK}front-matter/welcome/",
        f"{PB_BOOK}chapter/introduction/",
        f"{PB_BOOK}chapter/arriving/",
        f"{PB_BOOK}back-matter/credits/",
    )


def test_pressbooks_discovery_stays_inside_the_book_it_was_given():
    """A Pressbooks front page carries network chrome: a link to the catalogue, to a
    sibling book on the same host, to the publisher. Only the pages under this book's
    own root are its pages — a network host holds thousands of books, and harvesting a
    neighbour's chapters would attribute another book's terms to this one.
    """
    html = """
    <h1 class="entry-title">Academic Resilience</h1>
    <a href="https://ecampusontario.pressbooks.pub/">All books</a>
    <a href="https://ecampusontario.pressbooks.pub/french/chapter/bonjour/">A different book</a>
    <a href="https://pressbooks.com/">Pressbooks</a>
    <a href="https://ecampusontario.pressbooks.pub/academicresilience/chapter/arriving/">Arriving</a>
    <a href="#main">Skip to content</a>
    """
    client = _client(lambda request: httpx.Response(200, text=html))

    _, urls = discover(PB_BOOK, client)

    assert urls == (f"{PB_BOOK}chapter/arriving/",)


def test_pressbooks_discovery_names_the_book_from_its_own_page():
    """The book block is written into every row of the output, so a Pressbooks book
    needs one too — titled from its page, identified by its slug on its host, rather
    than by the LibreTexts library/cover-id pair it does not have.
    """
    client = _client(lambda request: httpx.Response(200, text=PB_FRONT_PAGE))

    book, _ = discover(PB_BOOK, client)

    assert book.title == "Academic Resilience"
    assert book.book_id == "academic-resilience"
    assert book.library == "ecampusontario.pressbooks.pub"
    assert book.cover_id == "academicresilience"
    assert book.index_url == PB_BOOK


def test_pressbooks_title_drops_the_screen_reader_label():
    """Pressbooks prefixes the book heading with a visually-hidden `Book Title:` for
    screen readers. Taken as text it becomes part of the title, and then part of every
    `book_id` slug and every row of output — live books came back as
    "Book Title: Basic Electricity For Technology Programs".
    """
    client = _client(lambda request: httpx.Response(200, text=PB_FRONT_PAGE))

    book, _ = discover(PB_BOOK, client)

    assert book.title == "Academic Resilience"
