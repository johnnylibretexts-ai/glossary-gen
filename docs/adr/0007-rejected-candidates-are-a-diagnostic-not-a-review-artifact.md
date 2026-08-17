# Rejected candidates are a diagnostic, not a review artifact

The scanner drops a candidate whose evidence fails the gate and writes it nowhere; only
`summary.unverified`, a count, survives. That is the same silent-loss shape ADR-0006 just ruled
against one stage downstream, and this record exists because the obvious next step — give rejected
candidates the same treatment as unwritten terms — is the wrong one.

Rejected candidates are now recorded in the scanner's existing diagnostic report,
`out/index-report.json`, with the reason the gate fired. They are not surfaced to a reviewer, they
do not get their own file, and they still never reach the index.

## Why not ADR-0006's treatment

The two look symmetrical and are not. An **unwritten** term is one the book demonstrably defines —
it earned its place in the index — that the generator could not write a definition for. Showing it
to a reviewer asks a fair question: this belongs in the book's vocabulary, do you want it anyway?

A **rejected candidate** has not earned anything. It is a claim a model made that failed the gate,
and the more interesting of the two failure reasons is that the span offered as proof **could not
be found on the page** — which is the signature of a model inventing both the term and its
evidence. Putting that in front of a reviewer asks them to adjudicate a suspected hallucination,
using a quotation that may be fabricated, about a book they are not assumed to know
(see `CONTEXT.md`, Reviewer). That is not a fair question, and answering it wrongly puts invented
vocabulary into a glossary.

`CONTEXT.md` calls evidence "a gate, not a hint". A gate whose refusals are re-presented as
suggestions is a hint.

## Considered options

**A reviewer-facing file, mirroring the unwritten sidecar.** Rejected for the reason above. It also
requires the derived-path and always-written machinery ADR-0006 needed, to deliver rows nobody
should act on.

**Both — diagnostic block and reviewer file.** Rejected: roughly double the work to produce two
artifacts that must agree about what was rejected, where the second one should not exist.

**A new diagnostic file rather than the existing report.** Rejected because the report is already
defined for exactly this. ADR-0004 redefined it as "a scanner diagnostic rather than a review aid:
it is how a prompt or verification change is compared against a previous run." A rejection is that
kind of observation, so it belongs in the file that already has that job. No new flag, no new path
derivation, nothing to keep in step with `--out`.

**One `rejected` count, no reasons.** Rejected: `verify` fails for two reasons that call for
opposite fixes. Evidence under `MIN_EVIDENCE_CHARS` is a model that found the right page and
returned a useless span — a prompt problem. Evidence absent from the page is a model inventing
things — a much worse problem. Collapsing them into one number is the fusion ADR-0004 removed from
the score and ADR-0005 was collected to prevent, and the count already existed anyway: it is
printed today and tells you nothing you can act on.

**Leaving it alone**, which is what the research note recommended and what this repo agreed to on
2026-08-16, on the grounds that the first full book run rejected 0 of 236 and ADR-0004 asks for
evidence before building. Overridden deliberately: the cost here turned out to be far smaller than
that reasoning assumed, because the artifact already exists and the reason is already computed. The
argument against building on principle alone applies to a *new* artifact, which this is not.

## Consequences

`verify()` keeps its name and its meaning but is now defined over `rejection_of()`, which returns
which reason fired or `None`. The length check runs first, so a short span that *is* on the page
reports as too-short rather than being mislabelled a hallucination. One rule, two callers:
`replay()` in the eval harness scores recall by slug and has no report to write, so it keeps using
the predicate.

`ScanSummary.unverified` becomes a property over the recorded list rather than a counter tallied
beside it, so the printed summary line and the report cannot disagree about how many were rejected.

The `rejected` block is always present, empty or not — the same rule as the unwritten sidecar, for
the same reason. A block that appears only when non-empty makes its absence ambiguous between "none
were rejected" and "this run predates the feature".

The block covers only the pages a run actually scanned. A page already `ok` in the ledger is
skipped before the attempt runs (`run.py:111`), so it contributes neither verified candidates nor
rejections. This is inherited behaviour, not new, but it means the report describes one run rather
than one book — and it is worth knowing that the same limitation applies to the index itself, which
is a separate and larger problem than this record addresses.

Nothing here changes what reaches the index. The gate is unchanged; only its bookkeeping is.
