from __future__ import annotations

import re
from pathlib import Path

from pydantic import ValidationError

from glossary_gen.llm import LLMClient, LLMStructuredOutputError, RawResult, extract_json
from glossary_gen.models import Page
from glossary_gen.scan.candidates import page_text
from glossary_gen.scan.models import PageCandidates

# A subdirectory, not `prompts/scan_v1.md`. `generate.prompt_versions()` globs
# `prompts/*.md` straight into the generator's `--prompt-version` choices, so a scan
# prompt sitting beside v1.md would become a valid `glossary-gen --prompt-version scan_v1`
# invocation. `Path.glob("*.md")` does not recurse, so a subdirectory is invisible to it.
PROMPT_DIR = Path(__file__).parent.parent / "prompts" / "scan"
_VERSION_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def scan_prompt_versions() -> list[str]:
    return sorted(path.stem for path in PROMPT_DIR.glob("*.md"))


def load_scan_prompt(version: str) -> str:
    if not _VERSION_RE.match(version):
        raise ValueError(f"invalid prompt version {version!r}")
    path = PROMPT_DIR / f"{version}.md"
    if not path.is_file():
        raise FileNotFoundError(f"no scan prompt template for version {version!r}")
    return path.read_text(encoding="utf-8")


def build_scan_prompt(template: str, page: Page) -> str:
    return template.format(page_url=page.url, page_text=page_text(page))


def propose_terms(
    client: LLMClient, template: str, page: Page, *, retries: int = 2
) -> tuple[PageCandidates, RawResult]:
    """Ask one page's worth of candidates. Transport errors propagate so ProviderChain,
    not this function, decides about fallback — matching `generate.generate_entry`.
    """
    prompt = build_scan_prompt(template, page)
    last: LLMStructuredOutputError | None = None
    for _ in range(retries + 1):
        raw = client.complete_raw(prompt)
        try:
            return PageCandidates.model_validate(extract_json(raw.text)), raw
        except LLMStructuredOutputError as exc:
            last = exc
        except ValidationError as exc:
            last = LLMStructuredOutputError(
                f"reply failed schema validation: {exc.error_count()} error(s)"
            )
    raise last  # type: ignore[misc]
