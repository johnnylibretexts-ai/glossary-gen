# Reference sets come from books, not experts

ADR-0005 designed a two-sitting labelling protocol and pre-registered how to read its result. The
sheets were built twice, the second time at 214 rows against the current index. Neither sitting
will happen: **there is no expert available to this project, and the one person who could sit for
it is not going to.** That is a standing fact about the project, not a scheduling problem, and it
was worth two sheets and a labelling tool to find out.

So the reference set comes from books that already carry one. LibreTexts renders author-written
glossary entries as definition lists under a `Glossary` or `Key Terms` heading, which makes
harvesting them parsing rather than inference. `glossary_gen.scan.reference` reads them;
`tools/harvest_glossary.py` scores a scan against what it finds.

This is not the same question ADR-0005 asked, and the difference is recorded here rather than
allowed to blur.

## What the author glossary can answer

**Recall.** Introductory Statistics defines 101 terms in its own glossary blocks across 33 of its
117 pages. The scanner proposed 60 of them. That is a measurement against published human
editorial judgement, independent of every model, free to regenerate when the book changes, and
impossible to tune after the fact — the properties ADR-0005 wanted from a sealed baseline and could
not keep once the seal was broken.

It also replaced the last hand-maintained reference list in the repo. `RECALL_FLOOR = 0.55` came
from 11 of 19 slugs someone typed; the second eval's floor comes from 101 nobody chose.

## What it cannot answer, and must never be read as answering

**It cannot measure term fit.** 155 slugs the scanner proposed for that book sit outside the author
glossary, and calling that a 73% over-proposal rate would be fabrication: only 33 of 117 pages
carry glossary blocks, so absence is silence rather than a judgement. `coverage` returns
`RecallReport`, which has no precision field, and `tools/harvest_glossary.py` prints the caveat on
every run.

**It answers a narrower question than a reviewer's.** These are the authors' editorial choices for
their own book, not what a reviewer of a generated CSV needs. The two correlate; they are not the
same thing, and nothing downstream may describe author agreement as reviewer agreement.

**It does not exist for every book.** Python Programming (OpenStax) carries no author glossary at
all: its back-matter page is the unfilled LibreTexts template, sample rows and nothing else. The
book that motivated this whole line of work is precisely the book this method cannot score — which
is also, exactly, why the tool exists.

## Consequences

The pre-registered bar in `docs/research/2026-08-16-openstax-review-labels.md` cannot be run as
written and is closed rather than left pending. Its clause 2 asked a candidate signal to beat a
sealed baseline **against human labels**; the seal was broken before any label existed, and now the
labels will never exist either. The pre-registration stays in the repo as the design it was, marked
closed.

The sheets stay committed and unlabelled, and `tools/label_sheet.py` stays usable, because an
expert may appear later and the sheets cost nothing to keep. Nothing in the repo may present them
as data.

**Under no circumstances does a model fill them.** That prohibition is stronger now, not weaker:
with no human pass to compare against, a machine-labelled sheet would face nothing that could
falsify it. It already happened once — a pass was discarded on 2026-08-16 after agreeing with a
prior machine pass on 100% of its cuts — and the discarded file is kept as a third machine pass so
the next reader can see the shape of the failure.

## Considered options

**Wait for an expert.** Rejected as the status quo that produced nothing. Two sheets, a labelling
tool, a protocol and an ADR already exist; a third artifact aimed at the same absent person is not
a plan.

**Let a model produce the ground truth and say so.** Rejected. Every downstream comparison is a
model against a model, the pre-registration voids itself, and the label set would look exactly like
the real thing while measuring agreement rather than correctness.

**Recruit LibreTexts reviewers.** Not rejected — out of scope for this repo, and it stays the right
answer if the relationship ever supports it. What changed is that the project no longer blocks on
it.

**Score against another book's glossary as a proxy for the Python book.** Rejected: subject changes
which terms belong, which is ADR-0004's founding observation and was measured again when neither of
the Python book's cut clusters appeared in the statistics book.
