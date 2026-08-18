from __future__ import annotations

from bs4 import BeautifulSoup
from bs4.element import Tag

# One selector per PLATFORM, tried in order, first match wins. Each is the template
# wrapper its platform puts every article inside — not a book- or publisher-specific
# marker — which is what makes hard-coding them safe. This is a different category from
# the `_BOILERPLATE` stoplist in scan_cli.py, which recognizes OpenStax-only section
# titles and is preview-only by design; it must never reach the scoring path. Narrowing
# to these, by contrast, is exactly what should happen before a page is scored: it removes
# the reader's navigation, display controls and footer, none of which is ever part of the
# book's content.
#
# Order, not specificity, decides between them: a page that somehow carried both is
# narrowed by the first, so adding a platform cannot change what an existing one extracts.
#
# `.mt-content-container` is the Mindtouch/CXone template class wrapping the article body
# on EVERY LibreTexts library (chem, eng, bio, ...), the same way `.libretexts.org` itself
# is platform-wide rather than per-book.
#
# `#content.site-content` is the Buckram wrapper every Pressbooks theme renders the article
# into — it holds exactly one `<section>` of type chapter / front-matter / back-matter.
# Verified 2026-08-17 on five ecampusontario books across four themes; the id is paired
# with the class deliberately, since a bare `#content` is a common id on arbitrary sites.
# Without it a Pressbooks page reaches the model as the whole document, and the book's
# entire table of contents — one `<p class="toc__title">` per chapter, repeated on every
# page — is a list of chapter titles in the exact shape of "a term this page defines".
# The evidence gate cannot refuse those: the nav text really is on the page.
CONTENT_SELECTORS = (".mt-content-container", "#content.site-content")


def content_element(html_or_soup: str | BeautifulSoup) -> Tag | None:
    """The first element matching a known platform wrapper, or None if none matches.

    The same choice `extract_content` makes, exposed as the element rather than as its
    inner HTML, for the one caller that needs to tell an article from the chrome around
    it instead of just keeping the article. `scan/toc.py` reads a part page twice over:
    the article says whether the part is a page or a divider, and the chrome carries the
    theme's copy of the book's table of contents. Detaching the element splits the
    document into exactly those two halves, from one parse and one definition of where
    the line falls.
    """
    soup = (
        html_or_soup
        if isinstance(html_or_soup, BeautifulSoup)
        else BeautifulSoup(html_or_soup, "html.parser")
    )
    for selector in CONTENT_SELECTORS:
        container = soup.select_one(selector)
        if container is not None:
            return container
    return None


def extract_content(html: str) -> str:
    """Return the inner HTML of the first element matching a known platform wrapper.

    Falls back to the original, unmodified `html` when NO selector matches — a book on a
    platform this does not know must degrade to the noisier (whole-page) behaviour, never
    to an empty page that starves the scanner of everything. That fallback triggers ONLY
    when nothing matched, deliberately not on an empty-but-present container.

    Do not add a "fall back when extraction is empty" guard — it was proposed in review
    and rejected after measuring all 136 pages cached from a real book's dry-run:

        .mt-content-container present per page : exactly 1 on all 136 (never 0 or >1)
        containers present but empty            : 0
        pages whose extracted content is empty  : 3 ("Index", "Detailed Licensing",
                                                       "Table of Contents")

    Those three are genuinely contentless front/back-matter pages: their container holds
    only scripts, divs, and a footer, so `get_text()` on the container really is `""`.
    Zero blocks is the CORRECT output for them, not a bug. Falling back to the whole
    document when extraction is empty would re-introduce exactly the site chrome this
    module exists to strip, and precisely on the pages that have no article to protect.
    The caller (`scan_cli.execute`) is responsible for skipping zero-block pages cheaply,
    not this function for papering over them with chrome.
    """
    container = content_element(html)
    return html if container is None else container.decode_contents()
