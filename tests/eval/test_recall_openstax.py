import json
from pathlib import Path

from glossary_gen.scan.evaluate import recall, replay

FIXTURE = Path(__file__).parent / "fixtures" / "replay_openstax.json"

# Measured recall rate from a live run against Python Programming (OpenStax):
# 11 of 19 reference terms found, rate = 11/19 = 0.579.
# This floor is rounded DOWN to 0.55 (nearest 0.05) as a REGRESSION FLOOR,
# not a performance target. Its purpose is to fail CI if a prompt or scoring
# change silently reduces recall below the measured baseline.
RECALL_FLOOR = 0.55


def _fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_recall_floor_guard_was_substituted():
    """A placeholder floor of 0.0 would pass vacuously. This guard asserts the
    floor was measured and substituted in (i.e. RECALL_FLOOR > 0.0).
    """
    assert RECALL_FLOOR > 0.0, "RECALL_FLOOR placeholder was never replaced with a measured value"


def test_recall_openstax_meets_baseline():
    """Replay the OpenStax fixture and assert recall >= the measured baseline."""
    fixture = _fixture()
    found_terms = replay(fixture)
    report = recall(found_terms, fixture["expected_slugs"])

    assert report.rate >= RECALL_FLOOR, (
        f"Recall {report.rate:.3f} dropped below floor {RECALL_FLOOR}. Missing: {report.missing}"
    )


def test_recall_openstax_fixture_shape():
    """Guard against truncation or regeneration of the fixture file without
    re-measuring the floor.
    """
    fixture = _fixture()
    expected_slugs = fixture["expected_slugs"]

    assert len(fixture["pages"]) == 16, f"Expected 16 pages in fixture, got {len(fixture['pages'])}"
    assert len(expected_slugs) == 19, f"Expected 19 reference terms, got {len(expected_slugs)}"
