# CLAUDE.md — glossary-gen

Generate page-grounded glossary definitions for LibreTexts books. Step 2 of the three-step
glossary pipeline: consumes a book index (terms plus the pages each term appears on) and emits a
CSV of AI-generated definitions for review and import. See `README.md` for the walkthrough and
full reference.

## Agent skills

### Issue tracker

GitHub Issues on `johnnylibretexts/glossary-gen`, via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

The five canonical roles, unchanged (`needs-triage`, `needs-info`, `ready-for-agent`,
`ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context — root `CONTEXT.md` is the project glossary and is the authority on domain
wording. `docs/adr/` does not exist yet; `/domain-modeling` creates it lazily. See
`docs/agents/domain.md`.
