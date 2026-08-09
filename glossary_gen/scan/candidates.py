from __future__ import annotations

import re

from glossary_gen.excerpt import DEFINITIONAL
from glossary_gen.models import Page
from glossary_gen.scan.models import Candidate

# A span shorter than this proves nothing — "a", "is", or a bare term name occurs on
# almost any page, so accepting it would make the gate a no-op for short hallucinations.
MIN_EVIDENCE_CHARS = 20

_WS = re.compile(r"\s+")


def _normalize(text: str) -> str:
    return _WS.sub(" ", text).strip().casefold()


def page_text(page: Page) -> str:
    """The page as the consumer sees it: heading and paragraph blocks only."""
    return " ".join(block.text for block in page.blocks)


def verify(candidate: Candidate, page: Page) -> bool:
    """True when the claimed evidence occurs literally on the page.

    This is a hard gate, not a scoring signal. A model that invents a term also
    invents its evidence, and an invented span will not be found here. Comparison
    is whitespace- and case-insensitive because `parse_page` already reflows text.
    """
    evidence = _normalize(candidate.evidence)
    if len(evidence) < MIN_EVIDENCE_CHARS:
        return False
    return evidence in _normalize(page_text(page))


# Weights are deliberately fixed, not fitted. Nineteen labelled reference terms
# cannot support fitting four parameters; the eval harness reports what these buy
# instead.
HEADING_BONUS = 0.15
CUE_BONUS = 0.10
MULTIPAGE_BONUS = 0.05


def _needle_pattern(candidate: Candidate) -> re.Pattern[str]:
    needles = [n for n in (candidate.term, *candidate.aliases) if n.strip()]
    alternatives = "|".join(re.escape(n) for n in needles)
    return re.compile(rf"\b({alternatives})\b", re.IGNORECASE)


def has_heading_match(candidate: Candidate, page: Page) -> bool:
    """True when the term or an alias appears in one of the page's headings.

    `parse_page` collects h1-h4 only, so the h5 template boilerplate that dominates
    LibreTexts pages ("Learning Objectives", "Concepts in Practice") is already
    excluded upstream and cannot inflate this signal.
    """
    pattern = _needle_pattern(candidate)
    return any(block.kind == "heading" and pattern.search(block.text) for block in page.blocks)


def score_on_page(candidate: Candidate, page: Page) -> float:
    """Model confidence plus corroboration bonuses, clamped to 1.0."""
    score = candidate.confidence
    if has_heading_match(candidate, page):
        score += HEADING_BONUS
    if DEFINITIONAL.search(candidate.evidence):
        score += CUE_BONUS
    return min(score, 1.0)
