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
