"""The author glossary a book already carries, harvested as a reference set."""

from glossary_gen.scan.evaluate import RecallReport
from glossary_gen.scan.reference import (
    author_glossary,
    book_glossary,
    coverage,
    pressbooks_book_glossary,
    pressbooks_glossary,
)

GLOSSARY_OF = "<h2>Glossary</h2><dl><dt>%s</dt><dd>%s</dd></dl>"

GLOSSARY_PAGE = """
<h2>Glossary</h2>
<dl><dt>Degrees of Freedom</dt><dd>the number of objects in a sample that are free to vary</dd></dl>
<dl><dt>Standard Deviation</dt><dd>a number equal to the square root of the variance</dd></dl>
"""


def test_harvests_term_and_definition_pairs():
    entries = author_glossary(GLOSSARY_PAGE)

    assert [(e.term, e.slug) for e in entries] == [
        ("Degrees of Freedom", "degrees-of-freedom"),
        ("Standard Deviation", "standard-deviation"),
    ]
    assert entries[0].definition == "the number of objects in a sample that are free to vary"


def test_ignores_definition_lists_outside_the_glossary_section():
    """Exercise answers are `<dl>` too. Harvesting every list on the page put
    "Answer a" and "Answer b" in the reference set, which would deflate recall
    against terms no author ever wrote.
    """
    html = """
    <h2>Glossary</h2>
    <dl><dt>Blinding</dt><dd>not telling participants which treatment they get</dd></dl>
    <h2>Solutions</h2>
    <dl><dt>Answer a</dt><dd>0.5</dd></dl>
    """

    assert [e.term for e in author_glossary(html)] == ["Blinding"]


def test_a_deeper_heading_does_not_end_the_glossary_section():
    html = """
    <h2>Glossary</h2>
    <dl><dt>Average</dt><dd>a number that describes the central tendency of the data</dd></dl>
    <h3>Notation</h3>
    <dl><dt>Median</dt><dd>the middle value in an ordered set</dd></dl>
    """

    assert [e.term for e in author_glossary(html)] == ["Average", "Median"]


def test_drops_the_unfilled_libretexts_template():
    """Every LibreTexts book ships a back-matter glossary page pre-populated with
    the template's own example rows. The Python book's is nothing but these, and
    counting them as author terms would invent a reference set out of chrome.
    """
    html = """
    <h2>Glossary Entries</h2>
    <dl><dt>Sample Word 1</dt><dd>Sample Definition 1</dd></dl>
    <dl><dt>Sample Word 2</dt><dd>Sample Definition 2</dd></dl>
    """

    assert author_glossary(html) == ()


def test_flattens_nested_markup_and_collapses_whitespace():
    html = """
    <h2>Glossary</h2>
    <dl><dt><strong>Student's <strong>t</strong>-Distribution</strong></dt>
    <dd>investigated  and reported
    by William S. Gossett</dd></dl>
    """

    (entry,) = author_glossary(html)
    assert entry.term == "Student's t -Distribution"
    assert entry.definition == "investigated and reported by William S. Gossett"


def test_a_page_without_a_glossary_heading_yields_nothing():
    assert author_glossary("<h2>Chapter Summary</h2><dl><dt>x</dt><dd>y</dd></dl>") == ()


def test_the_same_term_defined_on_two_pages_is_one_entry():
    html = """
    <h2>Glossary</h2>
    <dl><dt>Average</dt><dd>the first definition the book gives</dd></dl>
    <h2>Glossary</h2>
    <dl><dt>Average</dt><dd>a later restatement</dd></dl>
    """

    (entry,) = author_glossary(html)
    assert entry.definition == "the first definition the book gives"


def test_a_trailing_parenthetical_is_notation_not_part_of_the_term():
    """Authors write "Confidence Interval (CI)" — the term plus the symbol they will
    use for it. Slugging that whole string produces a key no scanner will ever
    match, so three real hits scored as misses on the statistics book.

    The term text stays verbatim: only the matching key is normalised.
    """
    html = GLOSSARY_OF % ("Confidence Interval (CI)", "an interval estimate for a parameter")

    (entry,) = author_glossary(html)
    assert (entry.term, entry.slug) == ("Confidence Interval (CI)", "confidence-interval")


def test_a_parenthetical_holding_markup_is_stripped_too():
    """LibreTexts renders notation as LaTeX, so the nested parens are real:
    "Degrees of Freedom (\\(df\\))".
    """
    (entry,) = author_glossary(GLOSSARY_OF % (r"Degrees of Freedom (\(df\))", "how many vary"))

    assert entry.slug == "degrees-of-freedom"


def test_a_term_that_is_only_a_parenthetical_keeps_it():
    """Stripping to nothing would collapse every such entry onto one empty key."""
    (entry,) = author_glossary(GLOSSARY_OF % ("(RV)", "a random variable"))

    assert entry.slug == "rv"


def test_page_chrome_outside_the_content_container_is_not_the_book():
    """LibreTexts renders the page-info footer as a definition list too. On the
    stats book's back-matter glossary page it follows the heading with no further
    heading to stop at, so harvesting raw HTML put "Page ID", "License" and
    "Author" in the reference set — nine invented terms that inflated the
    denominator and deflated recall from 55.9% to 51.4%.
    """
    html = """
    <div class="mt-content-container">
      <h2>Glossary</h2>
      <dl><dt>Average</dt><dd>a number that describes the central tendency</dd></dl>
    </div>
    <footer>
      <dl><dt>Page ID</dt><dd>13576</dd></dl>
      <dl><dt>License</dt><dd>CC BY</dd></dl>
    </footer>
    """

    assert [e.term for e in author_glossary(html)] == ["Average"]


def test_book_glossary_records_the_page_each_term_came_from():
    """The page is the whole point of a reference set a human can check: an entry
    nobody can trace back to a printed page is an assertion, not evidence.
    """
    pages = [
        ("https://x/1.02", GLOSSARY_OF % ("Blinding", "hiding the treatment")),
        ("https://x/1.09", GLOSSARY_OF % ("Average", "a central tendency")),
    ]

    entries = book_glossary(pages)

    assert [(e.term, e.page) for e in entries] == [
        ("Blinding", "https://x/1.02"),
        ("Average", "https://x/1.09"),
    ]


def test_book_glossary_keeps_the_first_page_that_defines_a_term():
    pages = [
        ("https://x/1.02", GLOSSARY_OF % ("Average", "where the book says it")),
        ("https://x/9.01", GLOSSARY_OF % ("Average", "a later restatement")),
    ]

    (entry,) = book_glossary(pages)
    assert (entry.page, entry.definition) == ("https://x/1.02", "where the book says it")


def test_coverage_counts_which_author_terms_the_scanner_found():
    entries = author_glossary(GLOSSARY_PAGE)

    report = coverage(entries, {"standard-deviation", "outlier"})

    assert isinstance(report, RecallReport)
    assert (report.found, report.total) == (1, 2)
    assert report.missing == ["degrees-of-freedom"]
    assert report.rate == 0.5


# --- Pressbooks -------------------------------------------------------------
#
# A different platform renders its glossary differently: terms are a first-class
# post type, and each inline mention carries its own definition in a `<template>`
# beside it. Markup below is copied from a live page — see
# `docs/research/2026-08-17-platform-discovery-probes.md`.

PRESSBOOKS_CHAPTER = """
<div class="entry-content">
  <p>Look for the
    <a class="glossary-term" aria-haspopup="dialog" href="#term_27_447">welcome booth.</a>
    when you land.</p>
  <template id="term_27_447"><div class="glossary__definition" role="dialog"><div tabindex="-1">
    <p>A kiosk setup at the airport to welcome arriving international students.</p>
  </div><button><span aria-hidden="true">&times;</span>
  <span class="screen-reader-text">Close definition</span></button></div></template>
</div>
"""


def test_reads_a_pressbooks_definition_out_of_its_template_block():
    """BeautifulSoup wraps `<template>` contents in `TemplateString`, which
    `get_text()` skips by default: it returns "" with no error while `str(node)`
    plainly shows the text. A harvester that reaches for `get_text()` reports every
    Pressbooks book as having no glossary, forever, without ever failing loudly.
    This test is here to fail when that happens.
    """
    entries = pressbooks_glossary(PRESSBOOKS_CHAPTER)

    assert [e.term for e in entries] == ["welcome booth"]
    assert entries[0].definition == (
        "A kiosk setup at the airport to welcome arriving international students."
    )


def test_two_surface_forms_of_one_pressbooks_term_are_a_single_entry():
    """Pressbooks points every inflection of a term at the same definition, so the
    surface form is not the term's identity — the id in the anchor's href is. One
    surveyed book carried 44 anchors, 30 distinct surface forms and 19 distinct term
    ids, against the 19 its API reported. A harvester keyed to what the sentence says
    over-reports that book by 58% while looking like it works.
    """
    html = """
    <div class="entry-content">
      <p>Set a <a class="glossary-term" href="#term_27_452">milestone</a>, then
         review your <a class="glossary-term" href="#term_27_452">milestones</a>.</p>
      <template id="term_27_452"><div class="glossary__definition"><div tabindex="-1">
        <p>A marker of progress toward a longer goal.</p>
      </div><button>Close definition</button></div></template>
    </div>
    """

    entries = pressbooks_glossary(html)

    assert [e.term for e in entries] == ["milestone"]
    assert entries[0].definition == "A marker of progress toward a longer goal."


def test_a_pressbooks_term_met_on_two_pages_is_a_single_entry():
    """Pressbooks renumbers the *prefix* of a term's id per page — `term_27_452` in
    one chapter, `term_31_452` in the next — so only the suffix identifies the term.
    Keyed on the whole id, a term mentioned in ten chapters is harvested ten times;
    one surveyed book showed 44 distinct ids for its 19 terms. The page kept is the
    first one, which for a book harvested in reading order is where it introduces
    the term — the rule `book_glossary` already follows.
    """
    anticipating = """
    <p>Set a <a class="glossary-term" href="#term_27_452">milestone</a>.</p>
    <template id="term_27_452"><div class="glossary__definition"><div tabindex="-1">
      <p>A marker of progress toward a longer goal.</p>
    </div><button>Close definition</button></div></template>
    """
    arriving = """
    <p>Review your <a class="glossary-term" href="#term_31_452">milestones</a>.</p>
    <template id="term_31_452"><div class="glossary__definition"><div tabindex="-1">
      <p>A marker of progress toward a longer goal.</p>
    </div><button>Close definition</button></div></template>
    """
    pages = [
        ("https://example.pressbooks.pub/b/chapter/anticipating/", anticipating),
        ("https://example.pressbooks.pub/b/chapter/arriving/", arriving),
    ]

    entries = pressbooks_book_glossary(pages)

    assert [e.term for e in entries] == ["milestone"]
    assert entries[0].page.endswith("/chapter/anticipating/")
