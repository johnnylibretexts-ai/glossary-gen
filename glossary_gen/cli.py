from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit
from typing import Any

import httpx

from glossary_gen.article import extract_content
from glossary_gen.csv_out import write_csv, write_unwritten_csv
from glossary_gen.excerpt import excerpts_for_term
from glossary_gen.fetch import (
    ALLOWED_HOST_SUFFIX,
    FetchError,
    PageCache,
    is_allowed_url,
    parse_page,
)
from glossary_gen.generate import generate_entry, load_prompt, prompt_versions
from glossary_gen.input import InputError, load_input
from glossary_gen.ledger import Ledger, LedgerRecord
from glossary_gen.llm import (
    GeminiClient,
    LLMClient,
    LLMError,
    OpenAICompatClient,
    ProviderChain,
    RetryingClient,
)
from glossary_gen.models import Book, Page, Term, slugify

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

# Per-term shape used only for the pre-run estimate, measured rather than guessed: 210
# billed terms of Python Programming (OpenStax) on 2026-08-16 averaged 479 tokens in and
# 130 out (input p90 585, output p90 157 — generation is remarkably uniform, because the
# prompt is three excerpts under a fixed character budget and the reply is one entry).
#
# These are MEANS, deliberately. The estimate predicts a total across many terms, and the
# total's expectation is the count times the mean; per-term spread averages out over a book
# and a median or a p90 would bias the total. The previous 1200/220 were a guess, and ran
# 2.1x high — safe for a gate, but high enough that someone sizing a book would decline a
# run they could easily afford.
EST_TOKENS_IN = 500
EST_TOKENS_OUT = 130

# `Mozilla/5.0 (compatible; …)` is the bot convention Googlebot and bingbot use, and
# the prefix is what the filters in front of several Pressbooks installs look for: a
# bare "glossary-gen/0.1 (+url)" is refused 403 there, this is served 200. It still
# names the tool and where to complain, which claiming to be Chrome would not.
USER_AGENT = (
    "Mozilla/5.0 (compatible; glossary-gen/0.1; +https://github.com/johnnylibretexts/glossary-gen)"
)


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


def _can_be_asked() -> bool:
    """Whether there is a terminal to put a question to.

    `sys.stdin` is `None` when fd 0 is closed (`nohup cmd 0<&- &`, some daemon launches),
    raises `ValueError` once closed in-process, and raises `OSError` (`EBADF`) when it is
    bound to an already-detached descriptor — `isatty()` bottoms out in an ioctl on the
    raw fd. All three are the daemonised launches this guard exists for, so `isatty()`
    alone would turn exactly those into an uncaught traceback with an undefined exit code.

    No terminal is not the same as no answer: the caller decides what a missing terminal
    means, and both callers here treat it as "cannot consent", never as "proceed".
    """
    try:
        return sys.stdin is not None and sys.stdin.isatty()
    except (ValueError, OSError):
        return False


def refuse_unattended(args: argparse.Namespace) -> int | None:
    """Refuse a run whose consent can never be obtained. `None` means carry on.

    Called immediately after parsing, before any fetching, because whether consent is
    *possible* depends only on `--yes` and the terminal — never on the estimate. Deferring
    it to where the estimate exists would make a forgotten `--yes` crawl an entire book,
    minutes of traffic, before refusing; on a cron schedule it would do that every tick.

    `EXIT_INPUT_ERROR`, not `EXIT_RUN_ABORTED`: nothing started and nothing was spent, so
    this is a misconfigured invocation. Exit 3 promises a run that began and can be
    resumed from its ledger, and there is no ledger here.

    A dry run is never refused: it calls no model and spends nothing, so there is nothing
    to consent to. Both CLIs define `--dry-run`, and the check lives here rather than at
    the two call sites so they cannot drift on it.
    """
    if args.dry_run or args.yes or _can_be_asked():
        return None
    print(
        "error: refusing to spend without confirmation; pass --yes for an unattended run",
        file=sys.stderr,
    )
    return EXIT_INPUT_ERROR


def confirm_spend(args: argparse.Namespace) -> int | None:
    """Put the cost to the operator once it is known. `None` means proceed.

    Shared by both CLIs rather than written twice: ADR-0002 records that the last pair of
    copies of the spend logic drifted, and five of the eight fixes that followed were one
    fix applied twice.

    `input()` is never reached without a terminal — `refuse_unattended` has already
    returned by then — so this cannot raise EOFError and exit undefined. Declining is not
    a failure: it is a run that did exactly what was asked, hence `EXIT_OK`.

    Without a terminal it **refuses** rather than returning "proceed". That branch is
    unreachable through either CLI today, and it is written this way so it stays harmless
    if it ever becomes reachable: a helper whose money decision defaults to yes when it
    cannot ask is one reordering away from being the defect this pair was written to fix.
    """
    if args.yes:
        return None
    if not _can_be_asked():
        return refuse_unattended(args)
    if input("proceed? [y/N] ").strip().casefold() not in {"y", "yes"}:
        print("aborted by user")
        return EXIT_OK
    return None


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
    # Wrapped here, once, so a provider added later gets the retry policy by being listed
    # above and never has to implement it. `RetryingClient` forwards `name`/`model`, so the
    # chain's ledger keys are exactly what they were before it existed. See ADR-0003.
    return ProviderChain([RetryingClient(client) for client in clients])


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

    def attempt(term: Term, subject: str) -> Attempt:
        failed_pages: list[str] = []
        pages = collect_pages(term, cache, failed_pages)
        base = {
            # The subject the run keyed on, not `term.slug` recomputed: the row must land
            # under the key `ledger.has()` will look for, or it is re-paid for every resume.
            "subject": subject,
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

        excerpts, excerpt_chars = excerpts_for_term(pages, term)
        if not excerpts:
            # The grounding total goes on the row even though no definition was written:
            # 0 means the term never matched its own occurrence pages (an index defect),
            # while a total just under the floor means the book mentions it in passing and
            # the reviewer may want it anyway. See ADR-0006.
            summary.no_excerpt += 1
            return Attempt(
                record=LedgerRecord(**base, status="no_excerpt", excerpt_chars=excerpt_chars),
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
    """Fetch each of a term's occurrence pages, narrowed to its article.

    Narrowed with the same `extract_content` the scanner uses, and for the same reason:
    an excerpt is the raw material for explaining a term, so it has to come from what the
    book's authors wrote rather than from the site around it. Reading the whole rendered
    document instead was merely noisy on LibreTexts, where the chrome is a display-settings
    menu and a "Recommended articles" footer. It is not noise on Pressbooks, which repeats
    the book's entire table of contents on every page — one line per chapter, each a
    chapter title, which is exactly the shape a term needle matches. A definition grounded
    in a contents list is grounded in nothing, while `x_source_pages` still names the page.
    """
    pages: list[Page] = []
    for url in term.pages:
        try:
            pages.append(parse_page(url, extract_content(cache.get_html(url))))
        except FetchError:
            if url not in failed:
                failed.append(url)
    return pages


def widening_host(book: Book | None) -> str:
    """The one extra host this run may fetch from, or `""` for none.

    `is_allowed_url` widens by exactly this host and no further — the same rule
    `glossary-scan` applies to `--book`. It travels through the index because the book
    block is where the URL a person pasted into the scan is written down. A term's
    occurrence pages deliberately widen NOTHING: those are data a scan produced, not a
    book a person named. An index with no book block (every CSV, and a JSON one that
    omits it) therefore widens nothing and reaches only the standing allowlist, which is
    exactly where the guard stood before.

    The scheme is checked because this URL arrives inside a data file rather than from a
    command line, and index files are generated artifacts that get passed around. A
    plain-`http` `index_url` is refused a widening rather than having its host taken on
    trust: the guard `glossary-scan` applies to `--book` insists on https too, and the
    weaker provenance here is a reason to be stricter, not laxer.
    """
    if book is None:
        return ""
    parts = urlsplit(book.index_url)
    return parts.hostname or "" if parts.scheme == "https" else ""


def no_page_is_allowed(terms: Sequence[Term], source_host: str) -> str:
    """A refusal to state when not one page of the index can be fetched, else `""`.

    Checked before anything is fetched, because a whole index on an unreachable host is a
    misconfigured invocation rather than a run that went wrong: every term would end
    `fetch_error`, the CSV would be written with zero rows, and a `--yes` run in CI would
    report all of that and exit 0, which reads as "this book has no glossary terms". This
    is the same reasoning `scan_cli` applies when its table of contents yields no pages.

    Deliberately "not one", not "not all". A single unfetchable page among many is an
    ordinary partial failure that ADR-0006 already reports in the unwritten sidecar; only
    an index that cannot be read at all is a misconfiguration.
    """
    if any(is_allowed_url(url, host=source_host) for term in terms for url in term.pages):
        return ""
    named = f"; the index's book URL widens that by {source_host}" if source_host else ""
    return (
        f"no page in this index is on an allowed source (https on "
        f"*{ALLOWED_HOST_SUFFIX} or a named host{named}). "
        "An index whose book block has no https `index_url` widens nothing, so a book "
        "outside the standing allowlist must carry one."
    )


def forced_subjects(values: Sequence[str]) -> set[str]:
    """Normalise `--regenerate` values to subjects.

    Slugified rather than matched literally, so a reviewer can name what the CSV shows them
    — `Equality`, `__init__()` — instead of deriving the slug. `slugify` is idempotent, so
    passing a slug already works and both spellings resolve to the same subject.
    """
    return {slugify(value) for value in values if value.strip()}


def regeneration_rule(forced: Collection[str]) -> Callable[[Any], bool]:
    """A completion rule that treats named subjects as not-done, so they are re-attempted.

    Reuses the `is_done` hook ADR-0008 added for the scanner rather than inventing a second
    way to say "not finished". Deliberately per-subject: a blanket `--force` would re-pay
    for a whole book, which is the one thing this tool is built to avoid. It does not
    version generation policy (ADR-0009) — it re-attempts work someone named.
    """
    subjects = set(forced)

    def is_done(record: Any) -> bool:
        return record.status == "ok" and record.subject not in subjects

    return is_done


def unwritten_path(out: Path) -> Path:
    """`out/glossary.csv` -> `out/glossary.unwritten.csv`.

    Derived from `--out` rather than given its own flag: a file that always exists whenever
    `--out` does needs no knob, and a knob could be set to something inconsistent with it —
    the two halves of one run's report landing in different directories.
    """
    return out.with_suffix(".unwritten" + (out.suffix or ".csv"))


def dry_run(terms: Sequence[Term], cache: PageCache) -> CoverageReport:
    """Fetch and excerpt every term without calling any model."""
    report = CoverageReport(total=len(terms))
    for term in terms:
        pages = collect_pages(term, cache, report.failed_pages)
        if pages and excerpts_for_term(pages, term)[0]:
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
    parser.add_argument(
        # Changing this changes the ledger key: rows are keyed on (subject, prompt_version,
        # model), so an existing ledger built against another model has nothing this run
        # counts as done, and the whole book is re-attempted and re-paid for. That is
        # correct — a definition written by a different model is a different result — but
        # it is a bill, so it is stated in the README rather than discovered.
        "--model",
        default="gemini-3.7-flash",
        help="Gemini model name",
    )
    parser.add_argument("--library", help="overrides the input file's book block")
    parser.add_argument("--cover-id", help="overrides the input file's book block")
    parser.add_argument("--book-id", help="overrides the input file's book block")
    parser.add_argument(
        "--max-terms", type=_positive_int, help="process at most N terms (smoke runs)"
    )
    parser.add_argument(
        "--budget-usd", type=float, help="abort if the estimated spend exceeds this"
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="confirm the spend up front; required for a non-interactive run",
    )
    parser.add_argument(
        "--regenerate",
        type=lambda v: [p.strip() for p in v.split(",") if p.strip()],
        default=[],
        help="re-attempt these terms even if already done (comma-separated; term or slug)",
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

    # After reading the input, before touching the network. Both failures exit 2, so
    # refusing first would tell the operator of a CI job with a typo in --input to pass
    # --yes, which fixes nothing. `load_input` does no I/O beyond the local file, so the
    # run still does no work before consent is settled.
    if (refusal := refuse_unattended(args)) is not None:
        return refusal

    terms = parsed.terms[: args.max_terms] if args.max_terms else parsed.terms

    # Refuse a --regenerate value that matches nothing, rather than doing nothing quietly.
    # A typo's only other symptom is a definition that did not change, discovered after the
    # run has already been paid for. Values are slugified, so a misspelling becomes a
    # plausible-looking subject that simply never matches — which is why this check exists.
    forced = forced_subjects(args.regenerate)
    if unknown := sorted(forced - {term.slug for term in terms}):
        print(
            f"error: --regenerate named {len(unknown)} term(s) not in {args.input}: "
            f"{', '.join(unknown)}",
            file=sys.stderr,
        )
        return EXIT_INPUT_ERROR

    source_host = widening_host(parsed.book)
    if unreachable := no_page_is_allowed(terms, source_host):
        print(f"error: {unreachable}", file=sys.stderr)
        return EXIT_INPUT_ERROR
    cache = PageCache(args.cache_dir, build_http_client(), source_host=source_host)

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
    if (refusal := confirm_spend(args)) is not None:
        return refusal

    ledger = Ledger(args.ledger, is_done=regeneration_rule(forced))
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

    scope = {
        "prompt_version": args.prompt_version,
        "model": client.model,
        "slugs": {t.slug for t in parsed.terms},
    }
    records = ledger.records()
    written = write_csv(args.out, records, book, **scope)
    unwritten_out = unwritten_path(args.out)
    unwritten = write_unwritten_csv(unwritten_out, records, book, **scope)
    print(
        f"ok={summary.ok} no_excerpt={summary.no_excerpt} "
        f"fetch_error={summary.fetch_error} llm_error={summary.llm_error} skipped={summary.skipped}"
    )
    print(f"wrote {written} row(s) to {args.out}")
    # A second line, not a redefinition of the first: `written` is what a reviewer and the
    # end-to-end test both read as "definitions produced", and folding definition-less rows
    # into it would look like tidying while destroying what the number meant (ADR-0006).
    print(f"{unwritten} term(s) unwritten -> {unwritten_out}")
    if summary.aborted:
        print("error: run aborted early — see the ledger", file=sys.stderr)
        return EXIT_RUN_ABORTED
    return EXIT_OK


if __name__ == "__main__":  # `python -m glossary_gen.cli`
    raise SystemExit(run())
