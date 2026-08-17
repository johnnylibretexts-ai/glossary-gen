# The resume key does not version generation policy

The first full book run predates `MIN_EXCERPT_CHARS = 100`. Eight of its rows were grounded on 14
to 82 characters of page text, and every one of them stayed in the CSV afterwards, because the
resume key is `(subject, prompt_version, model)` and none of those three changed when the floor
was introduced. The CSV shipped eight definitions the tool would no longer write.

The key stays as it is. It claims "the same prompt and model were used", not "re-running would
produce this row", and it is not being made to carry the second claim.

## Why not add the floor to the key

`MIN_EXCERPT_CHARS` is not special, and treating it as though it were is the trap this record
exists to close. `max_excerpts = 3`, `max_chars = 6000`, the excerpt ranking order, `bounded()`
and the scanner's `MIN_EVIDENCE_CHARS` all change output, and none of them is in any key. The
punctuation fix in `d53e235` changed output for four terms and invalidated nothing.

So the real question was never "add the floor to the key" but "does this project want a generation
policy version at all", and the answer is no. Every such version means a constant tweak re-pays for
a whole book, which fights the one thing the ledger exists to prevent. A tool built around never
paying twice should not acquire a mechanism whose purpose is to make it pay twice.

## What made this survivable

The rows were never hidden. `x_excerpt_chars` is on every row, the README already points reviewers
at it, and `14` against a documented floor of `100` is legible to anyone who looks. That is the
difference between this and the unwritten terms of ADR-0006, where the loss was invisible and the
silent-damage argument from ADR-0004 applied. It does not apply here.

## Considered options

**Record the floor in force on each row**, so a row can be audited against current policy. Rejected
as redundant for the case that motivated it: `x_excerpt_chars` plus today's constant already
answers it, entirely from data already on the row. It would only earn its place for policies whose
effect is invisible in the output — `max_excerpts`, the ranking order — and holding those means
inventing a policy blob that drifts and needs its own versioning story. `x_generated_at` plus git
history answers that question when it is ever actually asked.

**Warn at startup when a ledger holds rows below the current floor.** Rejected. The scanner's
comparable note (ADR-0008) announces something about to happen — pages will be re-scanned, money
will be spent. This one would announce a fact about rows the run is not touching, on every run
forever, with no action attached. A note nobody can act on teaches people to skip notes.

**Regenerate the affected rows automatically.** Rejected: that is policy versioning wearing a
smaller hat, and it spends money without being asked.

## Consequences

`--regenerate <term>,<term>` re-attempts named subjects even when they are already done. It reuses
the `is_done` hook ADR-0008 added rather than inventing a second way to say "not finished", and it
is deliberately per-subject — a blanket `--force` would re-pay for a whole book. It re-attempts
work someone named; it does not version anything.

Values are slugified, so a reviewer can name what the CSV shows them (`Equality`, `__init__()`)
without deriving a slug, and `slugify` is idempotent so a slug also works. A value matching no term
is refused with `EXIT_INPUT_ERROR` rather than quietly doing nothing: slugification turns a typo
into a plausible-looking subject that simply never matches, and the only other symptom would be a
definition that did not change, noticed after the run was paid for.

**Both CSV writers now key on a subject's LATEST attempt.** This generalises ADR-0006's "has no
`ok` row" without contradicting it: that rule assumed success was terminal, and `--regenerate`
breaks the assumption, since a term written before the floor existed can be re-attempted under it
and correctly refused. Found by running it — the first attempt emitted `215` rows for `214` terms,
with `Equality` and `Inequality` appearing twice, which `load_input` rejects on duplicate slugs and
which would therefore have failed at the very consumer the file targets. A failure followed by a
success still belongs in the CSV, exactly as before.

Ordering is by ledger position, never by `generated_at`. The timestamp is what a producer wrote
down; the position is what happened.

The eight rows were re-attempted once, as a one-off product decision about what LibreTexts
receives rather than as a policy the tool now enforces. Two recovered — `Equality` and
`Inequality`, whose `==` and `!=` aliases became matchable after `d53e235`, going from 17 and 19
characters of grounding to 132 and 134 — and six moved to the unwritten sidecar. The CSV is now
207 rows with nothing below the floor, plus 7 unwritten, still 214 terms accounted for. The
measured detail, including a correction to `d53e235`'s own arithmetic, is in
`docs/research/2026-08-16-first-full-book-run.md`.
