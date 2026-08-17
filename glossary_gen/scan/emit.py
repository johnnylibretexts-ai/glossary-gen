from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from glossary_gen.models import Book
from glossary_gen.scan.models import MergedTerm, RejectedCandidate


class EmitError(Exception):
    """The scan produced nothing worth writing."""


def index_payload(book: Book, terms: Sequence[MergedTerm]) -> dict[str, Any]:
    """Build exactly what `glossary_gen.input.load_input` accepts — and nothing more.

    Confidence and corroborations are deliberately absent: `input.py` owns this schema, and
    adding a field to it here would make the scanner the second owner of a contract that
    already has one. They go to the sidecar report instead.

    Every verified term is written. There is no threshold to filter on — see ADR-0004 — so
    the only way to emit nothing is to have found nothing.

    Raises EmitError if the input list is empty.
    """
    if not terms:
        raise EmitError("the scan produced no terms; nothing to write")
    kept = terms
    return {
        "book": {
            "library": book.library,
            "coverID": book.cover_id,
            "bookId": book.book_id,
            "title": book.title,
            "index_url": book.index_url,
        },
        "terms": [
            {"term": term.term, "aliases": list(term.aliases), "pages": list(term.pages)}
            for term in kept
        ],
    }


def report_payload(
    terms: Sequence[MergedTerm],
    rejected: Sequence[RejectedCandidate] = (),
) -> dict[str, Any]:
    """The scanner's diagnostic sidecar.

    Deliberately NOT a review aid: it records what the scanner observed, so a prompt or
    verification change can be compared against a previous run. The reviewer works from the
    generated CSV, which is the artifact a person can actually read (ADR-0004).

    `confidence` and `corroborations` are reported separately and never combined. A fused
    number told you only that it had saturated; "heading fired, cue did not" tells you what
    the scanner actually saw.

    `rejected` records the candidates the evidence gate turned away, with which of the two
    reasons fired (ADR-0007). This file is where they belong precisely because it is a
    diagnostic: a rejected candidate is an observation about the model's behaviour, not a
    term the book defines, and it is never offered to a reviewer to rescue. The block is
    always present, empty or not, so its absence cannot be read as "none were rejected".
    """
    return {
        "count": len(terms),
        "rejected": {
            "count": len(rejected),
            "candidates": [
                {
                    "term": candidate.term,
                    "aliases": list(candidate.aliases),
                    "reason": str(candidate.reason),
                    "page": candidate.page_url,
                    "confidence": round(candidate.confidence, 4),
                    "evidence": candidate.evidence,
                }
                for candidate in rejected
            ],
        },
        "terms": [
            {
                "slug": term.slug,
                "term": term.term,
                "confidence": round(term.confidence, 4),
                "corroborations": [str(c) for c in term.corroborations],
                "pages": list(term.pages),
                "evidence": term.evidence,
            }
            for term in terms
        ],
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
