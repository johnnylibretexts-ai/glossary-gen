# The scanner's output is rebuilt from the ledger

A resumed `glossary-scan` wrote a partial index, silently. `run.py:111` skips a subject the
ledger already has, so `attempt()` never runs for it and its verified candidates never reach
`summary.candidates` — and the index was built from that list. Scan half a book with `--limit`,
run again, and the first half's terms are simply gone from `out/index.json`.

The scanner now stores what each page yielded on its `ScanRecord`, and builds both the index and
the diagnostic report from `ledger.records()`.

## Why only the scanner had this bug

`glossary-gen` has always been immune, and not by having remembered to be. `write_csv` reads
`ledger.records()` — the durable, complete record — so a term skipped on resume still has its row
on disk and still reaches the CSV. `LedgerRecord` stores the whole definition, so the ledger is
sufficient to rebuild the output.

`ScanRecord` stored `n_proposed` and `n_verified`: how many terms a page yielded, never which.
That made the ledger insufficient to rebuild anything, which forced the scanner to write from an
in-memory per-run accumulator, which is what made resume lossy. The two producers differed on the
one property that decides whether resumption is safe, and nothing named that property.

The property is: **a row must contain what the output needs, or resuming past it loses data.**

## Considered options

**Refuse to write a partial index** — detect that pages were skipped and error out. Rejected: it
converts silent damage into loud damage without making resumption work, and resumption is the
feature the ledger exists to provide.

**Re-derive candidates by re-scanning skipped pages.** That is not resumption; it is paying twice,
which is the one thing this project is built to avoid.

**Cache candidates in a separate per-page file** beside the page cache. Rejected: a second durable
store that must be kept in step with the ledger, with its own staleness and its own failure modes,
to hold data that belongs on the row that already exists.

**Infer staleness from `n_verified == 0`** rather than storing an explicit marker. Rejected as
wrong, not merely inelegant: a page that verified nothing and a page written before candidates
were stored are different facts. Conflating them re-pays for every term-free page on every resume,
forever — the exact bug `ScanRecord`'s own docstring says the `ok`-for-empty-pages rule exists to
prevent.

## Consequences

`candidates` and `rejected` are `None` on a row written before this change and a list on every row
after, including `[]`. `None` means "this row cannot say what its page found"; `[]` means "this
page was scanned and found nothing". Both are `ok`; only the first needs re-scanning. The
distinction has to be exact in both directions — treat `None` as complete and the index stays
partial, treat `[]` as incomplete and every empty page is re-paid for on every run.

`Ledger` gains an `is_done` predicate, defaulting to `status == "ok"`. The scanner passes one that
also requires candidates to be present. This keeps the ledger blind to what any of it means — it
asks the predicate and nothing more — while letting each producer state what its own row must
contain to count as finished. That is the same division ADR-0002 drew for the run: the producer
builds the row, so the producer knows when a row is enough.

Existing scan ledgers are all stale by this rule. `out/scan.jsonl`'s 136 rows are `ok` and none is
rebuildable, so the next scan re-scans the whole book once, at about $0.17, and every scan after
that resumes correctly. A run prints how many such pages it found before the spend confirmation,
so the re-pay is disclosed rather than discovered. Old rows are still read, never rewritten.

`ScanSummary.candidates` and `.rejected` survive as this run's view — what this invocation did, which
is what the summary line reports. The index and report no longer read them. Two lists that look
alike now mean different things, which is a cost: the summary describes an invocation, the ledger
describes a book.

The report's contents change on a resumed run, and for the better: ADR-0007 recorded that the
`rejected` block covered only the pages one run scanned. It now covers every page the ledger has,
so the diagnostic finally describes the book it claims to.
