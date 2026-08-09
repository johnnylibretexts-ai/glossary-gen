from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

# Reused, not re-declared. The two entry points share one process contract: same exit
# codes, same User-Agent, same provider construction. Copying them would give the project
# two sources of truth for values that must agree.
from glossary_gen.cli import (
    EXIT_INPUT_ERROR,
    EXIT_OK,
    EXIT_RUN_ABORTED,
    build_http_client,
)
from glossary_gen.fetch import FetchError, PageCache
from glossary_gen.models import Page
from glossary_gen.scan.propose import scan_prompt_versions
from glossary_gen.scan.toc import TocError, discover

# Preview-only. These are OpenStax template artifacts, so they must never reach the scoring
# path — filtering them there would break the "any LibreTexts book" requirement. Here they
# only keep the free preview legible; on a non-OpenStax book the preview is simply noisier,
# which costs nothing and misleads no one.
_BOILERPLATE = re.compile(
    r"^(learning objectives|concepts in practice|answer|try it|check your understanding"
    r"|summary|key terms|exercises?|glossary|references?)\b",
    re.IGNORECASE,
)
_PAGEINDEX = re.compile(r"\\\(.*?\\\)")


@dataclass
class PreviewReport:
    pages: int = 0
    fetch_errors: list[str] = field(default_factory=list)
    candidates: list[str] = field(default_factory=list)


def structural_preview(pages: Sequence[Page]) -> PreviewReport:
    """Heading-derived candidates, no model and no key. The free `--dry-run` tier."""
    report = PreviewReport(pages=len(pages))
    for page in pages:
        for block in page.blocks:
            if block.kind != "heading":
                continue
            text = _PAGEINDEX.sub("", block.text).strip()
            if not text or _BOILERPLATE.match(text) or text in report.candidates:
                continue
            report.candidates.append(text)
    return report


def collect_pages(urls: Sequence[str], cache: PageCache, failed: list[str]) -> list[Page]:
    pages: list[Page] = []
    for url in urls:
        try:
            pages.append(cache.get(url))
        except FetchError as exc:
            failed.append(f"{url}: {exc}")
    return pages


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="glossary-scan",
        description="Build a term index for a LibreTexts book, for glossary-gen to consume.",
    )
    parser.add_argument("--book", required=True, help="book root URL on *.libretexts.org")
    parser.add_argument("--out", type=Path, default=Path("out/index.json"), help="index path")
    parser.add_argument(
        "--report", type=Path, default=Path("out/index-report.json"), help="score sidecar path"
    )
    parser.add_argument("--cache-dir", type=Path, default=Path("cache"), help="page cache dir")
    parser.add_argument("--ledger", type=Path, default=Path("out/scan.jsonl"), help="ledger path")
    parser.add_argument("--prompt-version", default="v1", choices=scan_prompt_versions())
    parser.add_argument("--model", default="gemini-3.5-flash", help="Gemini model name")
    parser.add_argument(
        "--min-score",
        type=float,
        default=0.0,
        help="omit terms scoring below this (default 0.0: emit everything, trim by hand)",
    )
    parser.add_argument("--limit", type=int, help="scan at most N pages (smoke runs)")
    parser.add_argument(
        "--delay", type=float, default=0.3, help="seconds between real page fetches"
    )
    parser.add_argument("--budget-usd", type=float, help="abort if spend exceeds this")
    parser.add_argument("--yes", action="store_true", help="skip the cost confirmation prompt")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="walk the book and report structural candidates; call no model, spend nothing",
    )
    return parser


def run(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    client = build_http_client()
    try:
        book, urls = discover(args.book, client)
    except TocError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_INPUT_ERROR

    if args.limit:
        urls = urls[: args.limit]

    cache = PageCache(args.cache_dir, client, delay=args.delay)
    failed: list[str] = []
    pages = collect_pages(urls, cache, failed)

    if args.dry_run:
        report = structural_preview(pages)
        print(f"book:       {book.title} ({book.library}/{book.cover_id})")
        print(f"pages:      {report.pages} fetched, {len(failed)} failed")
        print(f"candidates: {len(report.candidates)} structural (headings, boilerplate removed)")
        for text in report.candidates[:20]:
            print(f"  - {text}")
        if len(report.candidates) > 20:
            print(f"  ... and {len(report.candidates) - 20} more")
        print("\nThis is a free preview. Structural candidates are NOT the scanner's output —")
        print("a real run reads each page with a model and scores what it finds.")
        return EXIT_OK

    print("error: a full run is not implemented yet; use --dry-run", file=sys.stderr)
    return EXIT_RUN_ABORTED
