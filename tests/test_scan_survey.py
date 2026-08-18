"""Screening books for an author glossary before spending anything on them."""

import httpx
import pytest

from glossary_gen.fetch import PageCache
from glossary_gen.scan.survey import (
    evenly_spaced,
    network_books,
    screen,
    shelf_books,
    survey_pages,
)
from glossary_gen.scan.toc import TocError

GLOSSARY_OF = "<h2>Glossary</h2><dl><dt>%s</dt><dd>%s</dd></dl>"


def test_a_sample_spans_the_whole_book():
    """Glossary blocks sit in chapters, not front matter. A sample taken off the top
    would screen a book on its title page and licensing notice.

    The properties are asserted rather than one exact list of indices: which side of
    a half-step a middle item lands on is arbitrary, and pinning it would make a
    harmless rounding change look like a regression.
    """
    pages = list(range(100))

    sample = evenly_spaced(pages, 5)

    assert len(sample) == 5
    assert (sample[0], sample[-1]) == (0, 99)
    assert sample == sorted(set(sample))
    gaps = [b - a for a, b in zip(sample, sample[1:], strict=False)]
    assert max(gaps) - min(gaps) <= 1


def test_a_sample_larger_than_the_book_is_the_whole_book():
    assert evenly_spaced(["a", "b"], 10) == ["a", "b"]


def test_an_empty_book_samples_to_nothing():
    assert evenly_spaced([], 5) == []


def test_shelf_books_are_the_shelf_s_immediate_children():
    root = {
        "title": "Introductory Statistics",
        "url": "https://stats.libretexts.org/Bookshelves/Introductory_Statistics",
        "subpages": [
            {"title": "Introductory Statistics 1e (OpenStax)", "url": "https://x/1e"},
            {"title": "OpenIntro Statistics", "url": "https://x/openintro"},
        ],
    }

    assert shelf_books(root) == [
        ("Introductory Statistics 1e (OpenStax)", "https://x/1e"),
        ("OpenIntro Statistics", "https://x/openintro"),
    ]


def test_a_shelf_child_without_a_url_is_skipped():
    root = {"subpages": [{"title": "Broken"}, {"title": "Fine", "url": "https://x/fine"}]}

    assert shelf_books(root) == [("Fine", "https://x/fine")]


def test_survey_counts_pages_carrying_a_glossary_not_pages_fetched():
    pages = [
        ("https://x/1", GLOSSARY_OF % ("Average", "a central tendency")),
        ("https://x/2", "<h2>Chapter Summary</h2><p>nothing here</p>"),
        ("https://x/3", GLOSSARY_OF % ("Median", "the middle value")),
    ]

    result = survey_pages(pages)

    assert (result.sampled, result.with_glossary, result.terms) == (3, 2, 2)


def test_survey_counts_a_term_once_across_pages():
    pages = [
        ("https://x/1", GLOSSARY_OF % ("Average", "a central tendency")),
        ("https://x/9", GLOSSARY_OF % ("Average", "restated later")),
    ]

    assert survey_pages(pages).terms == 1


# --- Pressbooks -------------------------------------------------------------

NETWORK = "https://ecampusontario.pressbooks.pub"
PB_BOOK = f"{NETWORK}/screentest/"
PB_GLOSSARY_PAGE = f"{PB_BOOK}back-matter/glossary/"
PB_FRONT_PAGE = f"""
<h1 class="entry-title">Screen Test</h1>
<a href="{PB_BOOK}front-matter/preface/">Preface</a>
<a href="{PB_BOOK}chapter/one/">One</a>
<a href="{PB_BOOK}chapter/two/">Two</a>
"""
PB_INLINE_TERM = (
    '<a class="glossary-term" href="#term_27_447">welcome booth</a>'
    '<template id="term_27_447"><div class="glossary__definition">'
    "<p>A kiosk at the airport.</p></div></template>"
)


def _pressbooks_network(pages, per_page=10):
    """A `books` listing that pages, and refuses a `per_page` above the API's cap."""

    def handler(request):
        assert request.url.path == "/wp-json/pressbooks/v2/books"
        asked = int(request.url.params.get("per_page", 10))
        if asked > per_page:
            return httpx.Response(400, json={"code": "rest_invalid_param"})
        number = int(request.url.params.get("page", 1))
        body = pages[number - 1] if 0 < number <= len(pages) else []
        return httpx.Response(
            200,
            json=body,
            headers={
                "x-wp-total": str(sum(len(page) for page in pages)),
                "x-wp-totalpages": str(len(pages)),
            },
        )

    return handler


def _listing(*slugs):
    return [
        {"id": i, "link": f"{NETWORK}/{slug}/", "metadata": {"name": f"{slug.title()} "}}
        for i, slug in enumerate(slugs, start=1)
    ]


def test_network_books_reads_the_one_api_path_robots_allows():
    """Every per-book `/*/wp-json/` path is disallowed; the network listing is not."""
    client = httpx.Client(transport=httpx.MockTransport(_pressbooks_network([_listing("alpha")])))

    assert network_books(NETWORK, client).books == [("Alpha", f"{NETWORK}/alpha/")]


def test_network_books_pages_because_per_page_caps_at_ten():
    """`per_page=12` is answered `400 rest_invalid_param` — a cap, not a clamp."""
    pages = [_listing(*[f"b{n}" for n in range(i * 10, i * 10 + 10)]) for i in range(3)]
    client = httpx.Client(transport=httpx.MockTransport(_pressbooks_network(pages)))

    books = network_books(NETWORK, client).books

    assert len(books) == 30
    assert books[0][1] == f"{NETWORK}/b0/"
    assert books[-1][1] == f"{NETWORK}/b29/"


def test_a_limited_sweep_spreads_across_the_catalogue():
    """Taking the first N books would sample the oldest, which predate the glossary
    feature entirely. The listing pages are spread instead, first and last included.
    """
    pages = [_listing(*[f"b{n}" for n in range(i * 10, i * 10 + 10)]) for i in range(100)]
    client = httpx.Client(transport=httpx.MockTransport(_pressbooks_network(pages)))

    books = network_books(NETWORK, client, limit=40).books

    assert len(books) == 40
    assert books[0][1] == f"{NETWORK}/b0/"
    assert books[-1][1] == f"{NETWORK}/b999/"


def test_a_network_url_that_is_not_https_is_refused():
    def handler(request):  # pragma: no cover - must never be called
        raise AssertionError("no request should be made")

    client = httpx.Client(transport=httpx.MockTransport(handler))

    with pytest.raises(TocError, match="https"):
        network_books("http://ecampusontario.pressbooks.pub", client)


def _screen_client(routes):
    """A client whose `routes` map a URL to HTML, and 404 anything else."""
    seen: list[str] = []

    def handler(request):
        url = str(request.url)
        seen.append(url)
        if url in routes:
            return httpx.Response(200, text=routes[url])
        return httpx.Response(404, text="Not Found")

    return httpx.Client(transport=httpx.MockTransport(handler)), seen


def _screen(routes, tmp_path, url=PB_BOOK, **kwargs):
    client, seen = _screen_client(routes)
    cache = PageCache(tmp_path, client, source_host="ecampusontario.pressbooks.pub")
    return screen(url, client, cache, **kwargs), seen


def test_a_glossary_page_settles_a_carrier_in_one_request(tmp_path):
    """The whole point of screening Pressbooks separately: a book that published a
    glossary is answered by fetching it, not by reading the book around it.
    """
    routes = {PB_GLOSSARY_PAGE: GLOSSARY_OF % ("Affix", "a bound morpheme")}

    result, seen = _screen(routes, tmp_path)

    assert (result.result.terms, result.result.settled) == (1, True)
    assert seen == [PB_GLOSSARY_PAGE]


def test_the_walk_stops_at_the_first_page_carrying_a_term(tmp_path):
    """7 of 11 measured carriers have no glossary page and define terms inline. A hit
    is proof, so there is nothing left to settle once one page carries a term.
    """
    routes = {
        PB_BOOK: PB_FRONT_PAGE,
        f"{PB_BOOK}front-matter/preface/": "<p>nothing here</p>",
        f"{PB_BOOK}chapter/one/": f"<p>{PB_INLINE_TERM}</p>",
        f"{PB_BOOK}chapter/two/": f"<p>{PB_INLINE_TERM}</p>",
    }

    result, seen = _screen(routes, tmp_path)

    assert (result.result.terms, result.result.settled) == (1, True)
    assert result.result.sampled == 2
    assert result.pages == 3
    assert f"{PB_BOOK}chapter/two/" not in seen


def test_a_book_with_no_glossary_is_read_to_the_end_and_its_zero_is_settled(tmp_path):
    """The claim the LibreTexts survey cannot make: this zero is a zero, not
    "no evidence at 24 pages".
    """
    routes = {
        PB_BOOK: PB_FRONT_PAGE,
        f"{PB_BOOK}front-matter/preface/": "<p>nothing here</p>",
        f"{PB_BOOK}chapter/one/": "<p>nor here</p>",
        f"{PB_BOOK}chapter/two/": "<p>nor here</p>",
    }

    result, _ = _screen(routes, tmp_path)

    assert (result.result.terms, result.result.settled) == (0, True)
    assert (result.result.sampled, result.pages) == (3, 3)
    assert result.spans_book


def test_a_glossary_page_under_another_title_is_still_found_by_the_walk(tmp_path):
    """The canonical URL is an optimisation, never the only route. A book whose
    glossary page is titled `Glossaire` 404s the fast path and is found anyway.
    """
    front = PB_FRONT_PAGE + f'<a href="{PB_BOOK}back-matter/glossaire/">Glossaire</a>'
    routes = {
        PB_BOOK: front,
        f"{PB_BOOK}front-matter/preface/": "<p>nothing here</p>",
        f"{PB_BOOK}chapter/one/": "<p>nor here</p>",
        f"{PB_BOOK}chapter/two/": "<p>nor here</p>",
        f"{PB_BOOK}back-matter/glossaire/": GLOSSARY_OF % ("Affixe", "un morphème lié"),
    }

    result, _ = _screen(routes, tmp_path)

    assert (result.result.terms, result.result.settled) == (1, True)


def test_a_page_that_will_not_load_leaves_a_zero_unsettled(tmp_path):
    """A book read short is not a book without a glossary."""
    routes = {
        PB_BOOK: PB_FRONT_PAGE,
        f"{PB_BOOK}front-matter/preface/": "<p>nothing here</p>",
        f"{PB_BOOK}chapter/one/": "<p>nor here</p>",
    }

    result, _ = _screen(routes, tmp_path)

    assert (result.result.terms, result.result.settled) == (0, False)


def test_a_libretexts_book_is_screened_on_a_sample_and_its_zero_is_not_settled(tmp_path):
    """Routing is by host, as `discover`'s is. The LibreTexts screen keeps its caveat:
    there is no cheap exact test there, so a zero stays "no evidence at N pages".
    """
    book = "https://stats.libretexts.org/Bookshelves/Book"
    toc = {
        "toc": {
            "structured": {
                "title": "Book",
                "url": book,
                "subdomain": "stats",
                "subpages": [{"title": str(n), "url": f"{book}/{n}"} for n in range(10)],
            }
        }
    }

    def handler(request):
        if "api.libretexts.org" in str(request.url):
            return httpx.Response(200, json=toc)
        return httpx.Response(200, text="<p>nothing here</p>")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    cache = PageCache(tmp_path, client)

    result = screen(book, client, cache, sample=4)

    assert (result.result.sampled, result.pages) == (4, 10)
    assert (result.result.terms, result.result.settled) == (0, False)
    assert result.spans_book


def test_a_gap_in_the_walk_does_not_disqualify_the_pages_that_did_arrive(tmp_path):
    """`settled` and `spans_book` answer different questions, and one page 404ing
    separates them: the zero stops being proof, but 27 pages spread across a 28-page
    book are still what a per-page forecast is measured from. Met in a live sweep —
    a book read 27 of 28 pages reported no cost at all.
    """
    routes = {
        PB_BOOK: PB_FRONT_PAGE,
        f"{PB_BOOK}front-matter/preface/": "<p>nothing here</p>",
        f"{PB_BOOK}chapter/one/": "<p>nor here</p>",
    }

    result, _ = _screen(routes, tmp_path)

    assert not result.result.settled
    assert result.spans_book


def test_a_limited_sweep_returns_the_number_of_books_it_was_asked_for():
    """The catalogue's last listing page is short — 3 books, not 10, on the network
    measured — and it is always in the spread because the spread includes both ends.
    Sizing the sweep in whole pages therefore returns fewer books than asked for and
    says nothing about it: `--books 20` came back with 13.
    """
    pages = [_listing(*[f"b{n}" for n in range(i * 10, i * 10 + 10)]) for i in range(9)]
    pages.append(_listing("b90", "b91", "b92"))
    client = httpx.Client(transport=httpx.MockTransport(_pressbooks_network(pages)))

    assert len(network_books(NETWORK, client, limit=20).books) == 20


def test_a_limited_sweep_keeps_the_newest_books_it_paged_to_reach():
    """The surplus is trimmed from the spread, not off the end. Reading an extra
    listing page to include the catalogue's newest books and then slicing the list
    from the front drops exactly those books — and a test that counts the result
    passes anyway, which is how this survived being written.
    """
    pages = [_listing(*[f"b{n}" for n in range(i * 10, i * 10 + 10)]) for i in range(9)]
    pages.append(_listing("b90", "b91", "b92"))
    client = httpx.Client(transport=httpx.MockTransport(_pressbooks_network(pages)))

    books = network_books(NETWORK, client, limit=20).books

    assert (books[0][1], books[-1][1]) == (f"{NETWORK}/b0/", f"{NETWORK}/b92/")


def test_a_small_sweep_is_not_just_the_oldest_books_on_the_network():
    """`--books 10` is how someone tries the flag first. One listing page would answer
    it with the ten oldest books on the network — the least representative sample
    available, since they predate the glossary feature.
    """
    pages = [_listing(*[f"b{n}" for n in range(i * 10, i * 10 + 10)]) for i in range(9)]
    pages.append(_listing("b90", "b91", "b92"))
    client = httpx.Client(transport=httpx.MockTransport(_pressbooks_network(pages)))

    books = network_books(NETWORK, client, limit=10).books

    assert len(books) == 10
    assert books[-1][1] == f"{NETWORK}/b92/"


def test_a_listing_entry_pointing_off_the_network_is_dropped():
    """A book URL from the listing is data the network returned, not a host a person
    named. The run's fetch guard widens by the host the person typed — so a `link`
    somewhere else must not become a book, or the listing chooses what gets fetched.
    """
    listed = _listing("alpha")
    listed.append({"id": 9, "link": "https://attacker.example/x/", "metadata": {"name": "X"}})
    client = httpx.Client(transport=httpx.MockTransport(_pressbooks_network([listed])))

    assert network_books(NETWORK, client).books == [("Alpha", f"{NETWORK}/alpha/")]


def test_a_host_that_is_not_a_pressbooks_network_is_skipped_not_crashed():
    """A survey runs unattended over a list. A site that answers HTML where the API
    should be must skip that network, not end the run with a traceback.
    """

    def handler(request):
        return httpx.Response(200, text="<html>not an API</html>")

    client = httpx.Client(transport=httpx.MockTransport(handler))

    with pytest.raises(TocError, match="not JSON"):
        network_books(NETWORK, client)


def test_a_moved_network_says_so_rather_than_looking_missing():
    """The client does not follow redirects. A network that canonicalises its host
    answers 301, and "HTTP 301" alone reads as a missing endpoint rather than a moved
    one — on the flag whose whole point is networks other than the one built in.
    """

    def handler(request):
        return httpx.Response(301, headers={"location": "https://elsewhere.example/wp-json/"})

    client = httpx.Client(transport=httpx.MockTransport(handler))

    with pytest.raises(TocError, match="elsewhere.example"):
        network_books(NETWORK, client)


def test_a_one_book_sweep_does_not_pay_for_a_spread_it_cannot_use():
    """`--books 1` is a smoke test, not a sample: one book cannot span a catalogue, and
    `evenly_spaced` gives the first of whatever it collected either way. Reading a
    second listing page to reach the same book is a request spent for nothing.
    """
    pages = [_listing(*[f"b{n}" for n in range(i * 10, i * 10 + 10)]) for i in range(9)]
    pages.append(_listing("b90", "b91", "b92"))
    seen = []

    def handler(request):
        seen.append(int(request.url.params.get("page", 1)))
        return _pressbooks_network(pages)(request)

    client = httpx.Client(transport=httpx.MockTransport(handler))

    assert len(network_books(NETWORK, client, limit=1).books) == 1
    assert seen == [1]


def test_a_partial_off_host_drop_is_counted():
    """Every book being off-host raises; a FEW being off-host must not vanish just
    because it isn't the all-dropped case. `off_host` says how many were dropped,
    distinct from the books kept.
    """
    listed = _listing("alpha", "beta")
    listed.append({"id": 9, "link": "https://attacker.example/x/", "metadata": {"name": "X"}})
    client = httpx.Client(transport=httpx.MockTransport(_pressbooks_network([listed])))

    found = network_books(NETWORK, client)

    assert found.books == [("Alpha", f"{NETWORK}/alpha/"), ("Beta", f"{NETWORK}/beta/")]
    assert found.off_host == 1


def test_a_listing_whose_every_book_is_off_host_says_so():
    """The host filter is silent by design — but a network that puts each book on its
    own subdomain drops to zero books, and "screening 0 books" reads as an empty
    catalogue rather than as a guard that refused all of them.
    """
    listed = [
        {"id": i, "link": f"https://book{i}.pressbooks.pub/", "metadata": {"name": f"B{i}"}}
        for i in range(3)
    ]
    client = httpx.Client(transport=httpx.MockTransport(_pressbooks_network([listed])))

    with pytest.raises(TocError, match="off-host|another host"):
        network_books(NETWORK, client)
