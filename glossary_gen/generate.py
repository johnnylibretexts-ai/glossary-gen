from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path

from glossary_gen.llm import (
    LLMClient,
    LLMResult,
    LLMStructuredOutputError,
    LLMTransportError,
    parse_entry,
)
from glossary_gen.models import Excerpt, Term

PROMPT_DIR = Path(__file__).parent / "prompts"
_VERSION_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def prompt_versions() -> list[str]:
    return sorted(path.stem for path in PROMPT_DIR.glob("*.md"))


def load_prompt(version: str) -> str:
    """Read prompts/<version>.md. The version is the filename stem."""
    if not _VERSION_RE.match(version):
        raise ValueError(f"invalid prompt version {version!r}")
    path = PROMPT_DIR / f"{version}.md"
    if not path.is_file():
        raise FileNotFoundError(f"no prompt template for version {version!r}")
    return path.read_text(encoding="utf-8")


def _render_excerpts(excerpts: Sequence[Excerpt]) -> str:
    return "\n\n".join(f"[{e.page_url}]\n{e.text}" for e in excerpts)


def build_prompt(template: str, term: Term, excerpts: Sequence[Excerpt]) -> str:
    return template.format(
        term=term.term,
        aliases=", ".join(term.aliases) if term.aliases else "none",
        excerpts=_render_excerpts(excerpts),
    )


def generate_entry(
    client: LLMClient,
    template: str,
    term: Term,
    excerpts: Sequence[Excerpt],
    *,
    retries: int = 2,
) -> LLMResult:
    """Generate one entry. Retries malformed output; transport errors propagate
    immediately so the ProviderChain, not this function, decides about fallback.

    Drives `complete_raw` and validates here rather than calling `complete`: every attempt
    that got a reply back is real billed spend, and `complete` discards the attempt's token
    counts when validation fails.

    Accumulated totals travel with every exit from this loop, because the caller charges
    them against the budget ceiling and writes them to a ledger row that later runs reseed
    from. On success they are on the returned `LLMResult`; on either error they are set on
    the raised exception as `tokens_in`/`tokens_out`. A transport error on the *first*
    attempt is the one case with nothing to attach, and reports 0 — correctly, since
    `complete_raw` raised before any reply existed.
    """
    if not excerpts:
        raise ValueError(f"{term.term}: no excerpts to ground a definition")
    prompt = build_prompt(template, term, excerpts)
    last: LLMStructuredOutputError | None = None
    tokens_in = 0
    tokens_out = 0
    for _ in range(retries + 1):
        try:
            raw = client.complete_raw(prompt)
        except LLMStructuredOutputError as exc:
            # A malformed *envelope* ("response body is not JSON", "unexpected response
            # shape"). Retried like any other malformed reply, as it was when this loop
            # called `complete`. No RawResult exists, so there is nothing to bill.
            last = exc
            continue
        except LLMTransportError as exc:
            # Deliberately not retried — a ProviderChain has already exhausted its
            # fallbacks — but earlier attempts in this loop were billed, and that spend
            # must not leave with the exception.
            exc.tokens_in = tokens_in
            exc.tokens_out = tokens_out
            raise
        tokens_in += raw.tokens_in
        tokens_out += raw.tokens_out
        try:
            entry = parse_entry(raw.text)
        except LLMStructuredOutputError as exc:
            last = exc
            continue
        return LLMResult(
            # Every attempt's spend, not just the winning one's: a term that succeeded on
            # its third try still paid for the first two, and the caller writes this into
            # an `ok` ledger row that the budget ceiling reseeds from on every resume.
            entry=entry,
            model=raw.model,
            provider=raw.provider,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )
    last.tokens_in = tokens_in  # type: ignore[union-attr]
    last.tokens_out = tokens_out  # type: ignore[union-attr]
    raise last  # type: ignore[misc]
