# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

**Layout: single-context.** One `CONTEXT.md` glossary at the repo root, one `docs/adr/` directory
for decisions. `glossary-gen` is a single Python package with one bounded domain (book index →
AI-generated definitions → reviewable CSV), so there is nothing to split.

## Before exploring, read these

- **`CONTEXT.md`** at the repo root — the domain glossary.
- **`docs/adr/`** — read ADRs that touch the area you're about to work in.

If either doesn't exist, **proceed silently**. Don't flag their absence; don't suggest creating
them upfront. The `/domain-modeling` skill (reached via `/grill-with-docs` and
`/improve-codebase-architecture`) creates them lazily when terms or decisions actually get resolved.

Neither exists as of setup — that is the expected starting state, not a gap to fill.

## File structure

```
/
├── CONTEXT.md
├── docs/adr/
│   ├── 0001-....md
│   └── 0002-....md
└── glossary_gen/
```

If this repo ever grows genuinely separate contexts, the multi-context layout is a root
`CONTEXT-MAP.md` pointing at one `CONTEXT.md` per context, with context-scoped `docs/adr/`
directories beside them. Switch by creating `CONTEXT-MAP.md` — the skills key off its presence.

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a
test name), use the term as defined in `CONTEXT.md`. Don't drift to synonyms the glossary
explicitly avoids.

If the concept you need isn't in the glossary yet, that's a signal — either you're inventing
language the project doesn't use (reconsider) or there's a real gap (note it for `/domain-modeling`).

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently overriding:

> _Contradicts ADR-0007 (event-sourced orders) — but worth reopening because…_
