# First paid run on a Pressbooks book — measurements

Everything the tool had proven on Pressbooks before this was free: discovery, fetching, page
parsing, author-glossary harvest. Nothing downstream of a model call had ever been run against a
non-LibreTexts book ([#36](https://github.com/johnnylibretexts-ai/glossary-gen/issues/36)). This is
that run, recorded because the artifacts live in gitignored `out/`.

Book: **Language Foundations Handbook**, `ecampusontario.pressbooks.pub/languagefoundationshandbook`,
23 pages, 2026-08-17. Model `gemini-3.7-flash` throughout. It carries a 59-term author glossary,
which is why it was chosen: the run can be scored the same day.

## Bottom line

The paid path works on Pressbooks and costs about **7 cents** for a 23-page book. Recall against the
authors' own glossary is **50.8%**, statistically indistinguishable from the 54.5% the same scanner
gets on a LibreTexts book scored the same way.

It did **not** work before this run, and the reason was not in the model call. Three things in the
paid path assumed LibreTexts shape, all fixed first — see *What had to change* below. Had the run
gone ahead without them it would have paid for a corrupted index and read as a success.

## What it cost

| Stage | Estimate | Actual | Ratio |
|---|---|---|---|
| `glossary-scan`, 23 pages | $0.0289 | **$0.0357** | **0.81× — LOW** |
| `glossary-gen`, 48 terms | $0.0414 | **$0.0349** | 1.19× high |
| **Total** | | **$0.0706** | |

**The scan estimate ran low for the first time.** `EST_SCAN_TOKENS_IN/OUT` (1050/125) were measured
on 136 LibreTexts pages; these Pressbooks pages billed 1216 in and 171 out on average. The constants
were not changed — two books is not a recalibration, and the README already states they are means
for sizing a book rather than an upper bound for any one. What matters is that a low estimate does
not become an overspend: `--budget-usd` is charged against **real accumulated tokens**, not against
the estimate, so the ceiling still binds exactly where it is set.

Generation's per-term shape held: 410 in / 120 out against the 500/130 estimate.

## What it produced

    scan:  23 pages ok (3 in a first --limit 3 run, 20 resumed), 0 fetch_error, 0 llm_error,
           0 empty -> 53 candidates verified, 0 rejected -> 48 terms merged (7 on >1 page)
    gen:   46 ok, 2 no_excerpt, 0 llm_error, 0 fetch_error -> 46 rows

The two unwritten terms are `Cloze strategy` (16 chars of grounding) and `Derivation` (90, just
under the 100 floor). Zero rejected candidates over 23 pages, matching the LibreTexts books.

The resume key works across platforms: the second invocation reported `skipped=3` and re-paid for
nothing.

**Book identity carries the platform's shape, as intended.** `library` is a hostname
(`ecampusontario.pressbooks.pub`), `coverID` is a book slug (`languagefoundationshandbook`), where a
LibreTexts book puts a library code and a numeric cover id. Nothing in the paid path parsed either
one, and both reached the CSV unaltered.

## Recall against the authors' glossary

`tools/harvest_glossary.py` read the 23 already-cached pages — no network, no key, no cost:

| | |
|---|---|
| pages carrying an author glossary | 15 / 23 |
| author glossary terms | 59 |
| found by the scanner (incl. aliases) | **30 / 59 = 50.8%** |
| scanner slugs absent from the reference set | 47 |

Those 47 are **not** cuts. Only some pages carry glossary blocks, so absence is silence — the same
caveat ADR-0010 attaches to every reference set.

For comparison, *Introductory Statistics* (LibreTexts) scores 55/101 = 54.5% against its own author
glossary. Pressbooks is not a harder platform to read.

## An observation the reviewer needs

**15 of the 48 terms were found only on the book's back-matter glossary page.** Pressbooks renders
the author glossary as a definition list, the scanner reads it like any other page, and generation
then grounds those terms in the authors' own wording. That is not a defect — the glossary page is
part of the book, and every step behaved exactly as specified — but roughly a third of this CSV is
a paraphrase of a glossary the book already has, rather than an independent reading of its chapters.
On a book that carries an author glossary, a reviewer should expect that and may want to scan with
the glossary page excluded.

## What had to change

All three were in the paid path, invisible to every free probe, and none is about the model.

**1. The article extractor knew one platform.** `extract_content` matched
`.mt-content-container` and otherwise fell back to the whole document. A Pressbooks page therefore
reached the model complete with the site chrome — and Pressbooks repeats the **entire table of
contents of the book** in every page's header, one `<p class="toc__title">` per chapter. Measured
across these 23 pages:

| | characters | blocks |
|---|---|---|
| whole document | 121,856 | 1,605 |
| article only | 90,760 | 869 |
| removed | **25.5%** | **45.9%** |

The block share is the damaging one: every removed line is a chapter title, which is the exact shape
of "a term this page defines". The evidence gate cannot refuse them either — the nav text really is
on the page, so an invented-looking candidate would have verified cleanly and appeared on all 23
pages, collecting a `multipage` corroboration for good measure. `article.py` now holds one selector
per platform, tried in order, and `#content.site-content` was verified on five ecampusontario books
across four themes.

**2. Generation read the whole document even where the scanner did not.** `cli.collect_pages` called
`cache.get()` (whole page) while `scan_cli.collect_pages` narrowed first. On LibreTexts that was
noise; here it meant excerpts could be drawn from the contents sidebar. It now narrows identically.

**3. Generation had no per-run host guard.** `glossary-scan` widens `is_allowed_url` by the host of
`--book`; `glossary-gen` built its `PageCache` with no `source_host`, so it could only ever fetch the
standing allowlist. An index scanned from any host outside it — `www.saskoer.ca`, already probed and
proven fetchable — would have reached step 2 and failed **every page**. It now widens by the host of
the index's `book.index_url`, which is the same URL a person pasted, carried through the index. This
run did not depend on the fix: `ecampusontario.pressbooks.pub` is on the standing allowlist, which is
precisely why the bug could sit here unnoticed.

## If you generated a book before this

Nothing here reaches work already done. `Ledger.has()` treats a subject with an `ok` row as
finished, and there is no blanket `--force` by design — one would re-pay for a whole book. So a
book generated before this change keeps definitions excerpted from the whole rendered document,
including, on Pressbooks, the table-of-contents header this exists to remove, and a resumed run
will never revisit them.

Two ways out, both deliberate acts rather than something a resume does silently: name the affected
terms with `--regenerate`, or start a fresh `--ledger` and re-pay for the book. At the measured
7 cents for 23 pages, the second is usually the honest choice.

## Reproducing

    glossary-scan --book "https://ecampusontario.pressbooks.pub/languagefoundationshandbook/" \
      --budget-usd 0.20 --yes \
      --out out/pressbooks/index.json --report out/pressbooks/index-report.json \
      --ledger out/pressbooks/scan.jsonl

    glossary-gen --input out/pressbooks/index.json \
      --out out/pressbooks/glossary.csv --ledger out/pressbooks/run.jsonl \
      --budget-usd 0.20 --yes

    python3 tools/harvest_glossary.py --scan out/pressbooks/scan.jsonl \
      --index out/pressbooks/index.json --out out/pressbooks/reference.csv
