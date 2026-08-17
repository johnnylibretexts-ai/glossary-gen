"""Score generated definitions against the ones a book's authors wrote.

    uv run --env-file .env python tools/compare_definitions.py \
        --generated out/stats-overlap.csv \
        --author docs/research/2026-08-16-stats-author-glossary.csv \
        --out docs/research/2026-08-17-stats-definition-comparison.csv

One judge call per pair, asking only whether the generated definition asserts
something the author's contradicts. Structural flags are computed for free and
reported beside it, never fused with it.

Both definitions land in the output next to the verdict, because a model's
judgement that nobody can check is not evidence.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

from glossary_gen.cli import build_client
from glossary_gen.compare import judge_prompt, parse_verdict, structural_flags
from glossary_gen.models import slugify

COLUMNS = [
    "slug",
    "term",
    "verdict",
    "reason",
    "flags",
    "author_definition",
    "generated_definition",
]


def load_pairs(generated: Path, author: Path) -> list[dict[str, str]]:
    """Match on slug, which is how every other join in this project is made."""
    by_slug = {r["slug"]: r for r in csv.DictReader(author.open(encoding="utf-8"))}
    pairs = []
    for row in csv.DictReader(generated.open(encoding="utf-8")):
        slug = slugify(row["term"])
        reference = by_slug.get(slug) or next(
            (by_slug[slugify(a)] for a in row["aliases"].split("|") if slugify(a) in by_slug), None
        )
        if reference is None:
            continue
        pairs.append(
            {
                "slug": slug,
                "term": row["term"],
                "author_definition": reference["definition"],
                "generated_definition": row["definition"],
            }
        )
    return pairs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--generated", type=Path, required=True, help="a glossary-gen CSV")
    ap.add_argument("--author", type=Path, required=True, help="a harvested author glossary CSV")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--model", default="gemini-3.7-flash")
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args()

    pairs = load_pairs(args.generated, args.author)
    if not pairs:
        print("no term appears in both files", file=sys.stderr)
        return 1
    print(f"pairs to judge  {len(pairs)}")

    if not args.yes:
        if not sys.stdin.isatty():
            print("error: refusing to spend without --yes or a terminal", file=sys.stderr)
            return 2
        if input("proceed? [y/N] ").strip().casefold() not in {"y", "yes"}:
            print("aborted by user")
            return 0

    client = build_client(args)
    rows, tokens_in, tokens_out = [], 0, 0
    for i, pair in enumerate(pairs, start=1):
        raw = client.complete_raw(
            judge_prompt(
                term=pair["term"],
                author=pair["author_definition"],
                generated=pair["generated_definition"],
            )
        )
        tokens_in += raw.tokens_in or 0
        tokens_out += raw.tokens_out or 0
        verdict = parse_verdict(raw.text)
        flags = structural_flags(
            term=pair["term"],
            definition=pair["generated_definition"],
            reference=pair["author_definition"],
        )
        rows.append(
            {**pair, "verdict": verdict.verdict, "reason": verdict.reason, "flags": "|".join(flags)}
        )
        print(f"  [{i}/{len(pairs)}] {verdict.verdict:11} {pair['term']}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    tally = Counter(row["verdict"] for row in rows)
    flagged = Counter(flag for row in rows for flag in row["flags"].split("|") if flag)
    print(f"\nwrote {args.out}")
    print(f"  verdicts  {dict(tally)}")
    print(f"  flags     {dict(flagged)}")
    print(f"  tokens    in {tokens_in}, out {tokens_out}")
    print("\nFlags are places to look, not judgements, and are never summed with the verdicts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
