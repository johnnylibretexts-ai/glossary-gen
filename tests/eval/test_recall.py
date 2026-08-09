import json
from pathlib import Path

from glossary_gen.scan.candidates import CUE_BONUS, HEADING_BONUS, MULTIPAGE_BONUS
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


def test_replay_score_matches_model():
    """Exact score of a grounded candidate reflects confidence plus applicable
    bonuses.
    """
    terms = replay(_fixture())
    # "Recursion": confidence=0.9, heading match, "is a" in evidence
    #   -> 0.9 + HEADING_BONUS + CUE_BONUS = clamped to 1.0
    recursion = next(t for t in terms if t.slug == "recursion")
    expected_score = min(0.9 + HEADING_BONUS + CUE_BONUS, 1.0)
    assert recursion.score == expected_score
    # "Base case": confidence=0.7, no heading, "is the" in evidence
    #   -> 0.7 + CUE_BONUS
    base_case = next(t for t in terms if t.slug == "base-case")
    expected_score = 0.7 + CUE_BONUS
    assert base_case.score == expected_score


def test_replay_merge_picks_highest_score_and_preserves_aliases():
    """When a term appears on multiple pages with different surface forms, the
    highest-scoring form wins as term, the loser becomes an alias, and the
    multipage bonus is applied.
    """
    terms = replay(_fixture_scoring())
    assert len(terms) == 1
    term = terms[0]

    # "Algorithm" on page1: confidence=0.8, heading, "is a"
    #   -> 0.8 + HEADING_BONUS + CUE_BONUS = 1.05 -> clamped to 1.0
    # "algorithm" on page2: confidence=0.6, no heading, no definitional cue
    #   -> 0.6
    # Both slug to "algorithm", so they merge.
    # Winner is "Algorithm" with score 1.0 (higher than 0.6).
    # After multipage merge: 1.0 + MULTIPAGE_BONUS = 1.05 -> clamped to 1.0
    assert term.slug == "algorithm"
    assert term.term == "Algorithm"
    assert "algorithm" in term.aliases
    expected_score = min(1.0 + MULTIPAGE_BONUS, 1.0)
    assert term.score == expected_score
