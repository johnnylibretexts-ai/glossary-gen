# Review labels are collected blind and per concept

ADR-0004 removed a number because one quantity was answering two questions at once. The labelled
set built to replace it is collected so that the same conflation cannot re-enter through the ground
truth, where it would be unfalsifiable rather than merely wrong.

Two concepts are labelled, never one. **Term fit** — does this term belong in this book's glossary —
is recorded on a sheet that has no `definition` column at all. **Definition soundness** — is the
written text correct and self-contained — is recorded on a separate sheet. The **verdict** a
reviewer would reach is derived from the pair, not written down: cut when the term does not fit,
fix when it fits but its definition is unsound.

Term fit is labelled against a stated audience, because the concept is defined as audience-dependent
and an unstated audience cannot be audited or held steady across a two-hour sitting. For the first
run that sentence is *"Python Programming (OpenStax) — a first programming course. Readers have no
prior programming experience, but are not new to computers."* It is load-bearing, not ceremony:
"not new to computers" is what makes *Computer* a cut while *Ndarray* stays.

## Considered options

**One sheet, two passes over it.** Rejected: blindness enforced by scrolling discipline is not
blindness. The definition has to be absent by construction or the labeller will have read it.

**Withhold the page URLs too**, which would make `multipage` cleanly testable. Rejected: the
labeller then guesses on every term that cannot be judged from its spelling, and a guessed ground
truth poisons every candidate signal rather than just the one. The URLs stay, the page *count*
column does not, and `multipage` is recorded as a compromised candidate that this pass cannot
cleanly test.

**Record the verdict directly.** Rejected: a recorded verdict can drift out of sync with the two
labels it is supposed to follow from, and the derivation rule is the thing worth being able to
argue with later.

**Fixed reason codes instead of free text.** Rejected as a formula in disguise. Categories invented
before the data are the same move as the `+0.15` / `+0.10` / `+0.05` weights, which were also
plausible before any run existed. Codes are derived from the written reasons afterwards.

## Consequences

The two label sets age differently, and the collection is split along that seam. Term fit is a
property of a term and a book: it is keyed to slugs, survives every regeneration and every prompt
change, and is worth the hours on its own. Definition soundness is bound to one
`(prompt_version, model)` pair and expires when either moves. That is why term fit is labelled
first, and why it is labelled against the 212-term index rather than the 210-row CSV.

The soundness sheet carries 202 rows, not 210: the run predates `MIN_EXCERPT_CHARS = 100`, and the
eight rows beneath that floor — `Modulo`, `Equality`, `Repetition`, `Inequality`, `Real division`,
`Floor division`, `Copy method`, `Line plot` — would be reported `no_excerpt` today. Labelling text
the tool no longer emits spends the expensive input on nothing. `init` and `super` appear on the
term-fit sheet and nowhere else, having never received a definition at all.

Labels are one expert's judgement, recorded as such. They are not observed reviewer behaviour, and
nothing downstream may describe them as measuring what a LibreTexts reviewer did.

Merging the two sheets, or adding a definition column to the first, destroys the meaning of every
label on it while looking exactly like tidying up. That is the specific act this record exists to
prevent.
