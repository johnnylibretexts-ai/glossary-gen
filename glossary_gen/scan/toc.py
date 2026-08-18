from __future__ import annotations

import re
import urllib.parse
from collections.abc import Callable, Iterator
from typing import Any

import httpx
from bs4 import BeautifulSoup
from bs4.element import Tag

from glossary_gen.article import content_element
from glossary_gen.fetch import FetchError, PageCache, parse_page
from glossary_gen.models import Book, slugify

API = "https://api.libretexts.org/endpoint"

# All three headers are load-bearing. `getTOC` is public and needs no credentials, but
# omitting Accept or User-Agent makes it answer 403 — which reads exactly like an auth
# wall and is not one. Do not "tidy" these away.
TOC_HEADERS = {
    "Origin": "https://libretexts.org",
    "Accept": "application/json",
    "User-Agent": "LibreTexts-Reader/1.0",
}


class TocError(Exception):
    """The table of contents could not be retrieved or understood."""


def parse_libretexts_url(url: str) -> tuple[str, str]:
    """(subdomain, path) for a <sub>.libretexts.org URL; TocError otherwise."""
    parts = urllib.parse.urlparse(url)
    host = (parts.hostname or "").lower()
    labels = host.split(".")
    if len(labels) != 3 or f"{labels[1]}.{labels[2]}" != "libretexts.org":
        raise TocError(f"not a <sub>.libretexts.org host: {host!r}")
    return labels[0], urllib.parse.unquote(parts.path).strip("/")


def get_toc(book_url: str, client: httpx.Client) -> dict[str, Any]:
    parse_libretexts_url(book_url)
    encoded = urllib.parse.quote(book_url, safe="")
    try:
        response = client.get(f"{API}/getTOC/{encoded}", headers=TOC_HEADERS, timeout=90.0)
    except httpx.HTTPError as exc:
        raise TocError(f"{book_url}: transport error ({exc})") from exc
    if response.status_code == 403:
        raise TocError(
            f"{book_url}: HTTP 403. This endpoint is public and needs no "
            "credentials — a 403 means the Origin/Accept/User-Agent headers "
            "were not all sent."
        )
    if response.status_code != 200:
        raise TocError(f"{book_url}: HTTP {response.status_code}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise TocError(f"{book_url}: response body is not JSON") from exc
    structured = (payload.get("toc") or {}).get("structured")
    if not structured:
        raise TocError(f"no TOC returned for {book_url}")
    return structured


def iter_nodes(node: dict[str, Any]) -> Iterator[dict[str, Any]]:
    yield node
    subpages = node.get("subpages")
    if not subpages:
        return
    for child in subpages if isinstance(subpages, list) else [subpages]:
        if isinstance(child, dict):
            yield from iter_nodes(child)


def _node_url(node: dict[str, Any]) -> str:
    return str(node.get("url") or node.get("uri.ui") or "")


def leaf_urls(root: dict[str, Any]) -> tuple[str, ...]:
    """Content pages only: every node with no subpages, in document order."""
    seen: list[str] = []
    for node in iter_nodes(root):
        if node.get("subpages"):
            continue
        url = _node_url(node)
        if url and url not in seen:
            seen.append(url)
    return tuple(seen)


def book_from_root(root: dict[str, Any], book_url: str) -> Book:
    title = str(root.get("title") or "")
    return Book(
        library=str(root.get("subdomain") or ""),
        cover_id=str(root.get("@id") or root.get("id") or ""),
        book_id=slugify(title),
        title=title,
        index_url=book_url,
    )


# The sections a Pressbooks book's pages live under.
PRESSBOOKS_SECTIONS = ("front-matter/", "chapter/", "back-matter/")

# Parts are the fourth. They used to be excluded outright, on the grounds that a part is
# a section divider whose own page is a heading and nothing else. That is usually true
# and not always: Pressbooks lets a part carry post content, and when it does the
# content is a chapter introduction that defines terms. Measured across 18 books on
# `ecampusontario.pressbooks.pub` (2026-08-17): 3 of them have parts carrying 1,200 to
# 6,200 characters of prose each, 27 pages in all that were never scanned.
#
# The same survey settled where the part URLs come from. Pressbooks links a part from
# the front page's table of contents EXACTLY when that part has content — of 89 parts,
# none that was linked turned out empty and none that was unlinked turned out to carry
# anything. So the front page already offers every part worth reading, and this filter
# was throwing them away. The link is not taken as proof, though: `_part_carries_content`
# reads the page, because a rule that holds on one network's themes is not a rule.
PRESSBOOKS_PART = "part/"


def _book_links(soup: BeautifulSoup, root: str, prefixes: tuple[str, ...]) -> list[str]:
    """Every link on one page to a page of this book, deduped, in document order."""
    urls: list[str] = []
    for anchor in soup.select("a[href]"):
        href = urllib.parse.urljoin(root, anchor["href"]).split("#")[0]
        # Under this book's own root, so a link to a neighbouring book on the same
        # network — or anywhere else — is not mistaken for one of its pages.
        if not href.startswith(root):
            continue
        if href[len(root) :].startswith(prefixes) and href not in urls:
            urls.append(href)
    return urls


def _part_carries_content(url: str, article: Tag, root: str) -> bool:
    """Whether a part page is worth scanning, or is a divider wearing a title.

    Three shapes were measured, and only the first is a page:

    - an authored introduction to the chapters below it — kept;
    - nothing at all beyond the heading Pressbooks renders for every part — dropped;
    - `Chapter Outline` over a list of links to its own chapters — dropped, and this is
      the one a plain "has any text" test waves through. Every line of it is a chapter
      title, which is the exact shape of "a term this page defines", and the evidence
      gate cannot refuse it because the text really is on the page. `article.py` strips
      the same thing out of the site chrome for the same reason; a part page renders it
      INSIDE the article, where narrowing cannot reach it.

    So the test is a paragraph that survives having the book's own links taken out of
    it, judged with `parse_page` — the scanner's own notion of what a page yields —
    rather than a second definition of content that could drift from it. Mutates the
    element it is given, which is why it takes one detached from its document.
    """
    for anchor in article.select("a[href]"):
        if urllib.parse.urljoin(root, anchor.get("href") or "").startswith(root):
            anchor.decompose()
    return any(block.kind == "paragraph" for block in parse_page(url, str(article)).blocks)


def _uncached_reader(client: httpx.Client) -> Callable[[str], str]:
    """The degraded page reader, for a caller that has no `PageCache` to lend.

    One request, no retry, no size cap, no politeness delay and no allowlist check —
    everything `PageCache` exists to add. Every caller inside this package passes a
    cache; this keeps `discover` usable from a test or a script that has not built one,
    and is deliberately the worse of the two paths rather than a second normal one.
    """

    def read(url: str) -> str:
        response = client.get(url, timeout=60.0)
        if response.status_code != 200:
            raise FetchError(f"{url}: HTTP {response.status_code}")
        return response.text

    return read


def _read_part(url: str, root: str, read: Callable[[str], str]) -> tuple[bool, list[str]] | None:
    """`(worth scanning, the book pages it links)` for one part, or None if unreadable.

    A part that will not load is one page of a book, not the book: the run goes on. It
    is reported as unread rather than as empty so the caller can keep it — see there.

    Read through the run's `PageCache`, not with a bare client, and that is load-bearing
    three times over. It follows redirects (validated, up to three hops), so a part
    linked by an old slug is read instead of counting as unreadable — which would be the
    worst of both outcomes, the part kept unjudged AND its table of contents lost. It
    retries a 429 or a 5xx instead of turning one bad second into a missing page. And a
    part that turns out to be a page is downloaded ONCE: `collect_pages` gets it from the
    cache rather than fetching every part a second time. The politeness delay, the size
    cap and the allowlist come along with it.

    The links are read from the CHROME, the document with its article detached, and this
    is the whole reason the two halves are separated rather than the page scanned whole.
    The chrome is where the theme repeats the book's table of contents; the article is
    where the authors write prose, and prose contains cross-references to chapters —
    including stale ones. Measured on *Communication at Work*: reading the whole document
    found one URL the front page had not, `chapter/6-1-1-email-address/`, which 301s to a
    chapter already in the list. Kept, it would have been fetched, scanned and PAID for a
    second time under a second URL, and put that URL on the terms it found. A part page
    whose template is unrecognised is kept and contributes nothing, since without the
    split there is no way to tell one half from the other.
    """
    try:
        html = read(url)
    except (FetchError, httpx.HTTPError):
        return None
    soup = BeautifulSoup(html, "html.parser")
    article = content_element(soup)
    if article is None:
        return True, []
    # Detached first, and the links read before the article is judged. `_part_carries_content`
    # strips the book's own links out of what it is given, so leaving the two halves joined —
    # or reading the links afterwards — would filter the chrome by a side effect and hide
    # whether the split is doing anything. Separated, the test above fails the moment it is not.
    article.extract()
    listed = _book_links(soup, root, (*PRESSBOOKS_SECTIONS, PRESSBOOKS_PART))
    return _part_carries_content(url, article, root), listed


def pressbooks_discover(
    book_url: str, client: httpx.Client, cache: PageCache | None = None
) -> tuple[Book, tuple[str, ...]]:
    """A Pressbooks book's own front page, read as its table of contents, then its parts.

    There is no TOC API this tool may use: the platform's default robots.txt disallows
    the whole `/*/wp-json/` tree. The rendered front page lists the book's sections in
    reading order, which is the order that makes "the first page to define a term"
    mean anything.

    The front page is not TAKEN as the whole table of contents, which is what it used to
    be — a book that comes back with 8 pages instead of 30 reads as a small book rather
    than as a failure. Each part is fetched anyway to ask whether it carries content, so
    its own table of contents is read from the same request and the union taken.

    The book that showed this is not hypothetical is *Business Communication* on
    `ecampusontario.pressbooks.pub`: 19 parts, and no chapters at all — the whole book is
    written in its part pages. Front-page sections alone returned ONE page for it, and
    said nothing about the other nineteen.

    A page only a part knew about is read after everything the front page listed:
    reading order is the front page's, and a page it never listed has no position there
    to claim.
    """
    if urllib.parse.urlparse(book_url).scheme != "https":
        raise TocError(f"{book_url}: only https book URLs are read")
    root = book_url if book_url.endswith("/") else f"{book_url}/"
    try:
        response = client.get(root, timeout=60.0)
    except httpx.HTTPError as exc:
        raise TocError(f"{book_url}: transport error ({exc})") from exc
    if response.status_code != 200:
        raise TocError(f"{book_url}: HTTP {response.status_code}")

    soup = BeautifulSoup(response.text, "html.parser")
    read = cache.get_html if cache is not None else _uncached_reader(client)

    # Two lists, one order. `urls` is the front page's, which is reading order. `elsewhere`
    # holds pages only a part's table of contents knew about, which have no position on the
    # front page to claim, and is appended after it. A page is written to whichever list the
    # link that reached it belongs to, and never to both.
    urls: list[str] = []
    elsewhere: list[str] = []

    def note(href: str, into: list[str]) -> None:
        if href not in urls and href not in elsewhere:
            into.append(href)

    # A work list, not a loop over the front page, because a part's table of contents can
    # name a PART the front page left out — and on a book like *Business Communication*,
    # which is 19 parts and no chapters, parts are the only thing there is to leave out.
    # Harvesting chapters from the chrome and not parts would cross-check every book except
    # the shape that most needs it. `seen` bounds the work at one read per part however many
    # pages link it.
    queue: list[tuple[str, list[str]]] = [
        (href, urls) for href in _book_links(soup, root, (*PRESSBOOKS_SECTIONS, PRESSBOOKS_PART))
    ]
    seen: set[str] = set()
    while queue:
        href, into = queue.pop(0)
        if not href[len(root) :].startswith(PRESSBOOKS_PART):
            note(href, into)
            continue
        if href in seen:
            continue
        seen.add(href)
        part = _read_part(href, root, read)
        if part is None:
            # Unread, so unjudged. Kept rather than dropped, because dropping it would
            # decide it had no content on no evidence — the silent shortfall this reads
            # parts to avoid. `collect_pages` will fail to fetch it too, and say so in
            # the `fetch_error` count the run prints. Nothing is paid for it.
            note(href, into)
            continue
        keep, listed = part
        if keep:
            note(href, into)
        queue.extend((link, elsewhere) for link in listed)
    urls.extend(elsewhere)

    heading = soup.select_one("h1.book-header__title, h1.entry-title") or soup.find("h1")
    title = ""
    if heading:
        # Pressbooks prefixes the heading with a visually-hidden "Book Title:" for
        # screen readers. Read as text it lands in the title, the `book_id` slug, and
        # every row of output.
        for label in heading.select(".screen-reader-text"):
            label.decompose()
        title = re.sub(r"\s+", " ", heading.get_text(" ", strip=True)).strip()
    # `location`, not `parts` — a part is now a thing this module has an opinion about.
    location = urllib.parse.urlparse(root)
    return (
        Book(
            library=(location.hostname or ""),
            cover_id=location.path.strip("/"),
            book_id=slugify(title),
            title=title,
            index_url=book_url,
        ),
        tuple(urls),
    )


def discover(
    book_url: str, client: httpx.Client, cache: PageCache | None = None
) -> tuple[Book, tuple[str, ...]]:
    """Walk a book's TOC into a complete book block plus its leaf page URLs.

    Routed on the host: LibreTexts has a public TOC API, and every other source is
    read from the book's own front page.

    `cache` is the run's page cache, used for the pages discovery has to READ rather than
    merely list — a Pressbooks book's parts. Pass it: without one those requests lose the
    politeness delay, the retries, the redirect validation and the size cap, and every
    part that turns out to be a page is downloaded twice. The book's front page is
    deliberately NOT read through it: it is the table of contents, and a cached table of
    contents would not notice a chapter added since the first run.
    """
    if (urllib.parse.urlparse(book_url).hostname or "").lower().endswith(".libretexts.org"):
        root = get_toc(book_url, client)
        return book_from_root(root, book_url), leaf_urls(root)
    return pressbooks_discover(book_url, client, cache)
