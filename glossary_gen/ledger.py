from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

Status = Literal["ok", "no_excerpt", "fetch_error", "llm_error"]


class LedgerRecord(BaseModel):
    slug: str
    term: str
    prompt_version: str
    model: str
    provider: str = ""
    generated_at: str
    status: Status
    definition: str = ""
    x_category: str = ""
    x_context: str = ""
    x_example: str = ""
    x_related: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    pages: list[str] = Field(default_factory=list)
    source_pages: list[str] = Field(default_factory=list)
    excerpt_chars: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    error: str | None = None


class Ledger:
    """Append-only JSONL run log, keyed by (slug, prompt_version, model).

    A partially written final line is skipped rather than fatal, so a crash mid-append
    costs one term instead of the run.
    """

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._records: list[LedgerRecord] = []
        self._keys: set[tuple[str, str, str]] = set()
        self.skipped_lines = 0
        self._load()

    @staticmethod
    def _key(slug: str, prompt_version: str, model: str) -> tuple[str, str, str]:
        return (slug, prompt_version, model)

    def _load(self) -> None:
        if not self._path.exists():
            return
        for line in self._path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = LedgerRecord.model_validate(json.loads(line))
            except (json.JSONDecodeError, ValidationError):
                self.skipped_lines += 1
                continue
            self._records.append(record)
            self._keys.add(self._key(record.slug, record.prompt_version, record.model))

    def has(self, slug: str, prompt_version: str, model: str) -> bool:
        return self._key(slug, prompt_version, model) in self._keys

    def append(self, record: LedgerRecord) -> None:
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(record.model_dump_json() + "\n")
        self._records.append(record)
        self._keys.add(self._key(record.slug, record.prompt_version, record.model))

    def records(self) -> list[LedgerRecord]:
        return list(self._records)
