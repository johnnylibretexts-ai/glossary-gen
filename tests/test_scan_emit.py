import json

import pytest

from glossary_gen.input import load_input
from glossary_gen.models import Book
from glossary_gen.scan.emit import (
    EmitError,
    index_payload,
    report_payload,
    write_json,
)
from glossary_gen.scan.models import Corroboration, MergedTerm

BOOK = Book(
    library="eng",
    cover_id="117469",
    book_id="python-programming-openstax",
    title="Python Programming (OpenStax)",
    index_url="https://eng.libretexts.org/Bookshelves/CS/Python_Programming_(OpenStax)",
)
TERMS = [
    MergedTerm(
        term="Recursion",
        aliases=["recursive"],
        pages=["https://eng.libretexts.org/a"],
        confidence=0.9,
        corroborations=[Corroboration.HEADING, Corroboration.CUE],
    ),
    MergedTerm(
        term="Base case",
        pages=["https://eng.libretexts.org/b"],
        confidence=0.3,
    ),
]


def test_emitted_index_is_accepted_by_the_consumer(tmp_path):
    path = tmp_path / "index.json"
    write_json(path, index_payload(BOOK, TERMS))

    loaded = load_input(path)

    assert loaded.book is not None
    assert loaded.book.cover_id == "117469"
    assert [t.term for t in loaded.terms] == ["Recursion", "Base case"]
    assert loaded.terms[0].aliases == ("recursive",)


def test_scanner_signals_are_absent_from_the_index_payload():
    payload = index_payload(BOOK, TERMS)
    assert set(payload["terms"][0]) == {"term", "aliases", "pages"}


def test_report_carries_confidence_and_corroborations_separately(tmp_path):
    path = tmp_path / "report.json"
    write_json(path, report_payload(TERMS))

    report = json.loads(path.read_text(encoding="utf-8"))

    assert report["terms"][0]["slug"] == "recursion"
    assert report["terms"][0]["confidence"] == 0.9
    # Reported as the words they are, never fused into one number — see ADR-0004.
    assert report["terms"][0]["corroborations"] == ["heading", "cue"]
    assert report["terms"][1]["corroborations"] == []
    assert report["count"] == 2


def test_empty_terms_list_raises_emit_error():
    with pytest.raises(EmitError, match=r"the scan produced no terms"):
        index_payload(BOOK, [])


def test_report_payload_unfiltered_even_when_index_would_fail():
    report = report_payload([])
    assert report["count"] == 0
    assert report["terms"] == []

    report = report_payload(TERMS)
    assert report["count"] == 2
