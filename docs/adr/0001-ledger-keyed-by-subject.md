# Ledger rows are keyed by subject

Both commands resume by asking one append-only ledger whether a unit of paid work is already
done, but they spend in different units: `glossary-gen` spends per term, `glossary-scan` spends
per page. Rather than give each its own ledger, `Ledger` is generic over the **subject** —
whatever one paid model call is made about — and each record type exposes a `subject` field
holding the slug of its own unit.

## Considered options

**A ledger per producer**, each keyed by its own noun (`term_slug` / `page_slug`). Rejected: the
resume rule, the crash-tolerant read, the append-only guarantee and the "only `ok` counts as done"
rule are identical for both, and two copies would be free to drift on precisely the behaviour that
controls spend.

**Keeping the field called `slug`**, which is what it was until this decision. That achieved the
sharing at the cost of one word meaning two things — a page slug in one producer, a term slug in
the other — while `Term.slug` and `ScoredTerm.slug` also existed and meant only the latter. The
old docstring had to argue for the name (*"`slug` (not `page_slug`) because `Ledger` keys on
`record.slug`"*), which is the signal that a concept was missing rather than badly named.

## Consequences

The ledger is a persisted JSONL format, so the field name is part of that format. `LedgerRecord`
and `ScanRecord` therefore still accept `slug` on read for rows written before this change, and
only ever write `subject`.

That concession is load-bearing rather than politeness. `Ledger` counts a row it cannot parse as
*not done*, and reports the count only after the run — so dropping the old name would silently
re-issue a paid model call for every term and every page already completed, and the operator would
find out once the money was spent.
