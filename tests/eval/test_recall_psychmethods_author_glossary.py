"""Recall over a whole book, against 243 terms its own authors published.

The third and largest reference set in the repo, and the first from a Pressbooks
book. `test_recall_openstax.py` scores 19 slugs someone typed;
`test_recall_stats_author_glossary.py` scores 101 harvested from one book's
glossary blocks. This one scores **243** from *Research Methods in Psychology* —
100 listed on its back-matter glossary page and 143 linked inline in its chapters,
which is a shape only the Pressbooks harvest reaches.

Two things make it a different measurement from the other two, both deliberate:

**It replays the whole book, not just the pages carrying a glossary.** All 83
pages are in the fixture, so the figure is the one a real run produces rather than
a subset's. That includes the pages that proposed nothing — among them the book's
own glossary page, which the scanner is structurally unable to read and is no
longer paid to try (ADR-0011).

**Nothing was spent to record it.** The replies come from the ledger of the paid
run on 2026-08-18, rebuilt by `tools/record_fixture.py --from-ledger`. Buying the
same proposals twice is what ADR-0008 exists to prevent.
"""

import json
from pathlib import Path

from glossary_gen.scan.evaluate import recall, replay

FIXTURE = Path(__file__).parent / "fixtures" / "replay_psychmethods.json"

# Measured against the recorded fixture: 187 of 243 author-written terms found,
# rate = 0.770 — the same figure `tools/harvest_glossary.py` reports for that run
# against the live index, which is the point of them agreeing. Rounded DOWN to 0.75
# (nearest 0.05) as a REGRESSION FLOOR, the same convention as the other two. Not a
# target, and not a claim that three quarters of a book's glossary is good enough.
PSYCH_RECALL_FLOOR = 0.75


def _fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_recall_against_the_author_glossary_meets_baseline():
    fixture = _fixture()

    report = recall(replay(fixture), fixture["expected_slugs"])

    assert report.rate >= PSYCH_RECALL_FLOOR, (
        f"Recall {report.rate:.3f} dropped below floor {PSYCH_RECALL_FLOOR}. "
        f"Missing: {report.missing}"
    )


def test_the_replay_still_reproduces_the_run_it_was_recorded_from():
    """The paid run merged 303 terms from 343 proposals. Replaying the same replies
    through verify/corroborate/merge must land on the same 303 — otherwise the
    fixture is measuring a pipeline that no longer matches the one that produced it,
    and the recall figure above describes nothing that ever ran.
    """
    assert len(replay(_fixture())) == 303


def test_fixture_shape_guards_against_silent_regeneration():
    """A fixture rebuilt over fewer pages, or with a shrunken expected set, would
    raise the rate without the scanner improving. Both counts are pinned.
    """
    fixture = _fixture()

    assert len(fixture["pages"]) == 83, f"Expected 83 recorded pages, got {len(fixture['pages'])}"
    assert len(fixture["expected_slugs"]) == 243, (
        f"Expected 243 harvested terms, got {len(fixture['expected_slugs'])}"
    )


def test_the_expected_set_is_harvested_rather_than_hand_written():
    """Every expected slug must still be derivable from the book. A hand-added slug —
    the failure mode this whole approach exists to remove — would not survive a
    re-harvest, so it must not be possible to add one unnoticed.
    """
    fixture = _fixture()

    assert fixture["expected_slugs"] == sorted(set(fixture["expected_slugs"]))
