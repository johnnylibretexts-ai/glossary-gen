from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, BaseModel, Field, ValidationError

Status = Literal["ok", "no_excerpt", "fetch_error", "llm_error"]

# Ledgers written before `slug` was renamed to `subject` are still read. Dropping the old
# name would fail validation on every existing row, and an unreadable row is counted as
# not-done — silently re-paying for work already finished. New rows are written `subject`.
SUBJECT_ALIAS = AliasChoices("subject", "slug")


class LedgerRecord(BaseModel):
    subject: str = Field(validation_alias=SUBJECT_ALIAS)
    term: str
    prompt_version: str
    model: str
    served_by_model: str = ""
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
    """Append-only JSONL run log, keyed by (subject, prompt_version, model).

    A *subject* is the thing one paid model call is made about: a term when generating
    definitions, a page when scanning for them. It is named for the role, not for either
    producer's own vocabulary, because both key on the same field.

    A partially written final line is skipped rather than fatal, so a crash mid-append
    costs one term instead of the run.

    Only `status == "ok"` counts as done. `llm_error`, `fetch_error`, and `no_excerpt`
    rows are history, not completion — a term that failed is retried on the next run,
    not silently treated as finished. A term that fails repeatedly can therefore
    accumulate several rows under the same key; that's intentional (it's a useful
    failure history) and `write_csv` already filters to `ok`, so no dedup is needed here.

    The record type is a constructor parameter so a second producer (the scanner) can
    reuse the resume and crash-tolerance behaviour with a page-shaped record. Any record
    type must expose `subject`, `prompt_version`, `model`, and `status`, because those four
    are what keying and completion are computed from.
    """

    def __init__(self, path: Path, record_cls: type[BaseModel] = LedgerRecord) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._record_cls = record_cls
        self._records: list[BaseModel] = []
        self._ok_keys: set[tuple[str, str, str]] = set()
        self.skipped_lines = 0
        self._load()

    @staticmethod
    def _key(subject: str, prompt_version: str, model: str) -> tuple[str, str, str]:
        return (subject, prompt_version, model)

    def _load(self) -> None:
        if not self._path.exists():
            return
        for line in self._path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = self._record_cls.model_validate(json.loads(line))
            except (json.JSONDecodeError, ValidationError):
                self.skipped_lines += 1
                continue
            self._records.append(record)
            if record.status == "ok":
                self._ok_keys.add(self._key(record.subject, record.prompt_version, record.model))

    def has(self, subject: str, prompt_version: str, model: str) -> bool:
        """True only when a successful ('ok') record already exists for this key.

        A failed attempt does not count as done: it must be retried, not skipped.
        """
        return self._key(subject, prompt_version, model) in self._ok_keys

    def append(self, record: BaseModel) -> None:
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(record.model_dump_json() + "\n")
        self._records.append(record)
        if record.status == "ok":
            self._ok_keys.add(self._key(record.subject, record.prompt_version, record.model))

    def records(self) -> list[BaseModel]:
        return list(self._records)
