import pytest

from glossary_gen.models import Block, Excerpt, GlossaryEntry, Page, Term, slugify


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Recursion", "recursion"),
        ("List comprehension", "list-comprehension"),
        ("  Base case  ", "base-case"),
        ("Object-Oriented Programming", "object-oriented-programming"),
        ("C++", "c"),
    ],
)
def test_slugify(raw, expected):
    assert slugify(raw) == expected


def test_term_is_frozen():
    term = Term(term="Recursion", slug="recursion", aliases=("recursive",), pages=("https://x",))
    with pytest.raises(AttributeError):
        term.term = "other"


def test_page_holds_ordered_blocks():
    page = Page(
        url="https://x",
        blocks=(Block(kind="heading", text="Recursion"), Block(kind="paragraph", text="A call.")),
    )
    assert [b.kind for b in page.blocks] == ["heading", "paragraph"]


def test_excerpt_carries_rank_and_page():
    excerpt = Excerpt(page_url="https://x", text="A call.", rank=0)
    assert (excerpt.rank, excerpt.page_url) == (0, "https://x")


def test_glossary_entry_requires_definition():
    with pytest.raises(ValueError):
        GlossaryEntry(category="c", context="x", example="e", related=[], aliases=[])
