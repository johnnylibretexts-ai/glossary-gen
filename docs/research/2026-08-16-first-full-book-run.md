# First full-book run — measurements

The first end-to-end run of both commands over a whole book, 2026-08-16. Recorded because the
artifacts live in `out/`, which is gitignored: the numbers below cost $0.35 and about twelve
minutes of API calls, and one `rm -rf out/` or one fresh clone destroys them.

Book: **Python Programming (OpenStax)**, `eng/117469`, 136 pages. Model: `gemini-3.7-flash`
throughout. Spend ceiling `--budget-usd 10.00`, never approached.

## Bottom line

The pipeline works end to end and costs about 35 cents a book. Two things it does are measurably
wrong and neither is a bug: the pre-flight estimator overstates cost by roughly 2×, and the
scanner's **score ranks noise above signal** — the four thinnest entries in the output all scored
a perfect 1.0 while several genuinely useful terms scored lower.

## What it cost

| Stage | Estimate | Actual | Ratio |
|---|---|---|---|
| `glossary-scan`, 136 pages | $0.4080 | **$0.1687** | 2.42× high |
| `glossary-gen`, 212 terms | $0.3657 | **$0.1779** | 2.06× high |
| Probes (model list + one request) | — | ~$0.0006 | |
| **Total** | | **$0.347** | |

Same tokens on `gemini-3.5-flash` would have cost $0.3626 for the scan alone — **2.15×** more.

## What it produced

    scan:  136 pages ok, 0 fetch_error, 0 llm_error, 3 empty (front/back matter)
           236 candidates verified, 0 rejected -> 212 terms merged (18 on >1 page)
    gen:   210 ok, 2 no_excerpt, 0 llm_error, 0 fetch_error -> 210 rows

The two `no_excerpt` terms are `init` and `super` — almost certainly mangled `__init__` and
`super()`, which is a term-extraction question rather than an excerpting one.

CSV shape checks, all clean: 21 columns; every row `x_status = needs-review` and
`x_model = gemini-3.7-flash`; definitions 37–289 characters (median 130); no empty definitions;
no `addedBy` column; no cell required formula-injection escaping. **13 rows have
`pages != x_source_pages`** — precisely the "worth a human's eye" signal the README describes.

## Finding 1 — the estimator is ~2× high, from two different errors

`EST_TOKENS_IN = 1200` and `EST_TOKENS_OUT = 220` (`cli.py:44-45`) against measured reality:

| | Estimated | Measured | |
|---|---|---|---|
| Scan, per page | 1200 in / 220 out | **1035 in / 124 out** | output ~1.8× over |
| Generation, per term | 1200 in / 220 out | **479 in / 130 out** | input ~2.5× over |

The scan's input guess is close; its *output* guess is nearly double. Generation is the reverse —
its input guess is far too high, because the excerpt budget (~6,000 characters) is rarely filled.
Two constants wrong at opposite ends, and because output is the expensive side the errors compound
rather than cancel.

The direction is benign — a gate that over-warns is safer than one that under-warns — but the
figure shown at the confirmation prompt is about twice what will actually be charged, so someone
sizing a large book off it may decline a run they could easily afford. One shared pair of constants
serves two workloads with genuinely different shapes.

## Finding 2 — the score ranks noise above signal

This is the significant one. Score distribution across all 212 terms:

| Score | Terms |
|---|---|
| **1.00** | **135** (64%) |
| 0.95 | 22 |
| 0.90 | 19 |
| 0.85 | 32 |
| 0.80 | 3 |
| 0.70 | 1 |

Nearly two-thirds tie at the ceiling. But the distribution is the smaller problem. Here is what
those scores actually rank:

| Term | Definition produced | Score |
|---|---|---|
| Computer | "An electronic device that stores and processes information." | **1.00** |
| Object | "A single unit of data in a Python program." — wrong; an object is a class instance | **1.00** |
| Palindrome | "A word that is spelled the same forward and backward." | **1.00** |
| Panel data | "Multidimensional structured datasets." — a fragment | **1.00** |
| Ndarray | "A NumPy data type and multi-dimensional array structure that stores homogeneous numeric data…" | 0.90 |
| Except clause | — | 0.85 |
| Composition | — | 0.80 |
| Mad lib | — | 0.70 (lowest in the book) |

**A reviewer trimming this list from the bottom deletes `Except clause` and `Composition` while
keeping `Computer` and `Palindrome`.**

### Why, and why it is not a tuning problem

The mechanism is working exactly as specified. Score = the model's own confidence, `+0.15` if the
term appears in a heading, `+0.10` if its evidence matches the `is a` / `is called` / `refers to`
cue regex, `+0.05` if multipage, clamped to 1.0. *Computer* has its own heading and the page reads
"A computer **is an** electronic device…", so it collects both bonuses and saturates.

Every one of those signals answers **"is this term defined on this page?"** — and each answers it
well. But `CONTEXT.md` defines a **Score** as something that *"ranks terms for the human reviewing
them."* What that reviewer needs is **"is this term worth a glossary entry?"**

The two questions look identical and are mildly **opposed**: the clearest evidence that a page
*defines* a word is often that the word is basic enough for the book to stop and explain it.
Adjusting the four weights cannot fix that, because the weights are not what is wrong — the
quantity being measured is.

## Finding 3 — the evidence gate works; 0 rejections is real

236 of 236 candidates passed verification, which on its face is indistinguishable from a disabled
check. Tested adversarially against a synthetic page:

    PASS    real quote, exact
    PASS    real quote, case + whitespace noise
    REJECT  invented quote
    REJECT  too short (under 20 chars)
    REJECT  plausible but not on the page

The gate rejects what it should. And the 20-character floor was never the binding constraint:
evidence spans ran 43–208 characters (median 89), with none under 40. So `gemini-3.7-flash`
genuinely copied verbatim every time.

## Finding 4 — the 429 path was never exercised

Zero `llm_error` rows across 348 consecutive model calls on a brand-new key. Good news for the
pipeline, but it means the retry and backoff work landed in `6b16517` remains proven only by unit
tests: Google never rate-limited us, so no real 429 was ever handled. The scan that historically
halted after 7 pages did so on a metered key; this one was not metered.

## Reproducing this

    glossary-scan --book "https://eng.libretexts.org/Bookshelves/Computer_Science/\
    Programming_Languages/Python_Programming_(OpenStax)" \
      --model gemini-3.7-flash --budget-usd 10.00 \
      --out out/index.json --report out/index-report.json --ledger out/scan.jsonl

    glossary-gen --input out/index.json --model gemini-3.7-flash --budget-usd 10.00 \
      --out out/glossary.csv --ledger out/run.jsonl

Both `--dry-run` first: free, and the scan's dry run warms the page cache so the paid run does no
fetching. Note that the `proceed? [y/N]` gate is `and sys.stdin.isatty()`, so it is **skipped
entirely** when stdin is not a terminal — an unattended invocation spends without asking.

## Open, in the order they are worth taking

1. **What the score is for** — Finding 2. A domain question about what the number means, not a
   tuning exercise. Grill before touching `candidates.py`.
2. **The estimator constants** — Finding 1. Measured; the only real decision is whether to keep
   fixed constants or derive them from the ledger.
3. **`prices.json` effective dates** — `gemini-3.7-flash` and `gemini-3.6-flash` double on
   2027-01-01.
4. **The default model** — `gemini-3.7-flash` is proven working unmodified and 2.15× cheaper than
   the `gemini-3.5-flash` currently defaulted to in three places.
