from __future__ import annotations

import re
from dataclasses import dataclass

from pydantic import BaseModel, Field

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def slugify(value: str) -> str:
    """Lowercase, non-alphanumerics collapsed to single hyphens, trimmed."""
    return _NON_ALNUM.sub("-", value.strip().casefold()).strip("-")


@dataclass(frozen=True)
class Term:
    term: str
    slug: str
    aliases: tuple[str, ...]
    pages: tuple[str, ...]


@dataclass(frozen=True)
class Book:
    library: str
    cover_id: str
    book_id: str
    title: str
    index_url: str


@dataclass(frozen=True)
class Block:
    kind: str  # "heading" | "paragraph"
    text: str


@dataclass(frozen=True)
class Page:
    url: str
    blocks: tuple[Block, ...]


@dataclass(frozen=True)
class Excerpt:
    page_url: str
    text: str
    rank: int


class GlossaryEntry(BaseModel):
    """The structured output a provider must return for one term."""

    definition: str = Field(min_length=1)
    category: str = ""
    context: str = ""
    example: str = ""
    related: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
