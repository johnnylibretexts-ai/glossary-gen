from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import httpx

from glossary_gen.csv_out import write_csv
from glossary_gen.excerpt import excerpts_for_term
from glossary_gen.fetch import FetchError, PageCache
from glossary_gen.generate import generate_entry, load_prompt, prompt_versions
from glossary_gen.input import InputError, load_input
from glossary_gen.ledger import Ledger, LedgerRecord
from glossary_gen.llm import (
    GeminiClient,
    LLMClient,
    LLMError,
    OpenAICompatClient,
    ProviderChain,
)
from glossary_gen.models import Book, Page, Term

from glossary_gen.run import (
    Attempt,
    ModelCall,
    # Moved to `run`, which is what prices real spend, and re-exported here because callers
    # import it from this module. Moving a name is not a reason to break them.
    actual_cost,  # noqa: F401
    execute_run,
    load_prices,
)

EXIT_OK = 0
EXIT_INPUT_ERROR = 2
EXIT_RUN_ABORTED = 3

# Rough per-term shape used only for the pre-run estimate.
EST_TOKENS_IN = 1200
EST_TOKENS_OUT = 220

USER_AGENT = "glossary-gen/0.1 (+https://github.com/johnnylibretexts/glossary-gen)"


@dataclass
class CoverageReport:
    total: int = 0
    with_excerpts: int = 0
    without_excerpts: int = 0
    failed_pages: list[str] = field(default_factory=list)
    missing_terms: list[str] = field(default_factory=list)


@dataclass
class RunSummary:
    ok: int = 0
    no_excerpt: int = 0
    fetch_error: int = 0
    llm_error: int = 0
    skipped: int = 0
    aborted: bool = False


def estimate_cost(model: str, term_count: int, prices: dict[str, dict[str, float]]) -> float | None:
    """USD estimate from the flat per-term guess, or None when the model has no configured
    price. For the pre-run gate only, where no actuals exist yet — see `actual_cost` for
    the mid-run check, which prices real accumulated token counts instead.
    """
    entry = prices.get(model)
    if not entry:
        return None
    per_term = (
        EST_TOKENS_IN * entry["input_per_mtok"] + EST_TOKENS_OUT * entry["output_per_mtok"]
    ) / 1_000_000
    return per_term * term_count


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_client(args: argparse.Namespace) -> LLMClient:
    """Gemini first when a key is present; an OpenAI-compatible endpoint as fallback."""
    clients: list[LLMClient] = []
    gemini_key = os.environ.get("GLOSSARY_GEN_GEMINI_API_KEY")
    if gemini_key:
        clients.append(GeminiClient(api_key=gemini_key, model=args.model))
    base_url = os.environ.get("GLOSSARY_GEN_OPENAI_BASE_URL")
    if base_url:
        clients.append(
            OpenAICompatClient(
                base_url=base_url,
                model=os.environ.get("GLOSSARY_GEN_OPENAI_MODEL", "llama3.1"),
                api_key=os.environ.get("GLOSSARY_GEN_OPENAI_API_KEY"),
            )
        )
    if not clients:
        raise InputError(
            "no provider configured: set GLOSSARY_GEN_GEMINI_API_KEY "
            "or GLOSSARY_GEN_OPENAI_BASE_URL"
        )
    return ProviderChain(clients)


def execute(
    terms: Sequence[Term],
    cache: PageCache,
    client: LLMClient,
    ledger: Ledger,
    template: str,
    prompt_version: str,
    *,
    max_consecutive_failures: int = 5,
    budget_usd: float | None = None,
) -> RunSummary:
    """Generate one entry per term, recording every outcome in the ledger.

    An adapter over `execute_run`: everything about spend, resumption and stopping lives
    there, and everything about what a term's row contains lives here.
    """
    summary = RunSummary()

    def attempt(term: Term) -> Attempt:
        failed_pages: list[str] = []
        pages = collect_pages(term, cache, failed_pages)
        base = {
            "subject": term.slug,
            "term": term.term,
            "prompt_version": prompt_version,
            "model": client.model,
            "provider": getattr(client, "name", ""),
            "generated_at": _now(),
            "pages": list(term.pages),
        }

        # Unfetchable pages and pages with no usable excerpt both end the term before any
        # model is asked about it. They cost nothing, and they say nothing about whether the
        # provider is healthy, so `NOT_MADE` leaves the failure counter exactly as it was.
        if not pages:
            summary.fetch_error += 1
            return Attempt(
                record=LedgerRecord(**base, status="fetch_error", error="; ".join(failed_pages)),
                model_call=ModelCall.NOT_MADE,
            )

        excerpts = excerpts_for_term(pages, term)
        if not excerpts:
            summary.no_excerpt += 1
            return Attempt(
                record=LedgerRecord(**base, status="no_excerpt"),
                model_call=ModelCall.NOT_MADE,
            )

        try:
            result = generate_entry(client, template, term, excerpts)
        except LLMError as exc:  # base class of LLMTransportError and LLMStructuredOutputError
            # A failed term still cost real, billed tokens: every attempt that reached a
            # reply was a paid call, even though it ended in a schema error and got retried.
            # `generate_entry` attaches the accumulated total to `LLMStructuredOutputError`.
            # A bare `LLMTransportError` never gets that far (raised before any reply
            # exists), so `getattr` with a 0 default is correct there, not a workaround.
            # The counts go on the record because that is what the run charges.
            summary.llm_error += 1
            return Attempt(
                record=LedgerRecord(
                    **base,
                    status="llm_error",
                    error=str(exc),
                    tokens_in=getattr(exc, "tokens_in", 0),
                    tokens_out=getattr(exc, "tokens_out", 0),
                ),
                model_call=ModelCall.FAILED,
            )

        summary.ok += 1
        entry = result.entry
        return Attempt(
            record=LedgerRecord(
                # `model` stays the chain's DECLARED primary (already in `base`) so the
                # resume key matches what ledger.has() looks up. `served_by_model` records
                # which model actually answered. Overriding `model` here would write a
                # fallback-served term under a key its own lookup can never find, and it
                # would regenerate and re-bill on every later run.
                **{**base, "provider": result.provider},
                status="ok",
                served_by_model=result.model,
                definition=entry.definition,
                x_category=entry.category,
                x_context=entry.context,
                x_example=entry.example,
                x_related=entry.related,
                aliases=sorted({*term.aliases, *entry.aliases}),
                source_pages=sorted({e.page_url for e in excerpts}),
                excerpt_chars=sum(len(e.text) for e in excerpts),
                tokens_in=result.tokens_in,
                tokens_out=result.tokens_out,
            ),
            model_call=ModelCall.ANSWERED,
        )

    outcome = execute_run(
        terms,
        ledger,
        subject_of=lambda term: term.slug,
        attempt=attempt,
        prompt_version=prompt_version,
        model=client.model,
        budget_usd=budget_usd,
        max_consecutive_failures=max_consecutive_failures,
    )
    summary.skipped = outcome.skipped
    summary.aborted = outcome.aborted
    return summary


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


def _positive_int(value: str) -> int:
    """argparse type for --max-terms: 0 or negative reads as "no limit" if left as a plain
    int, which is the opposite of what a value that low should mean — reject it instead.
    """
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError(f"must be a positive integer, got {value!r}")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="glossary-gen",
        description="Generate page-grounded glossary definitions for a LibreTexts book.",
    )
    parser.add_argument(
        "--input", required=True, type=Path, help="step-1 index file (.json or .csv)"
    )
    parser.add_argument(
        "--out", type=Path, default=Path("out/glossary.csv"), help="output CSV path"
    )
    parser.add_argument(
        "--cache-dir", type=Path, default=Path("cache"), help="page cache directory"
    )
    parser.add_argument(
        "--ledger", type=Path, default=Path("out/run.jsonl"), help="run ledger path"
    )
    parser.add_argument("--prompt-version", default="v1", choices=prompt_versions())
    parser.add_argument("--model", default="gemini-3.5-flash", help="Gemini model name")
    parser.add_argument("--library", help="overrides the input file's book block")
    parser.add_argument("--cover-id", help="overrides the input file's book block")
    parser.add_argument("--book-id", help="overrides the input file's book block")
    parser.add_argument(
        "--max-terms", type=_positive_int, help="process at most N terms (smoke runs)"
    )
    parser.add_argument(
        "--budget-usd", type=float, help="abort if the estimated spend exceeds this"
    )
    parser.add_argument("--yes", action="store_true", help="skip the cost confirmation prompt")
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


def _resolve_book(parsed_book: Book | None, args: argparse.Namespace) -> Book:
    library = args.library or (parsed_book.library if parsed_book else None)
    cover_id = args.cover_id or (parsed_book.cover_id if parsed_book else None)
    book_id = args.book_id or (parsed_book.book_id if parsed_book else None)
    missing = [
        name
        for name, value in (
            ("--library", library),
            ("--cover-id", cover_id),
            ("--book-id", book_id),
        )
        if not value
    ]
    if missing:
        raise InputError(f"missing book identity: supply {', '.join(missing)} or a book block")
    return Book(
        library=library,
        cover_id=cover_id,
        book_id=book_id,
        title=parsed_book.title if parsed_book else "",
        index_url=parsed_book.index_url if parsed_book else "",
    )


def run(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        parsed = load_input(args.input)
    except InputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_INPUT_ERROR

    terms = parsed.terms[: args.max_terms] if args.max_terms else parsed.terms
    cache = PageCache(args.cache_dir, build_http_client())

    if args.dry_run:
        _print_coverage(dry_run(terms, cache))
        return EXIT_OK

    try:
        book = _resolve_book(parsed.book, args)
        client = build_client(args)
    except InputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_INPUT_ERROR

    estimate = estimate_cost(client.model, len(terms), load_prices())
    if estimate is None:
        if args.budget_usd is not None:
            # The human partner has ruled: an explicit ceiling the tool cannot verify
            # is not a ceiling — refuse to start rather than silently ignore it.
            print(
                f"error: --budget-usd was given but {client.model} has no configured "
                "price; add it to glossary_gen/prices.json or drop --budget-usd",
                file=sys.stderr,
            )
            return EXIT_INPUT_ERROR
        print(
            f"warning: no price configured for {client.model}; --budget-usd is disabled",
            file=sys.stderr,
        )
    else:
        print(f"{len(terms)} terms, estimated ~${estimate:.2f}")
        if args.budget_usd is not None and estimate > args.budget_usd:
            print(
                f"error: estimate ${estimate:.2f} exceeds --budget-usd {args.budget_usd:.2f}",
                file=sys.stderr,
            )
            return EXIT_INPUT_ERROR
    if (
        not args.yes
        and sys.stdin.isatty()
        and input("proceed? [y/N] ").strip().casefold() not in {"y", "yes"}
    ):
        print("aborted by user")
        return EXIT_OK

    ledger = Ledger(args.ledger)
    if ledger.skipped_lines:
        print(f"note: skipped {ledger.skipped_lines} unreadable ledger line(s)")

    summary = execute(
        terms,
        cache,
        client,
        ledger,
        load_prompt(args.prompt_version),
        args.prompt_version,
        budget_usd=args.budget_usd,
    )

    written = write_csv(
        args.out,
        ledger.records(),
        book,
        prompt_version=args.prompt_version,
        model=client.model,
        slugs={t.slug for t in parsed.terms},
    )
    print(
        f"ok={summary.ok} no_excerpt={summary.no_excerpt} "
        f"fetch_error={summary.fetch_error} llm_error={summary.llm_error} skipped={summary.skipped}"
    )
    print(f"wrote {written} row(s) to {args.out}")
    if summary.aborted:
        print("error: run aborted early — see the ledger", file=sys.stderr)
        return EXIT_RUN_ABORTED
    return EXIT_OK


if __name__ == "__main__":  # `python -m glossary_gen.cli`
    raise SystemExit(run())
