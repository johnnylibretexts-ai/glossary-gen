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

    The empty-string guard is not defensive padding. `"" in _FORMULA_PREFIXES` is True —
    the empty string is a substring of every string — so a `value[:1] in ...` test escapes
    an empty cell into a lone `'`. Measured on the first full-book run: 76 cells across
    `x_example`, `aliases` and `x_related` shipped that way. It went unseen because only
    `ok` rows were ever written and every one of those has a definition; an unwritten row
    is empty in `definition` by construction, which is what made it visible.
    """
    return "'" + value if value and value[0] in _FORMULA_PREFIXES else value


def _join(values: Sequence[str]) -> str:
    return "|".join(values)


def _row(record: LedgerRecord, book: Book, *, status: str) -> dict[str, str]:
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
        "x_status": status,
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


def _scoped(
    records: Sequence[LedgerRecord],
    prompt_version: str,
    model: str,
    slugs: Collection[str],
) -> list[LedgerRecord]:
    """Records belonging to THIS run, whatever their status.

    The ledger is deliberately append-only and remembers every attempt ever made against
    this ledger file, across prompt versions, models, and even different books (when
    `--ledger` points at a reused path). A record belongs to this run when it matches its
    declared `prompt_version` and `model` (the chain's DECLARED primary — see `ledger.py`,
    not `served_by_model`, since filtering on the serving model would drop fallback-served
    rows) and its subject is one of this run's terms.

    Both output files scope identically; they differ only in what they then keep.
    """
    slug_set = set(slugs)
    return [
        record
        for record in records
        if record.prompt_version == prompt_version
        and record.model == model
        and record.subject in slug_set
    ]


def _latest_per_subject(records: Sequence[LedgerRecord]) -> list[LedgerRecord]:
    """One record per subject: the last one in the ledger, which is its current state.

    The ledger is append-only history, so a subject may hold several attempts. Ordinarily
    at most one is `ok` and this is a formality — but `--regenerate` re-attempts a subject
    that already succeeded, and then the older row is superseded rather than equal. Emitting
    both put a duplicate term in the CSV, which `load_input` rejects on duplicate slugs, so
    it would have failed at the very consumer the file targets.

    Ordered by ledger position, never by `generated_at`: the timestamp is what a producer
    wrote down, while position is what actually happened, and only one of those is a fact
    about this file. A regenerated subject keeps its original place in the output.
    """
    latest: dict[str, LedgerRecord] = {}
    for record in records:
        latest[record.subject] = record
    return list(latest.values())


def _write(path: Path, rows: Sequence[dict[str, str]]) -> int:
    """Write `rows` under the fixed header. Always writes the file, even with no rows:
    a header-only file has exactly one meaning, while a conditionally-written one leaves
    its absence ambiguous between "nothing to report" and "you are looking at an old run".
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return len(rows)


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

    This is the file an importer consumes, so it holds nothing an importer cannot use:
    every row has a definition and `x_status` is always `needs-review`. Terms this run
    failed to define are reported by `write_unwritten_csv` instead — see ADR-0006.
    """
    scoped = _latest_per_subject(_scoped(records, prompt_version, model, slugs))
    usable = [r for r in scoped if r.status == "ok"]
    return _write(path, [_row(record, book, status=NEEDS_REVIEW) for record in usable])


def write_unwritten_csv(
    path: Path,
    records: Sequence[LedgerRecord],
    book: Book,
    *,
    prompt_version: str,
    model: str,
    slugs: Collection[str],
) -> int:
    """Write one row per UNWRITTEN term of this run — a term the run produced no definition
    for, whether because its pages grounded too little, would not fetch, or the model
    failed. Returns the number of data rows written.

    Membership is decided by a subject's LATEST attempt, which generalises ADR-0006's
    original "has no `ok` row" without contradicting it. That rule assumed success was
    terminal; `--regenerate` breaks the assumption, since a term written before
    `MIN_EXCERPT_CHARS` existed can be re-attempted under it and correctly refused. Its
    stale `ok` row must not keep a definition in the import CSV that the tool would no
    longer write. A failure followed by a success still belongs in the CSV, exactly as
    before — the latest attempt is the `ok` one. Where a term accumulated several attempts the
    latest is emitted, since the earlier ones are history the ledger already keeps.

    `x_status` carries the ledger status verbatim rather than `needs-review`, which would
    claim a human must read a row with nothing to read. Those values are disjoint from
    `needs-review`, so a reviewer who concatenates this file with the import CSV gets one
    legible sheet. `definition` is passed through rather than blanked: it is empty by
    construction on every failure path, and forcing it would hide a broken invariant
    instead of surfacing it.
    """
    scoped = _latest_per_subject(_scoped(records, prompt_version, model, slugs))
    return _write(
        path,
        [_row(r, book, status=r.status) for r in scoped if r.status != "ok"],
    )
