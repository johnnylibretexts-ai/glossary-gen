"""Screen a book for an author glossary before spending anything on it.

Fetching is free; only model calls cost money. So whether a book publishes its own
glossary — the thing that decides whether it can be measured at all (ADR-0010) — can
be answered for nothing, on a sample of its pages, before a scan is ever paid for.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, TypeVar

from glossary_gen.scan.reference import book_glossary

T = TypeVar("T")


@dataclass(frozen=True)
class SurveyResult:
    """What a sample of one book's pages says about its glossary."""

    sampled: int
    with_glossary: int
    terms: int
    chars: int = 0

    @property
    def share(self) -> float:
        return self.with_glossary / self.sampled if self.sampled else 0.0


def evenly_spaced(items: Sequence[T], count: int) -> list[T]:
    """`count` items spanning the whole sequence, first and last included.

    Glossary blocks live in chapters. A sample taken off the top would screen a book
    on its title page, its licensing notice and its table of contents, and conclude
    that no book has a glossary.
    """
    if not items or count <= 0:
        return []
    if count >= len(items):
        return list(items)
    if count == 1:
        return [items[0]]
    step = (len(items) - 1) / (count - 1)
    return [items[round(i * step)] for i in range(count)]


def shelf_books(root: dict[str, Any]) -> list[tuple[str, str]]:
    """`(title, url)` for a bookshelf's immediate children — the books on it."""
    subpages = root.get("subpages") or []
    children = subpages if isinstance(subpages, list) else [subpages]
    return [
        (str(child.get("title") or ""), str(child.get("url")))
        for child in children
        if isinstance(child, dict) and child.get("url")
    ]


def survey_pages(pages: Iterable[tuple[str, str]]) -> SurveyResult:
    """Count what a sample of `(url, html)` pages carries."""
    pages = list(pages)
    with_glossary = sum(1 for page in pages if book_glossary([page]))
    return SurveyResult(
        sampled=len(pages),
        with_glossary=with_glossary,
        terms=len(book_glossary(pages)),
        chars=sum(len(html) for _, html in pages),
    )
