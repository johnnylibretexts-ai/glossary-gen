import json

from glossary_gen.input import load_input
from glossary_gen.models import Book
from glossary_gen.scan.emit import index_payload, report_payload, write_json
from glossary_gen.scan.models import ScoredTerm

BOOK = Book(
    library="eng",
    cover_id="117469",
    book_id="python-programming-openstax",
    title="Python Programming (OpenStax)",
    index_url="https://eng.libretexts.org/Bookshelves/CS/Python_Programming_(OpenStax)",
)
TERMS = [
    ScoredTerm(
        term="Recursion",
        aliases=["recursive"],
        pages=["https://eng.libretexts.org/a"],
        score=0.9,
    ),
    ScoredTerm(term="Base case", pages=["https://eng.libretexts.org/b"], score=0.3),
]


def test_emitted_index_is_accepted_by_the_consumer(tmp_path):
    path = tmp_path / "index.json"
    write_json(path, index_payload(BOOK, TERMS, min_score=0.0))

    loaded = load_input(path)

    assert loaded.book is not None
    assert loaded.book.cover_id == "117469"
    assert [t.term for t in loaded.terms] == ["Recursion", "Base case"]
    assert loaded.terms[0].aliases == ("recursive",)


def test_min_score_filters_low_confidence_terms(tmp_path):
    path = tmp_path / "index.json"
    write_json(path, index_payload(BOOK, TERMS, min_score=0.5))

    assert [t.term for t in load_input(path).terms] == ["Recursion"]


def test_scores_are_absent_from_the_index_payload():
    payload = index_payload(BOOK, TERMS, min_score=0.0)
    assert set(payload["terms"][0]) == {"term", "aliases", "pages"}


def test_report_carries_the_scores(tmp_path):
    path = tmp_path / "report.json"
    write_json(path, report_payload(TERMS))

    report = json.loads(path.read_text(encoding="utf-8"))

    assert report["terms"][0]["slug"] == "recursion"
    assert report["terms"][0]["score"] == 0.9
    assert report["count"] == 2
