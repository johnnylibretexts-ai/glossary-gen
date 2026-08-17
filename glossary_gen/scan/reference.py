"""The glossary a book's own authors already wrote, harvested as a reference set.

LibreTexts renders author glossary entries as definition lists under a `Glossary`
or `Key Terms` heading, so harvesting them is parsing rather than inference — no
model sits in the loop. That is what makes the result usable as a reference the
scanner can be measured against: it is published human editorial judgement about
which terms belong in *that book's* glossary, and it costs nothing to regenerate.

Read `coverage`'s return type before drawing conclusions from it. Recall against
this set is meaningful; the terms the scanner proposes that are absent from it are
NOT cuts. Only some pages of a book carry glossary blocks, so absence is silence
rather than a judgement.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from bs4 import BeautifulSoup

from glossary_gen.models import slugify
from glossary_gen.scan.content import extract_content
from glossary_gen.scan.evaluate import RecallReport

GLOSSARY_HEADINGS = frozenset({"glossary", "key terms", "glossary entries"})
HEADING_TAGS = ("h1", "h2", "h3", "h4")

# Every LibreTexts book ships a back-matter glossary page pre-filled with the
# template's own example rows. An unedited one (the Python book's) is nothing but
# these, and counting them would invent a reference set out of page chrome.
_TEMPLATE_TERM = re.compile(r"^sample word\s*\d*$", re.I)

# "Confidence Interval (CI)", "Degrees of Freedom (\(df\))" — see `GlossaryEntry.slug`.
_TRAILING_PARENTHETICAL = re.compile(r"\s*\(.*\)\s*$", re.S)


@dataclass(frozen=True)
class GlossaryEntry:
    """One author-written term, its definition, and the page that carries it."""

    term: str
    definition: str
    page: str = ""

    @property
    def slug(self) -> str:
        """The matching key, with the author's notation gloss removed.

        "Confidence Interval (CI)" is one term and the symbol the chapter will use
        for it, so the whole string slugs to a key no scanner will ever produce.
        Greedy to the last `)` because the parenthetical often holds LaTeX with
        parens of its own: "Degrees of Freedom (\\(df\\))". A term that is nothing
        but a parenthetical keeps it, or every such entry collapses onto one key.
        """
        stripped = _TRAILING_PARENTHETICAL.sub("", self.term).strip()
        return slugify(stripped or self.term)


def _text(node) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()


def author_glossary(html: str) -> tuple[GlossaryEntry, ...]:
    """Term/definition pairs under every glossary heading on the page.

    A section runs until the next heading of the same or a higher level: a `<h3>`
    inside a `<h2>Glossary</h2>` stays part of it, while the next `<h2>` ends it.
    Without that boundary the exercise-answer lists further down the page ("Answer
    a", "Answer b") land in the reference set and deflate every recall figure
    computed from it.
    """
    # Narrow to the article body first, for the reason `scan.content` gives: the
    # page-info footer is a definition list as well, and on a back-matter glossary
    # page nothing follows it to stop the walk. Harvesting raw HTML turned "Page
    # ID", "License" and "Author" into author-written terms.
    soup = BeautifulSoup(extract_content(html), "html.parser")
    entries: dict[str, GlossaryEntry] = {}

    for heading in soup.find_all(HEADING_TAGS):
        if heading.get_text(strip=True).casefold() not in GLOSSARY_HEADINGS:
            continue
        level = int(heading.name[1])
        for element in heading.find_all_next():
            if element.name in HEADING_TAGS and int(element.name[1]) <= level:
                break
            if element.name != "dl":
                continue
            term_node, definition_node = element.find("dt"), element.find("dd")
            if term_node is None:
                continue
            term = _text(term_node)
            if not term or _TEMPLATE_TERM.match(term):
                continue
            # First definition wins: a term restated in a later chapter's glossary
            # is the same entry, and the book introduces it where it introduces it.
            definition = _text(definition_node) if definition_node else ""
            entries.setdefault(slugify(term), GlossaryEntry(term=term, definition=definition))

    return tuple(entries.values())


def book_glossary(pages: Iterable[tuple[str, str]]) -> tuple[GlossaryEntry, ...]:
    """Harvest `(url, html)` pairs into one reference set, tagged with provenance.

    Terms keep the first page that defines them, in the order the pages arrive —
    which for a book scanned in reading order is where the book introduces them.
    """
    entries: dict[str, GlossaryEntry] = {}
    for url, html in pages:
        for entry in author_glossary(html):
            entries.setdefault(entry.slug, GlossaryEntry(entry.term, entry.definition, url))
    return tuple(entries.values())


def coverage(author: Sequence[GlossaryEntry], found: Iterable[str]) -> RecallReport:
    """How many author-written terms the scanner proposed.

    Returns `RecallReport`, whose docstring explains why it carries no precision
    field — the same reasoning applies with more force here.
    """
    found_slugs = set(found)
    missing = [entry.slug for entry in author if entry.slug not in found_slugs]
    return RecallReport(
        found=len(author) - len(missing),
        total=len(author),
        candidates=len(found_slugs),
        missing=missing,
    )
