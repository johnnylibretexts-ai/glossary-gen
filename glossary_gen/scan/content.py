from __future__ import annotations

from bs4 import BeautifulSoup

# `.mt-content-container` is the Mindtouch/CXone template class that wraps the article
# body on EVERY LibreTexts library (chem, eng, bio, ...), not a book- or publisher-
# specific marker. That is what makes it safe to hard-code here: it is platform-wide,
# the same way `.libretexts.org` itself is. This is a different category from the
# `_BOILERPLATE` stoplist in scan_cli.py, which recognizes OpenStax-only section titles
# and is preview-only by design — it must never reach the scoring path. Narrowing to
# this selector, by contrast, is exactly what should happen before a page is scored: it
# removes the reader's display-settings menu, navigation, and footer, none of which is
# ever part of the book's content on any library.
CONTENT_SELECTOR = ".mt-content-container"


def extract_content(html: str) -> str:
    """Return the inner HTML of the first `.mt-content-container` element.

    Falls back to the original, unmodified `html` when that element is absent — a book
    whose template differs must degrade to today's noisier (whole-page) behaviour, never
    to an empty page that starves the scanner of everything. That fallback triggers ONLY
    on `container is None` (the container itself is missing), deliberately not on an
    empty-but-present container.

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
    soup = BeautifulSoup(html, "html.parser")
    container = soup.select_one(CONTENT_SELECTOR)
    if container is None:
        return html
    return container.decode_contents()
