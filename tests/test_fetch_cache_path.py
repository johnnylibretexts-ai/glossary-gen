"""Where a cached page lands is a shared fact, not a private detail of PageCache.

Anything that reads the cache without going through `PageCache` — the reference
harvester reads all 117 pages of an already-scanned book with no network and no
key — has to derive the same filename. A second copy of the hashing rule would
drift silently: the reader would simply find no pages and report an empty book.
"""

import httpx

from glossary_gen.fetch import PageCache, cache_path

URL = "https://stats.libretexts.org/Bookshelves/Introductory_Statistics/01%3A_Sampling"


def test_cache_path_is_where_page_cache_stores_the_page(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html><body><p>cached</p></body></html>")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        PageCache(tmp_path, client).get_html(URL)

    assert cache_path(tmp_path, URL).read_text(encoding="utf-8").endswith("</html>")


def test_cache_path_distinguishes_urls(tmp_path):
    assert cache_path(tmp_path, URL) != cache_path(tmp_path, URL + "_and_Data")
