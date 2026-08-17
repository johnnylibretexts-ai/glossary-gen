"""Recording a replay fixture is the inverse of replaying one.

An eval fixture is only worth committing if what comes out of `replay` is what
went in. These tests hold the two halves against each other so a change to either
model's JSON shape fails here rather than silently producing an eval that scores
an empty pipeline as passing.
"""

import json

from glossary_gen.models import Block, Page
from glossary_gen.scan.evaluate import fixture_payload, replay
from glossary_gen.scan.models import Candidate, PageCandidates

PAGE = Page(
    url="https://stats.libretexts.org/Bookshelves/x/1.02%3A_Definitions",
    blocks=(
        Block(kind="heading", text="Definitions of Statistics"),
        Block(kind="paragraph", text="A population is the set of all objects under study."),
    ),
)
CANDIDATES = PageCandidates(
    terms=[
        Candidate(
            term="Population",
            aliases=["populations"],
            evidence="A population is the set of all objects under study.",
            confidence=0.9,
        )
    ]
)


def test_a_recorded_page_replays_into_the_term_it_recorded():
    payload = fixture_payload([(PAGE, CANDIDATES)], expected=["population"])

    assert [term.slug for term in replay(payload)] == ["population"]


def test_the_payload_carries_the_expected_slugs_it_was_given():
    payload = fixture_payload([(PAGE, CANDIDATES)], expected=["population", "sample"])

    assert payload["expected_slugs"] == ["population", "sample"]


def test_the_payload_is_json_serialisable():
    """It is written to disk and read back by the eval, so a value that only
    survives in memory (a tuple of Blocks, a pydantic model) is a broken fixture.
    """
    payload = fixture_payload([(PAGE, CANDIDATES)], expected=["population"])

    reloaded = json.loads(json.dumps(payload))

    assert [term.slug for term in replay(reloaded)] == ["population"]
    assert reloaded["pages"][0]["url"] == PAGE.url
