# Scanning the densest carrier, scored against its own glossary

**Research Methods in Psychology**, `ecampusontario.pressbooks.pub/psychmethods3ecan`, 83 pages,
2026-08-18. Model `gemini-3.7-flash`. It was picked because the
[80-book sweep](./2026-08-17-platform-discovery-probes.md) found it the densest carrier on the
network, so the scan could be scored the same day against a reference set nobody wrote by hand
([ADR-0010](../adr/0010-reference-sets-come-from-books-not-experts.md)). Artifacts live in
gitignored `out/`, which is why this is recorded here.

## Bottom line

| | |
|---|---|
| pages | 83, `ok=83 skipped=0 fetch_error=0 llm_error=0 empty=0` |
| candidates | 343 proposed, **343 verified, 0 rejected** |
| terms | 303 merged |
| reference set | 243 author terms ([CSV](./2026-08-18-psychmethods-author-glossary.csv)) |
| **recall** | **187 / 243 = 77.0%** |
| spend | **$0.2332** |

**77.0% is the highest this project has measured, on the largest reference set it has.** The prior
figures are 57.9% against a 19-term hand-built index (Python Programming), 54.5% against 101 author
terms (Introductory Statistics), and 50.8% against 59 (Language Foundations Handbook). One book is
not a trend and this one is not a like-for-like comparison — a 243-term set from an 83-page book is
a different measurement from a 59-term set on 23 pages — but the direction is worth having.

**Recall is the same by either route into the reference set**, which is the more reassuring number:

| where the author term came from | in the set | found | |
|---|---|---|---|
| the back-matter glossary page | 100 | 77 | 77% |
| linked inline in a chapter | 143 | 110 | 77% |

## The scanner proposed nothing at all from the book's own glossary page

That page was scanned like any other — `ok`, 2,580 input tokens — and returned **0 candidates**. The
cause is exact, and it is not the model.

`fetch.parse_page` collects headings and `<p>` and nothing else. On a definition list the
definitions sit in `<p>` inside each `<dd>` and survive; the **terms are `<dt>`, which is neither**,
so they are dropped. The model was handed 100 orphaned definitions with no terms attached and
correctly proposed none — it cannot name a term whose name is not on the page it can see.

**This cuts both ways and the direction is a decision, not a bug:**

- It wastes a real paid call on the single most term-dense page in the book, every run.
- It also makes the 77% **uncontaminated**. The scanner never sees the answer key, so it cannot
  score by copying the authors' list. Teaching `parse_page` about `<dt>` would raise recall on every
  carrier and destroy the measurement that says so.

The cheap half of the fix has no such tension: a page the harvester can read for free is a page
worth *not* paying a model to read. Skipping author-glossary pages during a scan would save the call
without touching what the scanner is shown elsewhere.

## The pre-flight estimate was 2.3x low, and the ceiling was not

Printed `estimated cost: $0.10 for 83 pages`; actual **$0.2332** (177,461 in / 26,686 out). Third
data point for `EST_SCAN_TOKENS_IN`, which is calibrated to one book: **2.1x high** on that book,
**3x low** on the statistics pages, 2.3x low here. It is a sizing aid and should not be read as
anything tighter.

**`--budget-usd` is not affected**, and it is worth being precise about why: the ceiling is checked
before every page against spend recomputed from the ledger's own recorded token counts
(`run.execute_run`), seeded from prior runs of the same ledger — not against the estimate. So the
$5 ceiling given here was a real $5, whatever the estimate said.

## 0 of 343 candidates were rejected

The evidence gate refused nothing across the whole book. Recorded rather than explained: the gate is
covered by tests and a run where every candidate's evidence is genuinely on its page is exactly what
a well-behaved model produces. But a 0% refusal rate is the reading a broken gate would also give,
so it is worth watching on the next book rather than being taken as a result.

## What is not measured here

The 290 scanner slugs absent from the author glossary are **not** cuts. Only some pages carry
glossary entries, so absence is silence — this set grades recall and says nothing about whether a
term belongs. Nothing here has been reviewed by a person, and term fit remains a human judgement
that no reference set answers ([ADR-0010](../adr/0010-reference-sets-come-from-books-not-experts.md)).
