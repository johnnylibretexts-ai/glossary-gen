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


PROMPT_VERSION = "v1"
MODEL = "gemini-3.5-flash"


def make_record(
    slug="recursion",
    status="ok",
    definition="A function calling itself.",
    prompt_version=PROMPT_VERSION,
    model=MODEL,
):
    return LedgerRecord(
        slug=slug,
        term="Recursion",
        prompt_version=prompt_version,
        model=model,
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


def write(path, records, book=BOOK, *, prompt_version=PROMPT_VERSION, model=MODEL, slugs=None):
    """Test helper: defaults prompt_version/model/slugs to this run's records so most
    tests don't have to restate the scoping args they aren't exercising.
    """
    if slugs is None:
        slugs = {r.slug for r in records}
    return write_csv(path, records, book, prompt_version=prompt_version, model=model, slugs=slugs)


def test_header_order_is_core_then_extension_then_provenance(tmp_path):
    path = tmp_path / "out.csv"
    write(path, [make_record()])
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
    write(path, [make_record("a"), make_record("b")])
    rows = read(path)
    assert [r["library"] for r in rows] == ["eng", "eng"]
    assert [r["coverID"] for r in rows] == ["12345", "12345"]
    assert [r["bookId"] for r in rows] == ["python-openstax", "python-openstax"]


def test_multi_values_are_pipe_delimited(tmp_path):
    path = tmp_path / "out.csv"
    write(path, [make_record()])
    row = read(path)[0]
    assert row["pages"] == "https://a|https://b"
    assert row["aliases"] == "recursive"
    assert row["x_related"] == "Base case|Function"


def test_pages_and_source_pages_stay_distinct(tmp_path):
    path = tmp_path / "out.csv"
    write(path, [make_record()])
    row = read(path)[0]
    assert row["pages"] == "https://a|https://b"
    assert row["x_source_pages"] == "https://a"


def test_status_defaults_to_needs_review(tmp_path):
    path = tmp_path / "out.csv"
    write(path, [make_record()])
    assert read(path)[0]["x_status"] == "needs-review"


def test_definition_with_commas_and_quotes_round_trips(tmp_path):
    tricky = 'A "call", of sorts, that repeats.'
    path = tmp_path / "out.csv"
    write(path, [make_record(definition=tricky)])
    assert read(path)[0]["definition"] == tricky


def test_non_ok_records_are_excluded(tmp_path):
    path = tmp_path / "out.csv"
    written = write(
        path,
        [
            make_record("a"),
            make_record("b", status="no_excerpt"),
            make_record("c", status="llm_error"),
        ],
    )
    assert written == 1
    assert [r["term"] for r in read(path)] == ["Recursion"]


def test_definition_starting_with_equals_is_neutralized(tmp_path):
    """A leading '=' is evaluated as a formula by Excel/Sheets even inside a quoted
    CSV field — RFC 4180 quoting alone does not stop it. The writer must prefix a
    guard character so spreadsheet apps treat the cell as text.
    """
    path = tmp_path / "out.csv"
    write(path, [make_record(definition="=cmd|' /c calc'!A1")])
    row = read(path)[0]
    assert row["definition"] == "'=cmd|' /c calc'!A1"
    assert not row["definition"].startswith("=")


def test_term_starting_with_at_sign_is_neutralized(tmp_path):
    """Covers a second dangerous prefix (not just '=') across a different column."""
    record = make_record()
    record = record.model_copy(update={"term": "@SUM(1,1)"})
    path = tmp_path / "out.csv"
    write(path, [record])
    row = read(path)[0]
    assert row["term"] == "'@SUM(1,1)"


def test_ordinary_definition_is_left_untouched(tmp_path):
    path = tmp_path / "out.csv"
    write(path, [make_record(definition="A function calling itself.")])
    assert read(path)[0]["definition"] == "A function calling itself."


def test_csv_scopes_to_the_run_prompt_version(tmp_path):
    """Prompt iteration: the ledger keeps 'ok' rows for every prompt_version ever run
    against a slug. Without run-scoping, re-running with --prompt-version v2 would
    emit both v1's and v2's definitions for the same term with no way to tell which
    to import.
    """
    path = tmp_path / "out.csv"
    records = [
        make_record("recursion", prompt_version="v1", definition="v1 definition"),
        make_record("recursion", prompt_version="v2", definition="v2 definition"),
    ]
    written = write(path, records, prompt_version="v2", slugs={"recursion"})
    assert written == 1
    rows = read(path)
    assert len(rows) == 1
    assert rows[0]["definition"] == "v2 definition"
    assert rows[0]["x_prompt_version"] == "v2"


def test_csv_scopes_to_the_run_model(tmp_path):
    """Same failure mode as prompt_version, but for --model."""
    path = tmp_path / "out.csv"
    records = [
        make_record("recursion", model="gemini-3.5-flash", definition="gemini definition"),
        make_record("recursion", model="llama3.1", definition="llama definition"),
    ]
    written = write(path, records, model="llama3.1", slugs={"recursion"})
    assert written == 1
    rows = read(path)
    assert rows[0]["definition"] == "llama definition"
    assert rows[0]["x_model"] == "llama3.1"


def test_csv_scopes_to_the_run_slugs(tmp_path):
    """Cross-book contamination: `--ledger` defaults to the same path for every book run
    from the same directory. A ledger holding a prior book's terms must not leak into
    this book's CSV just because it shares a prompt_version and model.
    """
    path = tmp_path / "out.csv"
    other_book_record = make_record("photosynthesis", definition="From a different book.")
    this_book_record = make_record("recursion", definition="From this book.")
    written = write(
        path,
        [other_book_record, this_book_record],
        slugs={"recursion"},  # only this book's slugs
    )
    assert written == 1
    rows = read(path)
    assert [r["term"] for r in rows] == ["Recursion"]
    assert rows[0]["definition"] == "From this book."
