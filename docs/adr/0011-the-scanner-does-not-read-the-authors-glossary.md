# The scanner does not read the authors' glossary

`fetch.parse_page` collects headings and `<p>`. In a definition list the definitions sit in `<p>`
inside each `<dd>` and survive; the terms are `<dt>`, which is neither, so they are dropped. A page
that is nothing but the authors' glossary therefore reaches the model as definitions with no terms
attached, and the model proposes nothing from it.

That was found by measurement, not by reading the code. *Research Methods in Psychology* publishes
a 100-entry glossary page. The scan sent it, spent 2,580 input tokens on it, and got **0
candidates** back — recorded in
[`docs/research/2026-08-18-psychmethods-scan-vs-author-glossary.md`](../research/2026-08-18-psychmethods-scan-vs-author-glossary.md).

The obvious repair is to teach `parse_page` about `<dt>`. **That repair is refused**, and this ADR
exists because the reason is not visible from the code that would change.

## Why it looks like a bug

Recall against that book's author glossary is 187/243 = 77.0%, and 23 of the 56 misses are terms the
authors listed on that very page. Teaching the parser one tag would hand the scanner the exact
strings it is scored against. Recall would rise on every carrier, immediately, with a one-line diff.

## Why it is not

**The reference set is the author glossary** (ADR-0010). A scanner that reads the glossary page is
scored on its ability to copy the answer key, and the number it produces stops describing anything.
The 77.0% is worth having precisely because the scanner could not see the list it was measured
against — a property that is structural today, and would be gone the moment `<dt>` became a block.

The measurement is also the only one this project has that nobody chose. Its predecessor floors
came from 19 slugs someone typed and 101 harvested from one book; both were replaced *because*
hand-chosen sets can be tuned against after the fact. A scanner that reads glossary pages restores
that failure mode in a worse form, since nothing would look wrong.

And the terms are not lost. `scan.reference` harvests them for free, with no model in the loop, on
allowed paths — 243 terms from that book against the scan's 303. A term on the authors' glossary
page is already available to anyone who wants it; paying a model to re-derive it buys nothing.

## What follows from it

The scan **skips a page that is nothing but the authors' glossary** rather than paying for a call
that cannot return anything (`scan.reference.is_author_glossary_page`, `scan_cli.execute`). The
skip is deliberately narrow: a chapter that ends in a glossary block is a chapter, and its prose is
the whole point of a scan. The rule is "no paragraph left once the glossary is taken out", checked
against every cached page rather than argued — 1 of 83 pages flagged on the Pressbooks book, 0 of
1,833 cached LibreTexts pages, including the 78 that carry real glossary blocks inside chapters.

**The skipped page still gets a scan record, and it is `ok`.** Two things depend on that: a resumed
run must not re-pay for it, and `tools/harvest_glossary.py --scan` reads a scan's page list to find
the page the glossary is on. A page dropped from the record would take every term the authors
listed there out of the reference set — the measurement destroying itself by a different route.

## Consequences

A future reader who notices `parse_page` dropping `<dt>` and raises recall by fixing it will have
broken the evaluation, and the evaluation will not complain. That is the whole reason this is an
ADR and not a comment: the code that would change is in `fetch.py`, and nothing there knows about
reference sets.

If the trade is ever revisited, revisit it explicitly. A defensible version exists — read `<dt>` for
*generation*, where a page's own definitions are grounding material, while keeping the scanner blind
— but it must be a decision with its own record, not a tidy-up of a parser that looks incomplete.

## Considered options

**Teach `parse_page` about `<dt>`.** Rejected above. It is the change this ADR exists to prevent.

**Keep paying for the glossary page.** Rejected. The call cannot return anything — measured at
2,580 tokens for 0 candidates — and every run and every resume pays it again.

**Drop the glossary page from the scan entirely.** Rejected: it would silently shrink the reference
set that `--scan` harvests, and a resumed run would re-evaluate it forever.

**Detect the page by URL** (`back-matter/glossary/`). Rejected. It is the shape of the page that
matters, not its slug: the same books publish `Glossaire` and `Glossary of Key Terms for Online
Learning`, and a URL rule would miss those while claiming to be general.
