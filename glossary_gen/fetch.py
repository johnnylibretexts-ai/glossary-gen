from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from glossary_gen.models import Block, Page

ALLOWED_HOST_SUFFIX = ".libretexts.org"

# Matched exactly, never as a suffix. Every LibreTexts library is a subdomain of one
# host, so a suffix is right for it; Pressbooks is thousands of independent installs
# under a shared name, so a suffix there would admit every other install on the
# network — and anyone who registers a name ending in this one. Each entry is a host
# whose operator was considered on its own; see
# `docs/research/2026-08-17-platform-discovery-probes.md`.
ALLOWED_HOSTS = frozenset({"ecampusontario.pressbooks.pub"})
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


def _allowed_sources(host: str = "") -> str:
    """The allowlist, as a refusal can state it — built from what the guard actually
    permits, including this run's own host, so it cannot drift out of step."""
    named = sorted(ALLOWED_HOSTS | ({host.casefold()} if host else set()))
    return ", ".join([f"*{ALLOWED_HOST_SUFFIX}", *named])


def is_allowed_url(url: str, *, host: str = "") -> bool:
    """Only https, on a standing allowed host or the one host this run was given.

    `host` is the run's own source, taken from the book URL a person pasted. That is
    the authorisation: a human naming a book. A link discovered part-way through a
    crawl is not, which is why the widening is one exact host and never a suffix — a
    run pointed at `www.saskoer.ca` must still refuse `evil.www.saskoer.ca`.
    """
    parts = urlsplit(url)
    if parts.scheme != "https":
        return False
    hostname = (parts.hostname or "").casefold()
    if hostname.endswith(ALLOWED_HOST_SUFFIX) or hostname in ALLOWED_HOSTS:
        return True
    return bool(host) and hostname == host.casefold()


def parse_page(url: str, html: str) -> Page:
    """Extract ordered heading and paragraph blocks; drop scripts, styles, and blanks.

    `<dt>` is deliberately not among them, and that is a decision rather than an
    oversight: adding it would let the scanner read a book's own glossary page, which
    is the set its recall is measured against. Read
    `docs/adr/0011-the-scanner-does-not-read-the-authors-glossary.md` before changing
    this list — the reason lives nowhere near this file, and the evaluation it protects
    will not complain when it breaks.
    """
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


def cache_path(cache_dir: Path, url: str) -> Path:
    """Where a page's HTML lives on disk, for readers outside `PageCache`.

    Module level rather than a method so a reader that never fetches — the author
    glossary harvester walks an already-cached book with no client and no key —
    derives the filename from the same rule instead of a second copy of it.
    """
    return Path(cache_dir) / f"{hashlib.sha256(url.encode('utf-8')).hexdigest()}.html"


class PageCache:
    """Fetch pages once, then serve them from an on-disk HTML cache."""

    def __init__(
        self,
        cache_dir: Path,
        client: httpx.Client,
        *,
        max_bytes: int = 2_000_000,
        delay: float = 0.0,
        source_host: str = "",
    ) -> None:
        self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._client = client
        self._max_bytes = max_bytes
        self._delay = delay
        # The one host this run was pointed at, beyond the standing allowlist. Every
        # request the run makes — first hop and every redirect — is checked against it.
        self._source_host = source_host

    def _path_for(self, url: str) -> Path:
        return cache_path(self._cache_dir, url)

    def _download(self, url: str) -> str:
        # Politeness, on cache misses only: a book scan is 130+ requests against a public
        # API we do not own. Cache hits must stay free, so this belongs here and not in `get`.
        if self._delay:
            time.sleep(self._delay)
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
            if hop > 0 and not is_allowed_url(current_url, host=self._source_host):
                raise FetchError(
                    f"{url}: redirect to {current_url} is not allowed "
                    f"(not https on {_allowed_sources(self._source_host)})"
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

    def get_html(self, url: str) -> str:
        """Return the page's raw HTML, guarded by `is_allowed_url`, served from the cache
        file when it exists and downloaded once (with the politeness delay) when it does
        not. The single source of truth for "download or read cache", and the ONLY way a
        page leaves this class.

        Raw is deliberate. Every caller narrows the document to its article with
        `article.extract_content` before parsing, and both entry points do so through
        their own `collect_pages`. A convenience `get()` returning a parsed `Page` used to
        live here and was removed once its last caller was gone: it was a second, quieter
        route to the same bytes that skipped the narrowing, which is exactly the mistake
        a new caller would make by reaching for the shorter name.
        """
        if not is_allowed_url(url, host=self._source_host):
            raise FetchError(
                f"{url}: not an allowed source URL (https on {_allowed_sources(self._source_host)})"
            )
        cached = self._path_for(url)
        if cached.exists():
            try:
                return cached.read_text(encoding="utf-8", errors="replace")
            except (UnicodeDecodeError, LookupError) as exc:
                raise FetchError(f"{url}: could not decode cached file ({exc})") from exc
        body = self._download(url)
        cached.write_text(body, encoding="utf-8")
        return body
