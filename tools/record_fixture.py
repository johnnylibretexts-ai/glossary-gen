"""Record a replay eval fixture from the pages a book writes its own glossary on.

    uv run --env-file .env python tools/record_fixture.py \
        --scan out/stats-scan.jsonl --out tests/eval/fixtures/replay_stats.json

    python3 tools/record_fixture.py --from-ledger \
        --scan out/psychmethods-ledger.jsonl --out tests/eval/fixtures/replay_psych.json

Pages come from the on-disk cache an earlier scan filled, so nothing is fetched.
Where the model's replies come from is the choice `--from-ledger` makes:

- **Without it**, one propose call per recorded page, paid for now. Only pages that
  carry an author glossary are recorded, because each one costs money and those are
  the pages whose expected terms the book itself supplies.
- **With it**, the replies already in the scan's own ledger, paid for once when the
  scan ran. Nothing is spent and nothing is asked. Every page the scan recorded is
  kept, so the fixture reproduces a whole-book measurement rather than a subset —
  including the pages that proposed nothing, which is where a book's own glossary
  page lands (ADR-0011). Rebuilding a paid result from the ledger rather than buying
  it twice is ADR-0008's rule, applied to fixtures.

`expected_slugs` is harvested, never typed: nobody chooses which terms count.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from harvest_glossary import cached_pages, page_urls

from glossary_gen.cli import build_client
from glossary_gen.fetch import parse_page
from glossary_gen.run import PRICES_PATH, load_prices
from glossary_gen.article import extract_content
from glossary_gen.ledger import Ledger
from glossary_gen.scan.evaluate import fixture_payload
from glossary_gen.scan.models import Candidate, PageCandidates, ScanRecord
from glossary_gen.scan.propose import load_scan_prompt, propose_terms
from glossary_gen.scan.reference import author_glossary, book_glossary
from glossary_gen.scan_cli import estimate_scan_cost


def recorded_reply(record: ScanRecord) -> PageCandidates:
    """The proposals one page produced, rebuilt from what the scan wrote down.

    Verified and rejected together, in that order: both were proposed, and a fixture
    holding only what passed would replay the evidence gate over inputs already known
    to pass — an eval that cannot notice the gate going soft. (On the book this was
    written for, `rejected` is empty across all 83 pages, which is exactly why it must
    be carried rather than assumed away.)
    """
    proposed = [*(record.candidates or []), *(record.rejected or [])]
    return PageCandidates(
        terms=[
            Candidate(
                term=c.term,
                aliases=list(c.aliases),
                evidence=c.evidence,
                confidence=c.confidence,
            )
            for c in proposed
        ]
    )


def from_ledger(args: argparse.Namespace) -> int:
    """Build the fixture from replies already paid for, over the whole book."""
    records = [
        r for r in Ledger(args.scan, record_cls=ScanRecord).records() if r.candidates is not None
    ]
    pages, absent = cached_pages([r.page_url for r in records], args.cache)
    if absent:
        print(f"error: {len(absent)} page(s) are not in {args.cache}", file=sys.stderr)
        return 1
    html_by_url = dict(pages)

    # Narrowed exactly as the scan narrowed it. A fixture whose blocks differ from the
    # ones the model was shown would replay the evidence gate against different text,
    # and every candidate would fail for a reason that never happened.
    recorded = [
        (parse_page(r.page_url, extract_content(html_by_url[r.page_url])), recorded_reply(r))
        for r in records
    ]
    expected = sorted({entry.slug for entry in book_glossary(pages)})

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(fixture_payload(recorded, expected), indent=2), encoding="utf-8")
    print(f"wrote {args.out}")
    print(f"  pages {len(recorded)}, proposals {sum(len(c.terms) for _, c in recorded)}")
    print(f"  expected slugs (harvested) {len(expected)}")
    print("  spent nothing: every reply was already paid for by the scan")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--scan", type=Path, required=True, help="the run's scan.jsonl")
    ap.add_argument("--cache", type=Path, default=Path("cache"))
    ap.add_argument("--out", type=Path, required=True, help="fixture path to write")
    ap.add_argument("--model", default="gemini-3.7-flash")
    ap.add_argument("--prompt-version", default="v1")
    ap.add_argument("--limit", type=int, help="record at most N pages")
    ap.add_argument("--yes", action="store_true", help="skip the spend confirmation")
    ap.add_argument(
        "--from-ledger",
        action="store_true",
        help="replay the proposals the scan already recorded; spends nothing",
    )
    args = ap.parse_args()

    if args.from_ledger:
        return from_ledger(args)

    pages, _ = cached_pages(page_urls(args.scan), args.cache)
    with_glossary = [(url, html) for url, html in pages if author_glossary(html)]
    if args.limit:
        with_glossary = with_glossary[: args.limit]
    if not with_glossary:
        print("no cached page carries an author glossary", file=sys.stderr)
        return 1

    expected = sorted({e.slug for _, html in with_glossary for e in author_glossary(html)})
    estimate = estimate_scan_cost(args.model, len(with_glossary), load_prices(PRICES_PATH))

    print(f"pages with an author glossary  {len(with_glossary)}")
    print(f"expected terms (harvested)     {len(expected)}")
    print(f"estimated spend                {'unknown' if estimate is None else f'${estimate:.4f}'}")

    # The repo's rule, restated here rather than imported: a money decision that cannot
    # be asked must refuse, never default to yes.
    if not args.yes:
        if not sys.stdin.isatty():
            print("error: refusing to spend without --yes or a terminal", file=sys.stderr)
            return 2
        if input("proceed? [y/N] ").strip().casefold() not in {"y", "yes"}:
            print("aborted by user")
            return 0

    client = build_client(args)
    template = load_scan_prompt(args.prompt_version)
    recorded, tokens_in, tokens_out = [], 0, 0
    for i, (url, html) in enumerate(with_glossary, start=1):
        page = parse_page(url, html)
        candidates, raw = propose_terms(client, template, page)
        recorded.append((page, candidates))
        tokens_in += raw.tokens_in or 0
        tokens_out += raw.tokens_out or 0
        print(f"  [{i}/{len(with_glossary)}] {len(candidates.terms):2d} proposed  {url[-58:]}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(fixture_payload(recorded, expected), indent=2), encoding="utf-8")
    print(f"\nwrote {args.out}")
    print(f"  pages {len(recorded)}, expected slugs {len(expected)}")
    print(f"  tokens in {tokens_in}, out {tokens_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
