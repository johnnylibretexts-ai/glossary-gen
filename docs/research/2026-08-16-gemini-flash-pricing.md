# Gemini Flash pricing — verified against primary sources

## Bottom line

"Gemini 3.7 Flash" is real — exact API model id `gemini-3.7-flash`, currently Google's newest
Stable Flash model — so the question wasn't based on a fictional name, but `gemini-3.5-flash`
(the model this repo actually calls) is a different, older Stable sibling that Google's own docs
now label "legacy." The placeholder rate in `prices.json` (input 0.30 / output 2.50 USD per
1M tokens) is **wrong for `gemini-3.5-flash`** — the real Standard-tier rate is **1.50 / 9.00**
— and those placeholder numbers instead exactly match a *different* model, `gemini-3.5-flash-lite`.
A single flat input/output pair is structurally adequate for context-length (Flash models are not
tiered by prompt size, unlike Pro models) and for "thinking" tokens (billed at the plain output
rate, not separately), but it silently ignores three real pricing axes that do apply to Flash
models today — audio input costs more than text/image/video on several Flash models, a
Standard/Batch/Flex/Priority service-tier multiplier exists, and discounted context-caching has
its own rate plus an hourly storage fee — so `actual_cost`'s flat model is a reasonable
approximation only as long as the run never uses audio input, Batch/Flex/Priority calls, or
context caching, none of which `run.py` appears to do today (source: `llm.py:275` uses
`generativelanguage.googleapis.com/v1beta`, the plain synchronous Developer API endpoint).

## Model table (Gemini Developer API, Standard tier, paid, per 1,000,000 tokens, USD)

All figures from https://ai.google.dev/gemini-api/docs/pricing, accessed 2026-08-16, raw HTML
fetched directly (not summarized) and cross-checked line-by-line. "Standard" is the tier that
applies to a plain synchronous `generateContent` call — the kind this repo makes; Batch/Flex/
Priority require an explicit opt-in this repo does not make.

| Model | API model id | Input $/Mtok | Output $/Mtok (incl. thinking) | Tier conditions |
|---|---|---|---|---|
| Gemini 3.7 Flash | `gemini-3.7-flash` | $0.75 (thru 2026‑12‑31), **$1.50 from 2027‑01‑01** | $3.75 → $7.50 | No context-length tiering. Input unified across modalities. Scheduled price increase (see note). |
| Gemini 3.6 Flash | `gemini-3.6-flash` | $0.75 → $1.50 (same schedule) | $3.75 → $7.50 | Same structure as 3.7 Flash. |
| **Gemini 3.5 Flash** (repo default) | `gemini-3.5-flash` | **$1.50** (flat, no scheduled change) | **$9.00** (flat) | Unified across text/image/video/audio input. No context-length tiering. |
| Gemini 3.5 Flash-Lite | `gemini-3.5-flash-lite` | $0.30 (unified: text/image/video/audio) | $2.50 | This is where the repo's placeholder numbers actually belong. |
| Gemini 3.1 Flash-Lite | `gemini-3.1-flash-lite` | $0.25 (text/image/video), $0.50 (audio) | $1.50 | Audio input priced 2x text. |
| Gemini 3 Flash Preview | `gemini-3-flash-preview` | $0.50 (text/image/video), $1.00 (audio) | $3.00 | Preview status. |
| Gemini 2.5 Flash | `gemini-2.5-flash` | $0.30 (text/image/video), $1.00 (audio) | $2.50 | Older generation, still GA. |
| Gemini 2.5 Flash-Lite | `gemini-2.5-flash-lite` | $0.10 (text/image/video), $0.30 (audio) | $0.40 | Older generation, still GA. |
| Gemini 2.0 Flash | `gemini-2.0-flash` | — | — | **Deprecated, shut down 2026‑06‑01** — no longer callable. |
| Gemini 2.0 Flash-Lite | `gemini-2.0-flash-lite` | — | — | **Deprecated, shut down 2026‑06‑01** — no longer callable. |

Audio/video/image-specialty models that also carry the "Flash" name but are not general-purpose
text generation models (out of scope for this repo's usage, listed for completeness per the
research brief):

| Model | API model id | Input $/Mtok | Output $/Mtok | Notes |
|---|---|---|---|---|
| Gemini 3.1 Flash Live Preview | `gemini-3.1-flash-live-preview` | $0.75 (text), $3.00 or $0.005/min (audio), $1.00 or $0.002/min (image/video) | $4.50 (text), $12.00 or $0.018/min (audio) | Real-time audio-to-audio dialogue. |
| Gemini 3.1 Flash TTS Preview | `gemini-3.1-flash-tts-preview` | $1.00 (text) | $20.00 (audio) | Text-to-speech only. |
| Gemini Omni Flash (Preview) | `gemini-omni-flash-preview` | $1.50 (all modalities) | $9.00 (text), $17.50 (video, ≈$0.10/sec of 720p) | Video generation model. No free tier. |
| Gemini 3.1 Flash Image ("Nano Banana 2") | `gemini-3.1-flash-image` | $0.50 (text/image) | $3.00 (text/thinking), $60.00/Mtok for image output (~$0.067/1K image) | Image generation, not text. |
| Gemini 3.1 Flash Lite Image | `gemini-3.1-flash-lite-image` | $0.25 (text/image/video) | $1.50 (text/thinking), $30.00/Mtok for image output | Image generation, not text. |

Source for the whole table: https://ai.google.dev/gemini-api/docs/pricing, accessed 2026-08-16.
Model ids and stable/preview/deprecated status cross-checked against
https://ai.google.dev/gemini-api/docs/models, accessed 2026-08-16.

## Answers to the five questions

### 1. Does "Gemini 3.7 Flash" exist?

Yes. `https://ai.google.dev/gemini-api/docs/models` (accessed 2026-08-16) lists it under the
"Gemini 3" family as **"New Stable"**, described as "Our latest and most capable Flash model,
built for complex coding, agentic workflows, and reliable multi-step execution," with API model
id `gemini-3.7-flash`. It sits alongside two other current Flash siblings: Gemini 3.6 Flash
("Stable," "previous-generation Flash model") and **Gemini 3.5 Flash** ("Stable," but described
verbatim as *"Our legacy Flash model, providing baseline speed and foundational performance for
routine, high-throughput workloads"* — i.e. Google's own docs now call the model this repo uses
"legacy"), plus Gemini 3.5 Flash-Lite and Gemini 3.1 Flash-Lite (both "Stable"). One more, Gemini
3 Flash (`gemini-3-flash-preview`), is Preview, not Stable. All of the above quotes and ids are
verbatim from the raw page HTML.

### 2. Current paid-tier price for `gemini-3.5-flash`

**$1.50 per 1M input tokens, $9.00 per 1M output tokens (Standard tier)** — confirmed on both
`ai.google.dev/gemini-api/docs/pricing` and, independently, on
`https://cloud.google.com/vertex-ai/generative-ai/pricing` (which redirected to
`https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing`; accessed
2026-08-16), where the "Global" region price for Gemini 3.5 Flash is listed as $1.50 input /
$9.00 output per 1M tokens, with a 10% "Non-global" surcharge ($1.65 / $9.90). **The placeholder
values in `prices.json` (0.30 / 2.50) are incorrect for this model** — they understate input cost
by 5x and output cost by 3.6x. Coincidentally, 0.30 / 2.50 is the *exact* Standard-tier rate for
`gemini-3.5-flash-lite`, which strongly suggests the placeholder was copied from the wrong model
id (or from an even older `gemini-2.5-flash`-generation number, which is also 0.30 input, though
2.5 Flash's output is 2.50 while 3.5 Flash-Lite's is also 2.50 — either source is plausible, but
neither is `gemini-3.5-flash`).

### 3. Every other currently-offered Flash model

Covered in the two tables above. In summary, the currently-offered Flash-tier *text-generation*
models are: `gemini-3.7-flash`, `gemini-3.6-flash`, `gemini-3.5-flash`, `gemini-3.5-flash-lite`,
`gemini-3.1-flash-lite`, `gemini-3-flash-preview` (Preview), `gemini-2.5-flash`, and
`gemini-2.5-flash-lite`. `gemini-2.0-flash` and `gemini-2.0-flash-lite` are still listed on the
pricing page but carry an explicit "deprecated and has been shut down June 1, 2026" warning —
already unusable as of the 2026-08-16 access date, so not worth adding to `prices.json`. Several
more "Flash"-branded models exist for audio (`gemini-3.1-flash-live-preview`,
`gemini-3.1-flash-tts-preview`, `gemini-3.5-live-translate-preview`), video
(`gemini-omni-flash-preview`), and image generation (`gemini-3.1-flash-image`,
`gemini-3.1-flash-lite-image`) — out of scope for a text-only glossary-definition workload but
listed above for completeness.

### 4. Is the pricing flat or tiered?

**Tiered, on three axes that matter and one that doesn't for Flash models specifically:**

- **Context-length threshold: does NOT apply to any Flash model.** The `> 200k tokens` tiered
  rate that appears repeatedly on the pricing page belongs only to Pro-tier models (verified by
  reading the surrounding page text: it appears under "Gemini 3.1 Pro Preview" and "Gemini 2.5
  Pro," never under any Flash section). Every Flash model's Standard-tier row is a single number
  (or a single number per modality) regardless of prompt length. So this one risk from the task
  brief does not apply — a flat rate is correct on this axis for Flash models.
- **Thinking/reasoning tokens: NOT priced separately.** Every Flash pricing row is explicitly
  labeled "Output price (including thinking tokens)" — thinking tokens are billed at the same
  rate as ordinary output tokens, not a separate rate. A flat output rate is correct here too.
- **Audio/image/video input vs. text input: DOES apply, on several models.** `gemini-3.5-flash`,
  `gemini-3.5-flash-lite`, and `gemini-3.1-flash-live-preview` price all input modalities
  uniformly, but `gemini-2.5-flash`, `gemini-2.5-flash-lite`, `gemini-3.1-flash-lite`, and
  `gemini-3-flash-preview` all charge a materially higher rate for audio input than for
  text/image/video input (e.g. 2.5 Flash: $0.30 text/image/video vs. $1.00 audio — 3.3x). A
  single flat `input_per_mtok` cannot represent this for those models if audio input is ever
  used.
- **Cached-input discount: DOES exist, and is structurally different from a normal input
  rate.** Every Flash model has a separate, discounted "Context caching price" (e.g. $0.15/Mtok
  for 3.5 Flash vs. its $1.50 normal input rate) **plus** a separate per-hour storage fee (e.g.
  $1.00 per 1M tokens per hour). `actual_cost()` has no notion of cached tokens or storage-time
  charges at all.
- **Batch-mode discount: DOES exist and is large** — Batch-tier Standard input/output is
  consistently ≈50% of the Standard (synchronous) rate across every model checked (e.g. 3.5
  Flash: $0.75/$4.50 batch vs. $1.50/$9.00 standard). There is also a **Priority** tier that costs
  *more* than Standard (≈1.8x on 3.5 Flash: $2.70/$16.20), and a **Flex** tier priced the same as
  Batch. `run.py`'s `actual_cost()` has no tier parameter at all — it implicitly assumes Standard,
  which happens to be correct for what this repo calls today (plain `generateContent` via
  `generativelanguage.googleapis.com/v1beta`, confirmed by reading `glossary_gen/llm.py:275`),
  but the price table has no way to express the difference if that ever changes.
- **One more axis found that the task didn't ask about:** `gemini-3.7-flash` and
  `gemini-3.6-flash` (but *not* `gemini-3.5-flash`) carry a **scheduled price increase**: the
  quoted rate is explicitly "$0.75 through December 31, 2026. $1.50 starting January 1, 2027" (and
  correspondingly for output/caching/batch/priority). A flat number for either of those two models
  would go stale on a fixed calendar date even if nothing else about the repo changes.

**Conclusion for the repo's cost model:** `actual_cost()`'s single flat input/output pair per
model is *not* a general solution — it happens to be adequate for `gemini-3.5-flash` specifically
under the repo's current usage (text-only input, Standard/synchronous calls, no caching), but it
cannot correctly price audio input, Batch/Flex/Priority calls, cached input, or (for 3.6/3.7 Flash
specifically) post-2027 rates. This is a structural gap in the price model, not a data-entry
question, if the repo ever changes model or call pattern.

### 5. Free tier vs. paid tier

A free tier exists for every Flash model checked — the pricing page's "Free Tier" column reads
"Free of charge" across the board (Standard and, where applicable, Batch/Priority). It is a
*separate, capped-rate-limit* tier, not what a paid API key using `--budget-usd` is billed at;
the "Paid Tier, per 1M tokens in USD" column is the one relevant to this repo's cost ceiling, and
that's the column all figures above come from. (Source:
https://ai.google.dev/gemini-api/docs/pricing, accessed 2026-08-16 — every model section repeats
this Free Tier / Paid Tier split verbatim.)

## What this means for `prices.json`

The current entry is wrong for the model it claims to price. If glossary-gen keeps defaulting to
`gemini-3.5-flash` with Standard-tier synchronous calls (as `glossary_gen/llm.py:275` currently
does — no audio input, no Batch/Flex/Priority, no explicit context caching), the correct flat
entry is:

```json
{
  "_comment": "USD per 1,000,000 tokens, keyed by model name. Verified against https://ai.google.dev/gemini-api/docs/pricing (accessed 2026-08-16), Standard tier, paid tier, text/image/video input rate. Does NOT account for audio input (not applicable to gemini-3.5-flash — its input rate is unified across modalities), Batch/Flex/Priority service tiers, or context caching, none of which this repo currently uses.",
  "gemini-3.5-flash": {
    "input_per_mtok": 1.50,
    "output_per_mtok": 9.00
  }
}
```

If the repo intends to move to a newer/cheaper Flash model instead of fixing the price for
`gemini-3.5-flash`, the two additional entries most worth adding (also Standard-tier, paid,
text/image/video input) are:

```json
  "gemini-3.5-flash-lite": { "input_per_mtok": 0.30, "output_per_mtok": 2.50 },
  "gemini-2.5-flash": { "input_per_mtok": 0.30, "output_per_mtok": 2.50 }
```

Watch the trap in that second line: `gemini-2.5-flash`'s *output* rate is $2.50 — it is easy to
instead reach for the $1.00 figure that appears right next to it on the pricing page, but that
$1.00 is 2.5 Flash's **audio input** rate, not its output rate. Either way, both of these
single-pair entries are unpriced for audio input (2.5 Flash: $1.00/Mtok; 3.5 Flash-Lite: same
$0.30 as text, since its audio input happens to be unified with the rest) — the schema has no
field for a modality-specific rate, so an audio-input run against either model would be priced
too low by this table.

## Unverified / could not confirm

- **Whether `run.py` or `llm.py` ever sends audio, image, or video input, or uses context
  caching, Batch mode, or a Priority/Flex header.** I read `glossary_gen/run.py`'s `actual_cost`
  function and confirmed `glossary_gen/llm.py:275` targets the plain
  `generativelanguage.googleapis.com/v1beta` endpoint, but I did not do a full audit of every
  call site in `glossary_gen/llm.py` to rule out caching or alternate content types. This matters
  because if any of those are used, the flat-rate gap described in Q4 becomes a live pricing bug,
  not just a theoretical one.
- **Exact rate-limit numbers for the free tier** (e.g. RPD/RPM caps per model) — the pricing page
  states "Free of charge" but rate limits live on a separate page
  (`ai.google.dev/gemini-api/docs/rate-limits`, referenced in the sidebar nav but not fetched for
  this note) that I did not verify.
- **Whether `gemini-3.5-flash`'s Standard-tier rate has any of its own future scheduled change.**
  Unlike 3.6/3.7 Flash, its pricing page row shows a single number with no "through/starting"
  language, which I read as "flat, no scheduled change" — but I did not find an explicit
  statement ruling out a future change, only the absence of one on the current page.
- **Live/TTS/video/image "Flash" model figures** (the second table above) were read from the same
  raw HTML dump as everything else, but I gave them one pass rather than the line-by-line
  cross-check I did for the text-generation models, since they're out of scope for this
  text-only glossary workload.

## Sources

- https://ai.google.dev/gemini-api/docs/pricing — accessed 2026-08-16. Primary source for all
  Standard/Batch/Flex/Priority pricing figures, free-tier statements, context-caching prices, and
  the `> 200k tokens` Pro-only tiering. Fetched as raw HTML via `curl` and read directly (not
  via an intermediate summarizer) to rule out fabricated figures.
- https://ai.google.dev/gemini-api/docs/models — accessed 2026-08-16. Primary source for model
  ids, Stable/Preview/deprecated status, and the "legacy" description of `gemini-3.5-flash`.
  Fetched as raw HTML via `curl`.
- https://cloud.google.com/vertex-ai/generative-ai/pricing — accessed 2026-08-16. Redirected to
  `https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing`. Used only to
  cross-check `gemini-3.5-flash`'s $1.50/$9.00 Standard-tier figure independently (Vertex "Global"
  region matches exactly; "Non-global" carries a 10% surcharge). Not used as the primary source
  for this repo, since `glossary_gen/llm.py:275` calls the Developer API
  (`generativelanguage.googleapis.com`), not Vertex.
- Repo files read for context (not web sources): `glossary_gen/prices.json`,
  `glossary_gen/run.py` (`actual_cost`, `execute_run`), `glossary_gen/llm.py` (line 275, base
  URL).
