import csv

from glossary_gen.csv_out import COLUMNS, CORE_COLUMNS, write_csv
from glossary_gen.ledger import LedgerRecord
from glossary_gen.models import Book

BOOK = Book(
    library="eng",
    cover_id="12345",
    book_id="python-openstax",
    title="Python Programming (OpenStax)",
    index_url="https://eng.libretexts.org/index",
)


def make_record(slug="recursion", status="ok", definition="A function calling itself."):
    return LedgerRecord(
        slug=slug,
        term="Recursion",
        prompt_version="v1",
        model="gemini-flash-3.6",
        provider="gemini",
        generated_at="2026-08-07T00:00:00Z",
        status=status,
        definition=definition,
        x_category="Functions and flow",
        x_context="Used for tree traversal.",
        x_example="fact(n)",
        x_related=["Base case", "Function"],
        aliases=["recursive"],
        pages=["https://a", "https://b"],
        source_pages=["https://a"],
        excerpt_chars=42,
    )


def read(path):
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_header_order_is_core_then_extension_then_provenance(tmp_path):
    path = tmp_path / "out.csv"
    write_csv(path, [make_record()], BOOK)
    with path.open(encoding="utf-8", newline="") as handle:
        header = next(csv.reader(handle))
    assert header == COLUMNS
    assert header[: len(CORE_COLUMNS)] == CORE_COLUMNS


def test_every_non_core_column_is_x_prefixed():
    assert all(c.startswith("x_") for c in COLUMNS if c not in CORE_COLUMNS)


def test_added_by_is_never_emitted():
    assert "addedBy" not in COLUMNS
    assert "added_by" not in COLUMNS


def test_book_constants_repeat_on_every_row(tmp_path):
    path = tmp_path / "out.csv"
    write_csv(path, [make_record("a"), make_record("b")], BOOK)
    rows = read(path)
    assert [r["library"] for r in rows] == ["eng", "eng"]
    assert [r["coverID"] for r in rows] == ["12345", "12345"]
    assert [r["bookId"] for r in rows] == ["python-openstax", "python-openstax"]


def test_multi_values_are_pipe_delimited(tmp_path):
    path = tmp_path / "out.csv"
    write_csv(path, [make_record()], BOOK)
    row = read(path)[0]
    assert row["pages"] == "https://a|https://b"
    assert row["aliases"] == "recursive"
    assert row["x_related"] == "Base case|Function"


def test_pages_and_source_pages_stay_distinct(tmp_path):
    path = tmp_path / "out.csv"
    write_csv(path, [make_record()], BOOK)
    row = read(path)[0]
    assert row["pages"] == "https://a|https://b"
    assert row["x_source_pages"] == "https://a"


def test_status_defaults_to_needs_review(tmp_path):
    path = tmp_path / "out.csv"
    write_csv(path, [make_record()], BOOK)
    assert read(path)[0]["x_status"] == "needs-review"


def test_definition_with_commas_and_quotes_round_trips(tmp_path):
    tricky = 'A "call", of sorts, that repeats.'
    path = tmp_path / "out.csv"
    write_csv(path, [make_record(definition=tricky)], BOOK)
    assert read(path)[0]["definition"] == tricky


def test_non_ok_records_are_excluded(tmp_path):
    path = tmp_path / "out.csv"
    written = write_csv(
        path,
        [
            make_record("a"),
            make_record("b", status="no_excerpt"),
            make_record("c", status="llm_error"),
        ],
        BOOK,
    )
    assert written == 1
    assert [r["term"] for r in read(path)] == ["Recursion"]
