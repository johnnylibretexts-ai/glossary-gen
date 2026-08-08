# glossary-gen

Generate page-grounded glossary definitions for LibreTexts books.

Step 2 of the three-step glossary pipeline: it consumes a book index (terms plus the pages
each term appears on) and emits a CSV of AI-generated definitions for review and import.

- Step 1 (build the index) and step 3 (import into Conductor) are out of scope.
- Every row ships as `x_status = needs-review`. Nothing here is reviewed or approved content.

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
`prompts/v2.md`, edit it, and pass `--prompt-version v2`.

### Output columns

Core columns map to Conductor's `AddGlossaryParams`. Everything prefixed `x_` is
extension or provenance data an importer may ignore. `addedBy` is never emitted — the
importer must set it from the authenticated user.

`pages` is where the term is used; `x_source_pages` is which pages actually grounded the
definition. When they differ, the index mapping or the term itself is worth a look.
