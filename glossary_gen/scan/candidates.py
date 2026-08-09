from __future__ import annotations

import re
from collections.abc import Sequence

from glossary_gen.excerpt import DEFINITIONAL
from glossary_gen.models import Page
from glossary_gen.scan.models import Candidate, ScoredCandidate, ScoredTerm

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


def merge(scored: Sequence[ScoredCandidate]) -> list[ScoredTerm]:
    """Collapse per-page candidates into one row per slug, highest score first.

    Deduplication by slug is mandatory, not cosmetic: `input.load_input` raises
    `InputError` on a duplicate slug, so an unmerged index would be rejected by the very
    consumer it targets. Note this does not merge singular/plural pairs — "Dictionary"
    and "Dictionaries" slugify differently and both survive, by design (see the spec's
    known limitations); a string rule aggressive enough to merge them also merges
    genuinely distinct terms.
    """
    groups: dict[str, list[ScoredCandidate]] = {}
    for candidate in scored:
        groups.setdefault(candidate.slug, []).append(candidate)

    merged: list[ScoredTerm] = []
    for members in groups.values():
        best = max(members, key=lambda c: c.score)
        pages: list[str] = []
        aliases: list[str] = []
        for member in members:
            if member.page_url not in pages:
                pages.append(member.page_url)
            for alias in (*member.aliases, member.term):
                if alias != best.term and alias not in aliases:
                    aliases.append(alias)
        score = best.score + (MULTIPAGE_BONUS if len(pages) > 1 else 0.0)
        merged.append(
            ScoredTerm(
                term=best.term,
                aliases=aliases,
                pages=pages,
                score=min(score, 1.0),
                evidence=best.evidence,
            )
        )
    merged.sort(key=lambda t: (-t.score, t.slug))
    return merged
