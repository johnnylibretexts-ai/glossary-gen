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
    to an empty page that starves the scanner of everything.
    """
    soup = BeautifulSoup(html, "html.parser")
    container = soup.select_one(CONTENT_SELECTOR)
    if container is None:
        return html
    return container.decode_contents()
