# Migrating to Gemini 3.x — what `GeminiClient` would have to change

Companion to [`2026-08-16-gemini-flash-pricing.md`](2026-08-16-gemini-flash-pricing.md), which
answers what the models *cost*. This one answers what it would take to *call* one.

## Bottom line — CORRECTED 2026-08-16, same day

**Moving to `gemini-3.7-flash` is a `--model` change. It already works.** Verified against the
live API within hours of writing this note:

- `GET /v1beta/models` reports `gemini-3.7-flash` with
  `supportedGenerationMethods: generateContent, countTokens, createCachedContent,
  batchGenerateContent`. `:generateContent` is not withdrawn.
- One real request through the **unmodified** `GeminiClient` — `temperature: 0.2` and
  `responseMimeType: "application/json"` both still sent — returned valid JSON that `parse_entry`
  accepted (47 in / 142 out, about $0.0006).
- A full 136-page book scan then ran on `gemini-3.7-flash` with zero `llm_error` rows.

The original conclusion below was wrong, and the way it was wrong is worth keeping. Every *fact*
in it is accurate: Google really does say to strip `temperature`, and really has stopped
documenting `responseMimeType` and `:generateContent`. The *inference* — that the old shape must
therefore be rejected — did not follow. "The docs recommend a new way" is not "the old way is
refused."

**The lesson: for a live service, the API is a better primary source than its documentation.**
Both things that settled this were queries to the API itself, and the cheaper one was free. The
note's own provenance warning called this: two findings rested on an *absence* in summarised doc
pages, which is the weakest evidence there is.

What survives as true: the Interactions API is the documented direction of travel, so a rewrite
will be worth doing eventually — just not as a precondition for using a 3.x model. Read the rest
of this note as a description of that future work, not of a blocker.

## Provenance, and a warning about it

Every fact below comes from pages under `https://ai.google.dev/gemini-api/docs/`, accessed
**2026-08-16**, and was read through a fetch tool that *summarises* rather than returning raw
markup. The pricing research in the companion note found that summariser unreliable enough to
re-verify its numbers against raw HTML, and found a real discrepancy when it did.

**Treat the quotes below as accurate and the absences as provisional.** "The page does not mention
X" is exactly the kind of claim a summariser gets wrong, and two of the findings here rest on an
absence. Re-fetch raw before acting.

## 1. The generation parameters

From the 3.7 Flash model page
(https://ai.google.dev/gemini-api/docs/latest-model.md.txt, accessed 2026-08-16), quoted verbatim:

> "Change your target model string to `gemini-3.7-flash`."
>
> "Strip `temperature`, `top_p`, and `top_k` from generation configs."
>
> "Replace `thinking_budget` with the string enum `thinking_level`."
>
> "Remove `candidate_count` (unsupported in Gemini 3.x)."
>
> "Standardize multi-turn conversations on server-side `previous_interaction_id`."
>
> "Remove prefilled model turns."

The page does **not** state what happens if a request sends a stripped parameter anyway — ignored,
warned, or rejected. That is unresolved and matters: it is the difference between a migration and
an outage.

**What this repo sends:** `glossary_gen/llm.py:287` —
`"generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"}`. So `temperature`
is one of the four named parameters. `top_p`, `top_k` and `candidate_count` are not sent, and
multi-turn does not apply: every call here is a single-shot prompt.

**A decision hides in this.** `temperature: 0.2` was not decoration — it was chosen to keep
definitions stable across runs. Gemini 3.x apparently does not accept the request. Whoever migrates
has to decide whether reproducibility mattered, not just delete the line.

## 2. `thinking_level`, and why it is a cost question

`thinking_budget` becomes `thinking_level`, a string enum documented as `low` / `medium` / `high`.

The companion pricing note establishes that **thinking tokens bill at the plain output rate** —
every Flash row on the price list is headed "Output price (including thinking tokens)". Output is
the expensive side: $9.00/Mtok on `gemini-3.5-flash`, $3.75 on `gemini-3.7-flash` introductory.

So `thinking_level` is a spend dial wearing a quality label. Left unset, this repo would be paying
for a default nobody chose, and `--budget-usd` would enforce a ceiling against it without anyone
having decided what "medium" costs per definition. Set it explicitly.

## 3. Structured output has a different shape

From the structured-output page (https://ai.google.dev/gemini-api/docs/structured-output, accessed
2026-08-16): the page **does not mention `responseMimeType` at all**. It documents instead:

```
"response_format": {
  "type": "text",
  "mime_type": "application/json",
  "schema": Recipe.model_json_schema()
}
```

with `schema` present in every example, and the examples written against `gemini-3.6-flash` and
`gemini-3.1-pro-preview`.

**This is the load-bearing one.** `parse_entry` (`llm.py`) requires a JSON object back, and the
whole tool's anti-hallucination posture rests on structured replies — the scanner's evidence gate
in particular. If `responseMimeType` silently stops being honoured, replies arrive as prose,
`LLMStructuredOutputError` fires on every attempt, and `generate_entry` burns its full retry budget
on each term before failing it. That is a loud failure rather than a silent one, which is some
comfort — but it is a whole-run failure.

Worth noting the upside: a `schema` field would be a genuine improvement over the current
approach, which asks for JSON by mime type and validates the shape client-side in `parse_entry`.
Sending `GlossaryEntry.model_json_schema()` would move that contract server-side.

## 4. The endpoint itself has moved

This is the finding that changes the size of the job. From the text-generation page
(https://ai.google.dev/gemini-api/docs/text-generation, accessed 2026-08-16), quoted verbatim:

```
curl -X POST "https://generativelanguage.googleapis.com/v1beta/interactions" \
      -H "x-goog-api-key: $GEMINI_API_KEY" \
      -H 'Content-Type: application/json' \
      -d '{"model": "gemini-3.6-flash", "input": "How does AI work?"}'
```

The page describes the Interactions API as generally available and the recommended way to reach
current models, and `:generateContent` **does not appear on it**.

Compare what this repo does:

| | This repo (`llm.py`) | Current docs |
|---|---|---|
| URL | `{base}/models/{model}:generateContent` (`:284`) | `{base}/interactions` |
| Model named in | the URL path | the request body |
| Prompt field | `"contents": [{"parts": [{"text": …}]}]` (`:286`) | `"input": "…"` |
| JSON output | `generationConfig.responseMimeType` (`:287`) | `response_format.mime_type` + `schema` |
| Reply text read from | `payload["candidates"][0]["content"]["parts"][0]["text"]` | not established here |
| Token counts read from | `payload["usageMetadata"]` — `promptTokenCount` / `candidatesTokenCount` (`:305`) | not established here |

Four of six rows differ, and the two unestablished rows are the ones the ledger and every cost
figure depend on. A migration therefore touches request construction, response parsing, **and**
token accounting — the last of which feeds `--budget-usd`, the ledger, and resume.

## What this means for glossary-gen

Sites that would change, all currently on the old shape:

- `llm.py:275` — `base_url` default, `.../v1beta`
- `llm.py:284` — the `:generateContent` URL
- `llm.py:286` — the `contents`/`parts` body
- `llm.py:287` — `temperature` (must go) and `responseMimeType` (probably becomes `response_format`)
- `llm.py:302` — reply text extraction from `candidates[0].content.parts[0].text`
- `llm.py:305` — `usageMetadata` token counts, which feed the ledger and the budget ceiling
- `llm.py:274`, `cli.py:282`, `scan_cli.py:249` — the three `gemini-3.5-flash` defaults

`OpenAICompatClient` is unaffected — it targets OpenAI-compatible endpoints (Ollama, vLLM, LM
Studio), not Google.

Note that `RetryingClient`, `ProviderChain`, `refusal()` and the `LLMRetryableError` classification
are all endpoint-agnostic: they act on HTTP status codes and on the `LLMClient` protocol, not on
Google's body shape. A rewritten Gemini client inherits the backoff behaviour by being wrapped in
`build_client`, with no changes. Likewise `prices.json` needs a rate, not a restructure — except
for the effective-date problem below.

## The pricing wrinkle, restated from the companion note

`gemini-3.7-flash` is $0.75 in / $3.75 out per Mtok **through 2026-12-31**, then $1.50 / $7.50.
`prices.json` has no notion of an effective date, so an entry is right today and half-price in
January — and a rate that is wrong on the cheap side does not disable `--budget-usd`, it silently
raises it.

Two ways out, and the choice should be deliberate: enter the **post-introductory** rate now
(wrong today, but conservative — the ceiling trips early, which costs a resume rather than money),
or give `prices.json` effective dates. The first needs no new machinery.

## Unverified / could not confirm

*Three entries below were resolved the same day by querying the API; struck through and answered
rather than deleted, so the reasoning trail survives.*

- ~~**Whether `:generateContent` still works at all**~~ — **ANSWERED: yes.** Listed as supported on
  `gemini-3.7-flash`, `gemini-3.6-flash`, `gemini-3.5-flash` and `gemini-3.5-flash-lite`, and
  exercised across a full 136-page scan.
- **Whether a retirement date exists for `:generateContent` or for `gemini-3.5-flash`.** Still no
  such date found, and `gemini-3.5-flash` is still listed and fully supported. Absence of a notice
  is not absence of a plan.
- ~~**What happens when a stripped parameter is sent anyway**~~ — **ANSWERED for `temperature`:**
  accepted without error by `gemini-3.7-flash`; the reply was valid JSON. Whether it is *honoured*
  or silently ignored is untested — a determinism check across repeated calls would settle that,
  and it matters, because `temperature: 0.2` was chosen for stable definitions.
- ~~**Whether `responseMimeType` still works**~~ — **ANSWERED: yes**, JSON came back and
  `parse_entry` accepted it. `response_format` with a `schema` remains the better long-term
  approach, since it moves the contract server-side.
- **The Interactions API's response shape** — where reply text lives, and where token counts live.
  Both are required before any cost or ledger code could be written against it.
- **Whether `response_format.schema` is mandatory** or merely shown in every example.
- Everything in §3 and §4 that rests on a *absence* ("the page does not mention X"), for the
  summariser reason given at the top.

## What was actually done

The step suggested here — one real request through the existing `:generateContent` path — was
taken the same day, preceded by the free `GET /v1beta/models` probe. Between them they cost about
$0.0006 and answered the note's central question in the opposite direction to its conclusion; see
the corrected bottom line. `gemini-3.7-flash` then scanned a full 136-page book with no client
changes at all.

**Remaining work, none of it blocking:**

- Migrate to the Interactions API eventually, since that is the documented direction. Its response
  shape still needs establishing before any ledger or cost code can be written against it.
- Check whether `temperature` is *honoured* or merely *tolerated* by 3.x — repeated identical
  calls, compared. It was chosen for reproducibility, so being silently ignored would matter.
- Give `prices.json` effective dates, or update `gemini-3.7-flash` / `gemini-3.6-flash` before
  2027-01-01, when their introductory rate doubles.
