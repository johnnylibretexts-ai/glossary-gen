from glossary_gen.fetch import parse_page
from glossary_gen.article import extract_content

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
    have no article to protect. See article.py's module-level measurement.
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


# Real Pressbooks markup, trimmed but not idealised: the shapes below were taken from
# https://ecampusontario.pressbooks.pub/languagefoundationshandbook/chapter/
# spelling-plurals-regular-patterns/ on 2026-08-17. The book-wide table of contents is
# `<p class="toc__title">` inside the header — real paragraph blocks, one per chapter,
# repeated on EVERY page of the book — which is why a whole-document fallback is not
# merely noisy here the way it is on an unknown LibreTexts template.
PRESSBOOKS_HTML = """
<html><body>
<div id="page" class="site">
<header class="header">
  <div class="header__container">
    <p class="screen-reader-text" id="primary-nav">Primary Navigation</p>
    <p>Want to create or adapt books like this? <a href="https://pressbooks.com/">Learn more</a>
       about how Pressbooks supports open publishing practices.</p>
  </div>
  <div class="reading-header">
    <p class="screen-reader-text" id="book-toc">Book Contents Navigation</p>
    <p class="toc__title"><a href="/languagefoundationshandbook/front-matter/introduction/">
      Introduction</a></p>
    <p class="toc__title"><a href="/languagefoundationshandbook/chapter/schwa-vowels/">
      7. Spelling - Schwa Vowels</a></p>
    <p class="toc__title"><a href="/languagefoundationshandbook/chapter/vocabulary-prefixes/">
      10. Vocabulary/Morphology - Prefixes</a></p>
  </div>
</header>
<main id="main">
  <div id="content" class="site-content">
    <section class="standard post-21 chapter type-chapter status-publish hentry">
      <header><h1 class="entry-title">1 Spelling: Plurals &#8211; Regular Patterns</h1></header>
      <p>The plural form of most nouns is created by adding s or es to the singular form.</p>
      <h2>Why does it matter?</h2>
      <p>Errors with regular plurals comprise a significant portion of spelling errors.</p>
    </section>
  </div>
  <nav class="nav-reading"><p>Previous/next navigation</p></nav>
  <div class="block block-reading-meta">
    <h2>License</h2>
    <p>Language Foundations Handbook Copyright &copy; 2025 by Ruth McQuirter is licensed
       under a Creative Commons Attribution licence.</p>
    <h2>Share This Book</h2>
  </div>
</main>
<footer class="footer footer--reading"><p>Powered by Pressbooks</p></footer>
</div>
</body></html>
"""


def test_extract_content_narrows_a_pressbooks_page_to_its_section():
    """The Pressbooks article wrapper, not the whole document.

    Without this the model is sent the book's entire table of contents on every page,
    and each of those lines is a chapter title — the exact shape of "a term this page
    defines". The evidence gate cannot catch it either, because the nav text really is
    on the page.
    """
    narrowed = extract_content(PRESSBOOKS_HTML)
    page = parse_page("https://ecampusontario.pressbooks.pub/x/chapter/plurals/", narrowed)
    text = " ".join(block.text for block in page.blocks)

    assert "The plural form of most nouns" in text
    assert [b.text for b in page.blocks if b.kind == "heading"] == [
        "1 Spelling: Plurals – Regular Patterns",
        "Why does it matter?",
    ]
    for chrome in (
        "Book Contents Navigation",
        "7. Spelling - Schwa Vowels",
        "10. Vocabulary/Morphology - Prefixes",
        "Primary Navigation",
        "open publishing practices",
        "Previous/next navigation",
        "License",
        "Share This Book",
        "Powered by Pressbooks",
    ):
        assert chrome not in text


def test_the_libretexts_container_wins_when_both_selectors_are_present():
    """Order is the guard, not specificity. A LibreTexts page carrying an unrelated
    `#content` wrapper must still narrow to `.mt-content-container`, so adding a second
    platform cannot change what the first one extracts.
    """
    both = """
    <html><body>
      <div id="content" class="site-content"><p>Wrong container.</p></div>
      <div class="mt-content-container"><p>The article.</p></div>
    </body></html>
    """
    narrowed = extract_content(both)

    assert "The article." in narrowed
    assert "Wrong container." not in narrowed
