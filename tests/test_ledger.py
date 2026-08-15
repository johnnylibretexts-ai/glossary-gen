import json

import pytest
from pydantic import BaseModel, ValidationError

from glossary_gen.ledger import Ledger, LedgerRecord


def make_record(subject="recursion", prompt_version="v1", model="gemini-3.5-flash", status="ok"):
    return LedgerRecord(
        subject=subject,
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
    assert ledger.has("recursion", "v1", "gemini-3.5-flash")


def test_has_is_false_for_unknown_key(tmp_path):
    ledger = Ledger(tmp_path / "run.jsonl")
    ledger.append(make_record())
    assert not ledger.has("other", "v1", "gemini-3.5-flash")


def test_changing_prompt_version_invalidates(tmp_path):
    ledger = Ledger(tmp_path / "run.jsonl")
    ledger.append(make_record(prompt_version="v1"))
    assert not ledger.has("recursion", "v2", "gemini-3.5-flash")


def test_changing_model_invalidates(tmp_path):
    ledger = Ledger(tmp_path / "run.jsonl")
    ledger.append(make_record(model="gemini-3.5-flash"))
    assert not ledger.has("recursion", "v1", "llama3.1")


def test_reopening_reloads_from_disk(tmp_path):
    path = tmp_path / "run.jsonl"
    Ledger(path).append(make_record())
    assert Ledger(path).has("recursion", "v1", "gemini-3.5-flash")


def test_truncated_final_line_is_skipped_not_fatal(tmp_path):
    path = tmp_path / "run.jsonl"
    Ledger(path).append(make_record())
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"subject": "half-writ')

    ledger = Ledger(path)

    assert ledger.skipped_lines == 1
    assert len(ledger.records()) == 1


def test_records_preserves_append_order(tmp_path):
    ledger = Ledger(tmp_path / "run.jsonl")
    ledger.append(make_record(subject="a"))
    ledger.append(make_record(subject="b"))
    assert [r.subject for r in ledger.records()] == ["a", "b"]


def test_error_status_round_trips(tmp_path):
    path = tmp_path / "run.jsonl"
    record = make_record(status="llm_error")
    record.error = "schema violation"
    Ledger(path).append(record)
    reloaded = Ledger(path).records()[0]
    assert (reloaded.status, reloaded.error) == ("llm_error", "schema violation")


def test_invalid_status_rejected_at_construction():
    with pytest.raises(ValidationError):
        LedgerRecord(
            subject="test",
            term="Test",
            prompt_version="v1",
            model="gemini-3.5-flash",
            provider="gemini",
            generated_at="2026-08-07T00:00:00Z",
            status="bogus",
            definition="A test.",
            pages=["https://a"],
            source_pages=["https://a"],
            excerpt_chars=42,
        )


def test_invalid_status_skipped_on_reload(tmp_path):
    path = tmp_path / "run.jsonl"
    # Write a valid record first
    Ledger(path).append(make_record())
    # Manually append a line with an invalid status
    with path.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "subject": "bad-status",
                    "term": "Bad",
                    "prompt_version": "v1",
                    "model": "gemini-3.5-flash",
                    "provider": "gemini",
                    "generated_at": "2026-08-07T00:00:00Z",
                    "status": "invalid_status",
                    "definition": "Invalid.",
                    "pages": ["https://a"],
                    "source_pages": ["https://a"],
                    "excerpt_chars": 42,
                }
            )
            + "\n"
        )

    ledger = Ledger(path)

    assert ledger.skipped_lines == 1
    assert len(ledger.records()) == 1
    assert ledger.records()[0].subject == "recursion"


def test_served_by_model_round_trips(tmp_path):
    path = tmp_path / "run.jsonl"
    record = make_record()
    record.served_by_model = "llama-fallback"
    Ledger(path).append(record)
    reloaded = Ledger(path).records()[0]
    assert reloaded.served_by_model == "llama-fallback"


def test_llm_error_record_does_not_count_as_done(tmp_path):
    """A failed attempt is history, not completion — it must be retried, not skipped."""
    ledger = Ledger(tmp_path / "run.jsonl")
    ledger.append(make_record(status="llm_error"))
    assert not ledger.has("recursion", "v1", "gemini-3.5-flash")


def test_fetch_error_and_no_excerpt_records_do_not_count_as_done(tmp_path):
    ledger = Ledger(tmp_path / "run.jsonl")
    ledger.append(make_record(subject="a", status="fetch_error"))
    ledger.append(make_record(subject="b", status="no_excerpt"))
    assert not ledger.has("a", "v1", "gemini-3.5-flash")
    assert not ledger.has("b", "v1", "gemini-3.5-flash")


def test_ok_record_counts_as_done(tmp_path):
    ledger = Ledger(tmp_path / "run.jsonl")
    ledger.append(make_record(status="ok"))
    assert ledger.has("recursion", "v1", "gemini-3.5-flash")


def test_failed_then_ok_record_counts_as_done(tmp_path):
    """A term that failed and later succeeded under the same key is done — the ok
    record is what matters, not the failure history alongside it.
    """
    ledger = Ledger(tmp_path / "run.jsonl")
    ledger.append(make_record(status="llm_error"))
    ledger.append(make_record(status="ok"))
    assert ledger.has("recursion", "v1", "gemini-3.5-flash")
    assert len(ledger.records()) == 2  # both rows kept — no dedup


def test_served_by_model_defaults_to_empty_when_not_set(tmp_path):
    path = tmp_path / "run.jsonl"
    # Manually write a record without served_by_model field
    with path.open("w", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "subject": "old-record",
                    "term": "Old",
                    "prompt_version": "v1",
                    "model": "gemini-3.5-flash",
                    "provider": "gemini",
                    "generated_at": "2026-08-07T00:00:00Z",
                    "status": "ok",
                    "definition": "Old record.",
                    "pages": ["https://a"],
                    "source_pages": ["https://a"],
                    "excerpt_chars": 42,
                }
            )
            + "\n"
        )

    ledger = Ledger(path)
    reloaded = ledger.records()[0]
    assert reloaded.served_by_model == ""


def test_ledger_written_before_the_subject_rename_still_counts_as_done(tmp_path):
    """A row keyed `slug` predates the rename to `subject` and must still resume.

    If the old name stopped validating, every such row would be counted as an unreadable
    line — which `Ledger` treats as not-done — and a resumed run would pay to generate
    every term in the book again.
    """
    path = tmp_path / "run.jsonl"
    with path.open("w", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "slug": "recursion",
                    "term": "Recursion",
                    "prompt_version": "v1",
                    "model": "gemini-3.5-flash",
                    "provider": "gemini",
                    "generated_at": "2026-08-07T00:00:00Z",
                    "status": "ok",
                    "definition": "A function calling itself.",
                }
            )
            + "\n"
        )

    ledger = Ledger(path)

    assert ledger.skipped_lines == 0
    assert ledger.records()[0].subject == "recursion"
    assert ledger.has("recursion", "v1", "gemini-3.5-flash")


def test_appended_records_are_written_under_the_new_name(tmp_path):
    """Reading `slug` is a concession to old files; writing it is not."""
    path = tmp_path / "run.jsonl"
    Ledger(path).append(make_record())
    written = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert written["subject"] == "recursion"
    assert "slug" not in written


class _OtherRecord(BaseModel):
    subject: str
    prompt_version: str
    model: str
    status: str
    n_proposed: int = 0


def test_ledger_stores_a_custom_record_type(tmp_path):
    path = tmp_path / "scan.jsonl"
    ledger = Ledger(path, record_cls=_OtherRecord)
    ledger.append(
        _OtherRecord(subject="p-1", prompt_version="v1", model="m", status="ok", n_proposed=3)
    )

    reloaded = Ledger(path, record_cls=_OtherRecord)

    assert reloaded.has("p-1", "v1", "m") is True
    assert reloaded.records()[0].n_proposed == 3


def test_ledger_defaults_to_the_generator_record_type(tmp_path):
    ledger = Ledger(tmp_path / "run.jsonl")
    assert ledger.records() == []
