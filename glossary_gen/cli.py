from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from glossary_gen.excerpt import excerpts_for_term
from glossary_gen.fetch import FetchError, PageCache
from glossary_gen.input import InputError, load_input
from glossary_gen.models import Page, Term

EXIT_OK = 0
EXIT_INPUT_ERROR = 2

USER_AGENT = "glossary-gen/0.1 (+https://github.com/johnnylibretexts/glossary-gen)"


@dataclass
class CoverageReport:
    total: int = 0
    with_excerpts: int = 0
    without_excerpts: int = 0
    failed_pages: list[str] = field(default_factory=list)
    missing_terms: list[str] = field(default_factory=list)


def build_http_client() -> httpx.Client:
    return httpx.Client(headers={"User-Agent": USER_AGENT})


def collect_pages(term: Term, cache: PageCache, failed: list[str]) -> list[Page]:
    pages: list[Page] = []
    for url in term.pages:
        try:
            pages.append(cache.get(url))
        except FetchError:
            if url not in failed:
                failed.append(url)
    return pages


def dry_run(terms: Sequence[Term], cache: PageCache) -> CoverageReport:
    """Fetch and excerpt every term without calling any model."""
    report = CoverageReport(total=len(terms))
    for term in terms:
        pages = collect_pages(term, cache, report.failed_pages)
        if pages and excerpts_for_term(pages, term):
            report.with_excerpts += 1
        else:
            report.without_excerpts += 1
            report.missing_terms.append(term.slug)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="glossary-gen",
        description="Generate page-grounded glossary definitions for a LibreTexts book.",
    )
    parser.add_argument(
        "--input", required=True, type=Path, help="step-1 index file (.json or .csv)"
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path("cache"),
        help="page cache directory",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="fetch and excerpt only; call no model, spend nothing, need no API key",
    )
    return parser


def _print_coverage(report: CoverageReport) -> None:
    print(f"terms total: {report.total}")
    print(f"terms with excerpts: {report.with_excerpts}")
    print(f"terms without: {report.without_excerpts}")
    print(f"pages failed: {len(report.failed_pages)}")
    for url in report.failed_pages:
        print(f"  ! {url}")
    if report.missing_terms:
        preview = ", ".join(report.missing_terms[:20])
        suffix = " ..." if len(report.missing_terms) > 20 else ""
        print(f"terms with no excerpt: {preview}{suffix}")
    print("dry run: no model was called and nothing was spent")


def run(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        parsed = load_input(args.input)
    except InputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_INPUT_ERROR

    client = build_http_client()
    cache = PageCache(args.cache_dir, client)

    if args.dry_run:
        _print_coverage(dry_run(parsed.terms, cache))
        return EXIT_OK

    print("error: only --dry-run is implemented so far", file=sys.stderr)
    return EXIT_INPUT_ERROR
