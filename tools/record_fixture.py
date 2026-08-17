"""Record a replay eval fixture from the pages a book writes its own glossary on.

    uv run --env-file .env python tools/record_fixture.py \
        --scan out/stats-scan.jsonl --out tests/eval/fixtures/replay_stats.json

Pages come from the on-disk cache an earlier scan filled, so nothing is fetched;
the spend is one propose call per recorded page. Only pages that carry an author
glossary are recorded — those are the pages whose expected terms the book itself
supplies, which is the entire reason this fixture is worth more than a hand-written
term list.

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
from glossary_gen.scan.evaluate import fixture_payload
from glossary_gen.scan.propose import load_scan_prompt, propose_terms
from glossary_gen.scan.reference import author_glossary
from glossary_gen.scan_cli import estimate_scan_cost


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--scan", type=Path, required=True, help="the run's scan.jsonl")
    ap.add_argument("--cache", type=Path, default=Path("cache"))
    ap.add_argument("--out", type=Path, required=True, help="fixture path to write")
    ap.add_argument("--model", default="gemini-3.7-flash")
    ap.add_argument("--prompt-version", default="v1")
    ap.add_argument("--limit", type=int, help="record at most N pages")
    ap.add_argument("--yes", action="store_true", help="skip the spend confirmation")
    args = ap.parse_args()

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
