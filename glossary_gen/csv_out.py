from __future__ import annotations

import csv
from collections.abc import Collection, Sequence
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


# Leading characters that Excel/Sheets treat as a formula prefix even inside an
# RFC 4180-quoted field. A leading tab or CR can also be (mis)interpreted by some
# spreadsheet importers as a formula lead-in once whitespace is stripped, so they're
# guarded too.
_FORMULA_PREFIXES = "=+-@\t\r"


def _safe(value: str) -> str:
    """Neutralize CSV formula injection: prefix a leading '\\'' so spreadsheet apps
    treat the cell as text instead of evaluating it as a formula. RFC 4180 quoting
    alone does not prevent this — Excel and Sheets evaluate a leading '=' even
    inside a quoted field.
    """
    return "'" + value if value[:1] in _FORMULA_PREFIXES else value


def _join(values: Sequence[str]) -> str:
    return "|".join(values)


def _row(record: LedgerRecord, book: Book) -> dict[str, str]:
    return {
        "term": _safe(record.term),
        "definition": _safe(record.definition),
        "aliases": _safe(_join(record.aliases)),
        "pages": _join(record.pages),
        "author": "",
        "link": "",
        "source": book.index_url,
        "library": book.library,
        "coverID": book.cover_id,
        "bookId": book.book_id,
        "x_category": _safe(record.x_category),
        "x_context": _safe(record.x_context),
        "x_example": _safe(record.x_example),
        "x_related": _safe(_join(record.x_related)),
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


def write_csv(
    path: Path,
    records: Sequence[LedgerRecord],
    book: Book,
    *,
    prompt_version: str,
    model: str,
    slugs: Collection[str],
) -> int:
    """Write successful records from THIS run only. Returns the number of data rows
    written.

    The ledger is deliberately append-only and remembers every attempt ever made
    against this ledger file, across prompt versions, models, and even different
    books (when `--ledger` points at a reused path). A record only belongs in this
    run's CSV when it is `ok` AND matches this run's declared `prompt_version` and
    `model` (the chain's DECLARED primary — see `ledger.py`, not `served_by_model`,
    since filtering on the serving model would drop fallback-served rows) AND its
    slug is one of this run's terms.
    """
    slug_set = set(slugs)
    usable = [
        record
        for record in records
        if record.status == "ok"
        and record.prompt_version == prompt_version
        and record.model == model
        and record.slug in slug_set
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        for record in usable:
            writer.writerow(_row(record, book))
    return len(usable)
