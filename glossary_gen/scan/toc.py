from __future__ import annotations

import re
import urllib.parse
from collections.abc import Iterator
from typing import Any

import httpx
from bs4 import BeautifulSoup

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


# The sections a Pressbooks book's pages live under. Parts are deliberately absent:
# they are section dividers whose own page is usually a heading and nothing else.
PRESSBOOKS_SECTIONS = ("front-matter/", "chapter/", "back-matter/")


def pressbooks_discover(book_url: str, client: httpx.Client) -> tuple[Book, tuple[str, ...]]:
    """A Pressbooks book's own front page, read as its table of contents.

    There is no TOC API this tool may use: the platform's default robots.txt disallows
    the whole `/*/wp-json/` tree. The rendered front page lists the book's sections in
    reading order, which is the order that makes "the first page to define a term"
    mean anything.
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
    urls: list[str] = []
    for anchor in soup.select("a[href]"):
        href = urllib.parse.urljoin(root, anchor["href"]).split("#")[0]
        # Under this book's own root, so a link to a neighbouring book on the same
        # network — or anywhere else — is not mistaken for one of its pages.
        if not href.startswith(root):
            continue
        rest = href[len(root) :]
        if rest.startswith(PRESSBOOKS_SECTIONS) and href not in urls:
            urls.append(href)

    heading = soup.select_one("h1.book-header__title, h1.entry-title") or soup.find("h1")
    title = ""
    if heading:
        # Pressbooks prefixes the heading with a visually-hidden "Book Title:" for
        # screen readers. Read as text it lands in the title, the `book_id` slug, and
        # every row of output.
        for label in heading.select(".screen-reader-text"):
            label.decompose()
        title = re.sub(r"\s+", " ", heading.get_text(" ", strip=True)).strip()
    parts = urllib.parse.urlparse(root)
    return (
        Book(
            library=(parts.hostname or ""),
            cover_id=parts.path.strip("/"),
            book_id=slugify(title),
            title=title,
            index_url=book_url,
        ),
        tuple(urls),
    )


def discover(book_url: str, client: httpx.Client) -> tuple[Book, tuple[str, ...]]:
    """Walk a book's TOC into a complete book block plus its leaf page URLs.

    Routed on the host: LibreTexts has a public TOC API, and every other source is
    read from the book's own front page.
    """
    if (urllib.parse.urlparse(book_url).hostname or "").lower().endswith(".libretexts.org"):
        root = get_toc(book_url, client)
        return book_from_root(root, book_url), leaf_urls(root)
    return pressbooks_discover(book_url, client)
