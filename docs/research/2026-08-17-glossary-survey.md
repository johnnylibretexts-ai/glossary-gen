# How many books can this method measure at all?

[ADR-0010](../adr/0010-reference-sets-come-from-books-not-experts.md) replaced an expert reference
set with the glossary a book's own authors publish. That leaves one question it could not answer
from a single book: **how many books have one?**

77 books across six LibreTexts libraries, screened by fetching 1,582 pages. No model was called, so
the whole survey cost nothing but politeness. `tools/survey_glossaries.py`, output in
[`2026-08-17-glossary-survey.csv`](./2026-08-17-glossary-survey.csv).

## The answer: 9 of 77, and density swings 35-fold

| share of sampled pages | book | terms in sample | book pages | scan forecast |
|---|---|---|---|---|
| **71%** | Concepts in Biology (OpenStax) | 177 | 114 | $0.32 |
| **54%** | General Biology 1e (OpenStax) | 144 | 307 | $0.77 |
| **42%** | Introductory Statistics 1e (OpenStax) | 10 | 117 | $0.33 |
| 25% | Map: Raven Biology 12th Edition | 41 | 570 | $1.26 |
| 12% | Introductory Psychology | 19 | 956 | $4.30 |
| 8% | Map: Essential Biology with Physiology (Campbell) | 38 | 181 | $0.27 |
| 8% | Precalculus 1e (OpenStax) | 9 | 124 | $0.67 |
| 4% | Precalculus 2e (OpenStax) | 17 | 166 | $0.53 |
| 2% | Introductory Statistics 2e (OpenStax) | 1 | 187 | $0.29 |

By library: **bio 4/13, math 2/14, stats 2/19, socialsci 1/8, chem 0/12, phys 0/11.**

## What a zero means, and what it does not

**A hit is proof; a zero is weak evidence.** The survey samples pages evenly across a book rather
than reading all of them, and the sample size turned out to be load-bearing in a way worth
recording:

- *Introductory Statistics 1e* carries blocks on 28% of its pages. A 12-page sample found 5.
- *Introductory Statistics 2e* carries them on roughly 2.5%. **The same 12-page sample found none**,
  and the tool reported the book as having no glossary. A 40-page sample found one.

So the 68 books that came back empty are "no evidence at 24 pages", not "no glossary". The real
carrier rate is somewhere at or above 12%, and the low-density tail is exactly where sampling
fails. The tool prints that caveat on every run rather than a clean "no".

## Two findings worth more than the count

**Editions diverge.** 1e and 2e of the same OpenStax book, on the same shelf, differ by more than an
order of magnitude in glossary density — 42% against 2% of sampled pages for statistics, 8% against
4% for precalculus. Whatever produces these blocks is a property of a particular import or edition,
not of a publisher or a subject. A method keyed to them inherits that instability.

**Subject matters more than publisher.** Biology carries them best (4 of 13, and the two densest
books in the survey); chemistry and physics carry none at all across 23 books. That is the third
time this project has measured subject as the dominant variable — after ADR-0004's *Computer*
example, and after neither of the Python book's cut clusters surviving into the statistics book.

## What this means for the method

It is real and it is narrow. Roughly one book in eight can be measured this way today, and the two
biology books at 71% and 54% are better reference material than anything measured so far — 177 and
144 author-written terms in a 24-page sample alone, against 101 for the whole statistics book.

But it cannot become *the* evaluation for the tool, because the tool's job is books that have no
glossary. Python Programming (OpenStax) has none; that is why it was scanned in the first place.
The method measures the scanner where a reference happens to exist and is silent everywhere else,
which is a fair description of its value and its ceiling.

**Recommended next measurement, if there is one:** *Concepts in Biology*, 114 pages, forecast $0.32.
It is the densest reference set found, in the library that carries them best, and it would answer
whether 55% recall and 1-in-59 contradictions were statistics-specific. That is a real question with
a $0.32 answer, and this note is not assuming it will be paid for.

## Method notes

- Books come from a shelf's `getTOC` children; pages from each book's own TOC, sampled evenly
  across the whole book. Sampling from the top screens a book on its title page and licence.
- The scan forecast is computed from each sample's own page text at ~4 characters per token, not
  from `EST_SCAN_TOKENS_IN`, which is calibrated to one book and ran 3x low on statistics pages
  ([detail](./2026-08-17-definition-comparison.md)). `Introductory Psychology` at $4.30 for 956
  pages is the reason a forecast per book is worth having at all.
- Fetches are cached, so re-surveying a shelf is free and instant.
