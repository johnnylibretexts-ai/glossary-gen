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
    _now,
    _positive_int,
    build_client,
    build_http_client,
    confirm_spend,
    refuse_unattended,
)
from glossary_gen.fetch import FetchError, PageCache, parse_page
from glossary_gen.input import InputError
from glossary_gen.ledger import Ledger
from glossary_gen.llm import LLMClient, LLMError
from glossary_gen.models import Page, slugify
from glossary_gen.run import PRICES_PATH, Attempt, ModelCall, execute_run, load_prices
from glossary_gen.scan.candidates import corroborations_on_page, merge, rejection_of
from glossary_gen.scan.content import extract_content
from glossary_gen.scan.emit import EmitError, index_payload, report_payload, write_json
from glossary_gen.scan.models import RejectedCandidate, ScanRecord, VerifiedCandidate
from glossary_gen.scan.propose import load_scan_prompt, propose_terms, scan_prompt_versions
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
    """Fetch each page's HTML, narrow it to article content, then parse.

    Unlike `cli.py`'s `collect_pages`, this one does not use `cache.get()` directly:
    the scanner must not see the rendered page's chrome (nav, display-settings menu,
    footer), so it fetches raw HTML via `cache.get_html()`, strips everything outside
    `.mt-content-container` with `extract_content()`, and only then calls `parse_page`.
    """
    pages: list[Page] = []
    for url in urls:
        try:
            html = cache.get_html(url)
        except FetchError as exc:
            failed.append(f"{url}: {exc}")
            continue
        pages.append(parse_page(url, extract_content(html)))
    return pages


# A scan prompt carries a full page, not three excerpts, so input runs roughly double a
# generation call. Measured over the 136 pages of Python Programming (OpenStax) on
# 2026-08-16: 1035 tokens in and 124 out per page on average. The earlier 2000/400 came
# from estimating page size before any run existed and were 1.9x and 3.2x high.
#
# Means, for the same reason as `cli.EST_TOKENS_*`: this predicts a whole book's total.
# Output is far more variable here than in generation (median 91, mean 124, max 454) since
# a page may define one term or a dozen — but that spread averages out across a book, which
# is the only quantity this is ever asked for. Rounded up from 1035.4 / 123.7, because for
# a spend gate leaning marginally high is the safe direction; it is not an upper bound for
# any other book, and cannot be.
EST_SCAN_TOKENS_IN = 1050
EST_SCAN_TOKENS_OUT = 125


@dataclass
class ScanSummary:
    ok: int = 0
    llm_error: int = 0
    skipped: int = 0
    aborted: bool = False
    # Pages whose extracted content had zero blocks (genuinely contentless front/back
    # matter — Index, Table of Contents, Detailed Licensing — see the measurement in
    # scan/content.py). These are recorded `ok` but never sent to the model, so they are
    # a subset of `ok`, not an addition to it.
    empty_pages: int = 0
    candidates: list[VerifiedCandidate] = field(default_factory=list)
    # Candidates the evidence gate turned away, with which reason fired (ADR-0007). Like
    # `candidates`, this covers only the pages THIS run actually scanned — a skipped page
    # is never re-attempted, so it contributes neither.
    rejected: list[RejectedCandidate] = field(default_factory=list)

    @property
    def unverified(self) -> int:
        """Derived, never tallied alongside `rejected`, so the printed count and the
        diagnostic report cannot disagree about how many candidates were turned away.
        """
        return len(self.rejected)


def estimate_scan_cost(
    model: str, page_count: int, prices: dict[str, dict[str, float]]
) -> float | None:
    """USD estimate for a whole book, or None when the model has no configured price."""
    entry = prices.get(model)
    if not entry:
        return None
    per_page = (
        EST_SCAN_TOKENS_IN * entry["input_per_mtok"]
        + EST_SCAN_TOKENS_OUT * entry["output_per_mtok"]
    ) / 1_000_000
    return per_page * page_count


def execute(
    pages: Sequence[Page],
    client: LLMClient,
    ledger: Ledger,
    template: str,
    prompt_version: str,
    *,
    budget_usd: float | None = None,
    max_consecutive_failures: int = 5,
) -> ScanSummary:
    """Propose, verify, and corroborate one page at a time, recording every outcome.

    An adapter over `execute_run`, which owns spend, resumption and stopping. What stays
    here is everything specific to a page: what its row holds, and what a scan produces
    beyond the ledger.
    """
    summary = ScanSummary()

    def attempt(page: Page, subject: str) -> Attempt:
        base = {
            # The subject the run keyed on, not `slugify(page.url)` computed a second time:
            # the row must land under the key `ledger.has()` will look for, or the page is
            # re-scanned and re-paid for on every resume.
            "subject": subject,
            "page_url": page.url,
            "prompt_version": prompt_version,
            "model": client.model,
            "provider": getattr(client, "name", ""),
            "generated_at": _now(),
        }

        # A page whose extracted content has zero blocks (Index, Table of Contents,
        # Detailed Licensing — see scan/content.py) is genuinely contentless: there is
        # nothing for a model to find, so asking anyway is a real paid call that always
        # returns nothing. Recorded `ok` rather than a new status for the same resume
        # reason as a term-free-but-nonempty page: `Ledger.has()` only counts `ok`, so
        # anything else would re-pay for it on every resumed run. `NOT_MADE` because no
        # provider was consulted, so this says nothing about whether one is healthy.
        if not page.blocks:
            summary.ok += 1
            summary.empty_pages += 1
            return Attempt(
                record=ScanRecord(**base, status="ok", n_proposed=0, n_verified=0),
                model_call=ModelCall.NOT_MADE,
            )

        try:
            candidates, raw = propose_terms(client, template, page)
        except LLMError as exc:
            # A failed page still cost real, billed tokens — every attempt that reached
            # `complete_raw` was a real provider call, even though it ended in a schema
            # error and got retried. `propose_terms` attaches the accumulated total to
            # `LLMStructuredOutputError`; a bare `LLMTransportError` never gets that far
            # (raised by `complete_raw` itself, before any reply exists), so `getattr` with
            # a 0 default is correct there, not a workaround. The counts go on the record
            # because that is what the run charges against the ceiling, and what a later
            # resume re-reads.
            summary.llm_error += 1
            return Attempt(
                record=ScanRecord(
                    **base,
                    status="llm_error",
                    error=str(exc),
                    tokens_in=getattr(exc, "tokens_in", 0),
                    tokens_out=getattr(exc, "tokens_out", 0),
                ),
                model_call=ModelCall.FAILED,
            )

        verified = []
        for candidate in candidates.terms:
            # The gate is unchanged — a rejected candidate still never reaches the index.
            # What changes is that it is now written down instead of vanishing into a
            # count, with which of the two reasons fired (ADR-0007).
            if (reason := rejection_of(candidate, page)) is not None:
                summary.rejected.append(
                    RejectedCandidate(
                        term=candidate.term,
                        aliases=candidate.aliases,
                        evidence=candidate.evidence,
                        page_url=page.url,
                        confidence=candidate.confidence,
                        reason=reason,
                    )
                )
                continue
            verified.append(candidate)
            summary.candidates.append(
                VerifiedCandidate(
                    term=candidate.term,
                    aliases=candidate.aliases,
                    evidence=candidate.evidence,
                    page_url=page.url,
                    confidence=candidate.confidence,
                    corroborations=corroborations_on_page(candidate, page),
                )
            )

        summary.ok += 1
        # A page that defines nothing is `ok` with n_proposed = 0, never its own status:
        # Ledger.has() counts only `ok`, so a distinct status would re-pay for every
        # term-free page on every resume, forever.
        return Attempt(
            record=ScanRecord(
                **base,
                status="ok",
                n_proposed=len(candidates.terms),
                n_verified=len(verified),
                served_by_model=raw.model,
                tokens_in=raw.tokens_in,
                tokens_out=raw.tokens_out,
            ),
            model_call=ModelCall.ANSWERED,
        )

    outcome = execute_run(
        pages,
        ledger,
        subject_of=lambda page: slugify(page.url),
        attempt=attempt,
        prompt_version=prompt_version,
        model=client.model,
        budget_usd=budget_usd,
        max_consecutive_failures=max_consecutive_failures,
    )
    summary.skipped = outcome.skipped
    summary.aborted = outcome.aborted
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="glossary-scan",
        description="Build a term index for a LibreTexts book, for glossary-gen to consume.",
    )
    parser.add_argument("--book", required=True, help="book root URL on *.libretexts.org")
    parser.add_argument("--out", type=Path, default=Path("out/index.json"), help="index path")
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("out/index-report.json"),
        help="diagnostic sidecar path",
    )
    parser.add_argument("--cache-dir", type=Path, default=Path("cache"), help="page cache dir")
    parser.add_argument("--ledger", type=Path, default=Path("out/scan.jsonl"), help="ledger path")
    parser.add_argument("--prompt-version", default="v1", choices=scan_prompt_versions())
    parser.add_argument("--model", default="gemini-3.7-flash", help="Gemini model name")
    parser.add_argument("--limit", type=_positive_int, help="scan at most N pages (smoke runs)")
    parser.add_argument(
        "--delay", type=float, default=0.3, help="seconds between real page fetches"
    )
    parser.add_argument("--budget-usd", type=float, help="abort if spend exceeds this")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="confirm the spend up front; required for a non-interactive run",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="walk the book and report structural candidates; call no model, spend nothing",
    )
    return parser


def run(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if (refusal := refuse_unattended(args)) is not None:
        return refusal
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

    # A paid run with zero pages is equally meaningless as a dry run with zero pages — it
    # must not proceed to spend money or write an index. Hoisted above the dry-run branch
    # so it guards both paths, not just the free preview.
    if not pages:
        if failed:
            print(
                f"error: every page failed to fetch ({len(failed)} failed, 0 succeeded)",
                file=sys.stderr,
            )
        else:
            print("error: the table of contents produced no content pages", file=sys.stderr)
        return EXIT_RUN_ABORTED

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
        print("a real run reads each page with a model and verifies what it finds.")
        return EXIT_OK

    prices = load_prices(PRICES_PATH)
    estimate = estimate_scan_cost(args.model, len(pages), prices)
    if args.budget_usd is not None and estimate is None:
        print(
            f"error: --budget-usd was given but {args.model!r} has no entry in prices.json, "
            "so no ceiling can be enforced",
            file=sys.stderr,
        )
        return EXIT_INPUT_ERROR
    if estimate is not None:
        print(f"estimated cost: ${estimate:.2f} for {len(pages)} pages")
        print("note: priced from prices.json, verified 2026-08-16 — re-check before a large run")
    # Shared with cli.py rather than mirrored, so the two entry points cannot drift on
    # the behaviour that controls spend. See `confirm_spend` for why a non-interactive
    # run is refused rather than prompted.
    if (refusal := confirm_spend(args)) is not None:
        return refusal

    try:
        llm = build_client(args)
    except InputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_INPUT_ERROR

    ledger = Ledger(args.ledger, record_cls=ScanRecord)
    summary = execute(
        pages,
        llm,
        ledger,
        load_scan_prompt(args.prompt_version),
        args.prompt_version,
        budget_usd=args.budget_usd,
    )
    terms = merge(summary.candidates)

    # The REPORT is written first and unconditionally. A scan that verified nothing cannot
    # write an index at all (`load_input` requires a non-empty terms list) — and that is
    # exactly the run where someone most needs to see what the scanner did observe.
    write_json(args.report, report_payload(terms, summary.rejected))

    print(
        f"pages ok={summary.ok} skipped={summary.skipped} "
        f"fetch_error={len(failed)} llm_error={summary.llm_error} "
        f"empty={summary.empty_pages}"
    )
    print(f"candidates: {len(summary.candidates)} verified, {summary.unverified} rejected")

    try:
        write_json(args.out, index_payload(book, terms))
    except EmitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        print(f"the diagnostic sidecar was still written to {args.report}", file=sys.stderr)
        return EXIT_RUN_ABORTED

    print(f"terms: {len(terms)} merged, all written to {args.out}")
    print(f"diagnostics: {args.report}")
    return EXIT_RUN_ABORTED if summary.aborted else EXIT_OK


if __name__ == "__main__":  # `python -m glossary_gen.scan_cli`
    raise SystemExit(run())
