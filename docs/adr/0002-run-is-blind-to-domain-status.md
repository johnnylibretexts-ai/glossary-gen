# The run is blind to domain status

Both commands walk a list of subjects paying for each one, and both implement the same seven
concerns to do it: seed spend from the ledger, skip a subject already done, refuse to start when
the ceiling is crossed, ask the model, charge what came back, record the attempt, and stop after
repeated failure. One **run** now owns all seven, generic over the subject the way `Ledger` already
is (ADR-0001).

What it deliberately does not own is anything the producers disagree about. The run never sees a
status — not `ok`, not `no_excerpt`, not `llm_error`. It learns only whether the model was
consulted and whether that call failed. Each producer builds its own ledger row and keeps its own
status counters; the run appends the row and returns the two numbers that are genuinely its own,
how many subjects it skipped and whether it stopped early.

## Considered options

**A run per producer**, which is what existed. Rejected on evidence rather than principle: the two
copies had already drifted on the behaviour that controls spend. One re-checked the ceiling after
paying and the other did not, so a scan whose final page crossed the ceiling reported success. Of
the eight fixes in `a62b3d6`, five were the same fix applied twice.

**A status-aware run** that reads `record.status` and returns the counters ready-made. Rejected
because it would have to hold both producers' vocabularies — one writes `no_excerpt` and
`fetch_error`, the other writes neither — and would grow an edit every time either gained a case.
It also cannot state the stop-after-repeated-failure rule without a table mapping every status to
one of three effects, which is a table that must be kept correct in a module that has no way to
know when it stops being.

## Consequences

The run distinguishes three outcomes of one subject, not two: the model answered, the model was
consulted and failed, or the model was never called. A boolean cannot express the third, and the
third is load-bearing. A term with no excerpt and a page with no article are already transparent
to the failure counter today — they neither raise it nor clear it — because they say nothing about
whether the model is healthy. Measured against the previous implementation: with the counter
transparent, two failures either side of an excerpt-less term stop the run on the third; were the
skip to clear the count, the run would pay for a fourth.

Because the producer builds the row and the run appends it, "one attempt, exactly one row, written
before the next subject is started" becomes a property of one module rather than a convention two
call sites are each trusted to keep. That is the guarantee resumption rests on, and it was
previously enforced only by the shape of two loops.

The cost is that a producer supplies two small functions — how to name a subject, and how to
attempt one — and that a future producer wanting run-level behaviour keyed on its own status
cannot have it without revisiting this decision. Nothing in either command needs that today, and a
run that changes behaviour based on domain vocabulary would be a run that has to be read alongside
every producer to be understood.
