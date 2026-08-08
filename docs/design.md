# Glossary definition generator — design

**Date:** 2026-08-07
**Status:** approved, not yet implemented
**Repo (to be created):** `johnnylibretexts/glossary-gen`

---

## 1. Where this came from

The original project brief,
2026-07-24. the project sponsor wants AI-generated glossary terms for LibreTexts books, starting from the
co-author AI prompt that already generates a keyword index per book.

In the brief (cc the Conductor developer, the platform developer) he specified a three-step
pipeline and assigned owners:

| # | Step | Owner |
|---|---|---|
| 1 | Get the existing index — keywords/phrases **with the pages associated to each term** | the platform developer |
| 2 | AI reviews those pages to generate definitions | **Johnny — this spec** |
| 3 | Push to the book's glossary with terms, definitions, pages | the Conductor developer |

The load-bearing architectural instruction in that message: **"centralize the terms on the Conductor
instead of on the book."**

### What already exists

**the Conductor developer's Glossary Manager is already merged upstream** — `libretexts/conductor` PR #833,
merged 2026-06-29, 24 files / 3,621 insertions. A follow-up commit with `bb759f1d`, restricting it to
internal access during beta. It is *not* in the local `conductor/` checkout (local HEAD `bf8d8396`,
2026-07-02, forked before the merge); read it with `git show origin/master:<path>`.

Its two Mongoose models are the brief's instruction expressed in code:

- `Glossary` — `term, definition, slug, termID, aliasesIDs` → the centralized term
- `GlossaryUsage` — `usageID, termID, term, definition, aliases, author, bookID, coverID, pages[],
  library, glossaryID` + image/caption/source/license → the per-book binding

The write contract is `AddGlossaryParams` in `server/api/services/glossary-service.ts`.

**There is no CSV import endpoint.** The commit title says "import/export features", but the import
is `addExternalGlossaryToGlossaryUsage` — *"read from cxone glossary and add to glossary usage"*,
i.e. ingesting an existing CXone glossary page. the project sponsor predicted this gap in his first message:
The brief anticipated this gap: an endpoint would be needed to accept an AI-generated CSV, which the Conductor side can
build into the glossary system. That endpoint is step 3 and belongs to the Conductor developer.

**The 2026-07-24 prototype** (`mirror/`, commits `836339b`…`4484531`) produced 19 hand-authored
entries and a static renderer at
`https://library.libretexts.dev/Books/Python_Programming_OpenStax/Glossary/`. It writes pages *into
the book*, which is the architecture the project sponsor steered away from four hours after it was shared. What
survives it is the entry schema and the demonstration of entry quality. **No AI definition
generation was ever built** — that is precisely what this spec covers.

---

## 2. Goals and non-goals

### Goals

- Turn a list of index terms + their page URLs into grounded, reviewable definitions
- Emit a CSV that a future Conductor importer can consume without renegotiation
- Keep per-run cost predictable and re-runs cheap, since prompt iteration is expected
- Publish a precise **input** contract, so step 1 becomes a concrete ask rather than a vague one

### Non-goals

- Scraping the book index (step 1 — upstream's). This tool consumes an index; it does not build one.
- Any live Conductor integration (step 3 — the Conductor developer's). The deliverable is a file.
- Rendering glossary pages. The `mirror/` prototype did this and the architecture moved on.
- Judging definition quality automatically. Every row ships as `needs-review`.

---

## 3. Decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | **CLI emitting a CSV file** | Matches the handoff the project sponsor described; runs today with zero dependency on the Conductor developer; reviewable as an email attachment |
| D2 | **Standalone repo**, not inside `assessment-ai` | Keeps an offline tool out of a deployed service under a qualification regime; shareable with the project sponsor/the Conductor developer, same precedent as `adapt-jingo`. Cost accepted: no reuse of `assessment-ai/app/llm.py` or `content.py` |
| D3 | **Core columns + `x_`-prefixed extensions** | Core maps exactly to `AddGlossaryParams`; the prefix makes "ignorable" mechanical. Since step 3 does not exist, we propose the schema rather than conform to one |
| D4 | **Excerpt windows around term occurrences** | the brief's step 2 is "AI reviews *the pages*" — grounding is what makes it this book's glossary. Keeps per-term cost flat instead of scaling with chapter length |
| D5 | **Gemini-first, self-hosted fallback** | Matches what is running today (Gemini Flash 3.6, personal account). The provider abstraction plus a working fallback satisfies the open-source rule; a public release must document the key requirement |
| D6 | **Provenance columns, `needs-review` default** | Consistent with how this project already labels AI output (BUILD-08's 380 drafts are explicitly AI-generated and unreviewed) |
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
- **`csv_out.py` is the only module that knows Conductor exists.** When the Conductor developer publishes the real
  importer contract, one file changes.
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
concrete ask for the platform developer.

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
{"slug":"recursion","term":"Recursion","prompt_version":"v1","model":"gemini-flash-3.6",
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
  asserting its own authorship is the fail-open shape that
  `assessment-ai/docs/adr/0001-forward-auth-identity-binding.md` exists to prevent.
- **`pages` and `x_source_pages` are distinct on purpose.** `pages` is where the term is *used*
  (Conductor's field, from upstream's input). `x_source_pages` is which pages actually yielded an
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

1. **Repo licence and visibility.** `adapt-jingo` is public MIT. If `glossary-gen` follows, the
   README must state plainly that the default path requires a Google API key (D5), because a
   LibreTexts-facing tool that hard-requires a proprietary API is in tension with the open-source
   rule. The self-hosted fallback is the mitigation and should be documented as a first-class path.
2. **Whether upstream's eventual index format matches §5.1.** It will not exactly. The input parser
   should be the thing that adapts; nothing downstream should learn his format.
3. **`coverID` / `bookId` values** for the OpenStax Python book are not yet known and must come from
   Conductor.

## 11. References

- Email thread, 2026-07-24 (the project brief)
- `libretexts/conductor` PR #833 — `server/api/services/glossary-service.ts`,
  `server/models/glossary.ts`, `server/models/glossaryusage.ts` (read via `git show origin/master:`)
- `mirror/` prototype: `glossary_demo.py`, `glossary_openstax_python.json`, commits
  `836339b`…`4484531`
- `assessment-ai/app/llm.py` — provider-chain design reference (not imported; see D2)
- `assessment-ai/docs/adr/0001-forward-auth-identity-binding.md` — the `addedBy` rationale

---

> **Storage note (resolved 2026-08-08).** This file originally lived only in the workspace root
> `docs/`, which is not a git repository, and was therefore uncommitted and unbacked. It has since
> been copied into `glossary-gen/docs/design.md` and committed here — per `CONTEXT.md`, anything
> durable belongs in a component repo. The workspace-root copy is the historical record of where
> the spec was authored; this copy is the durable one.
