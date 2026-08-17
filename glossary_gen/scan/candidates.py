from __future__ import annotations

import re
from collections.abc import Sequence

from glossary_gen.excerpt import DEFINITIONAL, bounded
from glossary_gen.models import Page
from glossary_gen.scan.models import (
    Candidate,
    Corroboration,
    MergedTerm,
    RejectedCandidate,
    Rejection,
    ScanRecord,
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


def rejection_of(candidate: Candidate, page: Page) -> Rejection | None:
    """Why this candidate fails the evidence gate, or `None` when it passes.

    This is a hard gate, not a scoring signal. A model that invents a term also
    invents its evidence, and an invented span will not be found here. Comparison
    is whitespace- and case-insensitive because `parse_page` already reflows text.

    The reason is returned rather than a bare bool because the two failures mean opposite
    things — see `Rejection` — and the scanner's diagnostic report records which one fired
    (ADR-0007). Order matters: the length check runs first, so a short span that IS on the
    page reports as too-short rather than being mislabelled a hallucination.
    """
    evidence = _normalize(candidate.evidence)
    if len(evidence) < MIN_EVIDENCE_CHARS:
        return Rejection.EVIDENCE_TOO_SHORT
    if evidence not in _normalize(page_text(page)):
        return Rejection.EVIDENCE_NOT_ON_PAGE
    return None


def verify(candidate: Candidate, page: Page) -> bool:
    """True when the claimed evidence occurs literally on the page.

    The readable predicate for callers that do not care WHY — `replay()` scores recall by
    slug and has no report to write. Defined in terms of `rejection_of` so the two cannot
    drift apart.
    """
    return rejection_of(candidate, page) is None


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
    # `bounded` rather than wrapping the group in `\b(...)\b`: a needle ending in `)` can
    # never satisfy a trailing `\b`, so `super()` and `__init__()` could never match a
    # heading here — losing a corroboration for exactly the terms `excerpt.py` was also
    # failing to ground. Shared with `excerpt.py` so the two cannot drift apart again.
    alternatives = "|".join(bounded(n) for n in needles)
    return re.compile(f"({alternatives})", re.IGNORECASE)


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


def is_rebuildable(record: ScanRecord) -> bool:
    """True when this row can contribute what it found to a rebuilt index.

    A row written before candidates were stored says `candidates is None`: it knows a page
    was scanned and how many terms it verified, but not which, so the page has to be scanned
    again. A row that stored `[]` is complete — the page defined nothing — and re-paying for
    it would be paying twice for a known answer.

    Only `ok` rows carry candidates at all; a `fetch_error` or `llm_error` row was never
    done in the first place and `Ledger.has` already refuses it.
    """
    return record.status == "ok" and record.candidates is not None


def terms_from_ledger(records: Sequence[ScanRecord]) -> list[MergedTerm]:
    """The book's terms, rebuilt from every page the ledger has ever scanned.

    This is what makes a resumed scan produce a whole book instead of whichever pages that
    invocation happened to pay for. `glossary-gen` has had the equivalent all along by
    writing its CSV from `ledger.records()`; the scanner could not, because its rows stored
    counts rather than candidates (ADR-0008).
    """
    return merge(
        [c for record in records if is_rebuildable(record) for c in record.candidates or []]
    )


def rejections_from_ledger(records: Sequence[ScanRecord]) -> list[RejectedCandidate]:
    """Every candidate the gate refused, across every page the ledger has scanned.

    Same rebuild rule as `terms_from_ledger` so the diagnostic report and the index always
    describe the same set of pages (ADR-0007 records what the block is for).
    """
    return [r for record in records if is_rebuildable(record) for r in record.rejected or []]


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

    That last clause is now measured rather than asserted. Over the 212 terms of the
    OpenStax run, the cheapest such rule — one term's words a strict subset of another's
    — fires on 73 pairs and collapses 3 of the 6 near-duplicates a reader flagged. The
    other 70 are "Function" against "Max function", "Statement" against "If statement",
    "Dictionary" against "Nested dictionary": deleting roughly seventy real terms to
    collapse three. Meanwhile "Modulo"/"Modulus" needs a rule no string comparison
    supplies, and "Boolean value"/"Boolean variable" are defined on one page, which is
    evidence the book distinguishes them rather than that we failed to. Genuine
    duplicates ran to about 1% of the book. Do not add a similarity rule here without
    numbers of the same kind.
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
