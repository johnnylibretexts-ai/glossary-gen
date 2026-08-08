from __future__ import annotations

import hashlib
import re
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from glossary_gen.models import Block, Page

ALLOWED_HOST_SUFFIX = ".libretexts.org"
HEADING_TAGS = ("h1", "h2", "h3", "h4")
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
MAX_ATTEMPTS = 3
MAX_REDIRECTS = 3


class FetchError(Exception):
    """A page could not be retrieved or was refused."""


class _RetryableError(Exception):
    """Internal: signals that a request failed with a retryable status code."""

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"HTTP {status_code} (retryable)")


def _decode(url: str, body: bytes) -> str:
    """Decode a page body as UTF-8, replacing undecodable bytes rather than raising.

    A single non-UTF-8 byte on one page must not kill an otherwise long, unattended
    run: `errors="replace"` swaps bad bytes for U+FFFD instead of raising, so the
    page still yields whatever text is recoverable. The try/except is defense in
    depth for the rare case decoding still fails for some other reason (e.g. an
    unknown codec) — that, too, becomes a `FetchError` so the caller (`collect_pages`
    in cli.py) already knows how to record it as `fetch_error` and continue.
    """
    try:
        return body.decode("utf-8", errors="replace")
    except LookupError as exc:  # pragma: no cover - "utf-8" is always a valid codec
        raise FetchError(f"{url}: could not decode response body ({exc})") from exc


def is_allowed_url(url: str) -> bool:
    """Only https on a *.libretexts.org host. Everything else is refused."""
    parts = urlsplit(url)
    if parts.scheme != "https":
        return False
    host = parts.hostname or ""
    return host.casefold().endswith(ALLOWED_HOST_SUFFIX)


def parse_page(url: str, html: str) -> Page:
    """Extract ordered heading and paragraph blocks; drop scripts, styles, and blanks."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    blocks: list[Block] = []
    for element in soup.find_all([*HEADING_TAGS, "p"]):
        text = re.sub(r"\s+", " ", element.get_text(" ", strip=True)).strip()
        if not text:
            continue
        kind = "heading" if element.name in HEADING_TAGS else "paragraph"
        blocks.append(Block(kind=kind, text=text))
    return Page(url=url, blocks=tuple(blocks))


class PageCache:
    """Fetch pages once, then serve them from an on-disk HTML cache."""

    def __init__(
        self, cache_dir: Path, client: httpx.Client, *, max_bytes: int = 2_000_000
    ) -> None:
        self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._client = client
        self._max_bytes = max_bytes

    def _path_for(self, url: str) -> Path:
        return self._cache_dir / f"{hashlib.sha256(url.encode('utf-8')).hexdigest()}.html"

    def _download(self, url: str) -> str:
        last_status: int | None = None
        for attempt in range(MAX_ATTEMPTS):
            try:
                return self._fetch_with_redirects(url)
            except _RetryableError as exc:
                last_status = exc.status_code
                continue
            except httpx.HTTPError as exc:
                if attempt == MAX_ATTEMPTS - 1:
                    raise FetchError(f"{url}: transport error ({exc})") from exc
                continue
        raise FetchError(f"{url}: HTTP {last_status} after {MAX_ATTEMPTS} attempts")

    def _fetch_with_redirects(self, url: str) -> str:
        """Fetch URL with manual redirect following (max 3 hops), each validated.

        Raises _RetryableError for 429/500/502/503/504 to signal retry.
        Raises FetchError for non-retryable errors.
        Lets httpx.HTTPError (transport errors) propagate for retry handling.
        """
        current_url = url
        for hop in range(MAX_REDIRECTS + 1):
            if hop > 0 and not is_allowed_url(current_url):
                raise FetchError(
                    f"{url}: redirect to {current_url} is not allowed (not https on "
                    "*.libretexts.org)"
                )
            with self._client.stream("GET", current_url, timeout=30.0) as response:
                if response.status_code in RETRYABLE_STATUS:
                    raise _RetryableError(response.status_code)
                if response.status_code >= 300 and response.status_code < 400:
                    location = response.headers.get("location")
                    if not location:
                        raise FetchError(f"{current_url}: redirect without Location header")
                    current_url = urljoin(current_url, location)
                    continue
                if response.status_code != 200:
                    raise FetchError(f"{current_url}: HTTP {response.status_code}")
                body = b""
                for chunk in response.iter_bytes():
                    body += chunk
                    if len(body) > self._max_bytes:
                        raise FetchError(f"{url}: response too large (> {self._max_bytes} bytes)")
                return _decode(url, body)
        raise FetchError(f"{url}: redirect chain exceeded {MAX_REDIRECTS} hops")

    def get(self, url: str) -> Page:
        if not is_allowed_url(url):
            raise FetchError(f"{url}: not an allowed source URL (https on *.libretexts.org only)")
        cached = self._path_for(url)
        if cached.exists():
            try:
                html = cached.read_text(encoding="utf-8", errors="replace")
            except (UnicodeDecodeError, LookupError) as exc:
                raise FetchError(f"{url}: could not decode cached file ({exc})") from exc
            return parse_page(url, html)
        body = self._download(url)
        cached.write_text(body, encoding="utf-8")
        return parse_page(url, body)
