from __future__ import annotations

import csv
from collections.abc import Sequence
from pathlib import Path

from glossary_gen.ledger import LedgerRecord
from glossary_gen.models import Book

# Consumable by Conductor's AddGlossaryParams. `addedBy` is deliberately absent:
# the importer must set it from the authenticated user.
CORE_COLUMNS = [
    "term",
    "definition",
    "aliases",
    "pages",
    "author",
    "link",
    "source",
    "library",
    "coverID",
    "bookId",
]

EXTENSION_COLUMNS = ["x_category", "x_context", "x_example", "x_related"]

PROVENANCE_COLUMNS = [
    "x_status",
    "x_model",
    "x_provider",
    "x_prompt_version",
    "x_generated_at",
    "x_source_pages",
    "x_excerpt_chars",
]

COLUMNS = [*CORE_COLUMNS, *EXTENSION_COLUMNS, *PROVENANCE_COLUMNS]

NEEDS_REVIEW = "needs-review"


def _join(values: Sequence[str]) -> str:
    return "|".join(values)


def _row(record: LedgerRecord, book: Book) -> dict[str, str]:
    return {
        "term": record.term,
        "definition": record.definition,
        "aliases": _join(record.aliases),
        "pages": _join(record.pages),
        "author": "",
        "link": "",
        "source": book.index_url,
        "library": book.library,
        "coverID": book.cover_id,
        "bookId": book.book_id,
        "x_category": record.x_category,
        "x_context": record.x_context,
        "x_example": record.x_example,
        "x_related": _join(record.x_related),
        "x_status": NEEDS_REVIEW,
        # `model` is the chain's DECLARED primary — the stable ledger resume key.
        # `served_by_model` is the model that actually answered. Report the latter
        # when present, so a fallback-served row is not mislabelled as the primary.
        "x_model": record.served_by_model or record.model,
        "x_provider": record.provider,
        "x_prompt_version": record.prompt_version,
        "x_generated_at": record.generated_at,
        "x_source_pages": _join(record.source_pages),
        "x_excerpt_chars": str(record.excerpt_chars),
    }


def write_csv(path: Path, records: Sequence[LedgerRecord], book: Book) -> int:
    """Write successful records only. Returns the number of data rows written."""
    usable = [record for record in records if record.status == "ok"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        for record in usable:
            writer.writerow(_row(record, book))
    return len(usable)
