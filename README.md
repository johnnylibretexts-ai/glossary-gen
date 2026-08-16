# glossary-gen

Generate page-grounded glossary definitions for LibreTexts books.

Step 2 of the three-step glossary pipeline: it consumes a book index (terms plus the pages
each term appears on) and emits a CSV of AI-generated definitions for review and import.

> **New here? Go straight to the [Walkthrough](#walkthrough--from-a-fresh-clone-to-a-csv).**
> It takes you from `git clone` to a CSV, and the first real step needs no API key and costs
> nothing. Everything below the walkthrough is reference material.

- Step 1 (build the index) and step 3 (import into Conductor) are out of scope.
- Every row ships as `x_status = needs-review`. Nothing here is reviewed or approved content.

License: [MIT](LICENSE).

## Where this fits

| Step | What it does | Owner |
|---|---|---|
| 1 | Produce the index — keywords/phrases **with the pages each appears on** | `glossary-scan` (this package) |
| 2 | **This tool.** AI reads those pages and writes a definition per term | — |
| 3 | Import the CSV into Conductor, where terms are centralised | Conductor side |

Steps 1 and 3 are deliberately out of scope. This tool consumes an index and emits a file;
it does not build an index and it does not talk to Conductor. The two contracts it does own
are the [input format](#input-format) and the [output columns](#output-columns) — those are
the integration surface, and both are specified below.

## Building an index (glossary-scan)

`glossary-scan` produces step 1's input: point it at a LibreTexts book and it writes an index
in exactly the format documented under [Input format](#input-format), ready to feed straight
into `glossary-gen`.

It walks the book's table of contents, and for each page asks a model one question — *what
terms does this page define?* — requiring a verbatim quote from that page as evidence for
every candidate it proposes. Only candidates whose quote actually checks out against the page
survive; what's left is then scored, so you get a ranked, reviewable list rather than a flat
dump of headings.

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
    a real run reads each page with a model and scores what it finds.

Structural candidates are headings with the obvious OpenStax boilerplate (Summary, Key Terms,
Exercises, …) filtered out — good for confirming the TOC resolves and sizing the book before
spending anything. They are **not** what the scanner produces. A real run reads every page
with a model and scores what it actually finds defined there.

**A real run**, capped for a first smoke test and with a spend ceiling:

    export GLOSSARY_GEN_GEMINI_API_KEY=...
    glossary-scan --book "https://eng.libretexts.org/Bookshelves/Computer_Science/Programming_Languages/Python_Programming_(OpenStax)" \
      --limit 20 --budget-usd 2.00 --out out/index.json --report out/index-report.json

Every term this writes is an **unreviewed candidate** — the same `x_status = needs-review`
posture stated elsewhere in this README, just one step earlier in the pipeline: nothing here
has been read by a human. `--min-score` defaults to `0.0`, so by default *everything* verified
is emitted and a human trims the list before it becomes `glossary-gen`'s input. The scores
themselves do not go into the index: `input.py` is the only file that owns the index schema,
so the scanner doesn't get to add a field to it. They go to the `--report` sidecar instead —
one row per term with its score, source pages, and evidence quote, for whoever does the
trimming.

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

⚠️ **`glossary_gen/prices.json`'s rates are unverified placeholders** — the same file and the
same caveat as the rest of this README: it covers exactly one model, `gemini-3.5-flash`, and
that rate has not been checked against current provider pricing. `--budget-usd` is only as
accurate as those numbers; check your provider's current pricing before relying on it as a
hard ceiling.

A replay-based recall eval harness exists under `tests/eval/` — it scores the
candidate-selection and verification logic against fixed fixtures, offline, with no model
call. It has been measured against a live model on a real book: against Python Programming
(OpenStax), `glossary-scan` found 11 of a 19-term reference index (recall 11/19 = 0.579).
That measurement is pinned as a regression floor of 0.55 in `tests/eval/test_recall_openstax.py`,
so a prompt or scoring change that drops recall below the measured baseline fails CI. Recall
0.579 is measured on **one book against a partial reference set** — read it as a baseline to
regress against, not as a validated recall rate for the tool in general.

A separate, real, billed run — a 20-page bounded scan of the same book — produced 39 verified
terms, and `glossary-gen` grounded all 39 of them (0 without excerpts, 0 page failures). Actual
spend was $0.0135, against a $0.03 pre-flight estimate (`prices.json`'s rates are still the
unverified placeholders noted below — the estimate and the actual both used them).

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

    TOC ──▶ fetch pages ──▶ extract article ──▶ per-page model call ──▶ verify ──▶ score ──▶ merge ──▶ emit
             (cached)        (chrome stripped)         │                  └─ pure, free ─────────────┘
                                                       └── consults ledger ──┘

Only the model call costs money. Verification, scoring, merging and writing are pure functions
over data — which is why the eval harness under `tests/eval/` can replay a recorded scan through
all of them offline, with no key and no spend.

**It reads the article, not the page.** A LibreTexts page as served carries the site's chrome —
the reader's display-settings menu, navigation, footer. On one measured page that was 54% of the
text and 8 of its 11 headings ("Search", "Text Color", "Margin Size", "Recommended articles", …).
The scanner narrows each page to its `.mt-content-container` element before parsing, which is the
platform-wide MindTouch/CXone article wrapper rather than anything book- or publisher-specific. If
a page lacks that container the whole document is used, so an unfamiliar template degrades to
noisier input rather than to nothing. Pages whose article is genuinely empty — front and back
matter like Index, Table of Contents and Licensing — are recorded as scanned with zero terms and
never sent to a model at all.

**The evidence quote is a gate, not a hint.** Every candidate must arrive with a span the model
copied verbatim from the page, and that span is then looked for in the page text — whitespace- and
case-insensitively, since the HTML has already been reflowed, and subject to a 20-character floor
so a two-word fragment can't satisfy it. A candidate whose quote isn't found is discarded outright.
This is the anti-hallucination mechanism: a model that invents a term invents its evidence too, and
invented evidence doesn't appear on the page. It is never softened into a score penalty.

**Scoring corroborates; it doesn't decide.** A surviving candidate starts at the model's own
confidence and gains a fixed bonus for each independent signal from the page: `+0.15` if the term
or one of its aliases appears in a heading, `+0.10` if its evidence matches the same
`is a`/`is called`/`refers to` regex `excerpt.py` uses to rank grounding paragraphs, and `+0.05` if
the term turned up on more than one page. The result is clamped to `1.0`. Reusing `excerpt.py`'s
regex is deliberate: agreement between what the scanner rates highly and what the generator can
later ground a definition in predicts whether a term will survive step 2 at all. The weights are
fixed rather than fitted — nineteen labelled reference terms cannot support fitting four
parameters, so the eval harness reports what they buy instead of tuning them.

**Merging is where the index contract is honoured.** The same term proposed on several pages
collapses into one row: pages and aliases are unioned, the highest-scoring surface form becomes the
`term`, and every other observed spelling is preserved as an alias so nothing seen is lost.
Deduplicating by slug is mandatory, not tidiness — `input.py` rejects an index containing two terms
with the same slug, so an unmerged index would be refused by the very tool it is built for.
Singular and plural are deliberately *not* unified: "Dictionary" and "Dictionaries" slug
differently and both survive, because any string rule aggressive enough to merge them also merges
genuinely distinct terms. Near-duplicates are left for the human doing the review.

| Module | Responsibility |
|---|---|
| `scan/toc.py` | table-of-contents walk and book metadata, via the public `getTOC` endpoint |
| `scan/content.py` | narrowing a fetched page to its article content |
| `scan/propose.py` | the scan prompt and one model call per page |
| `scan/candidates.py` | `verify` / `score_on_page` / `merge` — pure, no I/O, no LLM |
| `scan/emit.py` | writing the index and the score sidecar |
| `scan/evaluate.py` | the offline replay harness behind `tests/eval/` |
| `scan_cli.py` | argument parsing, cost control, the orchestration loop |

The boundaries from [How it works](#how-it-works) still hold, and the scanner is on the far side of
one of them: `input.py` remains the only file that knows the index format. The scanner conforms to
that format rather than extending it, which is why scores live in the `--report` sidecar instead of
in the index. `fetch.py`, `ledger.py` and `llm.py` are shared with `glossary-gen` — the scanner
adds a page-shaped ledger record and a second entry point, not a second copy of the machinery.

### glossary-scan options

| Flag | Default | Meaning |
|---|---|---|
| `--book` (required) | — | book root URL on `*.libretexts.org` |
| `--out` | `out/index.json` | index path, written in the [input format](#input-format) |
| `--report` | `out/index-report.json` | score sidecar path |
| `--cache-dir` | `cache` | page cache dir — same on-disk cache file and format as `glossary-gen`'s `--cache-dir` |
| `--ledger` | `out/scan.jsonl` | ledger path; resume/skip and cost-ceiling state live here |
| `--prompt-version` | `v1` | scan prompt version |
| `--model` | `gemini-3.5-flash` | Gemini model name |
| `--min-score` | `0.0` | omit terms scoring below this (default: emit everything, trim by hand) |
| `--limit` | — | scan at most N pages (smoke runs) |
| `--delay` | `0.3` | seconds between real page fetches |
| `--budget-usd` | — | abort if spend exceeds this |
| `--yes` | off | skip the cost confirmation prompt |
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

The one thing this tool does **not** do is build the index — that is deliberately upstream
of it. You supply a file in the [input format](#input-format): each term plus the page URLs
where that term is discussed.

Practical sources for that list, in rough order of effort:

- A book's back-matter **Index** page, which already pairs keywords with the pages they
  appear on — this is what `examples/openstax-python-index.json` was built from.
- Any existing keyword or co-author index export, converted to the three-column CSV form.
- Hand-written, for a first pass. Twenty terms is enough to judge output quality.

`examples/openstax-python-index.json` has `coverID` set to `REPLACE-ME` — substitute the
real Conductor coverID for your book, or pass `--cover-id` on the command line.

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

To regenerate already-succeeded terms after editing a prompt, copy `prompts/v1.md` to
`prompts/v2.md`, edit it, and pass `--prompt-version v2`. The ledger keeps rows for
**every** prompt version and model you've ever run against it — that's what makes resume
free — but the CSV only ever contains rows from *this* invocation: `status == "ok"` **and**
`prompt_version` **and** `model` matching the current run **and** the term's slug present
in the current input file. So running `v1` then `v2` from the same `--ledger` never mixes
both definitions into one CSV. If you want a side-by-side comparison of two prompt versions
or two models, run each to a different `--out` path.

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
| `--model` | `gemini-3.5-flash` | model name passed to the Gemini client only; the OpenAI-compatible fallback's model comes from `GLOSSARY_GEN_OPENAI_MODEL` |
| `--library`, `--cover-id`, `--book-id` | — | override the input file's `book` block; required (from one source or the other) when the input is CSV, which never carries a book block |
| `--max-terms` | — | process at most N terms (smoke runs); must be a positive integer |
| `--budget-usd` | — | pre-run estimate gate **and** mid-run abort ceiling, see Cost control below |
| `--yes` | off | skip the interactive `proceed? [y/N]` cost-confirmation prompt (needed for any non-interactive/CI invocation) |
| `--dry-run` | off | fetch and excerpt only; calls no model, needs no API key, costs nothing |

### Exit codes

| Code | Meaning |
|---|---|
| `0` | success (including a user declining the confirmation prompt) |
| `2` | input error — bad/missing input file, no provider configured, pre-run cost estimate exceeds `--budget-usd`, or `--budget-usd` was given for a model with no configured price |
| `3` | the run started but aborted early — 5 consecutive provider failures, or actual spend crossed `--budget-usd` mid-run. Check the ledger for what happened; already-succeeded terms are safe and the run is resumable |

## Cost control

Per-token prices live in `glossary_gen/prices.json`, keyed by model name. As of this
writing it covers **exactly one model**, `gemini-3.5-flash`, and **that rate is an unverified
placeholder** — check your provider's current pricing before relying on `--budget-usd`. Any other model — including
the OpenAI-compatible fallback's default `llama3.1` — has no configured price.

- With an unpriced model and no `--budget-usd`, the tool warns once to stderr and
  proceeds; there is no way to estimate or enforce a ceiling it can't price.
- With an unpriced model **and** `--budget-usd`, the tool now **refuses to start**
  (exit code `2`) rather than silently ignoring the ceiling you asked for. Add the
  model's price to `glossary_gen/prices.json`, or drop `--budget-usd`.

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
- **`x_status` is always `needs-review`.** Nothing in this file has been read by a human.
  Do not import it as approved content.
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

Every free-text cell (`term`, `definition`, `x_category`, `x_context`, `x_example`,
`aliases`, `x_related`) is checked for a leading `=`, `+`, `-`, `@`, tab, or carriage
return and prefixed with `'` when found, since a definition sourced from scraped web text
can legitimately start with any of those and Excel/Sheets will otherwise evaluate it as a
formula even inside a quoted CSV field.

## How it works

    load input ──▶ plan ──▶ fetch unique pages ──▶ per-term loop ──▶ write CSV
                    │           (cached)              │
                    └── consults ledger ──────────────┘

Pages are deduplicated before fetching — hundreds of terms usually cluster onto ~100–150
distinct pages. For each term: check the ledger, excerpt the grounding paragraphs, and only
then call a model. A term with no excerpt costs nothing, because the call is skipped
entirely.

Excerpt selection ranks *definitional-looking* text first — a paragraph following a heading
that matches the term, then one containing "is a"/"is called"/"refers to", then any other
mention — and keeps the top 3 within a ~6,000-character budget. That ranking is why the
definitions reflect how *this book* uses a word rather than the word's general meaning.

| Module | Responsibility |
|---|---|
| `models.py` | shared dataclasses and the `GlossaryEntry` schema |
| `input.py` | **the only file that knows the index format** |
| `fetch.py` | page retrieval, on-disk cache, URL allowlist, redirect validation, size cap |
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

    python3 -m pytest          # 274 tests, ~1s
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
