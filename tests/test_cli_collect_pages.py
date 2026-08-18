"""Generation reads the same article the scanner does.

`glossary-scan` has narrowed a fetched page to its article since it was written; the
generator did not, so it excerpted from the whole rendered document — navigation,
license block and footer included. On a LibreTexts page that is noise. On a Pressbooks
page the chrome carries the book's entire table of contents on every page, one line per
chapter, and a chapter title is exactly the kind of phrase a term matches. A definition
grounded in a table of contents is grounded in nothing.
"""

import httpx

from glossary_gen.cli import collect_pages
from glossary_gen.excerpt import excerpts_for_term
from glossary_gen.fetch import PageCache
from glossary_gen.models import Term

PAGE_URL = "https://ecampusontario.pressbooks.pub/handbook/chapter/plurals/"

# The same real Pressbooks shape as tests/test_article.py: the book-wide contents list is
# `<p class="toc__title">` in the header, repeated on every page of the book.
PRESSBOOKS_HTML = """
<html><body>
<div id="page" class="site">
<header class="header">
  <div class="reading-header">
    <p class="screen-reader-text">Book Contents Navigation</p>
    <p class="toc__title"><a href="/handbook/chapter/schwa-vowels/">
      7. Spelling - Schwa Vowels and how a schwa vowel is taught in the middle grades</a></p>
    <p class="toc__title"><a href="/handbook/chapter/prefixes/">
      10. Vocabulary/Morphology - Prefixes, and the place of prefixes in word study</a></p>
  </div>
</header>
<main id="main">
  <div id="content" class="site-content">
    <section class="standard chapter type-chapter">
      <header><h1 class="entry-title">1 Spelling: Plurals</h1></header>
      <p>A plural is the form of a noun that names more than one thing, and it is
         created by adding s or es to the singular form of that noun.</p>
    </section>
  </div>
  <nav class="nav-reading"><p>Previous/next navigation</p></nav>
  <div class="block block-reading-meta">
    <h2>License</h2>
    <p>Handbook Copyright &copy; 2025 by Ruth McQuirter is licensed under a Creative
       Commons Attribution 4.0 International licence, except where otherwise noted.</p>
  </div>
</main>
<footer class="footer"><p>Powered by Pressbooks</p></footer>
</div>
</body></html>
"""


def make_cache(tmp_path):
    def handler(request):
        if str(request.url) != PAGE_URL:
            return httpx.Response(404)
        return httpx.Response(200, text=PRESSBOOKS_HTML)

    return PageCache(tmp_path, httpx.Client(transport=httpx.MockTransport(handler)))


def _term(name, slug):
    return Term(term=name, slug=slug, aliases=(), pages=(PAGE_URL,))


def test_collect_pages_narrows_to_the_article(tmp_path):
    failed = []
    pages = collect_pages(_term("Plural", "plural"), make_cache(tmp_path), failed)

    assert failed == []
    text = " ".join(block.text for block in pages[0].blocks)
    assert "A plural is the form of a noun" in text
    for chrome in (
        "Book Contents Navigation",
        "Schwa Vowels",
        "Prefixes",
        "Previous/next navigation",
        "License",
        "Powered by Pressbooks",
    ):
        assert chrome not in text


def test_a_term_seen_only_in_the_books_navigation_grounds_nothing(tmp_path):
    """`Schwa vowels` is a real term of this book — but this page only lists it in the
    contents sidebar, and a contents line is not a passage to write a definition from.
    The term must come back with no excerpt, so the run reports it unwritten (ADR-0006)
    rather than paying for a definition the model would have to supply from its own
    knowledge while `x_source_pages` cites this page.
    """
    term = _term("Schwa vowel", "schwa-vowel")
    pages = collect_pages(term, make_cache(tmp_path), [])

    excerpts, chars = excerpts_for_term(pages, term)

    assert excerpts == []
    assert chars == 0
