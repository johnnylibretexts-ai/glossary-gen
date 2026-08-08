from glossary_gen.ledger import Ledger, LedgerRecord


def make_record(slug="recursion", prompt_version="v1", model="gemini-flash-3.6", status="ok"):
    return LedgerRecord(
        slug=slug,
        term="Recursion",
        prompt_version=prompt_version,
        model=model,
        provider="gemini",
        generated_at="2026-08-07T00:00:00Z",
        status=status,
        definition="A function calling itself.",
        pages=["https://a"],
        source_pages=["https://a"],
        excerpt_chars=42,
    )


def test_append_then_has_is_true(tmp_path):
    ledger = Ledger(tmp_path / "run.jsonl")
    ledger.append(make_record())
    assert ledger.has("recursion", "v1", "gemini-flash-3.6")


def test_has_is_false_for_unknown_key(tmp_path):
    ledger = Ledger(tmp_path / "run.jsonl")
    ledger.append(make_record())
    assert not ledger.has("other", "v1", "gemini-flash-3.6")


def test_changing_prompt_version_invalidates(tmp_path):
    ledger = Ledger(tmp_path / "run.jsonl")
    ledger.append(make_record(prompt_version="v1"))
    assert not ledger.has("recursion", "v2", "gemini-flash-3.6")


def test_changing_model_invalidates(tmp_path):
    ledger = Ledger(tmp_path / "run.jsonl")
    ledger.append(make_record(model="gemini-flash-3.6"))
    assert not ledger.has("recursion", "v1", "llama3.1")


def test_reopening_reloads_from_disk(tmp_path):
    path = tmp_path / "run.jsonl"
    Ledger(path).append(make_record())
    assert Ledger(path).has("recursion", "v1", "gemini-flash-3.6")


def test_truncated_final_line_is_skipped_not_fatal(tmp_path):
    path = tmp_path / "run.jsonl"
    Ledger(path).append(make_record())
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"slug": "half-writ')

    ledger = Ledger(path)

    assert ledger.skipped_lines == 1
    assert len(ledger.records()) == 1


def test_records_preserves_append_order(tmp_path):
    ledger = Ledger(tmp_path / "run.jsonl")
    ledger.append(make_record(slug="a"))
    ledger.append(make_record(slug="b"))
    assert [r.slug for r in ledger.records()] == ["a", "b"]


def test_error_status_round_trips(tmp_path):
    path = tmp_path / "run.jsonl"
    record = make_record(status="llm_error")
    record.error = "schema violation"
    Ledger(path).append(record)
    reloaded = Ledger(path).records()[0]
    assert (reloaded.status, reloaded.error) == ("llm_error", "schema violation")
