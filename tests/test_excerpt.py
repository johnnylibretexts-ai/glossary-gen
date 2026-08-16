from glossary_gen.excerpt import MIN_EXCERPT_CHARS
from glossary_gen.excerpt import excerpts_for_term as _excerpts_for_term
from glossary_gen.models import Block, Page, Term


def excerpts_for_term(pages, term, **kwargs):
    """Selection/ranking tests, with the grounding floor off.

    These exercise *which* paragraphs get picked and in what order, which is unrelated to
    whether there is enough text to write from. Leaving the floor on would force every
    fixture to carry a hundred characters of filler prose and would say nothing extra.
    The floor's own tests call `_excerpts_for_term` directly, which is also the only way to
    see the grounding total the pair carries — selection tests care about the passages.
    """
    kwargs.setdefault("min_chars", 0)
    return _excerpts_for_term(pages, term, **kwargs)[0]


def para(text):
    return Block(kind="paragraph", text=text)


def head(text):
    return Block(kind="heading", text=text)


def make_term(term="Recursion", aliases=(), pages=("https://a",)):
    return Term(term=term, slug="x", aliases=tuple(aliases), pages=tuple(pages))


def test_finds_paragraph_containing_term():
    page = Page(url="https://a", blocks=(para("Recursion is a technique."),))
    result = excerpts_for_term([page], make_term())
    assert [e.text for e in result] == ["Recursion is a technique."]


def test_word_boundary_prevents_substring_match():
    page = Page(url="https://a", blocks=(para("You should listen carefully."),))
    assert excerpts_for_term([page], make_term(term="list")) == []


def test_match_is_case_insensitive():
    page = Page(url="https://a", blocks=(para("RECURSION repeats."),))
    assert len(excerpts_for_term([page], make_term())) == 1


def test_alias_matches():
    page = Page(url="https://a", blocks=(para("A recursive call repeats."),))
    result = excerpts_for_term([page], make_term(aliases=("recursive",)))
    assert len(result) == 1


def test_term_absent_returns_empty():
    page = Page(url="https://a", blocks=(para("Nothing relevant here."),))
    assert excerpts_for_term([page], make_term()) == []


def test_paragraph_after_matching_heading_ranks_first():
    page = Page(
        url="https://a",
        blocks=(
            para("Later we mention recursion again in passing."),
            head("Recursion"),
            para("The defining paragraph."),
        ),
    )
    result = excerpts_for_term([page], make_term())
    assert result[0].text == "The defining paragraph."
    assert result[0].rank == 0


def test_definitional_phrase_outranks_plain_mention():
    page = Page(
        url="https://a",
        blocks=(
            para("We saw recursion in chapter two."),
            para("Recursion is a technique where a function calls itself."),
        ),
    )
    result = excerpts_for_term([page], make_term())
    assert result[0].text.startswith("Recursion is a technique")
    assert result[0].rank == 1
    assert result[1].rank == 2


def test_near_duplicate_paragraphs_collapse():
    text = "Recursion is a technique where a function calls itself repeatedly."
    pages = [
        Page(url="https://a", blocks=(para(text),)),
        Page(url="https://b", blocks=(para(text + " "),)),
    ]
    result = excerpts_for_term(pages, make_term())
    assert len(result) == 1


def test_text_with_suffix_collapses():
    """Text differing only in a short suffix should collapse (near-duplicate)."""
    text = "Recursion is a technique where a function calls itself repeatedly."
    pages = [
        Page(url="https://a", blocks=(para(text),)),
        Page(url="https://b", blocks=(para(text + " [edit]"),)),
    ]
    result = excerpts_for_term(pages, make_term())
    assert len(result) == 1


def test_max_excerpts_is_respected():
    blocks = tuple(para(f"Recursion note number {i}.") for i in range(10))
    page = Page(url="https://a", blocks=blocks)
    assert len(excerpts_for_term([page], make_term(), max_excerpts=3)) == 3


def test_max_chars_truncates_the_set():
    blocks = tuple(para("Recursion " + "x" * 500 + f" {i}") for i in range(5))
    page = Page(url="https://a", blocks=blocks)
    result = excerpts_for_term([page], make_term(), max_excerpts=5, max_chars=1100)
    assert sum(len(e.text) for e in result) <= 1100
    assert len(result) == 2


def test_page_order_breaks_rank_ties():
    pages = [
        Page(url="https://a", blocks=(para("Recursion appears here."),)),
        Page(url="https://b", blocks=(para("Recursion appears there."),)),
    ]
    result = excerpts_for_term(pages, make_term())
    assert [e.page_url for e in result] == ["https://a", "https://b"]


def test_refuses_grounding_too_thin_to_write_from():
    """A passage too short to ground anything is not an excerpt — see CONTEXT.md, Excerpt.

    Measured on a real book: 14 characters of page text still produced a fluent, correct
    definition of "modulo", because the model supplied it. Correctness there is evidence
    the model knew Python, not evidence the book taught it.
    """
    page = Page(url="https://a", blocks=(head("Modulo"), para("The % operator.")))
    term = Term(term="Modulo", slug="modulo", aliases=(), pages=("https://a",))
    assert _excerpts_for_term([page], term)[0] == []


def test_reports_the_grounding_total_even_when_it_is_under_the_floor():
    """How far under the floor a term fell is what the unwritten CSV reports — ADR-0006.

    Zero grounding means the term never matched its own occurrence pages, which is an index
    defect. A number just under the floor means the book does discuss the term, briefly, and
    a reviewer may still want it. Reporting both as 0 states a falsehood about the second.
    """
    page = Page(url="https://a", blocks=(head("Modulo"), para("The % operator.")))
    term = Term(term="Modulo", slug="modulo", aliases=(), pages=("https://a",))
    assert _excerpts_for_term([page], term) == ([], len("The % operator."))


def test_reports_zero_grounding_when_the_term_never_matched_its_pages():
    page = Page(url="https://a", blocks=(para("Nothing relevant on this page at all."),))
    term = Term(term="Modulo", slug="modulo", aliases=(), pages=("https://a",))
    assert _excerpts_for_term([page], term) == ([], 0)


def test_accepts_grounding_at_the_floor():
    page = Page(url="https://a", blocks=(head("Modulo"), para("M" + "o" * 120)))
    term = Term(term="Modulo", slug="modulo", aliases=(), pages=("https://a",))
    assert len(_excerpts_for_term([page], term)[0]) == 1


def test_the_floor_counts_total_grounding_not_each_passage():
    """Several short passages can add up to enough; the CSV reports the total too."""
    page = Page(
        url="https://a",
        blocks=(
            head("Modulo"),
            para("The % operator returns a remainder after division of two numbers."),
            para("Modulo is a common operation in programming and in number theory."),
        ),
    )
    term = Term(term="Modulo", slug="modulo", aliases=(), pages=("https://a",))
    got, chars = _excerpts_for_term([page], term)
    assert all(len(e.text) < MIN_EXCERPT_CHARS for e in got), "neither clears the floor alone"
    assert chars >= MIN_EXCERPT_CHARS
    assert len(got) == 2


def test_matches_a_term_that_ends_in_punctuation():
    """A trailing `\\b` can never match after ')', so `super()` found nothing at all.

    Measured on a real book: `super()` and `__init__()` reached the CSV with no definition,
    while `count()` and `find()` survived only because they also carry a paren-free alias.
    """
    page = Page(
        url="https://a",
        blocks=(
            para(
                "super () is a special method that provides a temporary superclass "
                "object instance for a subclass to use in its own methods."
            ),
        ),
    )
    term = Term(term="super()", slug="super", aliases=("super ()",), pages=("https://a",))
    assert len(excerpts_for_term([page], term)) == 1


def test_word_boundaries_still_protect_a_plain_term():
    """The fix must not turn every term into a substring match."""
    page = Page(url="https://a", blocks=(para("You should listen carefully to this."),))
    assert excerpts_for_term([page], make_term(term="list")) == []
