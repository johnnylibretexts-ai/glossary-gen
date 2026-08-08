from __future__ import annotations

import re
from collections.abc import Sequence

from glossary_gen.models import Excerpt, Page, Term

DEFINITIONAL = re.compile(r"\b(is a|is an|is the|is called|refers to|means)\b", re.IGNORECASE)

RANK_AFTER_HEADING = 0
RANK_DEFINITIONAL = 1
RANK_MENTION = 2


def _needles(term: Term) -> tuple[str, ...]:
    return (term.term, *term.aliases)


def _pattern(needles: Sequence[str]) -> re.Pattern[str]:
    alternatives = "|".join(re.escape(n) for n in needles if n.strip())
    return re.compile(rf"\b({alternatives})\b", re.IGNORECASE)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def excerpts_for_term(
    pages: Sequence[Page],
    term: Term,
    *,
    max_excerpts: int = 3,
    max_chars: int = 6000,
) -> list[Excerpt]:
    """Return the highest-ranked paragraphs grounding `term`, across `pages`.

    Pure: no I/O. Ranking is documented in the module's task contract — paragraphs
    following a matching heading first, then definitional phrasing, then plain mentions.
    """
    needles = [n for n in _needles(term) if n.strip()]
    if not needles:
        return []
    pattern = _pattern(needles)

    candidates: list[tuple[int, int, int, Excerpt]] = []
    for page_index, page in enumerate(pages):
        heading_matched = False
        for block_index, block in enumerate(page.blocks):
            if block.kind == "heading":
                heading_matched = bool(pattern.search(block.text))
                continue
            # Determine rank for this paragraph
            if heading_matched:
                rank = RANK_AFTER_HEADING
            elif pattern.search(block.text):
                if DEFINITIONAL.search(block.text):
                    rank = RANK_DEFINITIONAL
                else:
                    rank = RANK_MENTION
            else:
                # No rank - skip this paragraph
                heading_matched = False
                continue
            heading_matched = False
            candidates.append(
                (rank, page_index, block_index, Excerpt(page_url=page.url, text=block.text, rank=rank))
            )

    candidates.sort(key=lambda item: (item[0], item[1], item[2]))

    selected: list[Excerpt] = []
    seen: set[str] = set()
    used_chars = 0
    for _, _, _, excerpt in candidates:
        if len(selected) >= max_excerpts:
            break
        fingerprint = _normalize(excerpt.text)
        if fingerprint in seen:
            continue
        if used_chars + len(excerpt.text) > max_chars:
            continue
        seen.add(fingerprint)
        used_chars += len(excerpt.text)
        selected.append(excerpt)
    return selected
