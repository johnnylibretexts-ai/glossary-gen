"""Recall against terms the book's own authors chose, not terms anyone picked.

`test_recall_openstax.py` scores 19 reference slugs someone wrote by hand. This
one scores 101 harvested from Introductory Statistics' own glossary blocks: the
expected set is published editorial judgement, it costs nothing to regenerate
when the book changes, and no one can quietly tune it to the result.

The fixture holds one recorded propose call per page that carries a glossary
block (33 of 117), so the whole eval replays offline — no network, no key, no
spend. `tools/record_fixture.py` rebuilds it.
"""

import json
from pathlib import Path

from glossary_gen.scan.evaluate import recall, replay

FIXTURE = Path(__file__).parent / "fixtures" / "replay_stats.json"

# Measured against the recorded fixture: 55 of 101 author-written terms found,
# rate = 0.545. Rounded DOWN to 0.50 (nearest 0.05) as a REGRESSION FLOOR, the
# same convention as RECALL_FLOOR — not a target, and not a claim that half a
# book's glossary is good enough.
#
# That 0.545 was measured before `recall` counted alias slugs; the same fixture now
# scores 63/101 = 0.624. The floor is deliberately NOT raised to match. It records
# what was measured on 2026-08-16 and what the run of that day is entitled to claim,
# and re-cutting a floor to a definition adopted later would quietly rewrite it.
STATS_RECALL_FLOOR = 0.50


def _fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_recall_against_the_author_glossary_meets_baseline():
    fixture = _fixture()

    report = recall(replay(fixture), fixture["expected_slugs"])

    assert report.rate >= STATS_RECALL_FLOOR, (
        f"Recall {report.rate:.3f} dropped below floor {STATS_RECALL_FLOOR}. "
        f"Missing: {report.missing}"
    )


def test_fixture_shape_guards_against_silent_regeneration():
    """A fixture rebuilt over fewer pages, or with a shrunken expected set, would
    raise the rate without the scanner improving. Both counts are pinned.
    """
    fixture = _fixture()

    assert len(fixture["pages"]) == 33, f"Expected 33 recorded pages, got {len(fixture['pages'])}"
    assert len(fixture["expected_slugs"]) == 101, (
        f"Expected 101 harvested terms, got {len(fixture['expected_slugs'])}"
    )


def test_the_expected_set_is_harvested_rather_than_hand_written():
    """Every expected slug must still be derivable from the book. A hand-added
    slug — the failure mode this whole approach exists to remove — would not
    survive a re-harvest, so it must not be possible to add one unnoticed.
    """
    fixture = _fixture()

    assert fixture["expected_slugs"] == sorted(set(fixture["expected_slugs"]))
