from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from glossary_gen.models import Book, Term, slugify


class InputError(Exception):
    """The input file is missing, malformed, or internally inconsistent."""


@dataclass(frozen=True)
class InputFile:
    book: Book | None
    terms: list[Term]


def _split_multi(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(part.strip() for part in value.split("|") if part.strip())


def _as_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return _split_multi(value)
    return tuple(str(item).strip() for item in value if str(item).strip())


def _build_term(raw_term: Any, aliases: Any, pages: Any, position: int) -> Term:
    term = str(raw_term or "").strip()
    if not term:
        raise InputError(f"term {position}: 'term' is empty")
    page_urls = _as_tuple(pages)
    if not page_urls:
        raise InputError(f"term {position}: 'pages' is empty for {term!r}")
    return Term(term=term, slug=slugify(term), aliases=_as_tuple(aliases), pages=page_urls)


def _build_book(raw: dict[str, Any]) -> Book:
    missing = [k for k in ("library", "coverID", "bookId") if not str(raw.get(k, "")).strip()]
    if missing:
        raise InputError(f"book block is missing: {', '.join(missing)}")
    return Book(
        library=str(raw["library"]).strip(),
        cover_id=str(raw["coverID"]).strip(),
        book_id=str(raw["bookId"]).strip(),
        title=str(raw.get("title", "")).strip(),
        index_url=str(raw.get("index_url", "")).strip(),
    )


def _load_json(path: Path) -> InputFile:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise InputError(f"{path.name}: invalid JSON ({exc.msg} at line {exc.lineno})") from exc
    if not isinstance(payload, dict):
        raise InputError(f"{path.name}: top level must be an object")
    raw_terms = payload.get("terms")
    if not isinstance(raw_terms, list) or not raw_terms:
        raise InputError(f"{path.name}: 'terms' must be a non-empty list")
    terms = [
        _build_term(item.get("term"), item.get("aliases"), item.get("pages"), position)
        for position, item in enumerate(raw_terms, start=1)
    ]
    book_raw = payload.get("book")
    book = _build_book(book_raw) if isinstance(book_raw, dict) else None
    return InputFile(book=book, terms=terms)


def _load_csv(path: Path) -> InputFile:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise InputError(f"{path.name}: no data rows")
    terms = [
        _build_term(row.get("term"), row.get("aliases"), row.get("pages"), position)
        for position, row in enumerate(rows, start=1)
    ]
    return InputFile(book=None, terms=terms)


def load_input(path: Path) -> InputFile:
    """Load a step-1 index file. JSON may carry a book block; CSV never does."""
    if not path.exists():
        raise InputError(f"{path} does not exist")
    suffix = path.suffix.casefold()
    if suffix == ".json":
        result = _load_json(path)
    elif suffix == ".csv":
        result = _load_csv(path)
    else:
        raise InputError(f"unsupported input extension {path.suffix!r}; use .json or .csv")

    seen: dict[str, str] = {}
    for term in result.terms:
        if term.slug in seen:
            raise InputError(
                f"duplicate slug {term.slug!r} from {seen[term.slug]!r} and {term.term!r}"
            )
        seen[term.slug] = term.term
    return result
