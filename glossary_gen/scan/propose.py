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


# Mirrors `llm.extract_json`'s own fence-stripping (kept local, not imported, since
# `llm.py` is out of scope for this fix) so a bare JSON array can be recognised on the
# reply's own text -- before `extract_json` gets a chance to mangle it. Its object-only
# fallback regex (`\{.*\}`, greedy, DOTALL) matches from an array's first `{` to its
# last `}`, silently discarding the enclosing `[`/`]` and handing back just the inner
# object. By the time that has happened the array is gone, so this check must run first.
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _looks_like_bare_json_array(text: str) -> bool:
    candidate = text.strip()
    fenced = _FENCE.search(candidate)
    if fenced:
        candidate = fenced.group(1).strip()
    return candidate.startswith("[")


def _require_terms_shape(payload: object) -> dict:
    """Guard against a wrong-shaped-but-parseable reply reading as a silent empty result.

    Every field on `PageCandidates` has a default, so pydantic's `extra="ignore"` would
    otherwise turn any JSON object lacking a `terms` key into a silently successful
    `PageCandidates(terms=[])` — indistinguishable from a page that genuinely defines
    nothing. Catching that here, before `model_validate`, means it is retried like any
    other malformed reply and, after the retry budget, raises an error an operator can
    tell apart from a legitimate empty-terms page. The bare-array case is handled by
    `_looks_like_bare_json_array` before `extract_json` runs; the `list` branch below is
    defense in depth in case a future `extract_json` change lets one through parsed.
    """
    if isinstance(payload, list):
        raise LLMStructuredOutputError(
            "reply was a JSON array, not an object with a 'terms' key "
            f"(got a list of {len(payload)} item(s))"
        )
    if not isinstance(payload, dict):
        raise LLMStructuredOutputError(
            f"reply was not a JSON object (got {type(payload).__name__})"
        )
    if "terms" not in payload:
        raise LLMStructuredOutputError(
            f"reply was a JSON object but had no 'terms' key (keys: {sorted(payload)})"
        )
    return payload


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
            if _looks_like_bare_json_array(raw.text):
                raise LLMStructuredOutputError(
                    "reply was a JSON array, not an object with a 'terms' key"
                )
            payload = _require_terms_shape(extract_json(raw.text))
            return PageCandidates.model_validate(payload), raw
        except LLMStructuredOutputError as exc:
            last = exc
        except ValidationError as exc:
            last = LLMStructuredOutputError(
                f"reply failed schema validation: {exc.error_count()} error(s)"
            )
    raise last  # type: ignore[misc]
