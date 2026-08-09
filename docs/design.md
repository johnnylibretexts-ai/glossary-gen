# Glossary definition generator — design

**Date:** 2026-08-07
**Status:** approved

---

## 1. Where this came from

A request to generate glossary terms for LibreTexts books, starting from the co-author AI prompt
that already produces a keyword index per book.

The work was scoped as a three-step pipeline with separate owners:

| # | Step | Owner |
|---|---|---|
| 1 | Get the existing index — keywords/phrases **with the pages associated to each term** | upstream |
| 2 | AI reviews those pages to generate definitions | **this spec** |
| 3 | Push to the book's glossary with terms, definitions, pages | Conductor side |

The load-bearing architectural instruction: **centralize the terms on Conductor rather than on the
book.**

### What already exists

A **Glossary Manager is already merged upstream** in `libretexts/conductor` (PR #833). Its two
Mongoose models express the centralization decision directly:

- `Glossary` — `term, definition, slug, termID, aliasesIDs` → the centralized term
- `GlossaryUsage` — `usageID, termID, term, definition, aliases, author, bookID, coverID, pages[],
  library, glossaryID` + image/caption/source/license → the per-book binding

The write contract is `AddGlossaryParams` in `server/api/services/glossary-service.ts`.

**There is no HTTP endpoint that accepts a posted CSV.** Bulk-ingest machinery exists
(`GlossaryService.addGlossaryEntries`), but it is a service method rather than a route, its only
caller is the Pressbooks scraper, and it accepts `{term, definition}` only — dropping the page
associations that step 3 needs. Exposing a route and widening that shape is step 3's work, on the
Conductor side.

An **earlier prototype** produced 19 hand-authored entries and a static renderer, writing glossary
pages *into the book* — the architecture this design deliberately moves away from. What survives it
is the entry schema and the demonstration of entry quality. **No AI definition generation was ever
built** before this project, which is precisely what this spec covers.

---

## 2. Goals and non-goals

### Goals

- Turn a list of index terms + their page URLs into grounded, reviewable definitions
- Emit a CSV that a future Conductor importer can consume without renegotiation
- Keep per-run cost predictable and re-runs cheap, since prompt iteration is expected
- Publish a precise **input** contract, so step 1 becomes a concrete ask rather than a vague one

### Non-goals

- Scraping the book index (step 1 — upstream). This tool consumes an index; it does not build one.
- Any live Conductor integration (step 3 — Conductor side). The deliverable is a file.
- Rendering glossary pages. The earlier prototype did this and the architecture moved on.
- Judging definition quality automatically. Every row ships as `needs-review`.

---

## 3. Decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | **CLI emitting a CSV file** | Matches the handoff that was described; runs today with zero dependency on steps 1 or 3; reviewable as an email attachment |
| D2 | **Standalone repo**, not folded into an existing service | Keeps an offline batch tool out of a deployed service that is under a release-qualification process; shareable on its own terms. Cost accepted: no reuse of that service's existing LLM-provider and content-fetching modules |
| D3 | **Core columns + `x_`-prefixed extensions** | Core maps exactly to `AddGlossaryParams`; the prefix makes "ignorable" mechanical. Since step 3 does not exist, we propose the schema rather than conform to one |
| D4 | **Excerpt windows around term occurrences** | Step 2 is defined as "AI reviews *the pages*" — grounding is what makes it this book's glossary. Keeps per-term cost flat instead of scaling with chapter length |
| D5 | **Gemini-first, self-hosted fallback** | Gemini is the convenient default; the provider abstraction plus a working self-hosted fallback keeps open-weight models first-class. A public release must document the API-key requirement. **Verify any model id against the provider's live model list — a plausible-looking name that does not exist fails every call with a 404, and mocked tests cannot catch it.** |
| D6 | **Provenance columns, `needs-review` default** | Consistent with how AI output is labelled elsewhere in this programme: explicitly AI-generated and explicitly unreviewed |
| D7 | **Cached + resumable pipeline** | Prompt iteration is certain. Ledger keyed by `(slug, prompt_version, model)` means a re-run with an unchanged prompt is free and a tweaked prompt re-pays only for affected terms |

Batching multiple terms per LLM call was considered and deferred (YAGNI). It is a real cost lever
once the prompt stabilizes, but it muddies per-term validation and makes one malformed response
damage several terms.

---

## 4. Architecture

Python. Nine modules, one job each.

| module | purpose | I/O |
|---|---|---|
| `input.py` | parse the step-1 file into validated `Term` objects | reads file |
| `fetch.py` | `PageCache.get(url) -> Page`; on-disk cache, size limits, URL allowlist | network + disk |
| `excerpt.py` | `Page` + term/aliases → the paragraphs where it occurs, bounded | **pure** |
| `llm.py` | `LLMClient` protocol; `GeminiClient`, `OpenAICompatClient`, `ProviderChain` | network |
| `generate.py` | one term: excerpt → prompt → call → validate → `GlossaryEntry` | none |
| `ledger.py` | append-only JSONL keyed by `(slug, prompt_version, model)` | disk |
| `csv_out.py` | ledger → CSV in the agreed column order | writes file |
| `prompts/v1.md` | versioned template; the filename **is** `prompt_version` | — |
| `cli.py` | argparse, cost preview, progress, summary | — |

Boundaries that carry weight:

- **`excerpt.py` is pure.** Definition quality is won or lost here, so it must be iterable against
  fixtures in milliseconds rather than by paying a provider to find out.
- **`csv_out.py` is the only module that knows Conductor exists.** When the real importer
  contract is published, one file changes.
- **`generate.py` does no file I/O.** The expensive, hard-to-test stage stays free of path handling
  and is drivable from a fake client.
- **`ledger.py` is the only place resumability lives.** If resume semantics are wrong, the blast
  radius is one module.

`OpenAICompatClient` covers Ollama, vLLM, and LM Studio via the one OpenAI-compatible endpoint they
all speak, so the self-hosted fallback is a single adapter.

---

## 5. Data contracts

### 5.1 Input (the step-1 contract)

Publishing this precisely is deliberate leverage: it converts "get me the index somehow" into a
concrete ask upstream.

```json
{
  "book": { "library": "eng", "coverID": "...", "bookId": "...",
            "title": "Python Programming (OpenStax)", "index_url": "https://..." },
  "terms": [
    { "term": "Recursion", "aliases": ["recursive"],
      "pages": ["https://eng.libretexts.org/.../08%3A_Recursion/8.01%3A_..."] }
  ]
}
```

Required per term: `term`, `pages`. `aliases` optional. A flat CSV with the same three columns is
also accepted, since that is likelier what a co-author export produces.

### 5.2 Ledger (JSONL, append-only)

One record per attempt, keyed by `(slug, prompt_version, model)`:

```json
{"slug":"recursion","term":"Recursion","prompt_version":"v1","model":"gemini-3.5-flash",
 "provider":"gemini","generated_at":"2026-08-07T00:00:00Z","status":"ok",
 "definition":"...","x_category":"...","x_context":"...","x_example":"...","x_related":["..."],
 "pages":["..."],"source_pages":["..."],"excerpt_chars":1840,
 "tokens_in":612,"tokens_out":188,"error":null}
```

`status` ∈ `ok` | `no_excerpt` | `fetch_error` | `llm_error`.

Records are appended immediately per term, so a crash costs one term.

### 5.3 Output CSV

**Rule: anything `AddGlossaryParams` cannot consume gets an `x_` prefix.**

- **Core** — `term`, `definition`, `aliases`, `pages`, `author`, `link`, `source`, `library`,
  `coverID`, `bookId`
- **Extension** — `x_category`, `x_context`, `x_example`, `x_related`
- **Provenance** — `x_status`, `x_model`, `x_provider`, `x_prompt_version`, `x_generated_at`,
  `x_source_pages`, `x_excerpt_chars`

Notes:

- `library` / `coverID` / `bookId` come from CLI flags and repeat on every row. Redundant, but it
  keeps the file self-contained with no sidecar to lose in an email attachment.
- **`addedBy` is deliberately absent.** The importer must set it from the authenticated user. A CSV
  asserting its own authorship is a fail-open identity — a system accepting a supplied identity as
  though it were authenticated. Bind authorship to the authenticated session instead.
- **`pages` and `x_source_pages` are distinct on purpose.** `pages` is where the term is *used*
  (Conductor's field, from the index input). `x_source_pages` is which pages actually yielded an
  excerpt. Divergence indicates either a bad index mapping or a term listed but never discussed —
  both worth seeing during review, and invisible if collapsed.
- **`pages` and `x_source_pages` both carry page URLs, not Conductor page IDs.** URLs are what the
  input provides, and resolving a URL to a `pageID` requires Conductor context this tool does not
  have. Resolution is the importer's job.
- Multi-value cells are pipe-delimited (`a|b|c`); commas are unavoidable in prose. RFC 4180 quoting
  otherwise.
- **Aliases:** input aliases pass through and the model may propose additional ones; the two are
  merged. Every row is `needs-review` regardless, so a proposed alias is reviewed like any other
  field.

---

## 6. Pipeline

```
load input ──▶ plan ──▶ fetch unique pages ──▶ per-term loop ──▶ write CSV
                 │           (cached)              │
                 └── consults ledger ──────────────┘
```

**Page fetching dedupes first.** 685 terms across a book is roughly 100–150 distinct pages, and
terms cluster by chapter. The cache is keyed by URL and populated once.

**Per-term loop:** check ledger → excerpt → if no excerpt, record `no_excerpt` and **skip the LLM
call entirely** → else prompt, call, validate against the Pydantic schema, append to ledger.

### Excerpting rules

- Word-boundary, case-insensitive match on term and aliases (`list` must not match `listen`)
- **Rank definitional-looking occurrences first** — term in a heading, or in a paragraph containing
  "is a" / "is called" / "refers to". A term's first prose mention is usually where the book defines
  it; a later mention usually is not
- Keep the **top 3 occurrences after ranking** (not the first 3 by position), each as its containing
  paragraph; hard ceiling ~6,000 chars per term
- Collapse near-duplicate paragraphs before they burn tokens twice

### `--dry-run`

Excerpt everything, call nothing, report coverage: terms with excerpts, terms without, pages that
404'd. Zero cost, no API key required.

This is the audit of **step-1 index quality before any spend**. If 200 of 685 terms have no excerpt
on their linked pages, that is a step-1 defect, discoverable in a minute rather than in a CSV that
has already been paid for. Build this first.

---

## 7. Failure handling

| failure | behavior |
|---|---|
| page fetch fails | terms depending only on that page → `fetch_error`; run continues |
| term absent from its pages | `no_excerpt`, no LLM call, no cost |
| malformed structured output | 2 bounded retries, then `llm_error` |
| Gemini 429 / quota / 5xx | fall through the chain to the self-hosted provider |
| all providers failing repeatedly | abort the run after **5 consecutive** terms fail on every provider |

The last row is the financially important one: a misconfigured key must not produce 685
individually-failing terms.

## 8. Cost control

- `--budget-usd` — estimate before starting, refuse to begin if the plan exceeds it, abort mid-run
  if actuals cross it. Per-token prices are **configuration, not hardcoded constants**: provider
  pricing changes, and a stale baked-in rate produces a confidently wrong estimate. An unpriced
  model disables budget enforcement and says so, rather than silently estimating zero.
- `--max-terms` — smoke-run against 20 terms before committing to 685
- Concurrency cap with backoff; Gemini quota is per-minute (cf. the TTS work, where a preview-tier
  rate cap forced a provider switch)

Re-runs: bump `prompts/v1.md` → `v2.md` and only terms lacking a `v2` record regenerate. Fixing a
prompt after reviewing 50 entries re-pays for 50, not 685.

---

## 9. Testing

**Governing constraint: the whole pipeline runs in CI with no network and no API key.**

| module | tests |
|---|---|
| `excerpt.py` | term at paragraph start/end, alias hit, case variance, word boundary (`list` ≠ `listen`), term absent, heading ranked above prose, duplicate collapse, char-ceiling truncation |
| `csv_out.py` | golden file: column order, `x_` prefixing, pipe-delimited multi-values, quoting a definition containing commas and quotes |
| `ledger.py` | identical key skips, bumped `prompt_version` regenerates, bumped model regenerates, half-written file recovers |
| `fetch.py` | mocked transport: cache hit/miss, size cap, non-LibreTexts URL rejected, retry on 5xx |
| `llm.py` | fake client: chain falls through on 429, malformed JSON retried then failed, schema violation → `llm_error` |
| end-to-end | fixture pages + fake LLM → CSV, one row per status class |

**Tests deliberately do not assert definition wording.** LLM output is nondeterministic; a
string-matching test either pins to one provider's phrasing or proves nothing. Structure,
provenance, and status handling are machine-checkable. Definition *quality* is human judgment,
supported by `--dry-run` coverage and `x_status = needs-review`. This mirrors the E2E lesson in
`AGENTS.md`: verify through structure and events, not visible text.

**The e2e fixture input is the existing 19 entries** — their real terms and chapter URLs, giving a
regression corpus that was already reviewed once, and a diff target when prompts change.

**CI from the first commit.** The 2026-08-03 session's lesson was that
`tests/test_deployment_contract.py` had only ever run locally and failed the moment a gate finally
met it: *a test that has only ever run locally has not been tested.*

---

## 10. Open questions

1. **Repo licence and visibility.** If this ships publicly under MIT, the
   README must state plainly that the default path requires a Google API key (D5), because a
   LibreTexts-facing tool that hard-requires a proprietary API is in tension with the open-source
   rule. The self-hosted fallback is the mitigation and should be documented as a first-class path.
2. **Whether the eventual upstream index format matches §5.1.** It will not exactly. The input parser
   should be the thing that adapts; nothing downstream should learn his format.
3. **`coverID` / `bookId` values** for the OpenStax Python book are not yet known and must come from
   Conductor.

## 11. References

- Original project brief, 2026-07-24
- `libretexts/conductor` PR #833 — `server/api/services/glossary-service.ts`,
  `server/models/glossary.ts`, `server/models/glossaryusage.ts` (read via `git show origin/master:`)
- The earlier hand-authored glossary prototype (superseded; see §1)
- An existing internal service's LLM provider-chain — design reference only, not imported (see D2)

---

> **Storage note (resolved 2026-08-08).** This file originally lived only in the workspace root
> `docs/`, which is not a git repository, and was therefore uncommitted and unbacked. It has since
> been copied into `glossary-gen/docs/design.md` and committed here — per `CONTEXT.md`, anything
> durable belongs in a component repo. The workspace-root copy is the historical record of where
> the spec was authored; this copy is the durable one.
