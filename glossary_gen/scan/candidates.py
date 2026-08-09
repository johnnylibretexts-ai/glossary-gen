from __future__ import annotations

import re

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
