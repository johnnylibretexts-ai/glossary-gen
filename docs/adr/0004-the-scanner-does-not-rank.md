# The scanner does not rank

`glossary-scan` reports what it observed about each term and stops there. It records the model's
**confidence** unchanged, and lists each **corroboration** the page supplied by name — the term in
a heading, a definitional cue in its evidence, the term on more than one page. It does not combine
them, does not order terms by quality, and has no threshold to filter on. Output is ordered by
slug, which is to say not ordered at all.

Adding a single number back is the mistake this record exists to prevent.

## What was there before

Confidence plus three fixed bonuses — `+0.15` heading, `+0.10` cue, `+0.05` multipage — clamped to
1.0, written to a sidecar, and used by `--min-score` to drop terms from the index. The weights were
deliberately never fitted: nineteen labelled reference terms could not support fitting four
parameters, and the eval harness was meant to report what they bought once there was evidence.

The first full-book run produced that evidence: 212 terms from *Python Programming (OpenStax)*.

**135 of them — 64% — scored exactly 1.0.** Twenty-two at 0.95, nineteen at 0.90, thirty-two at
0.85, three at 0.80, one at 0.70. A model reporting confidence near 0.9 as a matter of course
saturates the clamp on almost any single bonus, so the bonuses bought nothing at the top of the
range and the number ranked, in practice, a third of the list.

Worse than uninformative, it was **uninformative in a way that looked authoritative**. Inside the
135-way tie sat both the strongest entries and the weakest — including *Panel data*, whose
definition came out as the fragment "Multidimensional structured datasets." Meanwhile *Ndarray*,
specific and correct, sat below all of them at 0.90, and *Except clause* at 0.85.

## Why a better formula was not the answer

Every signal answers **"is this term defined on this page?"** — and each answers it well. A heading
match, definitional phrasing, appearance across pages: these are good evidence of definition.

But the number was documented as ranking terms **for the human reviewing them**, and that reviewer
is asking **"does this belong in a glossary?"** Those questions look identical and are mildly
opposed: the clearest sign that a page *defines* a word is often that the word is basic enough for
the book to stop and explain it. *Computer* has its own heading and the page reads "A computer is
an electronic device…", so it collects both bonuses and saturates — correctly, by the measure being
computed.

Reweighting cannot fix a quantity that measures the wrong thing. And the right thing is not
available: glossary-worthiness depends on the book's audience, which the scanner cannot see.
*Computer* is noise in a compilers text and correct in an introductory one.

## Considered options

**Recalibrate the weights, or remove the clamp.** Rejected: both preserve the conflation. An
unclamped score would spread the distribution and still rank *Computer* above *Ndarray*.

**Score glossary-worthiness directly**, by asking the model. Rejected as out of scope rather than
impossible — it needs the audience, and the pipeline deliberately does not model one. A second
opinion presented as a rank would be a guess wearing a number's authority, which is the failure
being removed.

**Keep the score, plumb it into the CSV** so the reviewer sees it where they actually work.
Rejected twice over: it delivers a number the reviewer should not act on, and it requires either
breaking the rule that `input.py` alone owns the index schema or coupling the generator to the
scanner's optional sidecar.

## Consequences

`--min-score` is removed rather than defaulted off. It cut terms out of the index permanently,
before generation, on an uncalibrated number — and because a cut term was never written anywhere,
the loss was invisible. That is the one use where an uninformative score does silent damage.

The sidecar remains, redefined as a **scanner diagnostic** rather than a review aid: it is how a
prompt or verification change is compared against a previous run. Reporting components makes it
strictly better at that job — `1.0` told you only that it saturated, while "heading fired, cue did
not" says what the scanner saw.

Review happens on the generated CSV, which is the artifact a person can read. At a fraction of a
cent per term, generating a term that is later cut costs essentially nothing, so trimming before
generation was never buying much.

`merge` needs a rule for which surface form represents a term now that no score orders them: most
confident, then best corroborated, then first seen. Recall is unaffected — the eval harness scores
against slugs, never against the number — so the measured 0.55 floor still holds.

What this does not do is help anyone trim 212 terms. Nothing here replaces the score, because this
run also showed `x_excerpt_chars` does not predict quality either — the thinnest-grounded terms
produced some of the best definitions. Finding a signal that genuinely helps a reviewer is open
work, and it should start from evidence rather than from another plausible formula.
