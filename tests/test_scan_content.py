from glossary_gen.fetch import parse_page
from glossary_gen.scan.content import extract_content

# A realistic fixture: reader chrome (search box, display-settings menu, nav, footer)
# surrounding a `.mt-content-container` article body, mirroring what a real rendered
# LibreTexts page looks like — headings and text both inside and outside the container.
CHROME_AND_ARTICLE_HTML = """
<html><body>
<div id="elm-search"><h2>Search</h2><p>Search this book...</p></div>
<div id="mt-display-settings">
  <h3>Text Color</h3>
  <h3>Text Size</h3>
  <h3>Margin Size</h3>
  <h3>Font Type</h3>
</div>
<nav><h2>11.01 Object-Oriented Programming Basics</h2></nav>
<article class="mt-content-container">
  <h1>Object-Oriented Programming Basics</h1>
  <p>Object-oriented programming organizes code around objects.</p>
  <h2>Classes and Objects</h2>
  <p>A class is a blueprint for creating objects.</p>
</article>
<footer>
  <h3>Recommended articles</h3>
  <p>Some other page.</p>
  <h2>Error</h2>
</footer>
</body></html>
"""

NO_CONTAINER_HTML = """
<html><body>
<h2>Recursion</h2>
<p>Recursion is a technique.</p>
</body></html>
"""

# Models a real contentless page (e.g. "Index", "Table of Contents", "Detailed
# Licensing"): the container is PRESENT but holds only scripts/divs/a footer, so its
# decoded contents carry no heading/paragraph text. Surrounded by chrome, same as a
# real rendered page, to prove the empty result does not fall back to it.
EMPTY_CONTAINER_HTML = """
<html><body>
<nav><h2>Search</h2></nav>
<div class="mt-content-container"><script>track();</script><div></div></div>
<footer><h3>Recommended articles</h3></footer>
</body></html>
"""


def test_extract_content_narrows_to_the_content_container():
    narrowed = extract_content(CHROME_AND_ARTICLE_HTML)

    assert "Object-Oriented Programming Basics" in narrowed
    assert "Classes and Objects" in narrowed
    assert "A class is a blueprint for creating objects." in narrowed
    assert "Search" not in narrowed
    assert "Text Color" not in narrowed
    assert "Recommended articles" not in narrowed
    assert "Error" not in narrowed


def test_extract_content_falls_back_to_original_html_when_selector_absent():
    """A book whose template differs must degrade to today's noisier behaviour, not to
    an empty page.
    """
    assert extract_content(NO_CONTAINER_HTML) == NO_CONTAINER_HTML


def test_extract_content_does_not_fall_back_when_container_is_present_but_empty():
    """A present-but-empty `.mt-content-container` (a genuinely contentless page like
    Index/ToC/Detailed Licensing) must yield an empty-of-text result, NOT fall back to
    the surrounding document — that would re-introduce chrome on exactly the pages that
    have no article to protect. See scan/content.py's module-level measurement.
    """
    narrowed = extract_content(EMPTY_CONTAINER_HTML)
    page = parse_page("https://eng.libretexts.org/index", narrowed)

    assert page.blocks == ()
    assert "Search" not in narrowed
    assert "Recommended articles" not in narrowed


def test_end_to_end_page_contains_article_headings_not_chrome_headings():
    """Fetch -> extract_content -> parse_page, as `collect_pages` now does. The
    resulting Page must contain the article's headings and none of the chrome's.
    """
    narrowed = extract_content(CHROME_AND_ARTICLE_HTML)
    page = parse_page("https://eng.libretexts.org/11.01", narrowed)

    headings = [b.text for b in page.blocks if b.kind == "heading"]
    assert headings == ["Object-Oriented Programming Basics", "Classes and Objects"]

    all_text = " ".join(b.text for b in page.blocks)
    for chrome_text in (
        "Search",
        "Text Color",
        "Text Size",
        "Margin Size",
        "Font Type",
        "Recommended articles",
        "Error",
        "11.01 Object-Oriented Programming Basics",
    ):
        assert chrome_text not in all_text
