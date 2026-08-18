# glossary-gen

Generate page-grounded glossary definitions for LibreTexts books.

Step 2 of the three-step glossary pipeline: it consumes a book index (terms plus the pages
each term appears on) and emits a CSV of AI-generated definitions for review and import.

> **New here? Go straight to the [Walkthrough](#walkthrough--from-a-fresh-clone-to-a-csv).**
> It takes you from `git clone` to a CSV, and the first real step needs no API key and costs
> nothing. Everything below the walkthrough is reference material.

- Step 1 (build the index) ships here too, as a separate command: `glossary-scan`.
- Step 3 (import into Conductor) is out of scope.
- Every row ships as `x_status = needs-review`. Nothing here is reviewed or approved content.

License: [MIT](LICENSE).

## Where this fits

| Step | What it does | Owner |
|---|---|---|
| 1 | Produce the index — keywords/phrases **with the pages each appears on** | `glossary-scan` (this package) |
| 2 | **This tool.** AI reads those pages and writes a definition per term | — |
| 3 | Import the CSV into Conductor, where terms are centralised | Conductor side |

Step 3 is deliberately out of scope: nothing here talks to Conductor. Steps 1 and 2 are two
separate commands from the same package, and the boundary between them is real — `glossary-scan`
emits an index, `glossary-gen` consumes one and emits a CSV. Neither knows about the other
beyond that file, so you can hand-write the index and skip step 1 entirely.

The two contracts this package owns are the [input format](#input-format) and the
[output columns](#output-columns) — those are the integration surface, and both are specified
below.

## Building an index (glossary-scan)

`glossary-scan` produces step 1's input: point it at a LibreTexts book and it writes an index
in exactly the format documented under [Input format](#input-format), ready to feed straight
into `glossary-gen`.

It walks the book's table of contents, and for each page asks a model one question — *what
terms does this page define?* — requiring a verbatim quote from that page as evidence for
every candidate it proposes. Only candidates whose quote actually checks out against the page
survive; what's left is merged into one entry per term, so you get a reviewable list rather than
a flat dump of headings. It is not ranked — see [ADR-0004](docs/adr/0004-the-scanner-does-not-rank.md).

**Free preview first.** `--dry-run` walks the book and lists heading-derived "structural
candidates" — no model call, no key, no cost:

    glossary-scan --book "https://eng.libretexts.org/Bookshelves/Computer_Science/Programming_Languages/Python_Programming_(OpenStax)" --dry-run

Real output against that book:

    book:       Python Programming (OpenStax) (eng/117469)
    pages:      136 fetched, 0 failed
    candidates: 275 structural (headings, boilerplate removed)
      - Computer programs
      - The Python language
      - Basic output
      ...
    This is a free preview. Structural candidates are NOT the scanner's output —
    a real run reads each page with a model and verifies what it finds.

Structural candidates are headings with the obvious OpenStax boilerplate (Summary, Key Terms,
Exercises, …) filtered out — good for confirming the TOC resolves and sizing the book before
spending anything. They are **not** what the scanner produces. A real run reads every page
with a model and verifies what it actually finds defined there.

**A real run**, capped for a first smoke test and with a spend ceiling:

    export GLOSSARY_GEN_GEMINI_API_KEY=...
    glossary-scan --book "https://eng.libretexts.org/Bookshelves/Computer_Science/Programming_Languages/Python_Programming_(OpenStax)" \
      --limit 20 --budget-usd 2.00 --out out/index.json --report out/index-report.json

Every term this writes is an **unreviewed candidate** — the same `x_status = needs-review`
posture stated elsewhere in this README, just one step earlier in the pipeline: nothing here
has been read by a human. **Everything verified is emitted** — there is no threshold, because the
scanner does not rank (ADR-0004) — and a human trims the list. The scanner's observations
themselves do not go into the index: `input.py` is the only file that owns the index schema,
so the scanner doesn't get to add a field to it. They go to the `--report` sidecar instead —
one row per term with its confidence, its corroborations, source pages, and evidence quote. That
sidecar is a **diagnostic**, not a review aid: it is how you compare one scan against another after
a prompt change. Trimming happens on the generated CSV, which is the artifact a person can read.

Cost guards, in the order they apply:

- `--dry-run` is free — no key needed, no model called.
- `--budget-usd` aborts the run once spend crosses the ceiling. As with `glossary-gen`'s
  ledger, the running total is seeded from every `tokens_in`/`tokens_out` already recorded in
  the `--ledger` file, so the ceiling bounds **total spend across resumes**, not spend per
  invocation.
- `--ledger` is a resumable, append-only JSONL log keyed on the page. A re-run against the same
  ledger skips any page already recorded `ok`, so an interrupted or aborted scan picks back up
  instead of re-paying for pages it already scanned.
- `--delay` (default `0.3`s) is politeness between real page fetches — spacing out requests to
  LibreTexts' servers, not a rate-limit workaround.

`glossary_gen/prices.json` prices `gemini-3.7-flash` (the default), `gemini-3.6-flash`,
`gemini-3.5-flash` and `gemini-3.5-flash-lite`, verified
2026-08-16 against [Google's price list](https://ai.google.dev/gemini-api/docs/pricing) and
recorded in [`docs/research/2026-08-16-gemini-flash-pricing.md`](docs/research/2026-08-16-gemini-flash-pricing.md).
Any other model — including `gemini-3.7-flash` — has no entry, which disables `--budget-usd`
for it. Prices move, so re-check before a large run.

A replay-based recall eval harness exists under `tests/eval/` — it exercises the
candidate-selection and verification logic against fixed fixtures, offline, with no model
call. It has been measured against a live model on a real book: against Python Programming
(OpenStax), `glossary-scan` found 11 of a 19-term reference index (recall 11/19 = 0.579).
That measurement is pinned as a regression floor of 0.55 in `tests/eval/test_recall_openstax.py`,
so a prompt or verification change that drops recall below the measured baseline fails CI. Recall
0.579 is measured on **one book against a partial reference set** — read it as a baseline to
regress against, not as a validated recall rate for the tool in general.

A second eval scores recall against a reference set **nobody wrote by hand**. Some books publish
their own glossary — LibreTexts renders author-written entries as definition lists under a
`Glossary` or `Key Terms` heading — and `tools/harvest_glossary.py` harvests them from the page
cache an earlier scan already filled, for free:

```bash
python3 tools/harvest_glossary.py --scan out/stats-scan.jsonl --index out/stats-index.json
```

Against *Introductory Statistics 1e (OpenStax)*, that is 101 author-written terms across 33 of 117
pages, of which the scanner proposed 60. Replayed over the 33 recorded pages the figure is 55/101 =
0.545, pinned at 0.50 in `tests/eval/test_recall_stats_author_glossary.py`.

**Recall is all this measures.** 155 slugs the scanner proposed for that book are absent from the
author glossary, and that is not a 73% over-proposal rate: only some pages carry glossary blocks,
so absence is silence, not a judgement. `coverage` returns a report with no precision field and the
tool prints the caveat on every run. Not every book has one to harvest — Python Programming
(OpenStax) carries none, its back-matter page being the unfilled LibreTexts template. See
[ADR-0010](docs/adr/0010-reference-sets-come-from-books-not-experts.md).

A separate, real, billed run — a 20-page bounded scan of the same book — produced 39 verified
terms, and `glossary-gen` grounded all 39 of them (0 without excerpts, 0 page failures). It
reported $0.0135 actual against a $0.03 pre-flight estimate — but **both figures were computed
with a rate since found to be wrong**, the one belonging to `gemini-3.5-flash-lite` rather than
`gemini-3.5-flash`. Real spend was 3.6–5× those numbers depending on the token split, and the
ledger that would settle it exactly is long gone. What survives the correction is the ratio: the
estimate and the actual were computed the same way, so estimate-vs-actual agreement still holds
even though neither absolute figure does.

**Rate limiting.** A refused model request is waited out and retried, up to three requests per
refusal. When the provider says *when* to come back — a `Retry-After` header, or the `RetryInfo`
block Gemini returns with an exhausted quota — that hint is obeyed exactly, up to a 60-second cap.
A hint longer than the cap is read as "not coming back within this run": the subject fails at once
rather than the tool appearing to hang for an hour. Each wait is announced on stderr, so a run that
has gone quiet can be told apart from one that has stalled.

**The hole this leaves** is a provider that meters you *without* sending a hint. The unhinted wait
is deliberately short — roughly twelve seconds across two retries, not a full per-minute quota
window — because buying that window blind would cost every genuinely broken run five times as long
in dead waiting before the consecutive-failure breaker stops it. So on an unhinted per-minute
quota the subject still fails, the ledger still records it, and a re-run still resumes past it for
free. That is the scenario behind the scan that once halted after 7 pages; it is now much less
likely and not impossible. `--delay` paces page *fetches*, not model calls, and does not help here.
Why the waiting lives in the transport and nowhere above it:
[ADR-0003](docs/adr/0003-backoff-belongs-to-the-transport.md).

**The ceiling is per refusal, not per term.** A term whose reply also fails to parse is retried up
to three times, and each of those enters a fresh retry loop — so one term's worst case is nine
requests and six waits against a single provider, about six minutes at the 60-second cap, doubled
again if a fallback provider is configured. That worst case needs the provider to be metering *and*
answering with unparseable text at the same time. It is left unbounded on purpose; the
consecutive-failure breaker ends a genuinely stuck run.

### How glossary-scan works

    TOC ──▶ fetch pages ──▶ extract article ──▶ per-page model call ──▶ verify ──▶ corroborate ──▶ merge ──▶ emit
             (cached)        (chrome stripped)         │                  └─ pure, free ─────────────┘
                                                       └── consults ledger ──┘

Only the model call costs money. Verification, corroboration, merging and writing are pure functions
over data — which is why the eval harness under `tests/eval/` can replay a recorded scan through
all of them offline, with no key and no spend.

**It reads the article, not the page.** A page as served carries the site's chrome — the reader's
display-settings menu, navigation, footer. On one measured LibreTexts page that was 54% of the text
and 8 of its 11 headings ("Search", "Text Color", "Margin Size", "Recommended articles", …). Both
commands narrow a fetched page to its article before parsing (`article.py`), matching one platform
wrapper per platform, in order: `.mt-content-container` on LibreTexts (the MindTouch/CXone article
wrapper, platform-wide rather than book- or publisher-specific) and `#content.site-content` on
Pressbooks (the Buckram wrapper holding the one chapter / front-matter / back-matter section). If a
page matches neither the whole document is used, so an unfamiliar template degrades to noisier
input rather than to nothing. Pages whose article is genuinely empty — front and back matter like
Index, Table of Contents and Licensing — are recorded as scanned with zero terms and never sent to
a model at all.

On Pressbooks the narrowing is not a tidiness measure. Every page of a Pressbooks book repeats the
book's whole table of contents in its header, one `<p>` per chapter — measured on *Language
Foundations Handbook*, 26% of the page's characters and 46% of its blocks, every one of them a
chapter title, which is the exact shape of "a term this page defines". The evidence gate cannot
refuse those, because the nav text really is on the page.

**The evidence quote is a gate, not a hint.** Every candidate must arrive with a span the model
copied verbatim from the page, and that span is then looked for in the page text — whitespace- and
case-insensitively, since the HTML has already been reflowed, and subject to a 20-character floor
so a two-word fragment can't satisfy it. A candidate whose quote isn't found is discarded outright.
This is the anti-hallucination mechanism: a model that invents a term invents its evidence too, and
invented evidence doesn't appear on the page. It is never softened into a corroboration.

**Corroboration is reported, not scored.** A surviving candidate keeps the model's own confidence
unchanged, and the scanner records by name each independent signal the page supplied: `heading` if
the term or an alias appears in a heading, `cue` if its evidence matches the same
`is a`/`is called`/`refers to` regex `excerpt.py` uses to rank grounding paragraphs, and
`multipage` if the term turned up on more than one page. Reusing `excerpt.py`'s regex is
deliberate: agreement between what the scanner corroborates and what the generator can later ground
a definition in predicts whether a term will survive step 2.

**These are never combined into one number, and the scanner does not rank.** It used to: confidence
plus fixed bonuses, clamped to 1.0. On a real 212-term book that tied 64% of terms at exactly 1.0,
and the tie contained both the best entries and the worst, while genuinely useful terms sat below
it. Every signal answers *"is this defined on this page?"*, which is not the question a reviewer
trimming a glossary asks — and the two are mildly opposed, since a book most clearly defines the
words basic enough to need explaining. Full reasoning:
[ADR-0004](docs/adr/0004-the-scanner-does-not-rank.md).

**Merging is where the index contract is honoured.** The same term proposed on several pages
collapses into one row: pages, aliases and corroborations are unioned, the most confident surface
form becomes the `term` (ties broken by corroboration count, then by order seen), and every other
observed spelling is preserved as an alias so nothing seen is lost.
Deduplicating by slug is mandatory, not tidiness — `input.py` rejects an index containing two terms
with the same slug, so an unmerged index would be refused by the very tool it is built for.
Singular and plural are deliberately *not* unified: "Dictionary" and "Dictionaries" slug
differently and both survive, because any string rule aggressive enough to merge them also merges
genuinely distinct terms. Near-duplicates are left for the human doing the review.

| Module | Responsibility |
|---|---|
| `scan/toc.py` | discovery — book metadata and page URLs, via LibreTexts' public `getTOC` endpoint or a Pressbooks book's own front page |
| `scan/propose.py` | the scan prompt and one model call per page |
| `scan/candidates.py` | `verify` / `corroborations_on_page` / `merge` — pure, no I/O, no LLM |
| `scan/emit.py` | writing the index and the diagnostic sidecar |
| `scan/evaluate.py` | the offline replay harness behind `tests/eval/`, and the recorder that writes its fixtures |
| `scan/reference.py` | harvesting a book's own author glossary as a reference set |
| `scan_cli.py` | argument parsing, cost control, the orchestration loop |

Three scripts sit outside the package in `tools/`, because they serve a reviewer or a maintainer
rather than a run: `harvest_glossary.py` (above), `record_fixture.py` (records an eval fixture from
the page cache — the only one that spends, and it refuses to without `--yes` or a terminal), and
`label_sheet.py` (a keyboard labeller for the review sheets in `docs/research/`, which writes only
what a human types — see [ADR-0005](docs/adr/0005-review-labels-are-collected-blind.md) and
[ADR-0010](docs/adr/0010-reference-sets-come-from-books-not-experts.md)).

The boundaries from [How it works](#how-it-works) still hold, and the scanner is on the far side of
one of them: `input.py` remains the only file that knows the index format. The scanner conforms to
that format rather than extending it, which is why the scanner's own observations live in the `--report` sidecar instead of
in the index. `fetch.py`, `ledger.py` and `llm.py` are shared with `glossary-gen` — the scanner
adds a page-shaped ledger record and a second entry point, not a second copy of the machinery.

### What the `--report` sidecar holds

`out/index-report.json` is written **first and unconditionally** — a scan that verified nothing
cannot write an index at all, and that is exactly the run where you most need to see what the
scanner observed. It records, per term, the model's `confidence` and each `corroboration` by name,
never fused into one number (ADR-0004).

It also records the candidates the **evidence gate refused**, with which of two reasons fired:

```json
"rejected": {
  "count": 1,
  "candidates": [
    { "term": "Monad",
      "reason": "evidence_not_on_page",
      "page": "https://eng.libretexts.org/...",
      "confidence": 0.9,
      "evidence": "A monad is a monoid in the category of endofunctors." }
  ]
}
```

- **`evidence_not_on_page`** — the span the model offered as proof is not on the page. This is the
  signature of a model inventing a term *and* the quotation for it. The invented text is kept
  verbatim, because it is the whole reason to keep the row.
- **`evidence_too_short`** — under `MIN_EVIDENCE_CHARS` (20). The model found the right page and
  returned something useless. A prompt problem, not a hallucination.

The block is always present, empty or not, so its absence never has to be read as "none were
rejected".

**This is a diagnostic, not a review aid.** A rejected candidate is not a term — the book is not
known to define it, and its supporting quote may be fabricated — so it is never offered to a
reviewer to rescue, unlike an [unwritten term](#the-unwritten-sidecar), which the book *does*
define. That asymmetry is deliberate; see
[ADR-0007](docs/adr/0007-rejected-candidates-are-a-diagnostic-not-a-review-artifact.md). The
audience is whoever is tuning the prompt or the gate.

Both this file and the index are rebuilt from the **ledger**, not from whatever one invocation
happened to scan, so a resumed scan still describes the whole book.

**If you have a scan ledger from before 2026-08-16**, its rows record how many terms each page
yielded but not which, so they cannot rebuild an index. Those pages are treated as not-done and
re-scanned once — the run says so up front, before the spend confirmation:

    note: 136 page(s) in out/scan.jsonl predate candidate storage and must be
          re-scanned to rebuild the index; the estimate below covers them

That is a one-time re-pay (about $0.17 for a 136-page book). Every scan after it resumes correctly.
Old ledgers are still read and never rewritten. See
[ADR-0008](docs/adr/0008-the-scanners-output-is-rebuilt-from-the-ledger.md).

### glossary-scan options

| Flag | Default | Meaning |
|---|---|---|
| `--book` (required) | — | book root URL on `*.libretexts.org` |
| `--out` | `out/index.json` | index path, written in the [input format](#input-format) |
| `--report` | `out/index-report.json` | diagnostic sidecar path |
| `--cache-dir` | `cache` | page cache dir — same on-disk cache file and format as `glossary-gen`'s `--cache-dir` |
| `--ledger` | `out/scan.jsonl` | ledger path; resume/skip and cost-ceiling state live here |
| `--prompt-version` | `v1` | scan prompt version |
| `--model` | `gemini-3.7-flash` | Gemini model name. **Changing it re-runs the whole book** — see the ledger note under [Usage](#usage) |
| `--limit` | — | scan at most N pages (smoke runs) |
| `--delay` | `0.3` | seconds between real page fetches |
| `--budget-usd` | — | abort if spend exceeds this |
| `--yes` | off | confirm the spend up front. **Required for a non-interactive run** — without a tty and without this flag, the run refuses and exits 2 before fetching anything, rather than spending unasked |
| `--dry-run` | off | walk the book and report structural candidates; call no model, spend nothing |

## Install

    # Use it
    pip install .

    # Work on it
    pip install -e ".[dev]"

Requires Python ≥ 3.12. Building from source needs setuptools ≥ 77 (PEP 639 licence
metadata); `pip` supplies that automatically unless you build with `--no-build-isolation`.

The prompt templates (`glossary_gen/prompts/*.md`) and the price table
(`glossary_gen/prices.json`) ship inside the wheel, so a non-editable install is fully
functional.

## Providers

Configured entirely by environment variable. At least one must be set or the tool exits `2`.

| Variable | Required | Meaning |
|---|---|---|
| `GLOSSARY_GEN_GEMINI_API_KEY` | for Gemini | enables the Gemini client, tried **first** |
| `GLOSSARY_GEN_OPENAI_BASE_URL` | for self-hosted | any OpenAI-compatible `/v1` endpoint — Ollama, vLLM, LM Studio |
| `GLOSSARY_GEN_OPENAI_MODEL` | no | model for the above; defaults to `llama3.1` |
| `GLOSSARY_GEN_OPENAI_API_KEY` | no | bearer token, if your endpoint wants one |

Set both and you get a fallback chain: Gemini first, self-hosted on transport failure
(timeout, `429`, `5xx`). Set only `GLOSSARY_GEN_OPENAI_BASE_URL` and the tool runs entirely
against your own hardware with no third-party API involved.

    # Fully self-hosted, no API key anywhere
    export GLOSSARY_GEN_OPENAI_BASE_URL=http://localhost:11434/v1
    export GLOSSARY_GEN_OPENAI_MODEL=llama3.1
    glossary-gen --input index.json --out out/glossary.csv

Keys are read from the environment and travel only in request headers. They are never
written to the ledger, the CSV, or any error message.

## Walkthrough — from a fresh clone to a CSV

A worked example ships in `examples/`, so you can go end to end before wiring up a book of
your own.

**1. Install.** No API key needed yet.

    git clone https://github.com/johnnylibretexts/glossary-gen
    cd glossary-gen
    pip install .

**2. See it work, for free.** `--dry-run` fetches the real pages, finds the passages that
define each term, and reports coverage — **without calling any model**. No key, no cost.

    glossary-gen --input examples/openstax-python-index.json --dry-run

Expected output:

    terms total: 19
    terms with excerpts: 18
    terms without: 1
    pages failed: 0
    terms with no excerpt: algorithm
    dry run: no model was called and nothing was spent

That "1 without" is the tool doing its job: *algorithm* is listed against a page that never
really defines it. **Run this against any index before paying to generate from it** — it
tells you how good the index is, which is the cheapest quality signal you will get.

**3. Add a provider.** Either a Gemini key:

    export GLOSSARY_GEN_GEMINI_API_KEY=…

…or nothing but your own hardware, with no third-party API involved:

    export GLOSSARY_GEN_OPENAI_BASE_URL=http://localhost:11434/v1
    export GLOSSARY_GEN_OPENAI_MODEL=llama3.1

**4. Generate a small batch first.** Pennies, and it shows you real output before you commit
to a whole book.

    glossary-gen --input examples/openstax-python-index.json --max-terms 5 --out out/sample.csv

**5. Read `out/sample.csv`.** Every row is `x_status = needs-review`. If the definitions read
well, scale up; if they don't, edit the prompt (see [below](#usage)) rather than the code.

**6. Run the whole thing, with a spend ceiling.**

    glossary-gen --input examples/openstax-python-index.json --budget-usd 5.00 --out out/glossary.csv

### Pointing it at your own book

`glossary-gen` — the step 2 command the walkthrough above uses — does not build the index, it
consumes one. Either way you get there, the file is in the same
[input format](#input-format): each term plus the page URLs where that term is discussed.

**Build one with `glossary-scan`.** It ships in this package and is step 1 of the pipeline:
point it at a book and it writes an index ready to feed straight into `glossary-gen`. Start
with the free `--dry-run` — no key, no cost — and see
[Building an index](#building-an-index-glossary-scan) for the cost guards before a real run:

    glossary-scan --book "<book url>" --dry-run

**Or supply your own.** Practical sources for that list, in rough order of effort:

- A book's back-matter **Index** page, which already pairs keywords with the pages they
  appear on — this is what `examples/openstax-python-index.json` was built from.
- Any existing keyword or co-author index export, converted to the three-column CSV form.
- Hand-written, for a first pass. Twenty terms is enough to judge output quality.

`examples/openstax-python-index.json` has `coverID` set to `REPLACE-ME` — substitute the
real Conductor coverID for your book, or pass `--cover-id` on the command line.

### Which books these commands will fetch

Both commands refuse any URL that is not `https` on an allowed host. The standing allowlist is
every `*.libretexts.org` subdomain — matched as a suffix, because every LibreTexts library is one
host — plus a short list of exact hosts, currently just `ecampusontario.pressbooks.pub`. Pressbooks
is thousands of independent installs under a shared name, so a suffix there would admit every other
install on the network and anyone who registers a name ending in it; each entry is a host whose
operator was considered on its own.

Beyond that list, **each run is widened by the one book it was given**:

| Command | What authorises the widening | Provenance |
|---|---|---|
| `glossary-scan` | the host of `--book` | a person pasting a book URL on the command line |
| `glossary-gen` | the host of the index's `book.index_url` | the same URL, carried inside a data file |

The widening is one **exact** host, never a suffix — a run pointed at `www.saskoer.ca` still
refuses `evil.www.saskoer.ca`, `www.saskoer.ca.evil.com`, and plain `http` — and every redirect hop
is re-checked, since validating the typed URL and then trusting wherever it redirects is the same
hole as no guard. A term's occurrence pages deliberately widen nothing: those are data a scan
produced, not a book a person named. An index with no `book` block (every CSV one, and any JSON one
that omits it) therefore reaches only the standing allowlist.

**The two rows have different provenance, and `glossary-gen` is stricter for it.** An index file is
a generated artifact that gets passed around, so its `book.index_url` is not a person typing a URL
the way `--book` is. It must be `https` to widen anything at all — an `http://` one is refused a
widening rather than having its host taken on trust. When the result is that **no** page in the
index is on an allowed host, the run refuses up front (exit 2) instead of fetching every page,
failing every one, writing an empty CSV and exiting 0.

## Input format

Two accepted shapes. JSON is preferred because it carries the book identity.

**JSON** — `book` is optional but then `--library`, `--cover-id`, `--book-id` are required:

```json
{
  "book": {
    "library": "eng",
    "coverID": "12345",
    "bookId": "python-openstax",
    "title": "Python Programming (OpenStax)",
    "index_url": "https://eng.libretexts.org/.../zz%3A_Back_Matter/10%3A_Index"
  },
  "terms": [
    {
      "term": "Recursion",
      "aliases": ["recursive"],
      "pages": ["https://eng.libretexts.org/.../08%3A_Recursion/8.01%3A_Basics"]
    },
    { "term": "Base case", "pages": ["https://eng.libretexts.org/.../8.02%3A_Base_Cases"] }
  ]
}
```

**CSV** — three columns, multi-values pipe-delimited. Carries no book block, so the three
`--library`/`--cover-id`/`--book-id` flags are required:

```csv
term,aliases,pages
Recursion,recursive,https://eng.libretexts.org/a|https://eng.libretexts.org/b
Base case,,https://eng.libretexts.org/c
```

Rules: `term` and `pages` are required per entry; `aliases` is optional. Page URLs must be
`https` on a `*.libretexts.org` host — anything else is refused. Duplicate slugs across
terms are rejected with the offending pair named. Validation errors identify the entry by
its 1-based position.

`pages` is the single most important field: it is what the AI actually reads. A term whose
listed pages don't contain it produces no definition, which `--dry-run` reports for free.

## Usage

    # 1. Audit the index first. No key, no cost.
    glossary-gen --input index.json --dry-run

    # 2. Smoke-run 20 terms.
    export GLOSSARY_GEN_GEMINI_API_KEY=...
    glossary-gen --input index.json --max-terms 20 --out out/sample.csv

    # 3. Full run with a spend ceiling.
    glossary-gen --input index.json --budget-usd 5.00 --out out/glossary.csv

Re-running with an unchanged prompt costs nothing for terms that already succeeded: the
ledger skips any term with a recorded `ok` row. Terms that failed — a provider outage,
an unfetchable page, no excerpt found — are **not** treated as done and are retried on
the next run; a failed term can accumulate more than one row in the ledger before it
finally succeeds, which is expected and used as failure history.

**Changing `--model` re-runs the whole book.** The ledger is keyed on
`(subject, prompt_version, model)`, so a ledger built against one model has nothing a run on
another counts as done: every term is re-attempted and re-paid for. That is correct — a definition
written by a different model is a different result, not a cached one — but it is a real bill, so
give a model change its own `--out` path if you want to compare, and expect to pay again. The
default moved to `gemini-3.7-flash` on 2026-08-16; a ledger from before then will re-run in full
unless you pass `--model gemini-3.5-flash` explicitly.

To regenerate already-succeeded terms after editing a prompt, copy `prompts/v1.md` to
`prompts/v2.md`, edit it, and pass `--prompt-version v2`. The ledger keeps rows for
**every** prompt version and model you've ever run against it — that's what makes resume
free — but the CSV only ever contains rows from *this* invocation: `status == "ok"` **and**
`prompt_version` **and** `model` matching the current run **and** the term's slug present
in the current input file. So running `v1` then `v2` from the same `--ledger` never mixes
both definitions into one CSV. If you want a side-by-side comparison of two prompt versions
or two models, run each to a different `--out` path.

**To redo specific terms without touching the prompt, use `--regenerate`.** It re-attempts named
subjects even though the ledger says they are done, and it is per-subject on purpose — there is no
blanket `--force`, because one would re-pay for a whole book. Where a term ends up with several
attempts, both CSVs use its **latest**: a term regenerated into a failure leaves the import CSV for
the unwritten sidecar, and a term regenerated into a success stays.

**What the ledger key does and does not claim.** It is `(subject, prompt_version, model)`, and it
claims *"the same prompt and model were used"* — not *"re-running today would produce this row"*.
Constants that shape output but are not in the key (`MIN_EXCERPT_CHARS`, `max_excerpts`, the
excerpt ranking order, the term-matching rules) can change without invalidating anything, by
design: a tool built around never paying twice should not acquire a mechanism whose whole purpose
is to make it pay twice. When such a change matters for a specific term, name it to `--regenerate`.
See [ADR-0009](docs/adr/0009-the-resume-key-does-not-version-generation-policy.md).

**Give every book its own `--ledger` path.** Pointing `--ledger` at a file that already
holds another book's terms keeps that book's rows out of this CSV — *unless the two books
share a term*. The ledger key is `(subject, prompt_version, model)` — where the subject is
the term's slug — and carries no book identity, so for a slug present in both books the
lookup counts it as already done, skips
regeneration, and the CSV emits the first book's definition stamped with this book's
`library` / `coverID` / `bookId`. A separate ledger per book avoids this entirely.

### Options

| Flag | Default | Meaning |
|---|---|---|
| `--input` (required) | — | step-1 index file (`.json` or `.csv`) |
| `--out` | `out/glossary.csv` | output CSV path |
| `--cache-dir` | `cache` | on-disk HTML page cache; reused across runs so pages already fetched are never re-fetched |
| `--ledger` | `out/run.jsonl` | append-only run log; the resume/skip and cost-ceiling state live here. **Point every book at its own `--ledger` path** — see the prompt-iteration note above for why a shared/default path across books is safe for the CSV but wastes ledger disk space and history clarity |
| `--prompt-version` | `v1` | filename stem under `prompts/`, e.g. `v2` for `prompts/v2.md` |
| `--model` | `gemini-3.7-flash` | model name passed to the Gemini client only; the OpenAI-compatible fallback's model comes from `GLOSSARY_GEN_OPENAI_MODEL`. **Changing it re-runs the whole book** — the ledger is keyed on it |
| `--library`, `--cover-id`, `--book-id` | — | override the input file's `book` block; required (from one source or the other) when the input is CSV, which never carries a book block |
| `--max-terms` | — | process at most N terms (smoke runs); must be a positive integer |
| `--regenerate` | — | comma-separated terms to re-attempt even though the ledger says they are done. Accepts either spelling — `--regenerate 'Equality,__init__()'` or `--regenerate equality,init`. A value matching no term in `--input` refuses the run (exit 2) rather than quietly doing nothing. Per-subject on purpose: there is no blanket `--force`, because one would re-pay for a whole book |
| `--budget-usd` | — | pre-run estimate gate **and** mid-run abort ceiling, see Cost control below |
| `--yes` | off | confirm the spend up front, skipping the interactive `proceed? [y/N]` prompt. **Required for any non-interactive/CI invocation** — without a tty and without this flag, the run refuses and exits 2 before fetching anything, rather than spending unasked |
| `--dry-run` | off | fetch and excerpt only; calls no model, needs no API key, costs nothing |

### Exit codes

| Code | Meaning |
|---|---|
| `0` | success (including a user declining the confirmation prompt) |
| `2` | input error — bad/missing input file, no provider configured, pre-run cost estimate exceeds `--budget-usd`, `--budget-usd` was given for a model with no configured price, `--regenerate` named a term absent from the input, no page in the index is on an allowed source (see [Which books these commands will fetch](#which-books-these-commands-will-fetch)), or a non-interactive run was given no `--yes` to consent with. Nothing was spent and there is no ledger to resume |
| `3` | the run started but aborted early — 5 consecutive provider failures, or actual spend crossed `--budget-usd` mid-run. Check the ledger for what happened; already-succeeded terms are safe and the run is resumable |

> **Unattended runs need `--yes`, including ones that would cost nothing.** Consent is settled
> before the ledger is read, so a re-run that is fully resumable — every subject already `ok`, so
> nothing would be paid for — is still refused without `--yes`. The gate cannot know the ledger
> state without doing the work first, and doing work before consent is the thing it exists to
> prevent. Add `--yes` to any scheduled invocation.

## Cost control

Per-token prices live in `glossary_gen/prices.json`, keyed by model name. It covers
`gemini-3.7-flash` (the default), `gemini-3.6-flash`, `gemini-3.5-flash` and
`gemini-3.5-flash-lite`, all verified 2026-08-16 against
[Google's published rates](https://ai.google.dev/gemini-api/docs/pricing) and recorded with their
source in [`docs/research/2026-08-16-gemini-flash-pricing.md`](docs/research/2026-08-16-gemini-flash-pricing.md).
Any other model — `gemini-3.7-flash`, or the OpenAI-compatible fallback's default `llama3.1` —
has no configured price.

**Verify a rate before you add one, and record where you checked.** Until 2026-08-16 this file
carried `gemini-3.5-flash-lite`'s rate under `gemini-3.5-flash` — the two are adjacent rows on
Google's price list — which understated input 5× and output 3.6×. An error in that direction does
not disable the ceiling; it silently raises it, so a run reports success having spent several
times what `--budget-usd` was set to allow.

- With an unpriced model and no `--budget-usd`, the tool warns once to stderr and
  proceeds; there is no way to estimate or enforce a ceiling it can't price.
- With an unpriced model **and** `--budget-usd`, the tool now **refuses to start**
  (exit code `2`) rather than silently ignoring the ceiling you asked for. Add the
  model's price to `glossary_gen/prices.json`, or drop `--budget-usd`.

**The pre-flight estimate is calibrated to one book — treat it as an order of magnitude.**
`EST_SCAN_TOKENS_IN = 1050` was measured against Python Programming (OpenStax), whose 272 scanned
pages averaged 1,035 input tokens. Introductory Statistics averages **2,300**, so its scan was
quoted at $0.15 and cost **$0.245**; a subset of that book's longest pages came in at 4,054 per
page, 3.1× its estimate. The constant is not being re-fitted, because a constant averaged over two
books is wrong for both. Quote an estimate as an estimate, and read actual spend off the ledger's
`tokens_in`/`tokens_out`. `--budget-usd` is the thing that actually bounds a run. Measurements:
[`docs/research/2026-08-17-definition-comparison.md`](docs/research/2026-08-17-definition-comparison.md).

`--budget-usd` is a ceiling on **total spend recorded in the ledger**, not per-invocation:
resuming a run seeds the running token counters from every `tokens_in`/`tokens_out`
already in the ledger, so a resumed run cannot blow through the ceiling once per resume.

**The ceiling is a floor, not an exact meter** — but only by a bounded amount, and not for the
reason you might expect. **Every reply the provider billed is charged**, including one that failed
schema validation and was retried, and one whose term ultimately failed: `generate_entry` and
`propose_candidates` carry the accumulated token counts out on the raised exception, the failure is
written to the ledger with them, and the run reseeds its running total from rows of *every* status.
That is what makes `--budget-usd` bound total spend across resumes rather than per invocation.

Two things it genuinely cannot see:

- **The subject that crosses the ceiling is paid for in full.** Spend is checked before a subject
  is attempted and again once its attempt has been charged, so the crossing is detected after the
  fact. A run can therefore end slightly over. The overshoot is bounded by one subject's cost —
  which, since a subject may bill more than one reply, is a few calls rather than a few cents.
- **A call billed without a reply reports nothing.** If the request is served and charged but the
  connection drops before the response arrives, there is no usage block to read a token count from,
  so it is recorded as zero. Nothing can recover that number after the fact.

Neither is a leak you can close by reading the ledger more carefully; both are the cost of enforcing
a ceiling from the client side.

## Reliability notes

- **Three layers retry, and only the lowest one sleeps.** A *request* the provider refused is
  waited out by the transport (`RetryingClient`, wrapping each client in `build_client`). A reply
  that arrived but did not parse is retried **immediately** by `generate.py` and
  `scan/propose.py` — a malformed reply is not a server asking for time, and the same request a
  minute later is no more likely to parse. Page fetches (`fetch.py`) retry `429`/`5xx` three times
  with no delay, which is fine against LibreTexts pages because they do not meter us.

  The split is deliberate and load-bearing. The loops nest, so one term already costs up to nine
  requests when the provider is both metering and answering with prose; adding a delay to the
  outer loops would make it sleep on every one of them, for a failure that is not about timing. If
  you are about to make these consistent, read
  [ADR-0003](docs/adr/0003-backoff-belongs-to-the-transport.md) first.

## Output columns

21 columns in a fixed order. **The rule: anything an importer cannot consume is prefixed
`x_`.** That makes "ignorable" mechanical rather than a judgment call.

**Core** — maps to Conductor's `AddGlossaryParams`:

| Column | Notes |
|---|---|
| `term` | as supplied in the input |
| `definition` | the generated text — the point of the whole tool |
| `aliases` | input aliases merged with any the model proposed, pipe-delimited |
| `pages` | page **URLs** where the term is used, pipe-delimited |
| `author` | always empty; present for shape |
| `link` | always empty; present for shape |
| `source` | the book's `index_url` |
| `library`, `coverID`, `bookId` | book identity, repeated on every row |

**Extension** — richer than the import contract needs, safe to drop:
`x_category`, `x_context`, `x_example`, `x_related`

**Provenance** — how the row was produced:
`x_status`, `x_model`, `x_provider`, `x_prompt_version`, `x_generated_at`,
`x_source_pages`, `x_excerpt_chars`

### Notes for whoever writes the importer

- **`addedBy` is never emitted.** Set it from the authenticated user. A CSV that asserts its
  own authorship is exactly the failure this was designed against.
- **`pages` holds URLs, not Conductor page IDs.** Resolving a URL to a `pageID` needs
  Conductor context this tool doesn't have, so resolution is the importer's job.
- **`x_status` is always `needs-review` in this file.** Nothing in it has been read by a
  human. Do not import it as approved content. The sidecar described below is the one place
  `x_status` carries anything else, and it is not an import file.
- **`pages` and `x_source_pages` are different on purpose.** `pages` is where the term is
  *used* (straight from the index); `x_source_pages` is which pages actually grounded the
  definition. When they diverge you're looking at either a bad index mapping or a term
  that's listed but never really discussed — both worth a human's eye.
- **`x_model` vs the ledger's `model`.** `x_model` reports the model that actually answered,
  which may be the fallback provider. The ledger separately keys on the chain's declared
  primary so resume stays stable; you don't need to care, but that's why the two can differ.
- **Multi-value cells are pipe-delimited** (`a|b|c`), with RFC 4180 quoting otherwise.
- **Rows only ever come from one run.** The CSV is filtered to the current invocation's
  prompt version, model, and input slugs, so a shared ledger cannot leak another run's rows.

### The unwritten sidecar

Not every term gets a definition. A term whose pages ground too little, won't fetch, or whose
model call keeps failing is **unwritten** — and every unwritten term is reported in a second
CSV beside `--out`:

    --out out/glossary.csv  ──▶  out/glossary.csv             the import file, definitions only
                                 out/glossary.unwritten.csv   what got no definition, and why

The path is derived from `--out`; there is no flag for it. The file is **always written**,
header-only when nothing is unwritten, so its absence never has to be read as either "clean
run" or "stale directory."

It carries the same 21 columns, so you can concatenate the two into one sheet. What differs:

- **`definition` is empty**, and `x_status` holds `no_excerpt`, `fetch_error` or `llm_error`
  instead of `needs-review`. Those values are disjoint, so a concatenated sheet stays legible.
- **`x_excerpt_chars` is the shortfall.** `0` means the term matched nothing at all on its own
  occurrence pages — an index or matching defect, not a thin book. Anything between `0` and
  `MIN_EXCERPT_CHARS` means the book does mention it, briefly, and whether it belongs anyway is
  your call. On the first full book run both unwritten terms read `0`, and the cause was a
  regex bug that made `super()` and `__init__()` unmatchable — exactly the class of problem this
  number is meant to expose rather than silently absorb.
- **A term is unwritten when it has no `ok` row**, not when it has a failed one. A term that
  failed in an earlier run and succeeded in this one is in the import CSV, not here.

**Do not feed this file to the importer.** A row with an empty `definition` and a
`needs-review` status would become an empty glossary entry, which is why it is a separate file
rather than extra rows in the CSV. See
[ADR-0006](docs/adr/0006-unwritten-terms-are-reported-beside-the-csv.md).

Terms a run never reached — after it aborts on the spend ceiling or repeated model failure —
have no ledger record and are absent from both files. That run prints `run aborted early` and
exits non-zero, so the gap is announced rather than silent.

Every free-text cell (`term`, `definition`, `x_category`, `x_context`, `x_example`,
`aliases`, `x_related`) is checked for a leading `=`, `+`, `-`, `@`, tab, or carriage
return and prefixed with `'` when found, since a definition sourced from scraped web text
can legitimately start with any of those and Excel/Sheets will otherwise evaluate it as a
formula even inside a quoted CSV field.

## How it works

    load input ──▶ plan ──▶ fetch unique pages ──▶ per-term loop ──┬─▶ write CSV
                    │           (cached)              │            └─▶ write unwritten sidecar
                    └── consults ledger ──────────────┘

Pages are deduplicated before fetching — hundreds of terms usually cluster onto ~100–150
distinct pages. For each term: check the ledger, excerpt the grounding paragraphs, and only
then call a model. A term with no excerpt costs nothing, because the call is skipped
entirely.

**A term with too little page text gets no definition.** If the selected passages total under
`MIN_EXCERPT_CHARS` (100), `glossary-gen` records the term `no_excerpt` and never calls a model.
Measured on a real book, 14 characters of page text still produced a fluent, correct definition of
*modulo* — supplied by the model, not the page, while `x_source_pages` cited the page as its
source. Correctness there was evidence the model knew Python, not that the book taught it. The
floor is what makes "page-grounded" mean something; `x_excerpt_chars` in the CSV reports how much
text actually backed each definition, so a reviewer can see how thin the survivors are.

Such a term is not dropped on the floor. It is reported in the [unwritten
sidecar](#the-unwritten-sidecar) with the grounding it *did* find, so the reviewer decides whether
it belongs in the glossary anyway — a term can be correctly denied a definition and still be one
the book's readers need. On the first full book run that was 2 terms of 212 (`init` and `super`,
both mangled by term extraction rather than by excerpting); at today's floor it would be about 10.

Excerpt selection ranks *definitional-looking* text first — a paragraph following a heading
that matches the term, then one containing "is a"/"is called"/"refers to", then any other
mention — and keeps the top 3 within a ~6,000-character budget. That ranking is why the
definitions reflect how *this book* uses a word rather than the word's general meaning. It
selects from the page's [article](#how-glossary-scan-works), not the whole rendered document.

**A change to excerpting does not reach a book you have already generated.** The ledger treats a
term with an `ok` row as done, and there is no blanket `--force` — one would re-pay for a whole
book. A book generated before excerpting narrowed to the article therefore keeps definitions drawn
from the whole document, and a resumed run will never revisit them. Name the affected terms with
`--regenerate`, or start a fresh `--ledger` and re-pay; both are deliberate acts, which is the
point.

| Module | Responsibility |
|---|---|
| `models.py` | shared dataclasses and the `GlossaryEntry` schema |
| `input.py` | **the only file that knows the index format** |
| `fetch.py` | page retrieval, on-disk cache, URL allowlist, redirect validation, size cap |
| `article.py` | narrowing a fetched page to its article content — shared with `glossary-scan` |
| `excerpt.py` | pure selection of grounding paragraphs — no I/O, no LLM |
| `ledger.py` | **the only place resumability lives** |
| `llm.py` | provider clients and the fallback chain |
| `generate.py` | prompt rendering and one-term generation |
| `csv_out.py` | **the only file that knows the import contract** |
| `cli.py` | argument parsing, cost control, the orchestration loop |

Those three bolded boundaries are the ones to respect when modifying this. If the index
format changes, `input.py` changes and nothing else. If the import contract changes,
`csv_out.py` changes and nothing else.

## Development

    python3 -m pytest          # 397 tests, ~1s
    python3 -m ruff check .
    python3 -m ruff format --check .

**The entire suite runs with no network access and no API key.** Every HTTP interaction goes
through `httpx.MockTransport`; every LLM interaction goes through a fake client. If a change
makes a test need the network, the change is wrong. CI (`.github/workflows/ci.yml`) runs
exactly the three commands above.

Use `python3 -m …` rather than `uv run` — `uv` resolves its own ruff version, which will
report findings this project's pinned configuration does not have.

**To edit the prompt:** copy `glossary_gen/prompts/v1.md` to `v2.md`, edit, and pass
`--prompt-version v2`. The filename stem *is* the version recorded in the ledger, so only
terms lacking a `v2` row regenerate — you re-pay for what the change affects and nothing
else.

**To add a provider:** implement the `LLMClient` protocol in `llm.py` (`name`, `model`,
`complete(prompt) -> LLMResult`), raising `LLMTransportError` for anything retryable and
`LLMStructuredOutputError` for a malformed reply. That distinction matters — the chain falls
through on the former and not the latter, so misclassifying a bad reply as a transport
failure makes it burn a second provider call to produce the same error. Then add the client
to the chain in `cli.build_client` and its per-million-token prices to `prices.json`.

Raise a non-200 through `refusal(self.name, response)` rather than constructing the error
yourself: that is what decides whether the refusal is temporary, and a client that raises a bare
`LLMTransportError` for a `429` gets no backoff at all. Pass `body_hint=` if your provider puts its
retry delay in the error body, as Gemini does. You do not need to implement retrying — `build_client`
wraps every client in `RetryingClient`, which is the only place the policy lives.

Every free-text cell (`term`, `definition`, `x_category`, `x_context`, `x_example`,
`aliases`, `x_related`) is checked for a leading `=`, `+`, `-`, `@`, tab, or carriage
return and prefixed with `'` when found, since a definition sourced from scraped web text
can legitimately start with any of those and Excel/Sheets will otherwise evaluate it as a
formula even inside a quoted CSV field.
