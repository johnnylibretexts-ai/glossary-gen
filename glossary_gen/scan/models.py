from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, computed_field

from glossary_gen.models import slugify

ScanStatus = Literal["ok", "fetch_error", "llm_error"]


class Candidate(BaseModel):
    """One term a model claims a page defines, with the span it claims proves it."""

    # `min_length=1` alone accepts a whitespace-only string (e.g. a single space);
    # the pattern additionally requires at least one non-whitespace character, while
    # still allowing legitimate short terms like "IO" or "if".
    term: str = Field(min_length=1, pattern=r"\S")
    aliases: list[str] = Field(default_factory=list)
    evidence: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)


class PageCandidates(BaseModel):
    """The schema one page's LLM call must return."""

    terms: list[Candidate] = Field(default_factory=list)


class ScoredCandidate(BaseModel):
    """A verified candidate with its per-page score, before cross-page merging."""

    term: str
    aliases: list[str] = Field(default_factory=list)
    evidence: str
    page_url: str
    score: float

    @computed_field
    @property
    def slug(self) -> str:
        return slugify(self.term)


class ScoredTerm(BaseModel):
    """One merged term, ready to emit."""

    term: str
    aliases: list[str] = Field(default_factory=list)
    pages: list[str]
    score: float
    evidence: str = ""

    @computed_field
    @property
    def slug(self) -> str:
        return slugify(self.term)


class ScanRecord(BaseModel):
    """One ledger row per page.

    `slug` (not `page_slug`) because `Ledger` keys on `record.slug`. A page that defines
    no terms is `ok` with `n_proposed = 0`, never a distinct status — `Ledger.has()` counts
    only `ok` as done, so a separate status would re-issue a paid call for every term-free
    page on every resumed run, forever.
    """

    slug: str
    page_url: str
    prompt_version: str
    model: str
    served_by_model: str = ""
    provider: str = ""
    generated_at: str
    status: ScanStatus
    n_proposed: int = 0
    n_verified: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    error: str | None = None
