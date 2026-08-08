from __future__ import annotations

import hashlib
import re
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from bs4 import BeautifulSoup

from glossary_gen.models import Block, Page

ALLOWED_HOST_SUFFIX = ".libretexts.org"
HEADING_TAGS = ("h1", "h2", "h3", "h4")
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
MAX_ATTEMPTS = 3


class FetchError(Exception):
    """A page could not be retrieved or was refused."""


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
                response = self._client.get(url, follow_redirects=True, timeout=30.0)
            except httpx.HTTPError as exc:
                if attempt == MAX_ATTEMPTS - 1:
                    raise FetchError(f"{url}: transport error ({exc})") from exc
                continue
            if response.status_code in RETRYABLE_STATUS:
                last_status = response.status_code
                continue
            if response.status_code != 200:
                raise FetchError(f"{url}: HTTP {response.status_code}")
            body = response.text
            if len(body.encode("utf-8")) > self._max_bytes:
                raise FetchError(
                    f"{url}: response too large (> {self._max_bytes} bytes)"
                )
            return body
        raise FetchError(f"{url}: HTTP {last_status} after {MAX_ATTEMPTS} attempts")

    def get(self, url: str) -> Page:
        if not is_allowed_url(url):
            raise FetchError(
                f"{url}: not an allowed source URL (https on *.libretexts.org only)"
            )
        cached = self._path_for(url)
        if cached.exists():
            return parse_page(url, cached.read_text(encoding="utf-8"))
        body = self._download(url)
        cached.write_text(body, encoding="utf-8")
        return parse_page(url, body)
