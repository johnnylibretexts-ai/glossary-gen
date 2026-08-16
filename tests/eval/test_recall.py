import json
from pathlib import Path

from glossary_gen.scan.models import Corroboration
from glossary_gen.scan.evaluate import recall, replay

FIXTURE = Path(__file__).parent / "fixtures" / "replay_minimal.json"
FIXTURE_SCORING = Path(__file__).parent / "fixtures" / "replay_scoring.json"


def _fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _fixture_scoring():
    return json.loads(FIXTURE_SCORING.read_text(encoding="utf-8"))


def test_replay_drops_the_unverifiable_candidate():
    terms = replay(_fixture())
    assert "monad" not in {t.slug for t in terms}


def test_replay_keeps_the_grounded_candidates():
    assert {t.slug for t in replay(_fixture())} == {"recursion", "base-case"}


def test_recall_reports_found_and_missing_against_the_expected_set():
    fixture = _fixture()
    report = recall(replay(fixture), fixture["expected_slugs"])

    assert report.found == 2
    assert report.total == 3
    assert report.missing == ["algorithm"]
    assert report.rate == 2 / 3


def test_recall_reports_candidate_volume_and_not_precision():
    report = recall(replay(_fixture()), _fixture()["expected_slugs"])

    assert report.candidates == 2
    assert not hasattr(report, "precision")


def test_replay_reports_confidence_and_corroborations_unfused():
    """The model's confidence is passed through untouched, and each page signal is named.

    Previously these were added together and clamped, which is what ADR-0004 removed: the
    old assertion for "Recursion" expected exactly 1.0, and so would have been satisfied by
    any confidence at or above 0.75 — the clamp hid the input.
    """
    terms = replay(_fixture())
    # "Recursion": confidence=0.9, heading match, "is a" in evidence.
    recursion = next(t for t in terms if t.slug == "recursion")
    assert recursion.confidence == 0.9
    assert set(recursion.corroborations) == {Corroboration.HEADING, Corroboration.CUE}
    # "Base case": confidence=0.7, no heading, "is the" in evidence.
    base_case = next(t for t in terms if t.slug == "base-case")
    assert base_case.confidence == 0.7
    assert base_case.corroborations == [Corroboration.CUE]


def test_replay_merge_promotes_the_confident_form_and_preserves_aliases():
    """The most confident surface form represents the term; the other becomes an alias.

    "Algorithm" on page1: confidence=0.5, heading, "is a".
    "algorithm" on page2: confidence=0.4, no heading, no cue.
    Both slug to "algorithm", so they merge, and 0.5 beats 0.4.
    """
    terms = replay(_fixture_scoring())
    assert len(terms) == 1
    term = terms[0]

    assert term.slug == "algorithm"
    assert term.term == "Algorithm"
    assert "algorithm" in term.aliases
    assert term.confidence == 0.5
    # Unioned across both pages, plus MULTIPAGE, which only merging can know.
    assert set(term.corroborations) == {
        Corroboration.HEADING,
        Corroboration.CUE,
        Corroboration.MULTIPAGE,
    }
