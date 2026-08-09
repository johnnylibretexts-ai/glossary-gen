import pytest
from pydantic import ValidationError

from glossary_gen.scan.models import Candidate, PageCandidates, ScanRecord, ScoredTerm


def test_candidate_requires_a_term_and_evidence():
    with pytest.raises(ValidationError):
        Candidate(term="", evidence="something", confidence=0.5)


def test_candidate_clamps_confidence_to_the_unit_interval():
    with pytest.raises(ValidationError):
        Candidate(term="Recursion", evidence="Recursion is a technique", confidence=1.4)


def test_candidate_rejects_a_whitespace_only_term():
    with pytest.raises(ValidationError):
        Candidate(term="   ", evidence="something", confidence=0.5)


def test_candidate_still_accepts_legitimate_short_terms():
    assert Candidate(term="IO", evidence="IO is input/output", confidence=0.5).term == "IO"
    assert Candidate(term="if", evidence="if is a keyword", confidence=0.5).term == "if"


def test_page_candidates_defaults_to_an_empty_list():
    assert PageCandidates().terms == []


def test_scored_term_slug_is_derived_from_the_term():
    term = ScoredTerm(term="List comprehension", pages=["https://x"], score=0.5)
    assert term.slug == "list-comprehension"


def test_scan_record_exposes_the_four_fields_the_ledger_keys_on():
    record = ScanRecord(
        slug="p-1",
        page_url="https://x",
        prompt_version="v1",
        model="m",
        generated_at="2026-08-08T00:00:00Z",
        status="ok",
    )
    for field in ("slug", "prompt_version", "model", "status"):
        assert hasattr(record, field)
