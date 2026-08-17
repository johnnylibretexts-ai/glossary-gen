import csv

from glossary_gen.csv_out import COLUMNS, CORE_COLUMNS, write_csv, write_unwritten_csv
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
    subject="recursion",
    status="ok",
    definition="A function calling itself.",
    prompt_version=PROMPT_VERSION,
    model=MODEL,
):
    return LedgerRecord(
        subject=subject,
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
        slugs = {r.subject for r in records}
    return write_csv(path, records, book, prompt_version=prompt_version, model=model, slugs=slugs)


def write_unwritten(
    path, records, book=BOOK, *, prompt_version=PROMPT_VERSION, model=MODEL, slugs=None
):
    """Same defaulting as `write`, for the sidecar that reports unwritten terms."""
    if slugs is None:
        slugs = {r.subject for r in records}
    return write_unwritten_csv(
        path, records, book, prompt_version=prompt_version, model=model, slugs=slugs
    )


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


# --- the unwritten sidecar (ADR-0006) ---------------------------------------------------


def test_an_unwritten_term_gets_a_row_carrying_its_status_and_no_definition(tmp_path):
    """The whole point: a term the run failed to define is reported, not silently dropped.

    `x_status` holds the ledger status verbatim rather than `needs-review`, which would put
    "a human must read this" on a row with nothing to read.
    """
    path = tmp_path / "unwritten.csv"
    written = write_unwritten(path, [make_record("modulo", status="no_excerpt", definition="")])
    assert written == 1
    row = read(path)[0]
    assert row["term"] == "Recursion"
    assert row["definition"] == ""
    assert row["x_status"] == "no_excerpt"


def test_an_empty_cell_stays_empty_rather_than_becoming_a_lone_apostrophe(tmp_path):
    """`"" in "=+-@..."` is True — the empty string is a substring of every string — so a
    `value[:1] in ...` guard escapes empty cells. The first full-book run shipped 76 such
    cells across `x_example`, `aliases` and `x_related`.
    """
    record = make_record().model_copy(
        update={"x_example": "", "aliases": [], "x_related": [], "x_context": ""}
    )
    path = tmp_path / "out.csv"
    write(path, [record])
    row = read(path)[0]
    assert row["x_example"] == ""
    assert row["aliases"] == ""
    assert row["x_related"] == ""
    assert row["x_context"] == ""


def test_a_term_that_later_succeeded_is_not_unwritten(tmp_path):
    """Membership is "has no ok row", not "has a non-ok row". With a shared ledger a term
    that failed in one run and succeeded in the next carries both records; reporting it
    unwritten would tell the reviewer to chase a term that has a definition in the CSV.
    """
    path = tmp_path / "unwritten.csv"
    written = write_unwritten(
        path,
        [
            make_record("modulo", status="no_excerpt", definition=""),
            make_record("modulo", status="ok"),
        ],
    )
    assert written == 0
    assert read(path) == []


def test_the_latest_failed_attempt_is_the_one_reported(tmp_path):
    """A term can accumulate several failures under one key — that history is the ledger's
    job, not the sidecar's. The reviewer needs the current state, once.
    """
    path = tmp_path / "unwritten.csv"
    early = make_record("modulo", status="fetch_error", definition="")
    late = make_record("modulo", status="no_excerpt", definition="")
    written = write_unwritten(path, [early, late])
    assert written == 1
    assert read(path)[0]["x_status"] == "no_excerpt"


def test_every_failure_status_is_reported_not_just_no_excerpt(tmp_path):
    """`llm_error` is the worst of the three — the model was billed and the term vanished
    anyway — so scoping the sidecar to `no_excerpt` would leave the costliest loss hidden.
    """
    path = tmp_path / "unwritten.csv"
    written = write_unwritten(
        path,
        [
            make_record("a", status="no_excerpt", definition=""),
            make_record("b", status="fetch_error", definition=""),
            make_record("c", status="llm_error", definition=""),
            make_record("d", status="ok"),
        ],
    )
    assert written == 3
    assert {r["x_status"] for r in read(path)} == {"no_excerpt", "fetch_error", "llm_error"}


def test_the_sidecar_is_written_even_when_nothing_is_unwritten(tmp_path):
    """Written conditionally, a previous run's file survives a clean run and reports terms
    that now have definitions — and its absence would mean either "nothing was unwritten"
    or "this directory is stale", with no way to tell which.
    """
    path = tmp_path / "unwritten.csv"
    written = write_unwritten(path, [make_record("recursion", status="ok")])
    assert written == 0
    assert path.exists()
    with path.open(encoding="utf-8", newline="") as handle:
        assert next(csv.reader(handle)) == COLUMNS


def test_a_stale_sidecar_is_replaced_not_appended_to(tmp_path):
    path = tmp_path / "unwritten.csv"
    write_unwritten(path, [make_record("modulo", status="no_excerpt", definition="")])
    write_unwritten(path, [make_record("recursion", status="ok")])
    assert read(path) == []


def test_the_sidecar_scopes_to_the_run_the_same_way_the_csv_does(tmp_path):
    """A prior book's failures share the default ledger path; a prior prompt version's
    share the ledger outright. Neither belongs in this run's report.
    """
    path = tmp_path / "unwritten.csv"
    written = write_unwritten(
        path,
        [
            make_record("photosynthesis", status="no_excerpt", definition=""),
            make_record("modulo", status="no_excerpt", definition="", prompt_version="v0"),
            make_record("modulo", status="no_excerpt", definition="", model="llama3.1"),
            make_record("modulo", status="no_excerpt", definition=""),
        ],
        prompt_version=PROMPT_VERSION,
        model=MODEL,
        slugs={"modulo"},
    )
    assert written == 1
    assert read(path)[0]["x_prompt_version"] == PROMPT_VERSION


def test_a_term_defined_under_another_prompt_version_is_unwritten_for_this_run(tmp_path):
    """Scoping happens before the done-check, deliberately: v1's definition is not in v2's
    CSV, so under v2 the term genuinely has none and the reviewer should be told.
    """
    path = tmp_path / "unwritten.csv"
    written = write_unwritten(
        path,
        [
            make_record("modulo", status="ok", prompt_version="v1"),
            make_record("modulo", status="no_excerpt", definition="", prompt_version="v2"),
        ],
        prompt_version="v2",
        slugs={"modulo"},
    )
    assert written == 1


def test_an_unwritten_row_carries_the_grounding_it_did_find(tmp_path):
    """0 is an index defect, 97 is a book that mentions the term in passing — ADR-0006."""
    path = tmp_path / "unwritten.csv"
    record = make_record("modulo", status="no_excerpt", definition="").model_copy(
        update={"excerpt_chars": 97, "source_pages": []}
    )
    write_unwritten(path, [record])
    row = read(path)[0]
    assert row["x_excerpt_chars"] == "97"
    assert row["pages"] == "https://a|https://b"
    assert row["x_source_pages"] == ""


def test_the_sidecar_has_the_same_columns_as_the_import_csv(tmp_path):
    """Same 21 columns so the two files concatenate into one sheet — the single-file view
    the reviewer wants, without handing an importer rows it would turn into empty entries.
    """
    path = tmp_path / "unwritten.csv"
    write_unwritten(path, [make_record("modulo", status="no_excerpt", definition="")])
    with path.open(encoding="utf-8", newline="") as handle:
        assert next(csv.reader(handle)) == COLUMNS


# --- --regenerate makes a subject's LATEST attempt the one that counts (ADR-0009) --------


def test_a_regenerated_term_appears_once_not_twice(tmp_path):
    """`--regenerate` re-attempts a subject that already has an `ok` row, so the ledger ends
    up holding two. Emitting both puts a duplicate term in the CSV — which `load_input`
    rejects outright on duplicate slugs, so it would fail at the very consumer it targets.
    """
    path = tmp_path / "out.csv"
    written = write(
        path,
        [
            make_record("equality", definition="thin, from 17 chars"),
            make_record("equality", definition="grounded, from 132 chars"),
        ],
        slugs={"equality"},
    )
    assert written == 1
    assert read(path)[0]["definition"] == "grounded, from 132 chars"


def test_a_term_that_regenerated_into_a_failure_leaves_the_csv(tmp_path):
    """The case that made this necessary: a term written before `MIN_EXCERPT_CHARS` existed,
    re-attempted under it, now correctly refused. Its stale `ok` row must not keep it in the
    import CSV — the definition it carries is one the tool would no longer write.
    """
    path = tmp_path / "out.csv"
    written = write(
        path,
        [
            make_record("modulo", definition="written before the floor existed"),
            make_record("modulo", status="no_excerpt", definition=""),
        ],
        slugs={"modulo"},
    )
    assert written == 0
    assert read(path) == []


def test_that_same_term_becomes_unwritten(tmp_path):
    """The other half: it does not vanish, it moves. Every term stays accounted for."""
    path = tmp_path / "unwritten.csv"
    written = write_unwritten(
        path,
        [
            make_record("modulo", definition="written before the floor existed"),
            make_record("modulo", status="no_excerpt", definition=""),
        ],
        slugs={"modulo"},
    )
    assert written == 1
    assert read(path)[0]["x_status"] == "no_excerpt"


def test_a_failure_followed_by_success_is_still_not_unwritten(tmp_path):
    """ADR-0006's original rule, which the latest-attempt rule must keep satisfying."""
    path = tmp_path / "unwritten.csv"
    records = [
        make_record("modulo", status="no_excerpt", definition=""),
        make_record("modulo", status="ok"),
    ]
    assert write_unwritten(path, records, slugs={"modulo"}) == 0
    assert write(tmp_path / "out.csv", records, slugs={"modulo"}) == 1
