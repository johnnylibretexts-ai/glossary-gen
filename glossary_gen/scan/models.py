from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, computed_field

from glossary_gen.ledger import SUBJECT_ALIAS
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


class Corroboration(StrEnum):
    """An independent signal from a page agreeing that a term is defined there.

    Recorded individually and never fused into one number — see ADR-0004. A `StrEnum` so a
    corroboration survives a round trip through JSON as the word it is, keeping the sidecar
    readable by the human it is written for.
    """

    HEADING = "heading"
    CUE = "cue"
    MULTIPAGE = "multipage"


class VerifiedCandidate(BaseModel):
    """A candidate whose evidence checked out, with what the page corroborated.

    `confidence` is the model's own, unmodified: nothing here adjusts it, because a
    corroboration is a separate observation about the page, not a correction to what the
    model said.
    """

    term: str
    aliases: list[str] = Field(default_factory=list)
    evidence: str
    page_url: str
    confidence: float
    corroborations: list[Corroboration] = Field(default_factory=list)

    @computed_field
    @property
    def slug(self) -> str:
        return slugify(self.term)


class MergedTerm(BaseModel):
    """One term, collapsed across every page that proposed it, ready to emit."""

    term: str
    aliases: list[str] = Field(default_factory=list)
    pages: list[str]
    confidence: float
    corroborations: list[Corroboration] = Field(default_factory=list)
    evidence: str = ""

    @computed_field
    @property
    def slug(self) -> str:
        return slugify(self.term)


class ScanRecord(BaseModel):
    """One ledger row per page.

    The subject here is the page (`slugify(page_url)`); in `LedgerRecord` it is the term.
    Both producers key on the same field because `Ledger` is generic over whatever one
    paid call is made about.

    A page that defines no terms is `ok` with `n_proposed = 0`, never a distinct status —
    `Ledger.has()` counts only `ok` as done, so a separate status would re-issue a paid
    call for every term-free page on every resumed run, forever.
    """

    subject: str = Field(validation_alias=SUBJECT_ALIAS)
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
