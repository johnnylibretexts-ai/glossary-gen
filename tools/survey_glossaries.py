"""Find which books publish their own glossary. Free — no model is called.

    python3 tools/survey_glossaries.py --shelf https://stats.libretexts.org/Bookshelves/Introductory_Statistics
    python3 tools/survey_glossaries.py --network https://ecampusontario.pressbooks.pub --books 80
    python3 tools/survey_glossaries.py --book <url> --book <url> --out survey.csv

Fetching costs nothing but politeness, so the question that decides whether a book can
be measured at all — does it carry an author-written glossary — is answered before any
scan is paid for.

What that costs, and what the answer is worth, depends on the platform; `scan.survey`
explains the split. In short, a LibreTexts book is screened on a sample and its zero
means "no evidence at N pages", while a Pressbooks book is screened exactly and its
zero means no glossary. The `settled` column is where a row says which it is.

The token forecast printed per book is measured from the pages read, not from a
constant, and only where those pages are a fair sample of the book. `EST_SCAN_TOKENS_IN`
is calibrated to one book and was 3x low on the statistics pages — see
docs/research/2026-08-17-definition-comparison.md.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from glossary_gen.article import extract_content
from glossary_gen.cli import build_http_client
from glossary_gen.fetch import PageCache, parse_page
from glossary_gen.run import PRICES_PATH, load_prices
from glossary_gen.scan.survey import Screen, network_books, screen, shelf_books
from glossary_gen.scan.toc import TocError, get_toc

# Gemini bills roughly one token per four characters of English prose. Used only to turn
# a sample's own page text into a forecast, never to bound a run — `--budget-usd` does that.
CHARS_PER_TOKEN = 4
COLUMNS = ["title", "url", "pages", "read", "with_glossary", "terms", "settled", "forecast_usd"]


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


def book_forecast(found: Screen, model: str) -> float | None:
    """What scanning this book would cost, where the pages read can say.

    None where they cannot. A Pressbooks carrier settled by its glossary page was never
    walked, and one stopped at its third page read the front matter — projecting a whole
    book from either would print a number with nothing behind it.
    """
    if not (found.spans_book and found.pages):
        return None
    # Narrowed to the article first, exactly as `scan_cli.collect_pages` does before it
    # parses. Counting the whole document instead measures the chrome as though a scan
    # would pay for it, and on Pressbooks the chrome is the whole book: the theme
    # repeats every chapter title on every page, one `<p>` each, so a 77-page book
    # forecasts a 77-line table of contents 77 times over.
    text_chars = [
        sum(len(block.text) for block in parse_page(url, extract_content(html)).blocks)
        for url, html in found.fetched
    ]
    if not text_chars:
        return None
    return forecast_usd(sum(text_chars) / len(text_chars), found.pages, model)


def verdict(found: Screen) -> str:
    """What this row settles, in the width the run prints it."""
    if found.result.terms:
        return "GLOSSARY   "
    return "no glossary" if found.result.settled else "no evidence"


def collect_books(args: argparse.Namespace, client: httpx.Client) -> list[tuple[str, str]]:
    """Every book to screen, from the enumerator each platform offers."""
    books: list[tuple[str, str]] = [("", url) for url in args.book]
    for shelf in args.shelf:
        try:
            books.extend(shelf_books(get_toc(shelf, client)))
        except TocError as exc:
            print(f"shelf skipped: {exc}", file=sys.stderr)
    for network in args.network:
        try:
            sweep = network_books(network, client, limit=args.books)
        except TocError as exc:
            print(f"network skipped: {exc}", file=sys.stderr)
            continue
        # Said before the fetching starts, because `--books 0` is every book on the
        # network and a Pressbooks screen walks each one. eCampusOntario is 3,033 books,
        # which is a day of polite fetching rather than the half hour 20 books takes.
        off_host = (
            f" ({sweep.off_host} listed entries are on another host)" if sweep.off_host else ""
        )
        print(f"{network}: screening {len(sweep.books)} books{off_host}")
        books.extend(sweep.books)
    return books


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--shelf", action="append", default=[], help="bookshelf URL (repeatable)")
    ap.add_argument(
        "--network", action="append", default=[], help="Pressbooks network URL (repeatable)"
    )
    ap.add_argument(
        "--books",
        type=int,
        default=0,
        help="books per network, spread across its catalogue (0 = every book on it)",
    )
    ap.add_argument("--book", action="append", default=[], help="book URL (repeatable)")
    ap.add_argument("--sample", type=int, default=16, help="pages to fetch per LibreTexts book")
    ap.add_argument("--cache", type=Path, default=Path("cache"))
    ap.add_argument("--delay", type=float, default=0.3)
    ap.add_argument("--model", default="gemini-3.7-flash")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    client = build_http_client()
    books = collect_books(args, client)
    if not books:
        print("nothing to survey: pass --shelf, --network or --book", file=sys.stderr)
        return 1

    rows = []
    for title, url in books:
        # A cache per book, because its source host is the book's own. `is_allowed_url`
        # widens by exactly one host — the one a person named — and a sweep names a
        # different one per book. Sharing one cache across a mixed list would either
        # refuse every book but the first or, if opened wider, stop being a guard.
        cache = PageCache(
            args.cache, client, delay=args.delay, source_host=urlsplit(url).hostname or ""
        )
        try:
            found = screen(url, client, cache, sample=args.sample)
        except TocError as exc:
            print(f"  skipped {title or url}: {exc}", file=sys.stderr)
            continue

        cost = book_forecast(found, args.model)
        result = found.result
        # The URL is the last resort, and a real case rather than a defensive one: a
        # book settled by its glossary page is never discovered, so it has no title of
        # its own, and `--book` supplies none either. A network sweep does.
        label = found.title or title or url
        rows.append(
            {
                "title": found.title or title,
                "url": url,
                # Blank, not 0: a book settled by its glossary page was never walked,
                # and 0 would read as a book with no pages.
                "pages": found.pages or "",
                "read": result.sampled,
                "with_glossary": result.with_glossary,
                "terms": result.terms,
                "settled": "yes" if result.settled else "no",
                "forecast_usd": "" if cost is None else f"{cost:.3f}",
            }
        )
        print(
            f"  {verdict(found)}  {result.terms:4d} terms, "
            f"{result.sampled:3d} of {found.pages or '?':>4} pages read, "
            f"{'         ' if cost is None else f'~${cost:6.2f}'}  {label}"
        )

    if args.out:
        with args.out.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        print(f"\nwrote {args.out}")

    carriers = [r for r in rows if r["terms"]]
    unsettled = [r for r in rows if r["settled"] == "no"]
    print(f"\n{len(carriers)} of {len(rows)} surveyed books carry an author glossary")
    print(f"{len(rows) - len(carriers) - len(unsettled)} settled as having none.")
    if unsettled:
        print(
            f"{len(unsettled)} inconclusive: a sample says a book HAS blocks, never that "
            "it has none."
        )
    if carriers:
        print("A carrier's term count is a floor: only the pages read are counted, and a")
        print("screen stops as soon as the book is settled. A harvest says how many it has.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
