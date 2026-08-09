from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from glossary_gen.models import Book
from glossary_gen.scan.models import ScoredTerm


class EmitError(Exception):
    """The scan produced nothing worth writing."""


def index_payload(book: Book, terms: Sequence[ScoredTerm], *, min_score: float) -> dict[str, Any]:
    """Build exactly what `glossary_gen.input.load_input` accepts — and nothing more.

    Scores are deliberately absent: `input.py` owns this schema, and adding a field to it
    here would make the scanner the second owner of a contract that already has one. The
    scores go to the sidecar report instead.

    Raises EmitError if no terms meet the min_score threshold or if the input list is empty.
    """
    if not terms:
        raise EmitError("the scan produced no terms; nothing to write")
    kept = [term for term in terms if term.score >= min_score]
    if not kept:
        raise EmitError(
            f"min_score={min_score} filtered out all {len(terms)} terms; nothing to write"
        )
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


def report_payload(terms: Sequence[ScoredTerm]) -> dict[str, Any]:
    """The score sidecar: everything a reviewer needs to trim the list by hand."""
    return {
        "count": len(terms),
        "terms": [
            {
                "slug": term.slug,
                "term": term.term,
                "score": round(term.score, 4),
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
