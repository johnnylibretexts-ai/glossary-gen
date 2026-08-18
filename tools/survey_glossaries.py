"""Find which LibreTexts books publish their own glossary. Free — no model is called.

    python3 tools/survey_glossaries.py --shelf https://stats.libretexts.org/Bookshelves/Introductory_Statistics
    python3 tools/survey_glossaries.py --book <url> --book <url> --out survey.csv

Fetching costs nothing but politeness, so the question that decides whether a book can
be measured at all — does it carry author-written glossary blocks — is answered before
any scan is paid for. A sample of pages spanning the whole book is enough to answer it:
blocks sit in chapters, and a book that has them has them repeatedly.

The token forecast printed per book is measured from that sample's own page text, not
from a constant. `EST_SCAN_TOKENS_IN` is calibrated to one book and was 3x low on the
statistics pages — see docs/research/2026-08-17-definition-comparison.md.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from glossary_gen.cli import build_http_client
from glossary_gen.fetch import FetchError, PageCache, parse_page
from glossary_gen.run import PRICES_PATH, load_prices
from glossary_gen.scan.survey import evenly_spaced, shelf_books, survey_pages
from glossary_gen.scan.toc import TocError, discover, get_toc

# Gemini bills roughly one token per four characters of English prose. Used only to turn
# a sample's own page text into a forecast, never to bound a run — `--budget-usd` does that.
CHARS_PER_TOKEN = 4
COLUMNS = ["title", "url", "pages", "sampled", "with_glossary", "terms_in_sample", "forecast_usd"]


def forecast_usd(page_chars: float, pages: int, model: str) -> float | None:
    """Scan cost projected from measured page text rather than a fixed constant."""
    entry = load_prices(PRICES_PATH).get(model)
    if not entry:
        return None
    tokens_in = page_chars / CHARS_PER_TOKEN * pages
    # Output is small and stable across both measured books (98-124 tokens per page).
    tokens_out = 125 * pages
    spend = tokens_in * entry["input_per_mtok"] + tokens_out * entry["output_per_mtok"]
    return spend / 1_000_000


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--shelf", action="append", default=[], help="bookshelf URL (repeatable)")
    ap.add_argument("--book", action="append", default=[], help="book URL (repeatable)")
    ap.add_argument("--sample", type=int, default=16, help="pages to fetch per book")
    ap.add_argument("--cache", type=Path, default=Path("cache"))
    ap.add_argument("--delay", type=float, default=0.3)
    ap.add_argument("--model", default="gemini-3.7-flash")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    client = build_http_client()
    books: list[tuple[str, str]] = [("", url) for url in args.book]
    for shelf in args.shelf:
        try:
            books.extend(shelf_books(get_toc(shelf, client)))
        except TocError as exc:
            print(f"shelf skipped: {exc}", file=sys.stderr)
    if not books:
        print("nothing to survey: pass --shelf or --book", file=sys.stderr)
        return 1

    cache = PageCache(args.cache, client, delay=args.delay)
    rows = []
    for title, url in books:
        try:
            book, urls = discover(url, client, cache)
        except TocError as exc:
            print(f"  skipped {title or url}: {exc}", file=sys.stderr)
            continue

        fetched = []
        for page_url in evenly_spaced(urls, args.sample):
            try:
                fetched.append((page_url, cache.get_html(page_url)))
            except FetchError:
                continue
        result = survey_pages(fetched)

        # Page text, not raw HTML: the scanner sends blocks, and chrome is most of a page.
        text_chars = [
            sum(len(block.text) for block in parse_page(page_url, html).blocks)
            for page_url, html in fetched
        ]
        mean_chars = sum(text_chars) / len(text_chars) if text_chars else 0
        cost = forecast_usd(mean_chars, len(urls), args.model)

        rows.append(
            {
                "title": book.title or title,
                "url": url,
                "pages": len(urls),
                "sampled": result.sampled,
                "with_glossary": result.with_glossary,
                "terms_in_sample": result.terms,
                "forecast_usd": "" if cost is None else f"{cost:.3f}",
            }
        )
        marker = "GLOSSARY" if result.with_glossary else "        "
        print(
            f"  {marker}  {result.with_glossary:2d}/{result.sampled:2d} sampled pages, "
            f"{result.terms:3d} terms, {len(urls):3d} pages, "
            f"~${cost:.2f}  {book.title or title}"
        )

    if args.out:
        with args.out.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        print(f"\nwrote {args.out}")

    carriers = [r for r in rows if r["with_glossary"]]
    print(f"\n{len(carriers)} of {len(rows)} surveyed books carry an author glossary")
    print("A sample says a book HAS blocks; only a full harvest says how many terms.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
