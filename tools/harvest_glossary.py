"""Harvest a scanned book's own author glossary and score the scan against it.

    python3 tools/harvest_glossary.py --scan out/stats-scan.jsonl --index out/stats-index.json

Reads only the on-disk HTML cache the scan already populated: no network, no API
key, no cost. Writes the reference set to `--out` when asked, and prints what the
scanner did against it.

Recall against this set is a real measurement. The terms the scanner proposed that
are *absent* from it are NOT cuts — only some pages of a book carry glossary blocks,
so absence is silence. The report says so on every run rather than trusting whoever
reads it to remember.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from glossary_gen.fetch import cache_path
from glossary_gen.models import slugify
from glossary_gen.scan.reference import book_glossary, coverage


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
    ap.add_argument("--scan", type=Path, required=True, help="the run's scan.jsonl")
    ap.add_argument("--cache", type=Path, default=Path("cache"))
    ap.add_argument("--index", type=Path, help="index.json to score against")
    ap.add_argument("--out", type=Path, help="write the reference set here as CSV")
    ap.add_argument("--show", type=int, default=15, help="how many missing terms to print")
    args = ap.parse_args()

    urls = page_urls(args.scan)
    pages, absent = cached_pages(urls, args.cache)
    entries = book_glossary(pages)
    with_glossary = sum(1 for url, html in pages if book_glossary([(url, html)]))

    print(f"pages scanned      {len(urls)}")
    if absent:
        print(f"  not in cache     {len(absent)} (re-run the scan to refill)")
    print(f"pages with an author glossary  {with_glossary}")
    print(f"author glossary terms          {len(entries)}")

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
