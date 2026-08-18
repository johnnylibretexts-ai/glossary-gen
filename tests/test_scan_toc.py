import httpx
import pytest

from glossary_gen.fetch import PageCache
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


# --- Pressbooks parts -------------------------------------------------------

PB_PART = f"{PB_BOOK}part/main-body/"
PB_FRONT_WITH_PART = f"""
<h1 class="entry-title">Academic Resilience</h1>
<ol class="toc">
  <li><a href="{PB_BOOK}front-matter/welcome/">Welcome</a></li>
  <li class="toc__part"><div><a href='{PB_PART}'>Main Body</a></div>
    <ol><li><a href="{PB_BOOK}chapter/arriving/">Arriving</a></li></ol></li>
  <li><a href="{PB_BOOK}back-matter/credits/">Credits</a></li>
</ol>
"""


def _pb_routes(pages: dict[str, str]):
    """Serve one HTML body per path, 404 for anything else."""

    def handler(request):
        body = pages.get(str(request.url))
        if body is None:
            return httpx.Response(404, text="<h1>Oops! That content can't be found.</h1>")
        return httpx.Response(200, text=body)

    return _client(handler)


def _pb_discover(pages: dict[str, str], tmp_path):
    """Discover a fake book through a real `PageCache` — the path a run actually takes.

    Discovery reads the parts, and a run lends it the cache so those reads get the same
    retries, redirect validation, size cap and politeness delay as any other page. Tests
    that went through a bare client would leave that path unexercised.
    """
    client = _pb_routes(pages)
    return discover(PB_BOOK, client, PageCache(tmp_path, client))


def _pb_part_page(body: str) -> str:
    """A part page as Buckram renders it: the whole book's nav, then the part's article."""
    return f"""
    <nav><ol class="toc">
      <li><a href="{PB_BOOK}front-matter/welcome/">Welcome</a></li>
      <li><a href="{PB_BOOK}chapter/arriving/">Arriving</a></li>
      <li><a href="{PB_BOOK}back-matter/credits/">Credits</a></li>
    </ol></nav>
    <div id="content" class="site-content">
      <section class="part" data-type="part">
        <header><h1 class="entry-title">Main Body</h1></header>
        {body}
      </section>
    </div>
    """


def test_pressbooks_keeps_a_part_that_carries_its_own_introduction(tmp_path):
    """A part is usually a divider, but Pressbooks lets one carry post content — and
    when it does, that content is a chapter introduction that defines terms. Measured
    on 2026-08-17: 3 of 18 ecampusontario books have parts with content, one of them
    with 1,200-6,200 characters of prose per part. Those pages were never scanned.
    """
    _, urls = _pb_discover(
        {
            PB_BOOK: PB_FRONT_WITH_PART,
            PB_PART: _pb_part_page(
                "<p>Communication at work begins with audience, purpose and tone.</p>"
            ),
        },
        tmp_path,
    )

    assert urls == (
        f"{PB_BOOK}front-matter/welcome/",
        PB_PART,
        f"{PB_BOOK}chapter/arriving/",
        f"{PB_BOOK}back-matter/credits/",
    )


def test_pressbooks_drops_a_part_that_is_only_its_own_heading(tmp_path):
    """The common case, and the reason parts were skipped wholesale before: an empty
    part renders its title and nothing else. Scanning it is a paid call over one
    heading.
    """
    _, urls = _pb_discover({PB_BOOK: PB_FRONT_WITH_PART, PB_PART: _pb_part_page("")}, tmp_path)

    assert PB_PART not in urls
    assert urls == (
        f"{PB_BOOK}front-matter/welcome/",
        f"{PB_BOOK}chapter/arriving/",
        f"{PB_BOOK}back-matter/credits/",
    )


def test_pressbooks_drops_a_part_whose_content_is_only_its_chapter_outline(tmp_path):
    """The third shape, and the one a plain "has any text" test would wave through.
    Several books render a part's content as `Chapter Outline` plus a list of links to
    its own chapters. That is a table of contents, not an article: every line is a
    chapter title, which is exactly the shape of "a term this page defines", and the
    evidence gate cannot refuse it because the text really is on the page.
    """
    outline = f"""
    <div class="textbox"><h2>Chapter Outline</h2>
      <p><a href="{PB_BOOK}chapter/arriving/">3.1 Arriving</a><br/>
         <a href="{PB_BOOK}chapter/settling/">3.2 Settling</a></p>
    </div>
    """
    _, urls = _pb_discover({PB_BOOK: PB_FRONT_WITH_PART, PB_PART: _pb_part_page(outline)}, tmp_path)

    assert PB_PART not in urls


def test_pressbooks_takes_the_union_of_the_front_page_and_the_parts(tmp_path):
    """The front page is not guaranteed to be the whole table of contents — a theme
    that paginates it, or a book that lists chapters only under their part, returns a
    short list and says nothing. A part is fetched anyway, so reading its table of
    contents costs nothing and turns that silence into pages.

    A page the front page never listed is read after the ones it did: reading order is
    the front page's, and a page it omitted has no position there to claim.
    """
    front = f"""
    <h1 class="entry-title">Academic Resilience</h1>
    <a href="{PB_BOOK}front-matter/welcome/">Welcome</a>
    <a href='{PB_PART}'>Main Body</a>
    """
    _, urls = _pb_discover(
        {PB_BOOK: front, PB_PART: _pb_part_page("<p>An introduction.</p>")}, tmp_path
    )

    assert urls == (
        f"{PB_BOOK}front-matter/welcome/",
        PB_PART,
        f"{PB_BOOK}chapter/arriving/",
        f"{PB_BOOK}back-matter/credits/",
    )


def test_pressbooks_finds_a_part_the_front_page_left_out(tmp_path):
    """The union harvests PARTS from a part's table of contents, not only chapters, and
    that asymmetry would matter most where it hurts most. *Business Communication* is 19
    parts and no chapters at all: on a book of that shape a union that skipped parts
    would cross-check nothing.
    """
    other = f"{PB_BOOK}part/appendices/"
    front = f"""
    <h1 class="entry-title">Academic Resilience</h1>
    <a href='{PB_PART}'>Main Body</a>
    """
    part_one = f"""
    <nav><a href='{PB_PART}'>Main Body</a><a href='{other}'>Appendices</a></nav>
    <div id="content" class="site-content">
      <h1>Main Body</h1><p>An introduction.</p>
    </div>
    """
    part_two = """
    <nav></nav>
    <div id="content" class="site-content">
      <h1>Appendices</h1><p>What follows collects the reference tables.</p>
    </div>
    """
    _, urls = _pb_discover({PB_BOOK: front, PB_PART: part_one, other: part_two}, tmp_path)

    assert urls == (PB_PART, other)


def test_pressbooks_keeps_a_part_it_could_not_read(tmp_path):
    """A part that 404s or times out is one page of a book, not the book — the run goes
    on. It is KEPT rather than dropped: dropping it would decide it had no content on
    no evidence, which is the silent shortfall this whole change is about. Kept, it
    reaches `collect_pages`, which counts it in the `fetch_error` the summary prints.
    Nothing is paid for a page that never arrives.
    """
    _, urls = _pb_discover({PB_BOOK: PB_FRONT_WITH_PART}, tmp_path)  # the part itself 404s

    assert urls == (
        f"{PB_BOOK}front-matter/welcome/",
        PB_PART,
        f"{PB_BOOK}chapter/arriving/",
        f"{PB_BOOK}back-matter/credits/",
    )


def test_pressbooks_follows_a_part_that_moved(tmp_path):
    """A part linked by an old slug redirects, and reading it through the run's
    `PageCache` follows that — validated, and no further than the allowlist reaches.
    A bare client would not: httpx does not follow redirects by default, so the part
    would count as unreadable, be kept unjudged, AND lose its table of contents to the
    union. That is the worst of both branches, from a book merely having been edited.
    """
    moved = f"{PB_BOOK}part/renamed/"
    front = f"""
    <h1 class="entry-title">Academic Resilience</h1>
    <a href='{PB_PART}'>Main Body</a>
    """

    def handler(request):
        url = str(request.url)
        if url == PB_BOOK:
            return httpx.Response(200, text=front)
        if url == PB_PART:
            return httpx.Response(301, headers={"location": moved})
        return httpx.Response(200, text=_pb_part_page("<p>An introduction.</p>"))

    client = _client(handler)

    _, urls = discover(PB_BOOK, client, PageCache(tmp_path, client))

    # Judged, not merely kept: the part was read, so its content was seen AND its table
    # of contents reached the union. Unread it would still be in the list — kept on no
    # evidence — with the three pages below missing and nothing said about them.
    assert urls == (
        PB_PART,
        f"{PB_BOOK}front-matter/welcome/",
        f"{PB_BOOK}chapter/arriving/",
        f"{PB_BOOK}back-matter/credits/",
    )


def test_pressbooks_keeps_a_part_whose_template_it_does_not_recognise(tmp_path):
    """Narrowing knows one wrapper per platform. A Pressbooks theme that renders neither
    means the article cannot be told from the chrome, so the part cannot be judged and
    cannot be read for a table of contents. It is kept — the same rule as a part that
    would not load — and contributes nothing, rather than having every link on the page
    taken for a chapter.
    """
    unfamiliar = f"""
    <div class="some-other-theme">
      <h1>Main Body</h1>
      <p>An introduction.</p>
      <a href="{PB_BOOK}chapter/nowhere/">Nowhere</a>
    </div>
    """
    _, urls = _pb_discover({PB_BOOK: PB_FRONT_WITH_PART, PB_PART: unfamiliar}, tmp_path)

    assert PB_PART in urls
    assert f"{PB_BOOK}chapter/nowhere/" not in urls


def test_pressbooks_reads_each_part_once_however_often_it_is_linked():
    """Buckram links a part from its own row and again from every chapter under it in
    some themes. Fetching it twice is a wasted request; listing it twice is a page
    scanned and paid for twice. Deliberately WITHOUT a cache, so the request count
    measures the `seen` set rather than the cache in front of it.
    """
    fetched: list[str] = []

    def handler(request):
        url = str(request.url)
        fetched.append(url)
        if url == PB_BOOK:
            return httpx.Response(
                200,
                text=f"""
                <h1 class="entry-title">Academic Resilience</h1>
                <a href='{PB_PART}'>Main Body</a>
                <a href="{PB_BOOK}chapter/arriving/">Arriving</a>
                <a href='{PB_PART}'>Main Body again</a>
                """,
            )
        return httpx.Response(200, text=_pb_part_page("<p>An introduction.</p>"))

    _, urls = discover(PB_BOOK, _client(handler))

    assert fetched.count(PB_PART) == 1
    assert urls.count(PB_PART) == 1


def test_pressbooks_does_not_take_a_cross_reference_in_a_parts_prose_for_a_page(tmp_path):
    """The union comes from the part page's chrome, where the theme repeats the book's
    table of contents — not from its article, where the authors write prose. Prose
    carries cross-references to other chapters, and some of them are stale: measured on
    *Communication at Work*, reading the whole document turned up
    `chapter/6-1-1-email-address/`, which 301s to a chapter the front page had already
    listed. Kept, it would be fetched, scanned and paid for a second time under a second
    URL, and that URL would go on every term found there.
    """
    prose = f"""
    <p>Email conventions are covered in
       <a href="{PB_BOOK}chapter/6-1-1-email-address/">the addressing chapter</a>.</p>
    """
    _, urls = _pb_discover({PB_BOOK: PB_FRONT_WITH_PART, PB_PART: _pb_part_page(prose)}, tmp_path)

    assert PB_PART in urls  # prose is content: the part is a page
    assert f"{PB_BOOK}chapter/6-1-1-email-address/" not in urls
