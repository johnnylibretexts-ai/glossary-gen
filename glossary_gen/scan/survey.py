"""Screen a book for an author glossary before spending anything on it.

Fetching is free; only model calls cost money. So whether a book publishes its own
glossary — the thing that decides whether it can be measured at all (ADR-0010) — can
be answered for nothing, before a scan is ever paid for.

What that costs depends on the platform, and the two are not alike:

- **LibreTexts** renders glossary entries as ordinary markup, so the only test is to
  read pages and look. A sample spanning the book answers "does it carry blocks" one
  way only: a hit is proof, a zero is *no evidence at the pages sampled*. A book
  carrying blocks on 2.5% of its pages was screened at 12 and reported as having none.
- **Pressbooks** makes glossary terms a post type, and renders each one into the HTML
  of the page that uses it. A book that published a glossary page is settled by ONE
  fetch of it; a book that did not is settled by walking it until a term appears, or
  to the end. Either way the answer is proof rather than evidence.

Nothing here reads a disallowed path. Pressbooks' default robots.txt disallows every
per-book `/*/wp-json/` endpoint — including the `glossary` route that would give an
exact term count in one request — so enumeration comes from the one network-level API
path that is not matched, and every other fact comes from rendered HTML. Measured in
docs/research/2026-08-17-platform-discovery-probes.md.
"""

from __future__ import annotations

import math
import urllib.parse
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from typing import Any, TypeVar

import httpx

from glossary_gen.fetch import FetchError, PageCache
from glossary_gen.scan.reference import book_glossary
from glossary_gen.scan.toc import TocError, discover

T = TypeVar("T")

# The one Pressbooks API path this tool reads. `/*/wp-json/` needs a path segment
# before `wp-json`, which the network-level listing does not have — so the enumerator
# is allowed where every per-book endpoint is disallowed.
PRESSBOOKS_BOOKS_PATH = "/wp-json/pressbooks/v2/books"

# A cap, not a clamp: `per_page=12` is answered `400 rest_invalid_param`. A sweep
# across a network of thousands therefore pages, and cannot ask for fewer requests.
BOOKS_PER_PAGE = 10

# Where Pressbooks puts a glossary its authors titled "Glossary". Fetching it is a
# shortcut and never the only route — a book whose page is titled `Glossaire` 404s
# here and is found by the walk, which reads the whole book including its back matter.
PRESSBOOKS_GLOSSARY_PAGE = "back-matter/glossary/"


@dataclass(frozen=True)
class SurveyResult:
    """What the pages read say about one book's glossary.

    `settled` is the difference between the two platforms. It says this row's answer
    is proof: either a page carried a term, or every page of the book was read and
    none did. Unsettled, a zero means only that nothing was found in what was read.
    """

    sampled: int
    with_glossary: int
    terms: int
    chars: int = 0
    settled: bool = False

    @property
    def share(self) -> float:
        return self.with_glossary / self.sampled if self.sampled else 0.0


@dataclass(frozen=True)
class Screen:
    """One book screened: what was read, what it settles, and what it cost to say so."""

    result: SurveyResult
    pages: int = 0
    title: str = ""
    fetched: tuple[tuple[str, str], ...] = ()
    spans_book: bool = False
    """Whether what was read is a fair basis for a per-page forecast — an even spread
    across the book, or all of it. A carrier the walk stopped early on is neither, and
    forecasting from the front matter it happened to read would understate every book."""


def evenly_spaced(items: Sequence[T], count: int) -> list[T]:
    """`count` items spanning the whole sequence, first and last included.

    Glossary blocks live in chapters. A sample taken off the top would screen a book
    on its title page, its licensing notice and its table of contents, and conclude
    that no book has a glossary. The same reasoning applies to a network's catalogue,
    whose oldest books predate the glossary feature entirely.
    """
    if not items or count <= 0:
        return []
    if count >= len(items):
        return list(items)
    if count == 1:
        return [items[0]]
    step = (len(items) - 1) / (count - 1)
    return [items[round(i * step)] for i in range(count)]


def shelf_books(root: dict[str, Any]) -> list[tuple[str, str]]:
    """`(title, url)` for a bookshelf's immediate children — the books on it."""
    subpages = root.get("subpages") or []
    children = subpages if isinstance(subpages, list) else [subpages]
    return [
        (str(child.get("title") or ""), str(child.get("url")))
        for child in children
        if isinstance(child, dict) and child.get("url")
    ]


def _books_listing(root: str, client: httpx.Client, page: int) -> httpx.Response:
    url = f"{root}{PRESSBOOKS_BOOKS_PATH}"
    try:
        response = client.get(url, params={"per_page": BOOKS_PER_PAGE, "page": page}, timeout=60.0)
    except httpx.HTTPError as exc:
        raise TocError(f"{url}: transport error ({exc})") from exc
    # Redirects are not followed, so a network that canonicalises its host answers one
    # here. `HTTP 301` on its own reads as a missing endpoint rather than a moved one,
    # on the very flag whose point is networks other than the host built in — so the
    # refusal names where it was sent instead.
    if 300 <= response.status_code < 400:
        moved = response.headers.get("location", "elsewhere")
        raise TocError(f"{url}: HTTP {response.status_code}, moved to {moved} — use that URL")
    if response.status_code != 200:
        raise TocError(f"{url}: HTTP {response.status_code} (page {page})")
    return response


def _books_payload(response: httpx.Response) -> Any:
    """The listing body, or a refusal a sweep over several networks can survive.

    A host that is not a Pressbooks install answers this path with its own 200 — a
    themed 404 page, usually — and a survey runs unattended over a list. `get_toc`
    turns the same case into a `TocError` for the same reason.
    """
    try:
        return response.json()
    except ValueError as exc:
        raise TocError(f"{response.url}: response body is not JSON") from exc


def _listed_books(payload: Any, host: str) -> list[tuple[str, str]]:
    """`(title, url)` per entry, for entries on `host`. The title is schema.org metadata.

    The host filter is the guard, not a tidy-up. Every fetch this tool makes is checked
    against a standing allowlist widened by exactly one host — the one a person named —
    and on a sweep that host is the network URL they typed. A `link` is data the network
    returned, so a listing entry pointing somewhere else must not become a book: it would
    be fetched under a widening it never earned, and the listing would be choosing what
    the run reaches. Same rule as a term's occurrence pages, which widen nothing.
    """
    if not isinstance(payload, list):
        raise TocError("the books listing is not a JSON list")
    books = []
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        link = str(entry.get("link") or "")
        if (urllib.parse.urlsplit(link).hostname or "").casefold() != host:
            continue
        metadata = entry.get("metadata")
        name = str((metadata or {}).get("name") or "") if isinstance(metadata, dict) else ""
        books.append((name.strip(), link))
    return books


def _header_count(response: httpx.Response, name: str, default: int) -> int:
    """A `x-wp-*` count header, or `default` when the host sends something that is not one."""
    try:
        return int(response.headers.get(name) or default)
    except ValueError:
        return default


def _listing_pages(limit: int, total_pages: int, total: int) -> int:
    """How many listing pages to read to come back with `limit` books.

    Not `limit / 10`. The catalogue's LAST page is short — 3 books of 3,033 on the
    network measured — and the spread always includes it, because a spread includes
    both ends. Sizing the sweep in whole pages therefore comes back short and says
    nothing about it: asking for 20 books returned 13.
    """
    if limit <= 0:
        return total_pages
    # One book cannot span a catalogue, and the trim would hand back the first book of
    # page 1 whatever else was read. Spreading for it spends a request to reach the same
    # oldest book — so `--books 1` is a smoke test, and says so by costing one request.
    if limit == 1:
        return 1
    last = total - (total_pages - 1) * BOOKS_PER_PAGE if total else BOOKS_PER_PAGE
    needed = 1 if limit <= last else math.ceil((limit - last) / BOOKS_PER_PAGE) + 1
    # Never one page, which is page 1 — the oldest books on the network, and the sample
    # this function exists to avoid. `--books 10` is how the flag gets tried first.
    return min(total_pages, max(2, needed))


def network_books(network_url: str, client: httpx.Client, limit: int = 0) -> list[tuple[str, str]]:
    """`(title, url)` for the books a Pressbooks network publishes.

    This is the counterpart to `shelf_books`, and it is a real enumerator rather than
    a shelf someone pasted: `GET /wp-json/pressbooks/v2/books` is the one Pressbooks
    API path the platform's robots.txt leaves allowed, and it returns every book on
    the network with the URL to read it from. A guessed book slug 404s; these are real.

    `limit` bounds a sweep by BOOKS, and spreads the listing pages it reads across the
    whole catalogue rather than taking the first N. eCampusOntario's oldest books
    predate the glossary feature, so the first page of 3,033 is the least representative
    sample available. Fewer come back only where the catalogue itself is smaller.
    """
    parts = urllib.parse.urlsplit(network_url)
    if parts.scheme != "https":
        raise TocError(f"{network_url}: only https network URLs are read")
    host = (parts.hostname or "").casefold()
    root = f"https://{parts.netloc}"

    first = _books_listing(root, client, 1)
    total_pages = max(_header_count(first, "x-wp-totalpages", 1), 1)
    total = _header_count(first, "x-wp-total", 0)
    numbers = evenly_spaced(range(1, total_pages + 1), _listing_pages(limit, total_pages, total))

    books: list[tuple[str, str]] = []
    listed = 0
    for number in numbers:
        response = first if number == 1 else _books_listing(root, client, number)
        payload = _books_payload(response)
        listed += len(payload) if isinstance(payload, list) else 0
        books.extend(_listed_books(payload, host))
    # A network that gives each book its own subdomain drops to zero books here, and
    # "screening 0 books" reads as an empty catalogue rather than as a guard that
    # refused every entry. Said once, at the only point where it is unambiguous.
    # Partial drops stay silent: some entries being elsewhere is ordinary.
    if listed and not books:
        raise TocError(
            f"{root}{PRESSBOOKS_BOOKS_PATH}: all {listed} listed books are on another host, "
            f"so none is reachable from a run pointed at {host}"
        )
    # Trimmed by spreading again, not by slicing the front. The extra listing page was
    # read precisely to reach the catalogue's newest books, and `books[:limit]` throws
    # away that page and nothing else — leaving the count right and the reason for it
    # broken, which is what a test counting rows does not catch.
    return evenly_spaced(books, limit) if limit > 0 else books


def survey_pages(pages: Iterable[tuple[str, str]], *, settled: bool = False) -> SurveyResult:
    """Count what the `(url, html)` pages read carry.

    `settled` is the caller's knowledge, not this function's: only the caller knows
    whether what it handed over is the whole book.
    """
    pages = list(pages)
    with_glossary = sum(1 for page in pages if book_glossary([page]))
    return SurveyResult(
        sampled=len(pages),
        with_glossary=with_glossary,
        terms=len(book_glossary(pages)),
        chars=sum(len(html) for _, html in pages),
        settled=settled,
    )


def glossary_page_url(book_url: str) -> str:
    """Where a Pressbooks book's glossary page lives, when its authors made one."""
    root = book_url if book_url.endswith("/") else f"{book_url}/"
    return f"{root}{PRESSBOOKS_GLOSSARY_PAGE}"


def _settled(carried: bool, read: int, pages: int) -> bool:
    """A hit is proof; a zero is proof only when every page of the book was read."""
    return carried or (pages > 0 and read == pages)


def _screen_pressbooks(book_url: str, client: httpx.Client, cache: PageCache) -> Screen:
    """One fetch when the book published a glossary page, a walk when it did not.

    The walk stops at the first page carrying a term because the screen's question is
    whether the book carries a glossary, and one page carrying one answers it. What
    that costs the row is its term count, which becomes a floor rather than a total —
    `sampled` against `pages` says so, and a harvest is what produces the real number.

    The fast path is an optimisation, never the only route. A glossary page titled
    anything else 404s it, and the walk reads the book's back matter like any other
    page. Measured on *Language Foundations Handbook*: 59 terms from one request, the
    same 59 the 23-page walk finds. The inline terms in its chapters are 26 of those.

    That book is not the general case, and the term count is a floor for a second
    reason because of it. *Research Methods in Psychology* settles here at 100 — its
    glossary page, in full — while a harvest of all 83 pages finds 243, the other 143
    linked inline and never listed on that page. A glossary page is the authors' list;
    it is not always the book's.
    """
    page = glossary_page_url(book_url)
    try:
        html = cache.get_html(page)
    except FetchError:
        html = ""
    if html:
        result = survey_pages([(page, html)], settled=True)
        if result.terms:
            # The book's page count is deliberately unknown: it was never walked, and
            # reporting 1 would read as a one-page book rather than as a book unread.
            return Screen(result, pages=0, fetched=((page, html),))

    book, urls = discover(book_url, client, cache)
    fetched: list[tuple[str, str]] = []
    visited = 0
    carried = False
    for url in urls:
        visited += 1
        try:
            fetched.append((url, cache.get_html(url)))
        except FetchError:
            continue
        if book_glossary([fetched[-1]]):
            carried = True
            break
    settled = _settled(carried, len(fetched), len(urls))
    return Screen(
        survey_pages(fetched, settled=settled),
        pages=len(urls),
        title=book.title,
        fetched=tuple(fetched),
        # Whether the walk reached the END of the book, which is not the same question
        # `settled` asks. A page that would not load leaves the zero unproven, but the
        # pages that did arrive are still spread across the whole book and are still
        # what a per-page cost is measured from. A walk that stopped early is not: it
        # read the front matter, and forecasting a book from that understates it.
        spans_book=visited == len(urls),
    )


def _screen_sampled(book_url: str, client: httpx.Client, cache: PageCache, sample: int) -> Screen:
    """The LibreTexts screen: an even spread, and a zero that stays weak evidence."""
    book, urls = discover(book_url, client, cache)
    fetched = []
    for url in evenly_spaced(urls, sample):
        try:
            fetched.append((url, cache.get_html(url)))
        except FetchError:
            continue
    read = survey_pages(fetched)
    return Screen(
        # Rebuilt rather than re-counted: `survey_pages` parses every page it is given,
        # and a second call to set one flag would parse the whole sample twice.
        replace(read, settled=_settled(bool(read.with_glossary), len(fetched), len(urls))),
        pages=len(urls),
        title=book.title,
        fetched=tuple(fetched),
        # An even spread, so the mean page is the book's mean page. That is what makes
        # a per-page forecast off a 16-page sample mean anything at all.
        spans_book=True,
    )


def screen(book_url: str, client: httpx.Client, cache: PageCache, *, sample: int = 16) -> Screen:
    """Screen one book for an author glossary, by the cheapest route its platform allows.

    Routed on the host, as `discover` is. `sample` bounds the LibreTexts screen, which
    has no exact test to reach for; it is ignored on a Pressbooks book, where sampling
    would re-import the "a zero is only weak evidence" caveat that platform does not
    need.
    """
    if (urllib.parse.urlsplit(book_url).hostname or "").lower().endswith(".libretexts.org"):
        return _screen_sampled(book_url, client, cache, sample)
    return _screen_pressbooks(book_url, client, cache)
