from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path

from glossary_gen.llm import LLMClient, LLMResult, LLMStructuredOutputError
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
    """
    if not excerpts:
        raise ValueError(f"{term.term}: no excerpts to ground a definition")
    prompt = build_prompt(template, term, excerpts)
    last: LLMStructuredOutputError | None = None
    for _ in range(retries + 1):
        try:
            return client.complete(prompt)
        except LLMStructuredOutputError as exc:
            last = exc
    raise last  # type: ignore[misc]
