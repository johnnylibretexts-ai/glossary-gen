# Unwritten terms are reported beside the CSV, not in it

`write_csv` filters the ledger to `status == "ok"`, so a term the run failed to define is not in
the output and is not mentioned anywhere a reviewer looks. Two of 212 terms vanished this way on
the first full-book run — `__init__()` and `super()`, unmatchable on their own pages because of
a regex bug since fixed. Under today's `MIN_EXCERPT_CHARS = 100` it would have been about ten.

Those terms are now **unwritten**, and every unwritten term is reported in a sidecar CSV beside
`--out`. The import CSV is unchanged: it still holds only rows an importer can consume.

ADR-0004 already ruled on this shape. `--min-score` was removed rather than defaulted off because
"a cut term was never written anywhere, [so] the loss was invisible. That is the one use where an
uninformative score does silent damage." The excerpt floor differs from `--min-score` in being
*correct* — `excerpt.py` argues it is what makes "page-grounded" mean something — but a rule being
correct is what makes it safe to apply, not what makes it safe to conceal. `super()` was rightly
denied a definition and still belongs in a Python glossary. Those are two judgements, and only one
of them is the tool's.

The unit is every term with no `ok` row, not `no_excerpt` alone. `fetch_error` and `llm_error`
disappear through the same clause, and `llm_error` is the worst of the three: the model was billed
and the term vanished regardless.

## Considered options

**Rows in the import CSV with an empty `definition`.** The obvious one-file answer, and the reason
this record exists. `README.md` promises the importer that `x_status` is always `needs-review`; a
definition-less row carrying that status tells a naive Conductor importer to create an empty
glossary entry. That manufactures bad data downstream, which is strictly worse than withholding
good data. The reviewer and the importer are different audiences that have so far wanted the same
rows, and `write_csv`'s `status == "ok"` clause is where the two silently became one filter.

**Console output only** — name the unwritten terms in the run summary. Rejected: a name scrolling
past in a terminal is not something a reviewer works from, and review happens hours later against a
file. It fails the same test ADR-0004 applied to the invisible cut.

**Recoverable by diffing the index against the CSV.** Rejected on the same ground: information that
requires the reviewer to first suspect the loss is information they will not find. ADR-0005 is
evidence that the workaround was already being paid for — term fit was labelled against the
212-term index "rather than the 210-row CSV."

**A cumulative sidecar** listing everything still unwritten across the whole ledger. Rejected: the
import CSV's rule is that rows only ever come from one run, and a sibling file with a different
temporal semantics is how two artifacts start disagreeing about what a run did. The ledger is
already the cumulative history.

**Collapsing the three statuses into "no definition written."** Rejected: they are three different
stories — the book barely discusses this, the page would not load, the model kept failing — and
only the first is a judgement the reviewer should act on. Fusing distinct signals into one
undifferentiated figure is what ADR-0004 removed and what ADR-0005 was collected to prevent.

## Consequences

Membership is "in this run's slugs, matching its prompt version and declared primary model, with no
`ok` row" — not "has a non-ok row." With a shared ledger a term that failed in one run and
succeeded in the next carries both records, and the later run must not report it unwritten. Where
several failed attempts exist the latest is emitted.

The sidecar is always written, header-only when nothing is unwritten. Written conditionally, a
previous run's file survives a clean run and reports terms that now have definitions, and its
absence would mean either "nothing was unwritten" or "you are looking at a stale directory" with no
way to tell which.

`x_status` carries the ledger status verbatim rather than `needs-review`, which would put "a human
must read this" on a row with nothing to read. The values are disjoint from `needs-review`, so a
reviewer who concatenates the two files gets one legible sheet — the one-file view the first
rejected option was reaching for, without handing it to an importer. `README.md`'s promise is
narrowed to the import CSV.

`x_excerpt_chars` now reports the real total on an unwritten row, which means `excerpts_for_term`
must return `used_chars` instead of discarding it on the `return []` path. It was already being
computed, under a comment claiming the total "is what `x_excerpt_chars` reports to the reviewer" —
true only for terms that cleared the floor. The distinction is load-bearing: `0` means the term
matched nothing at all on its own occurrence pages, which is an index or matching defect, while
`97` means the book discusses it briefly and a reviewer may want it anyway. Reporting both as `0`
is a false number where an empty cell would at least have been honest.

Regenerating both files from the first run's ledger is the worked example. It reports `0` for
`__init__()` and `super()` — the two terms that run lost — and the cause turned out to be the
trailing-`\b` bug in `bounded()` rather than either a thin book or the mangled term extraction
the research note had guessed. A number that separates "nothing matched" from "not quite enough"
points at the defect; the single hidden count it replaces pointed at nothing.

The `error` text stays out, so the file keeps 21 columns. A reviewer acts on the status, not an
exception string, and the operator who does want it has the ledger, which records it verbatim.

`write_csv` keeps returning the count of `ok` rows and `wrote N row(s)` keeps meaning definitions
produced; the unwritten count is a second line. Quietly redefining that number to include
definition-less rows would look like tidying and destroy what it meant.

Terms a run never reached — after an abort on the spend ceiling or repeated failure — have no
ledger record and so are absent from the sidecar. That loss is not silent: the run prints
`run aborted early` and exits non-zero. Emitting synthetic rows for them would require a status
word that no producer ever writes to the ledger, which is the coupling ADR-0002 refused when it
kept the run blind to domain vocabulary.

What this does not do is address the scanner, which discards evidence-failing candidates the same
way and writes them nowhere. The first full-book run rejected 0 of 236, so there is no measured
harm to design against, and ADR-0004's closing position — start from evidence rather than another
plausible formula — applies to a second sidecar built on principle alone. It is recorded as open,
not as settled.
