# Comparing generated definitions against the ones the authors wrote

Sitting two — 207 rows of human definition-soundness judgement — will not happen
([ADR-0010](../adr/0010-reference-sets-come-from-books-not-experts.md)). This is the automated
thing that can be done instead, and it is deliberately much narrower than the sitting was.

**Written before the comparison was run**, including what each outcome means, so no result can be
graded against a bar invented after seeing it.

## What is compared

*Introductory Statistics 1e (OpenStax)*, `stats/689` — the book that publishes its own glossary. 59
terms where the scanner's index and the author glossary name the same concept (matched on slug,
scanner aliases included). For each: the **author's** definition, printed in the book, against a
**generated** one from `glossary-gen` (`gemini-3.7-flash`, prompt `v1`).

The other 42 author terms have no generated counterpart because the scanner never proposed them —
those are the recall miss list, already measured, and nothing here adds to it.

## The one question a reference can settle

**Does the generated definition assert something the author's definition contradicts?**

That is the only question where the author text is real evidence rather than a second opinion. It
maps onto exactly one of ADR-0005's three soundness failure modes — **wrong** — and it is
checkable: both texts sit side by side in the output, so any verdict can be overturned by reading
two sentences.

Verdicts are `contradicts`, `consistent`, or `unclear`, each with a required one-sentence reason
naming the conflicting claim. A model produces them; a human can audit any row in seconds.

## The two failure modes a model must NOT be asked about

**Fragmentary** and **vacuous** are properties of the generated text alone. Asking a model to grade
them is a model grading a model, with no reference in the loop and nothing that could falsify it —
the exact circularity ADR-0005 was written to prevent, and the reason a labelled pass was already
discarded once.

So they are approximated by rules instead, computed for free and reported as **flags, not
verdicts**:

| flag | rule | what it is evidence of |
|---|---|---|
| `no-sentence` | no terminal punctuation, or under 25 characters | possibly fragmentary |
| `restates-term` | the definition's first clause is the term itself with nothing added | possibly circular |
| `much-shorter` | under half the length of the author's definition | possibly fragmentary |

A flag is a place to look, never a judgement. They are reported per definition and never summed
into a score — [ADR-0004](../adr/0004-the-scanner-does-not-rank.md) applies here as much as it does
to the scanner.

## Pre-registered: how to read the result

| contradictions in 59 | reading |
|---|---|
| 0 | **No evidence of wrongness from this method.** Not "the definitions are sound" — this test cannot see fragmentary or vacuous, and 59 terms of one book by one model is a small window. |
| 1–5 | The interesting outcome: a concrete, human-checkable list of definitions to fix, and the first real signal about what generation gets wrong. |
| over 5 | Roughly one in ten is contradicting the textbook. That is a prompt problem, upstream of any reviewer aid, and the fix belongs in `prompts/v1.md`. |

Written down now so the third outcome cannot be reinterpreted later as "the judge was too strict".

## What this cannot show

- **Agreement is not soundness.** A generated definition can differ from the author's and be
  perfectly correct; the two texts serve different books' conventions. Only the contradictions are
  a finding.
- **One book, one model, one prompt version.** Nothing here generalises to another subject, and a
  model change re-opens all of it.
- **The author's definitions are not neutral.** They are terse, notation-heavy, and written for a
  reader who has the chapter in front of them ("the number of objects in a sample that are free to
  vary"). A generated definition written to stand alone will legitimately say more.
- **The judge is a model.** Its verdicts are auditable because the evidence is printed beside them,
  which is the whole reason this comparison is allowed to exist while a model-labelled soundness
  sheet is not.

## Cost

Generation for 59 terms and one judge call per pair, at `gemini-3.7-flash` rates
(0.75 / 3.75 USD per Mtok): projected ~$0.05 and ~$0.04, so under $0.10 for the whole comparison.
Actuals are recorded in the results section below once it has run.

---

# Results, 2026-08-17

**One contradiction in 59.** That lands in the pre-registered 1–5 band: a concrete, checkable list
of definitions to fix.

| verdict | n |
|---|---|
| consistent | 58 |
| **contradicts** | **1** |
| unclear | 0 |

Full output, both definitions beside every verdict:
[`2026-08-17-stats-definition-comparison.csv`](./2026-08-17-stats-definition-comparison.csv).

## The contradiction, audited by hand

**Nonsampling Error.**

> **Author:** an issue that affects the reliability of sampling data other than natural variation;
> it includes a variety of human errors including poor study design, **biased sampling methods**,
> inaccurate information provided by study participants, data entry errors, and poor analysis.
>
> **Generated:** An error that affects data analysis caused by factors **unrelated to the actual
> sampling process**.

The judge is right, and this is the failure mode ADR-0005 calls **wrong** rather than a wording
difference. Nonsampling error is error not attributable to sampling *variation*; it can absolutely
arise from the sampling *process*, which is why the authors list biased sampling methods first
among its causes. The generated definition turns "not sampling variability" into "unrelated to
sampling", which excludes the textbook's own leading example.

It took two sentences to check, which is the entire argument for a reference-grounded judge over a
model grading a model.

## Flags: 10 `much-shorter`, 0 of the other two

No `no-sentence`, no `restates-term`. Ten definitions are under half the author's length —
*Analysis of variance*, *Central limit theorem*, *Data*, *Event*, *Expected value*, *Nonsampling
Error*, *Poisson probability distribution*, *Random variable*, *Systematic Sample*, *Uniform
distribution* — and reading them, brevity is mostly correct behaviour: the author entries run long
because they carry notation, worked parameters and examples that belong to a chapter, not to a
glossary row.

So the flag did what it was pre-registered to do and no more. It is a place to look, and looking
found nine fine definitions and one bad one.

**Do not read the co-occurrence as a signal.** *Nonsampling Error* is both the one contradiction
and one of the ten flags, which is exactly the kind of n=1 pattern this project has already been
burned by. One term is not evidence that short definitions are wrong.

## What it cost

| step | estimated | **actual** |
|---|---|---|
| generation, 59 terms | $0.05 | **$0.0616** |
| judge, 59 pairs | ~$0.04 | **$0.0185** |
| comparison total | <$0.10 | **$0.0801** |

## A correction the run forced: the scan estimator is calibrated to one book

Recording the eval fixture was quoted at **$0.0415** and actually cost **$0.1306** — 3.1x. Nothing
is wrong with the arithmetic; the constant is measured from a single book.

| | input tokens per page |
|---|---|
| `EST_SCAN_TOKENS_IN` | 1,050 |
| Python Programming, 272 scanned pages | **1,035** — the constant is this book |
| Introductory Statistics, 117 pages | **2,300** |
| the 33 glossary-bearing stats pages | **4,054** |

Two effects stack. A statistics text runs 2.2x heavier per page than a programming one, and
selecting the pages that carry glossary blocks selects the long chapter pages rather than a
random sample of them.

This also corrects a figure already in the repo: `2026-08-16-openstax-review-labels.md` recorded the
statistics scan as costing **$0.15**, which is what the estimator predicted (117 × 1,050/125). The
ledger's own token counts put the real figure at **$0.245**. The estimate was quoted as an actual.

The estimator is not being re-fitted. Averaging two books produces a constant wrong for both, and
`--budget-usd` remains the mechanism that actually bounds a run — an estimate is a forecast, and
the ledger is the receipt. What changes is that a quoted estimate must be labelled as one.
