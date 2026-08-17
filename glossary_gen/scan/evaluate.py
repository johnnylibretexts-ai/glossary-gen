from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from glossary_gen.models import Block, Page
from glossary_gen.scan.candidates import corroborations_on_page, merge, verify
from glossary_gen.scan.models import MergedTerm, PageCandidates, VerifiedCandidate


@dataclass
class RecallReport:
    """Recall against a known term set, plus raw candidate volume.

    There is deliberately no precision field. The reference set is a SUBSET of a
    book's real vocabulary, not an exhaustive gold standard, so a candidate
    outside it is not necessarily wrong and a precision figure computed against
    it would be fabricated. Measuring precision properly requires hand-labelling
    a whole book.
    """

    found: int = 0
    total: int = 0
    candidates: int = 0
    missing: list[str] = field(default_factory=list)

    @property
    def rate(self) -> float:
        return self.found / self.total if self.total else 0.0


def _page(raw: dict[str, Any]) -> Page:
    return Page(
        url=raw["url"],
        blocks=tuple(Block(kind=b["kind"], text=b["text"]) for b in raw["blocks"]),
    )


def fixture_payload(
    recorded: Sequence[tuple[Page, PageCandidates]], expected: Sequence[str]
) -> dict[str, Any]:
    """Build a replay fixture from pages and the candidates a model proposed for them.

    The inverse of `replay`, and deliberately adjacent to it: the two share one JSON
    shape, and a fixture recorded against a drifted shape would replay as an empty
    pipeline — an eval that passes by measuring nothing.
    """
    return {
        "expected_slugs": list(expected),
        "pages": [
            {
                "url": page.url,
                "blocks": [{"kind": block.kind, "text": block.text} for block in page.blocks],
                "reply": candidates.model_dump(),
            }
            for page, candidates in recorded
        ],
    }


def replay(fixture: dict[str, Any]) -> list[MergedTerm]:
    """Re-run stages 4-7 over recorded stage-3 output. No network, no key, no
    cost.
    """
    verified: list[VerifiedCandidate] = []
    for raw_page in fixture["pages"]:
        page = _page(raw_page)
        for candidate in PageCandidates.model_validate(raw_page["reply"]).terms:
            if not verify(candidate, page):
                continue
            verified.append(
                VerifiedCandidate(
                    term=candidate.term,
                    aliases=candidate.aliases,
                    evidence=candidate.evidence,
                    page_url=page.url,
                    confidence=candidate.confidence,
                    corroborations=corroborations_on_page(candidate, page),
                )
            )
    return merge(verified)


def recall(found: Sequence[MergedTerm], expected: Sequence[str]) -> RecallReport:
    found_slugs = {term.slug for term in found}
    missing = [slug for slug in expected if slug not in found_slugs]
    return RecallReport(
        found=len(expected) - len(missing),
        total=len(expected),
        candidates=len(found),
        missing=missing,
    )
