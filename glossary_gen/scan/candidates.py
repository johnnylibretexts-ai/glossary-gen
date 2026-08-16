from __future__ import annotations

import re
from collections.abc import Sequence

from glossary_gen.excerpt import DEFINITIONAL
from glossary_gen.models import Page
from glossary_gen.scan.models import (
    Candidate,
    Corroboration,
    MergedTerm,
    VerifiedCandidate,
)

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


# There are no weights here any more, and adding some back is the mistake ADR-0004 exists to
# prevent. Fusing these signals into one number produced a figure that tied 64% of a real
# book's 212 terms at the ceiling, ranking almost nothing — and every signal answers "is this
# defined on this page?", which is not the question a reviewer trimming a glossary is asking.


def _needle_pattern(candidate: Candidate) -> re.Pattern[str] | None:
    needles = [n for n in (candidate.term, *candidate.aliases) if n.strip()]
    if not needles:
        # No usable needles. Do NOT fall through to `re.compile(r"\b(|)\b")` here:
        # an empty alternation degenerates to `\b()\b`, which matches at essentially
        # every word boundary, so `has_heading_match` would return True for any
        # heading-bearing page instead of False.
        return None
    alternatives = "|".join(re.escape(n) for n in needles)
    return re.compile(rf"\b({alternatives})\b", re.IGNORECASE)


def has_heading_match(candidate: Candidate, page: Page) -> bool:
    """True when the term or an alias appears in one of the page's headings.

    `parse_page` collects h1-h4 only, so the h5 template boilerplate that dominates
    LibreTexts pages ("Learning Objectives", "Concepts in Practice") is already
    excluded upstream and cannot inflate this signal.
    """
    pattern = _needle_pattern(candidate)
    if pattern is None:
        return False
    return any(block.kind == "heading" and pattern.search(block.text) for block in page.blocks)


def corroborations_on_page(candidate: Candidate, page: Page) -> list[Corroboration]:
    """Which independent signals on this page agree the term is defined here.

    Never emits `MULTIPAGE`: whether a term appears on more than one page cannot be known
    from one page, so it is `merge`'s to add.
    """
    found: list[Corroboration] = []
    if has_heading_match(candidate, page):
        found.append(Corroboration.HEADING)
    if DEFINITIONAL.search(candidate.evidence):
        found.append(Corroboration.CUE)
    return found


def merge(verified: Sequence[VerifiedCandidate]) -> list[MergedTerm]:
    """Collapse per-page candidates into one row per slug, ordered by slug.

    Ordered by slug, not by any measure of quality, because there is no longer one and
    inventing an order would imply a ranking the scanner cannot justify (ADR-0004).

    Deduplication by slug is mandatory, not cosmetic: `input.load_input` raises
    `InputError` on a duplicate slug, so an unmerged index would be rejected by the very
    consumer it targets. Note this does not merge singular/plural pairs — "Dictionary"
    and "Dictionaries" slugify differently and both survive, by design (see the spec's
    known limitations); a string rule aggressive enough to merge them also merges
    genuinely distinct terms.
    """
    groups: dict[str, list[VerifiedCandidate]] = {}
    for candidate in verified:
        groups.setdefault(candidate.slug, []).append(candidate)

    merged: list[MergedTerm] = []
    for members in groups.values():
        # Which spelling represents the term: the most confident, then the best corroborated,
        # then whichever was seen first. `max` is stable and returns the earliest of equals,
        # so the last clause is the existing iteration order rather than an arbitrary pick —
        # an index would produce the same result and read as if it did more.
        best = max(members, key=lambda c: (c.confidence, len(c.corroborations)))
        pages: list[str] = []
        aliases: list[str] = []
        corroborations: list[Corroboration] = []
        for member in members:
            if member.page_url not in pages:
                pages.append(member.page_url)
            for alias in (*member.aliases, member.term):
                if alias != best.term and alias not in aliases:
                    aliases.append(alias)
            # Unioned across every page that proposed the term: a heading match on page 2 is
            # a real observation even when page 1 is the one representing the term.
            for corroboration in member.corroborations:
                if corroboration not in corroborations:
                    corroborations.append(corroboration)
        if len(pages) > 1:
            corroborations.append(Corroboration.MULTIPAGE)
        merged.append(
            MergedTerm(
                term=best.term,
                aliases=aliases,
                pages=pages,
                confidence=best.confidence,
                corroborations=corroborations,
                evidence=best.evidence,
            )
        )
    merged.sort(key=lambda t: t.slug)
    return merged
