# glossary-gen

Generate page-grounded glossary definitions for LibreTexts books.

Step 2 of the three-step glossary pipeline: it consumes a book index (terms plus the pages
each term appears on) and emits a CSV of AI-generated definitions for review and import.

- Step 1 (build the index) and step 3 (import into Conductor) are out of scope.
- Every row ships as `x_status = needs-review`. Nothing here is reviewed or approved content.

License: [MIT](LICENSE).

## Providers

Gemini is the default and requires `GLOSSARY_GEN_GEMINI_API_KEY`. A self-hosted
OpenAI-compatible endpoint (Ollama, vLLM, LM Studio) is a first-class fallback via
`GLOSSARY_GEN_OPENAI_BASE_URL`, and can be used alone.

## Quick start

    pip install -e ".[dev]"
    glossary-gen --input index.json --dry-run

`--dry-run` fetches pages and reports excerpt coverage without calling any model. It needs
no API key and costs nothing. Run it first.

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
both definitions into one CSV, and pointing `--ledger` at a file that already holds another
book's terms never leaks that book's rows into this one. If you want a side-by-side
comparison of two prompt versions or two models, run each to a different `--out` path.

### Options

| Flag | Default | Meaning |
|---|---|---|
| `--input` (required) | — | step-1 index file (`.json` or `.csv`) |
| `--out` | `out/glossary.csv` | output CSV path |
| `--cache-dir` | `cache` | on-disk HTML page cache; reused across runs so pages already fetched are never re-fetched |
| `--ledger` | `out/run.jsonl` | append-only run log; the resume/skip and cost-ceiling state live here. **Point every book at its own `--ledger` path** — see the prompt-iteration note above for why a shared/default path across books is safe for the CSV but wastes ledger disk space and history clarity |
| `--prompt-version` | `v1` | filename stem under `prompts/`, e.g. `v2` for `prompts/v2.md` |
| `--model` | `gemini-flash-3.6` | model name passed to the Gemini client only; the OpenAI-compatible fallback's model comes from `GLOSSARY_GEN_OPENAI_MODEL` |
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
writing it covers **exactly one model**, `gemini-flash-3.6`. Any other model — including
the OpenAI-compatible fallback's default `llama3.1` — has no configured price.

- With an unpriced model and no `--budget-usd`, the tool warns once to stderr and
  proceeds; there is no way to estimate or enforce a ceiling it can't price.
- With an unpriced model **and** `--budget-usd`, the tool now **refuses to start**
  (exit code `2`) rather than silently ignoring the ceiling you asked for. Add the
  model's price to `glossary_gen/prices.json`, or drop `--budget-usd`.

`--budget-usd` is a ceiling on **total spend recorded in the ledger**, not per-invocation:
resuming a run seeds the running token counters from every `tokens_in`/`tokens_out`
already in the ledger, so a resumed run cannot blow through the ceiling once per resume.

**The ceiling is a floor, not an exact meter.** It only counts tokens from LLM calls that
returned a usable result and were billed by the provider *and* recorded in the ledger.
A call that the provider billed but that then failed Pydantic schema validation
(`llm_error`) is not currently attributable to a token count and is therefore invisible to
`--budget-usd` — actual provider spend can run slightly ahead of what this tool reports or
enforces.

## Reliability notes

- **No backoff between retries.** Page fetches (`fetch.py`) and structured-output retries
  (`generate.py`) both retry a bounded number of times with no delay between attempts.
  This is fine against LibreTexts pages, but it matters against a quota-limited provider:
  a provider returning `429` in a tight loop gets hit again immediately, which can make a
  rate limit worse rather than better. If you're running against a provider with a strict
  per-minute quota, keep `--max-terms` small and watch for repeated `llm_error` rows.

## Output columns

Core columns map to Conductor's `AddGlossaryParams`. Everything prefixed `x_` is
extension or provenance data an importer may ignore. `addedBy` is never emitted — the
importer must set it from the authenticated user.

`pages` is where the term is used; `x_source_pages` is which pages actually grounded the
definition. When they differ, the index mapping or the term itself is worth a look.

Every free-text cell (`term`, `definition`, `x_category`, `x_context`, `x_example`,
`aliases`, `x_related`) is checked for a leading `=`, `+`, `-`, `@`, tab, or carriage
return and prefixed with `'` when found, since a definition sourced from scraped web text
can legitimately start with any of those and Excel/Sheets will otherwise evaluate it as a
formula even inside a quoted CSV field.
