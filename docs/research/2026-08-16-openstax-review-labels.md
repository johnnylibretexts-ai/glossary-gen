# Review labels — protocol and pre-registration

The open question ADR-0004 left behind is *what genuinely helps a reviewer trim 212 terms*, and it
asked that the answer start from evidence rather than another plausible formula. This is that
evidence being collected. Nothing has been labelled yet at the time of writing: everything below —
including the bar a candidate signal must clear and how each outcome is to be read — is recorded
**before** any label exists, so that the result cannot be graded against a target invented after
seeing it.

Protocol rationale and the rejected alternatives are in
[ADR-0005](../adr/0005-review-labels-are-collected-blind.md). This note is the working document.

## The audience

> **Python Programming (OpenStax)** — a first programming course. Readers have no prior
> programming experience, but are not new to computers.

Term fit is judged against this sentence and nothing else. It is load-bearing: "not new to
computers" is what makes *Computer* a cut and keeps *Ndarray*. A different sentence flips real rows,
which is the honest form of ADR-0004's "*Computer* is noise in a compilers text and correct in an
introductory one."

## What to label

| Sheet | Rows | Columns you fill |
|---|---|---|
| `2026-08-16-openstax-term-fit.csv` | **214** | `checked_page`, `term_fit`, `reason` |
| `2026-08-16-openstax-definition-soundness.csv` | 202 | `definition_sound`, `reason` | (not yet rebuilt against the 207-row CSV — sitting one first)

Both label columns take `yes`, `no`, or `borderline`. `reason` is free text, required on anything
that is not `yes` — write a sentence, not a category. `checked_page` takes `y` when you had to open
a page to decide, blank otherwise; it records which terms were not decidable from the term alone.

Ternary, not binary, because the borderline population is exactly what a signal would have to earn
its keep on. Free text, not codes, because categories invented before the data are a formula in
disguise; codes get derived from the reasons afterwards.

## How to run it

1. **Sitting one — term fit, 214 rows, roughly 55 minutes.** Do not open the soundness sheet. The
   term-fit sheet has no `definition` column by construction, and reading a definition before
   judging fit turns "does this belong?" into "is this any good?" — the exact conflation ADR-0004
   removed, this time baked into the ground truth where nothing downstream can falsify it.
2. **Sitting two — definition soundness, 202 rows, roughly 100 minutes.** The whole row is visible
   here; that is intended.

Sitting one is worth doing even if sitting two never happens: it alone answers how much of the list
a reviewer actually cuts, and its labels never expire.

## Rubric

**Term fit** asks *does a reader of this book need this term in a glossary* — never *is it defined
on that page*. The scanner already answered the second question well, and the two are mildly
opposed: the clearest sign a page defines a word is often that the word is basic enough to be worth
stopping for.

**Definition soundness** has exactly three failure modes:

- **Wrong** — *Object*: "A single unit of data in a Python program." An object is a class instance.
- **Fragmentary** — *Panel data*: "Multidimensional structured datasets." Not a sentence that
  defines anything.
- **Vacuous or circular** — restates the term without adding anything.

Style, tone, length, and a missing `x_example` or `x_category` are **not** soundness failures. They
are cheap edits, and folding them in inflates the derived `fix` class until it stops discriminating.
Note them in `reason` if they jump out; do not let them set the label.

## Verdict is derived, never recorded

| `term_fit` | `definition_sound` | Verdict |
|---|---|---|
| yes | yes | keep |
| no | — | cut |
| yes | no | fix |

A recorded verdict can drift out of sync with the two labels it should follow from, and the
derivation rule is the thing worth arguing with later.

## Provenance of the labelled material

Both sheets come from the first full-book run, measured in
[2026-08-16-first-full-book-run.md](./2026-08-16-first-full-book-run.md). Book `eng/117469`, 136
pages, `gemini-3.7-flash` throughout, $0.347 all in. `out/index.json` was written 2026-08-15
22:54, `out/glossary.csv` at 23:03; both live in gitignored `out/`, which is why the sheets are
committed here.

**⚠️ Rewritten 2026-08-16 (later the same day). All three staleness facts previously listed here
are now obsolete, and the term-fit sheet has been rebuilt.** What they said, and what is true now:

- ~~The soundness sheet carries 202 rows because eight sit beneath `MIN_EXCERPT_CHARS`~~ — those
  eight were re-attempted via `--regenerate` (ADR-0009). `Equality` and `Inequality` recovered real
  grounding (17→132 and 19→134 characters) and carry proper definitions; the other six moved to the
  unwritten sidecar. **The CSV is now 207 rows with nothing below the floor.**
- ~~`init` and `super` never received a definition~~ — **both now have one.** The punctuation fix
  `d53e235` made `__init__()` and `super()` matchable on their own pages.
- ~~`out/index-report.json` still carries the removed fused score~~ — **it does not.** The book was
  re-scanned, and the report now carries `confidence` and `corroborations` separately plus the
  `rejected` block (ADR-0007). It is still a scanner diagnostic, so still do not consult it while
  labelling — but the reason is now ADR-0004's, not staleness.

**The term-fit sheet is 214 rows, not 212 — a deliberate, additive change to the pre-registration.**
The re-scan moved the index from 212 slugs to 214: 5 new (`Delimiter`, `Fibonacci`, `Index method`,
`Outer loop`, `Overriding`), 3 gone (`method-overriding`, `python-tutor`, `string-slicing`), 209
shared. The sheet is built from the **current** index because term fit is keyed to slugs, survives
every regeneration, and is worth the hours only if it describes the list that would actually ship.

This does not weaken the pre-registered bar. Any comparison against the sealed
`model-fit-baseline` and `agent-pass` sheets — both still 212 rows, both untouched — is computed on
the **209-slug intersection**. The 5 new terms are labelled but excluded from that comparison; the 3
departed ones keep their baseline labels and get no human label. Labelling a superset costs five
extra rows and loses nothing; labelling the stale 212 would have spent the expensive input on three
terms that no longer exist.

Labels are one expert's judgement, recorded as such. They are not observed reviewer behaviour, and
nothing downstream may describe them as measuring what a LibreTexts reviewer did.

**A first attempt at sitting one was discarded, 2026-08-16.** The sheet was filled with a prior
session's context still loaded, so the labels were not independent of the `agent-pass` sheet they
would have been used to judge. The tell was arithmetic rather than suspicion: `agent-pass` flags 12
terms `no` and *all 12* fell inside the sheet's 14 cuts — precision 100%, lift 15.3x — while the
sealed `model-fit-baseline` managed 32.3% precision on the same task; overall agreement ran 90.9%
against the agent pass and 76.6% against the model baseline, when the two machine passes agree with
each other only 75.5% of the time. Independent raters do not produce a 100% subset. No cut rate or
signal result from that pass has been reported or committed as a finding.

It is preserved as `2026-08-16-openstax-term-fit-contaminated-pass.csv`, a **third machine pass**
and never ground truth. Add it to the do-not-open list below.

**Do not open while labelling:** `2026-08-16-openstax-definition-soundness.csv`,
`2026-08-16-openstax-term-fit-agent-pass.csv`, `2026-08-16-openstax-model-fit-baseline.csv`,
`2026-08-16-openstax-term-fit-contaminated-pass.csv`, `out/index-report.json`.

## Pre-registered: the bar a candidate signal must clear

A signal ships only if all four hold.

1. **It is an observation, not a coefficient.** Something a reviewer can verify on the page — "the
   term appears only in a caption" — not a fitted number.
2. **It beats both baselines**: slug order (i.e. no ordering at all), and the sealed model fit
   baseline described below.
3. **It is reported per concept.** Fit and soundness separately. Nothing fuses them, and nothing
   fuses the corroborations back into a single figure.
4. **It removes no rows.** No threshold that cuts terms out of the CSV, because a cut term written
   nowhere is an invisible loss — the specific damage `--min-score` did.

**If nothing clears the bar, we ship nothing** and record that the list is best read plainly. That
is a real result, not a failure to find one.

## Pre-registered: how to read the cut rate

Let the cut rate be the share of the 212 with `term_fit = no`.

| Cut rate | Reading |
|---|---|
| under 20% | Needle in a haystack. The right shape is a **flag** on suspect rows; precision matters more than recall. |
| 20–60% | Genuine **partition** territory. Grouping, or a named observation, could pay. |
| over 60% | The reviewer aid is the wrong project. The scanner is **over-proposing**, and the fix belongs in the scan prompt, upstream of the CSV. |

Written down now so the third outcome cannot be quietly reinterpreted as "so we need a better
signal."

## The sealed baseline

`2026-08-16-openstax-model-fit-baseline.csv` holds a model's own answer to *does this term belong
in a glossary for that audience*, given the term and the audience sentence only — no page, no
definition. It was generated **before** any human label existed and is not to be opened until both
sittings are done.

ADR-0004 rejected asking the model for glossary-worthiness as a **shipped rank**. It did not reject
it as a **measured baseline**, and that difference is the whole point of this note. Generated first
and left sealed, it is a held-out prediction rather than a post-hoc comparison — and it is the
strongest of the two baselines, because if one sentence of audience is enough to match expert
judgement, no page-derived signal needs building at all.

### The seal was broken on 2026-08-16, before any human label existed

At the owner's instruction, and it cannot be restored. What it bought and what it cost are both
recorded here rather than left to inference.

|  | cuts | rate | borderline | yes |
|---|---|---|---|---|
| agent pre-pass | 12 | 5.7% | 26 | 174 |
| sealed baseline | 32 | 15.1% | 30 | 150 |

Exact agreement 160/212 (75.5%). **Ten of the pre-pass's twelve cuts were independently cut by the
sealed pass**, and those ten are precisely the two clusters the pre-pass described: the spelled-out
operator names (*Greater than*, *Greater than or equal*, *Less than*, *Less than or equal*,
*Descending order*, *Computer*) and the exercise topics (*Mad lib*, *Palindrome*, *Prime number*,
*Panel data*). Two passes with different prompts, different context and different framing found the
same two structures. That is the most durable thing in this file.

No term cut by the pre-pass was kept by the baseline. The reverse happened six times — *Max
function*, *Min function*, *Mixin class*, *Euclid's method*, *Loop expression*, *Data science life
cycle* — where the baseline, seeing only the term and one sentence, cut things a reader of the book
would want. Every remaining disagreement is one step on the scale, mostly `borderline` against
`yes`.

**What this cannot do is settle the question.** Both passes come from one model family, so a shared
blind spot appears as consensus, and the pre-registered bar asked a candidate to beat this baseline
**against human labels** — which no longer exists as an unused test, because the baseline is now
public and any later human pass can be accused of having been influenced by it. The two cut rates
agree only on the band, not the number: 5.7% against 15.1% is a factor of nearly three.

The honest status: **the flag band is well supported, the ten-term core cut list is the strongest
candidate a signal could aim at, and clause 2 of the bar can no longer be run as written.**

## An agent pre-pass — not ground truth

`2026-08-16-openstax-term-fit-agent-pass.csv` holds an assistant's judgement of all 212 terms
against the audience sentence, made without opening the sealed baseline. It exists to say which
band the cut rate probably falls in before anyone spends an afternoon, and to give the human pass
something to disagree with.

**It is not the ground truth and must never be copied into the term-fit sheet.** The sealed
baseline is scored against *human* labels; score it against these and the comparison is
model-versus-model, which measures agreement rather than correctness and quietly voids the
pre-registration. Its second weakness is contamination: the terms *Computer*, *Palindrome*,
*Object*, *Panel data* and *Ndarray* are discussed by name in ADR-0004 and in the run note,
alongside remarks about which are noise — so those five judgements are not independent.

    no 12 (5.7%)   borderline 26   yes 174

Both readings land in the **under-20% flag band**: 5.7% counting only `no`, 17.9% counting
borderlines as cuts. If the human pass agrees, this is a needle-in-a-haystack problem and the
right shape is a flag on suspect rows.

Two structures showed up in the 12 cuts, and both are observations a reviewer can verify rather
than quantities:

- **Spelled-out operator names** — *Greater than*, *Greater than or equal*, *Less than*, *Less
  than or equal*, *Descending order*. English renderings of symbols the audience already reads.
- **Exercise topics rather than language concepts** — *Mad lib*, *Palindrome*, *Prime number*,
  *Shift cipher*, *Panel data*. The book stops to explain the puzzle, not Python, and the scanner
  correctly observes a definition. This is ADR-0004's opposition in its clearest form.

The borderline pile looked at first like a different problem hiding inside this one:
*Modulo*/*Modulus*, *Immutable*/*Immutable object*, *Mutable data type*/*Mutable object*,
*Computer program*/*Program*, *Repetition*/*Repetition operator* and *Boolean value*/*Boolean
variable* read as near-duplicate entries that survived merge, which no fit signal would ever fix.

**Measured, that reading does not hold, and it is corrected here rather than removed.** The
cheapest rule that could catch any of them — one term's words a strict subset of another's — fires
on **73 of the 212** and collapses **3 of the 6**. The other 70 are *Function* against *Max
function*, *Statement* against *If statement*, *Dictionary* against *Nested dictionary*: about
seventy real terms deleted to collapse three. *Modulo*/*Modulus* and *Mutable data type*/*Mutable
object* need a rule no string comparison supplies. *Boolean value*/*Boolean variable* are defined
on the **same page**, which is evidence the book distinguishes them rather than that merge failed.

Clean duplicates come to *Computer program*/*Program* and *Modulo*/*Modulus* — **about 1% of the
book**, caught by no single rule. Duplication is therefore not the reviewer's burden, and the
sentence that suggested it was over-read from a pre-pass that was never ground truth. The measured
version now sits in `merge`'s docstring so the next reader does not re-derive it.

## A second book: neither cut cluster survives

*Introductory Statistics 1e (OpenStax)*, `stats/689`, 117 pages, $0.15, scanned 2026-08-16.
Same publisher deliberately, so pedagogical style is held constant and **subject** is the only
variable.

| | Python (136pp) | Statistics (117pp) |
|---|---|---|
| terms | 212 | 123 |
| terms per page | 1.56 | 1.05 |
| spelled-out operator names | 6 | **0** |
| exercise topics | 4 | **0** |
| subset pairs per term | 0.34 | 0.33 |

**Both clusters were programming-text artifacts.** Nothing among the 123 statistics terms is an
English rendering of a symbol, and none is an exercise topic — the nearest candidates,
*Institutional Review Board*, *Placebo treatment*, *Plus four method*, are genuine research-methods
terms. The cut list this note offered as "two verifiable observations" does not generalise, and the
finding is recorded rather than quietly dropped.

There is a mechanism, which is why this is worth keeping rather than deleting. A programming text
must define the puzzle before the reader can code it, so *Palindrome* and *Shift cipher* get
definitions and the scanner correctly finds them. In a statistics text the exercise domain **is**
the subject: the book defines *Sampling bias*, never "dice". So "the book stops to explain
something that is not the subject" is a real phenomenon with a real cause — it is simply much rarer
outside programming.

The one quantity that replicated is the subset-pair rate, 0.34 against 0.33 per term. That is
strong evidence for the earlier correction: the rate is a property of the string rule, not a defect
in either book's merge.

**Standing conclusion after two books.** The flag band holds, and the statistics book's cut rate
looks lower still. But no cut *structure* has yet survived a change of subject, so there remains
nothing a reviewer can be handed. That is the third time this question has been answered "no usable
signal yet" — by ADR-0004, by the excerpt-chars finding, and now by cluster recurrence — which is
itself worth weighing before a fourth attempt.

## What this pass cannot test

- **`multipage` is compromised.** The term-fit sheet lists page URLs, so page count is countable.
  Withholding them would have bought a clean test at the cost of guessed labels, which poison every
  candidate rather than one.
- **One book, one subject, one labeller.** This set is for *rejecting* bad signals, not for fitting
  weights — the same reason nineteen reference terms could not support fitting four parameters.
- **The existing eval fixtures answer a different question.** `RECALL_FLOOR = 0.55` scores which
  slugs the scanner *found*, by set membership. Nothing here should be wired into it, and no floor
  should be added until a signal exists, or it will be fitted to.

## Open until the labels exist

1. Which page-derived signals to test. Two are free today: the excerpt **rank** (0 after-heading /
   1 definitional / 2 mention) is computed in `excerpt.py` and thrown away, and `x_category` /
   `x_related` are already sitting unused in every CSV row.
2. Whether any number is permitted at all under ADR-0004, or only named observations.
3. ~~Whether the CSV should stop hiding its `no_excerpt` terms~~ — **closed 2026-08-16 by
   [ADR-0006](../adr/0006-unwritten-terms-are-reported-beside-the-csv.md).** They are reported in
   a sidecar beside `--out`, not in the import CSV, and the unit is every term with no `ok` row
   rather than `no_excerpt` alone. This also affects the soundness sheet's provenance: the eight
   sub-floor rows named above are now visible output rather than terms the tool emits nothing
   about, so a future labelling pass can reach them from an artifact instead of by diffing the
   index against the CSV.
4. ~~Whether the **scanner** should do the same for candidates it rejects on evidence~~ —
   **closed 2026-08-16 by
   [ADR-0007](../adr/0007-rejected-candidates-are-a-diagnostic-not-a-review-artifact.md), and not
   the way this question assumed.** Rejections are recorded in the existing `out/index-report.json`
   with which of the two reasons fired, as an operator diagnostic. They are deliberately *not*
   given ADR-0006's treatment: an unwritten term is one the book demonstrably defines, while a
   rejected candidate may be a model inventing both a term and the quotation that proves it, and
   asking a reviewer to adjudicate that turns a gate into a hint. The "wait for evidence" objection
   was overridden because the cost collapsed — the report already existed and the reason was
   already computed — but it stays the right objection to a *new* artifact.
