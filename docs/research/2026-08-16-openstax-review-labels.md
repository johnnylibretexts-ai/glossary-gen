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
| `2026-08-16-openstax-term-fit.csv` | 212 | `checked_page`, `term_fit`, `reason` |
| `2026-08-16-openstax-definition-soundness.csv` | 202 | `definition_sound`, `reason` |

Both label columns take `yes`, `no`, or `borderline`. `reason` is free text, required on anything
that is not `yes` — write a sentence, not a category. `checked_page` takes `y` when you had to open
a page to decide, blank otherwise; it records which terms were not decidable from the term alone.

Ternary, not binary, because the borderline population is exactly what a signal would have to earn
its keep on. Free text, not codes, because categories invented before the data are a formula in
disguise; codes get derived from the reasons afterwards.

## How to run it

1. **Sitting one — term fit, 212 rows, roughly 55 minutes.** Do not open the soundness sheet. The
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

Three staleness facts the labeller should know:

- The soundness sheet carries **202 rows, not 210**. The run predates `MIN_EXCERPT_CHARS = 100`, so
  eight rows beneath that floor — `Modulo` (14 chars of excerpt), `Equality` (17), `Repetition`
  (18), `Inequality` (19), `Real division` (21), `Floor division` (23), `Copy method` (53),
  `Line plot` (82) — would be reported `no_excerpt` today and are excluded.
- `init` and `super` are on the term-fit sheet only. They never received a definition; both are
  almost certainly mangled `__init__` and `super()`, and the punctuation fix (`d53e235`) landed
  after this run.
- The on-disk `out/index-report.json` still carries the **removed fused score**. Do not consult it
  while labelling.

Labels are one expert's judgement, recorded as such. They are not observed reviewer behaviour, and
nothing downstream may describe them as measuring what a LibreTexts reviewer did.

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
3. Whether the CSV should stop hiding its `no_excerpt` terms — `write_csv` filters the ledger to
   `status == "ok"`, so a reviewer cannot see what was already trimmed for them.
