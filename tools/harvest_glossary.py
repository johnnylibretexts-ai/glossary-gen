"""Harvest a book's own author glossary, and score a scan against it.

    python3 tools/harvest_glossary.py --scan out/stats-scan.jsonl --index out/stats-index.json
    python3 tools/harvest_glossary.py --book https://ecampusontario.pressbooks.pub/<slug>/

Two ways in, and neither spends anything. `--scan` reads only the on-disk HTML cache a
scan already populated: no network, no API key. `--book` reads a book nobody has
scanned, fetching its pages once through the same cache — harvesting an author glossary
is parsing rather than inference, so a book that publishes one is worth harvesting
BEFORE deciding whether to pay to scan it, not only after. Writes the reference set to
`--out` when asked, and prints what a scanner did against it when given `--index`.

Recall against this set is a real measurement. The terms the scanner proposed that
are *absent* from it are NOT cuts — only some pages of a book carry glossary blocks,
so absence is silence. The report says so on every run rather than trusting whoever
reads it to remember.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from urllib.parse import urlsplit

from glossary_gen.cli import build_http_client
from glossary_gen.fetch import FetchError, PageCache, cache_path
from glossary_gen.models import slugify
from glossary_gen.scan.reference import book_glossary, coverage
from glossary_gen.scan.toc import TocError, discover


def page_urls(scan_jsonl: Path) -> list[str]:
    """Every page the scan visited, in order, deduplicated."""
    seen: dict[str, None] = {}
    for line in scan_jsonl.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        url = json.loads(line).get("page_url")
        if url:
            seen.setdefault(url, None)
    return list(seen)


def cached_pages(urls: list[str], cache_dir: Path) -> tuple[list[tuple[str, str]], list[str]]:
    pages, absent = [], []
    for url in urls:
        path = cache_path(cache_dir, url)
        if path.exists():
            pages.append((url, path.read_text(encoding="utf-8", errors="replace")))
        else:
            absent.append(url)
    return pages, absent


def book_pages(
    book_url: str, cache_dir: Path, delay: float
) -> tuple[list[tuple[str, str]], list[str]]:
    """Every page of a book, fetched once and thereafter served from the cache.

    Through `PageCache`, so the harvest inherits the politeness delay, the retries, the
    size cap and the allowlist — widened, as everywhere else, by the one host the person
    running this named. A page that will not load is reported rather than skipped
    silently: an author glossary harvested from a book read short is a reference set with
    a hole in it, and every recall figure measured against it would be wrong downward.
    """
    client = build_http_client()
    cache = PageCache(cache_dir, client, delay=delay, source_host=urlsplit(book_url).hostname or "")
    _, urls = discover(book_url, client, cache)
    pages, absent = [], []
    for url in urls:
        try:
            pages.append((url, cache.get_html(url)))
        except FetchError:
            absent.append(url)
    return pages, absent


def scanned_slugs(index_json: Path) -> set[str]:
    """Index slugs plus alias slugs — an author term the scanner recorded as an
    alias was still found, and scoring it as missing would understate recall.
    """
    index = json.loads(index_json.read_text(encoding="utf-8"))
    terms = index["terms"] if isinstance(index, dict) else index
    slugs = set()
    for term in terms:
        slugs.add(slugify(term["term"]))
        slugs.update(slugify(alias) for alias in term.get("aliases", []))
    return slugs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    source = ap.add_mutually_exclusive_group(required=True)
    source.add_argument("--scan", type=Path, help="the run's scan.jsonl, read from the cache")
    source.add_argument("--book", help="a book URL, fetched (free) instead of scanned")
    ap.add_argument("--cache", type=Path, default=Path("cache"))
    ap.add_argument("--delay", type=float, default=0.5, help="politeness delay, --book only")
    ap.add_argument("--index", type=Path, help="index.json to score against")
    ap.add_argument("--out", type=Path, help="write the reference set here as CSV")
    ap.add_argument("--show", type=int, default=15, help="how many missing terms to print")
    args = ap.parse_args()

    if args.book:
        try:
            pages, absent = book_pages(args.book, args.cache, args.delay)
        except TocError as exc:
            # A URL that is not a readable book — a stale slug, a page that is not a
            # book, a host with no table of contents this tool understands. The other
            # two callers of `discover` report it; a traceback here would read as a bug
            # in the harvester rather than as a wrong URL.
            print(f"error: {exc}", file=sys.stderr)
            return 1
        shortfall = "would not load"
    else:
        urls = page_urls(args.scan)
        pages, absent = cached_pages(urls, args.cache)
        shortfall = "not in cache (re-run the scan to refill)"
    entries = book_glossary(pages)
    with_glossary = sum(1 for url, html in pages if book_glossary([(url, html)]))

    print(f"pages read         {len(pages) + len(absent)}")
    if absent:
        print(f"  {len(absent)} {shortfall}")
    print(f"pages with an author glossary  {with_glossary}")
    print(f"author glossary terms          {len(entries)}")
    # Not every term arrives with words attached. Pressbooks serves an EMPTY
    # `<template>` for a term whose definition the authors never wrote, and 65 of
    # *Research Methods in Psychology*'s 243 terms are that. They still belong in the
    # set — the book marks them as terms it defines, and recall is scored on slugs —
    # but a set a quarter of which cannot be compared against is a fact the person
    # reading the count above should be given, not one they discover in the CSV.
    defined = sum(1 for entry in entries if entry.definition.strip())
    if defined != len(entries):
        print(f"  of those, with a definition  {defined}")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["slug", "term", "definition", "page"])
            for entry in entries:
                writer.writerow([entry.slug, entry.term, entry.definition, entry.page])
        print(f"wrote {args.out}")

    if args.index:
        found = scanned_slugs(args.index)
        report = coverage(entries, found)
        print(f"\nscanner slugs (incl. aliases)  {len(found)}")
        print(f"author terms the scanner found {report.found}/{report.total} = {report.rate:.1%}")
        if report.missing:
            shown = report.missing[: args.show]
            print(f"\nmissed ({len(report.missing)}), first {len(shown)}:")
            by_slug = {e.slug: e for e in entries}
            for slug in shown:
                print(f"  {by_slug[slug].term}")
        extra = len(found - {e.slug for e in entries})
        print(f"\nscanner slugs absent from the author glossary: {extra}")
        print("  Not cuts. Only some pages carry glossary blocks, so absence is silence:")
        print("  this set grades recall, and says nothing about whether a term belongs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
