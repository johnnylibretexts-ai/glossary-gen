import json
from pathlib import Path

from glossary_gen.scan.evaluate import recall, replay

FIXTURE = Path(__file__).parent / "fixtures" / "replay_minimal.json"


def _fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


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
