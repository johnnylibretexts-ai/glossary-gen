import json

from glossary_gen.ledger import Ledger
from glossary_gen.llm import LLMTransportError, RawResult
from glossary_gen.models import Block, Page, slugify
from glossary_gen.scan.candidates import (
    is_rebuildable,
    stale_page_count,
    terms_from_ledger,
)
from glossary_gen.scan.models import Rejection, ScanRecord
from glossary_gen.scan.propose import load_scan_prompt
from glossary_gen.scan_cli import estimate_scan_cost, execute

PAGE = Page(
    url="https://eng.libretexts.org/a",
    blocks=(
        Block(kind="heading", text="Recursion"),
        Block(kind="paragraph", text="Recursion is a technique where a function calls itself."),
    ),
)
# A distinct URL (and therefore a distinct ledger subject) from PAGE. A real book never
# produces two pages with the same URL — reusing PAGE for a second slot in a list would
# silently test "one page listed twice" instead of "two pages", which is a different
# (and undefined) scenario for the resume-key logic.
PAGE2 = Page(
    url="https://eng.libretexts.org/b",
    blocks=(
        Block(kind="heading", text="Recursion"),
        Block(kind="paragraph", text="Recursion is a technique where a function calls itself."),
    ),
)
# A genuinely contentless page (e.g. "Index", "Table of Contents", "Detailed
# Licensing" — see the 136-page measurement in article.py): its container held
# only scripts/divs/a footer, so extract_content -> parse_page yields zero blocks.
EMPTY_PAGE = Page(url="https://eng.libretexts.org/index", blocks=())

GOOD = (
    '{"terms": [{"term": "Recursion", "aliases": [], '
    '"evidence": "Recursion is a technique where a function calls itself.", '
    '"confidence": 0.8}]}'
)
HALLUCINATED = (
    '{"terms": [{"term": "Monad", "aliases": [], '
    '"evidence": "A monad is a monoid in the category of endofunctors.", '
    '"confidence": 0.9}]}'
)
# A well-formed JSON object missing the required "terms" key. `propose_terms` retries
# this (default retries=2, so 3 attempts total) and then raises LLMStructuredOutputError
# — the failure path whose billed tokens must not vanish.
BAD = '{"no_terms_key": true}'


class _FakeClient:
    name = "fake"
    model = "fake-model"

    def __init__(self, replies):
        self._replies = list(replies)
        self.calls = 0

    def complete_raw(self, prompt):
        self.calls += 1
        return RawResult(
            text=self._replies.pop(0),
            model=self.model,
            provider=self.name,
            tokens_in=100,
            tokens_out=20,
        )


class _TransportFailClient:
    """Every call raises LLMTransportError before any RawResult exists — there is
    nothing to bill, so 0 tokens is the correct outcome here, not a gap in the fix.
    """

    name = "fake-transport"
    model = "fake-model"

    def __init__(self):
        self.calls = 0

    def complete_raw(self, prompt):
        self.calls += 1
        raise LLMTransportError("boom")


def _ledger(tmp_path):
    # Same completion rule the CLI uses, so tests cannot pass under a laxer one.
    return Ledger(tmp_path / "scan.jsonl", record_cls=ScanRecord, is_done=is_rebuildable)


def test_execute_keeps_a_verified_candidate(tmp_path):
    summary = execute([PAGE], _FakeClient([GOOD]), _ledger(tmp_path), load_scan_prompt("v1"), "v1")

    assert summary.ok == 1
    assert [c.term for c in summary.candidates] == ["Recursion"]


def test_execute_drops_a_candidate_whose_evidence_is_absent(tmp_path):
    summary = execute(
        [PAGE], _FakeClient([HALLUCINATED]), _ledger(tmp_path), load_scan_prompt("v1"), "v1"
    )

    assert summary.candidates == []
    assert summary.unverified == 1


def test_a_page_with_no_terms_is_ok_not_a_failure(tmp_path):
    ledger = _ledger(tmp_path)
    summary = execute([PAGE], _FakeClient(['{"terms": []}']), ledger, load_scan_prompt("v1"), "v1")

    assert summary.ok == 1
    assert ledger.records()[0].status == "ok"
    assert ledger.records()[0].n_proposed == 0


def test_a_term_free_page_is_not_rescanned_on_resume(tmp_path):
    path = tmp_path / "scan.jsonl"
    template = load_scan_prompt("v1")
    execute(
        [PAGE],
        _FakeClient(['{"terms": []}']),
        Ledger(path, record_cls=ScanRecord),
        template,
        "v1",
    )

    client = _FakeClient([])
    summary = execute([PAGE], client, Ledger(path, record_cls=ScanRecord), template, "v1")

    assert client.calls == 0
    assert summary.skipped == 1


def test_a_page_with_no_blocks_is_skipped_without_calling_the_client(tmp_path):
    """A contentless page (Index, ToC, Detailed Licensing) must not cost a paid call —
    it is skipped before `propose_terms` is ever reached.
    """
    ledger = _ledger(tmp_path)
    client = _FakeClient([])
    summary = execute([EMPTY_PAGE], client, ledger, load_scan_prompt("v1"), "v1")

    assert client.calls == 0
    assert summary.ok == 1
    assert summary.empty_pages == 1
    record = ledger.records()[0]
    assert record.status == "ok"
    assert record.n_proposed == 0
    assert record.n_verified == 0
    assert record.tokens_in == 0
    assert record.tokens_out == 0


def test_a_resumed_run_does_not_recheck_an_empty_page(tmp_path):
    path = tmp_path / "scan.jsonl"
    template = load_scan_prompt("v1")
    execute([EMPTY_PAGE], _FakeClient([]), Ledger(path, record_cls=ScanRecord), template, "v1")

    resumed_client = _FakeClient([])
    summary = execute(
        [EMPTY_PAGE], resumed_client, Ledger(path, record_cls=ScanRecord), template, "v1"
    )

    assert resumed_client.calls == 0
    assert summary.skipped == 1
    assert summary.empty_pages == 0  # this run skipped via resume, not the empty-page path


def test_budget_ceiling_stops_the_run(tmp_path):
    # The client's model MUST be one that prices.json prices. `actual_cost` returns None
    # for an unpriced model, and the ceiling check short-circuits on None — so a fake
    # model name would make this test silently pass through the guard it means to prove.
    # Two DISTINCT pages, not the same Page object twice: a repeated object slugifies to
    # the same ledger key, so the second entry would be resumed as already-done instead
    # of reaching the budget check at all.
    client = _FakeClient([GOOD, GOOD])
    client.model = "gemini-3.5-flash"
    summary = execute(
        [PAGE, PAGE2], client, _ledger(tmp_path), load_scan_prompt("v1"), "v1", budget_usd=0.0
    )

    assert summary.aborted is True
    assert summary.ok == 1  # first page ran, second was stopped by the ceiling


def test_a_resumed_run_already_over_budget_still_finishes_already_done_pages(tmp_path):
    """--budget-usd ceilings SPEND, not existence of prior spend. A page already `ok` in
    the ledger costs nothing to skip, so a resumed run whose recorded spend already
    exceeds the ceiling must still be able to walk past every already-done page (and
    report skipped, not aborted) rather than refusing to finish at all. Pins the resume
    check running BEFORE the budget check — reversing that order would make this abort
    with zero work left to do, and zero pages already-priced-and-paid-for could ever be
    merged and emitted again.
    """
    path = tmp_path / "scan.jsonl"
    template = load_scan_prompt("v1")
    priming_client = _FakeClient([GOOD, GOOD])
    priming_client.model = "gemini-3.5-flash"
    execute(
        [PAGE, PAGE2],
        priming_client,
        Ledger(path, record_cls=ScanRecord),
        template,
        "v1",
    )  # no budget_usd here: just get both pages recorded `ok` with real token counts

    resumed_client = _FakeClient([])
    resumed_client.model = "gemini-3.5-flash"
    summary = execute(
        [PAGE, PAGE2],
        resumed_client,
        Ledger(path, record_cls=ScanRecord),
        template,
        "v1",
        budget_usd=0.0,  # already exceeded by the priming run's recorded spend
    )

    assert summary.skipped == 2
    assert summary.aborted is False
    assert resumed_client.calls == 0


def test_a_page_that_fails_every_attempt_records_its_real_token_cost(tmp_path):
    """Spend from FAILED calls must not be invisible. Three attempts (the default retry
    budget) at 100 tokens_in / 20 tokens_out each must total 300/60 on the llm_error
    ledger row, not 0 — providers generally bill input tokens even for a malformed
    reply, and a call that got far enough to receive a reply is real spend.
    """
    ledger = _ledger(tmp_path)
    client = _FakeClient([BAD, BAD, BAD])
    summary = execute([PAGE], client, ledger, load_scan_prompt("v1"), "v1")

    assert summary.llm_error == 1
    assert client.calls == 3
    record = ledger.records()[0]
    assert record.status == "llm_error"
    assert record.tokens_in == 300
    assert record.tokens_out == 60


def test_budget_ceiling_trips_on_a_run_of_only_failures(tmp_path):
    """THE DEFECT THIS FIX CLOSES: without accumulating tokens from failed attempts, a
    run that never succeeds reports $0 tracked spend and can never trip --budget-usd,
    however many billed retries it burns through. This test fails against the
    pre-fix code (aborted stays False, both pages exhaust every retry, llm_error == 2).
    """
    client = _FakeClient([BAD, BAD, BAD, BAD, BAD, BAD])
    client.model = "gemini-3.5-flash"
    # First page's 3 failed attempts cost (300*1.5 + 60*9.0) / 1e6 = $0.00099 — comfortably
    # over this ceiling, so the second page must never be attempted.
    summary = execute(
        [PAGE, PAGE2],
        client,
        _ledger(tmp_path),
        load_scan_prompt("v1"),
        "v1",
        budget_usd=0.0001,
    )

    assert summary.aborted is True
    assert summary.llm_error == 1
    assert client.calls == 3


def test_a_resumed_run_seeds_spend_from_llm_error_rows_too(tmp_path):
    """The budget seed on resume sums every ledger record's tokens, not just `ok` ones
    (`Ledger.records()` returns all statuses) — but that only carries real spend if the
    llm_error row itself was written with non-zero tokens. Pins both halves together.
    """
    path = tmp_path / "scan.jsonl"
    template = load_scan_prompt("v1")
    priming_client = _FakeClient([BAD, BAD, BAD])
    priming_client.model = "gemini-3.5-flash"
    execute([PAGE], priming_client, Ledger(path, record_cls=ScanRecord), template, "v1")
    # Ledger now holds one llm_error row worth 300 tokens_in / 60 tokens_out, no ok rows.

    resumed_client = _FakeClient([])
    resumed_client.model = "gemini-3.5-flash"
    summary = execute(
        [PAGE2],
        resumed_client,
        Ledger(path, record_cls=ScanRecord),
        template,
        "v1",
        budget_usd=0.0001,  # already exceeded by the priming run's llm_error spend
    )

    assert summary.aborted is True
    assert resumed_client.calls == 0


def test_a_transport_error_records_zero_tokens_without_crashing(tmp_path):
    """A transport error is raised by complete_raw itself, before any RawResult exists
    — there is nothing to bill. `getattr(exc, "tokens_in", 0)` must not crash on an
    LLMTransportError, which never gets propose_terms's tokens_in/tokens_out attached.
    """
    ledger = _ledger(tmp_path)
    client = _TransportFailClient()
    summary = execute([PAGE], client, ledger, load_scan_prompt("v1"), "v1")

    assert summary.llm_error == 1
    assert client.calls == 1  # LLMTransportError is not retried inside propose_terms
    record = ledger.records()[0]
    assert record.tokens_in == 0
    assert record.tokens_out == 0


def test_an_empty_article_neither_trips_nor_clears_the_failure_counter(tmp_path):
    """The generator's twin: a page with no article is skipped before any paid call, so it
    must be transparent to the consecutive-failure counter — neither a provider failure nor
    evidence of recovery. Two failures either side of one must still stop on the third.

    Pinned before the run is extracted, because a two-valued outcome cannot express
    "untouched" and would silently buy a fourth failed call.
    """
    pages = [
        Page(url=f"https://eng.libretexts.org/p{i}", blocks=() if i == 2 else PAGE.blocks)
        for i in range(5)
    ]
    client = _TransportFailClient()

    summary = execute(
        pages,
        client,
        _ledger(tmp_path),
        load_scan_prompt("v1"),
        "v1",
        max_consecutive_failures=3,
    )

    assert summary.aborted is True
    assert summary.llm_error == 3
    assert summary.empty_pages == 1
    assert client.calls == 3  # the fifth page was never reached


def test_a_final_page_that_crosses_the_ceiling_still_aborts(tmp_path):
    """A top-of-loop ceiling check needs a NEXT page to fire, and the last page has none.

    A scan whose final page crosses --budget-usd used to report success and exit 0, so the
    overspend was invisible until someone read the ledger. The generator has caught this
    since a62b3d6; the scanner never has, because its check ran only before each page.

    _FakeClient bills 100 in / 20 out, which is $0.00008 at gemini-3.5-flash rates — over
    the $0.00 ceiling here, and the page is the only one in the run.
    """
    client = _FakeClient([GOOD])
    client.model = "gemini-3.5-flash"

    summary = execute(
        [PAGE], client, _ledger(tmp_path), load_scan_prompt("v1"), "v1", budget_usd=0.0
    )

    assert summary.ok == 1  # the page itself completed
    assert summary.aborted is True


def test_estimate_scan_cost_returns_none_for_an_unpriced_model():
    assert estimate_scan_cost("no-such-model", 100, {}) is None


# Same pinning as the generation estimate, from the same run: 136 pages cost 140,809
# tokens in / 16,821 out on gemini-3.7-flash.
MEASURED_SCAN_PAGES = 136
MEASURED_SCAN_TOKENS_IN = 140_809
MEASURED_SCAN_TOKENS_OUT = 16_821


def test_scan_estimate_tracks_the_measured_run():
    prices = {"m": {"input_per_mtok": 1.0, "output_per_mtok": 1.0}}
    estimated = estimate_scan_cost("m", MEASURED_SCAN_PAGES, prices)
    actual = (MEASURED_SCAN_TOKENS_IN + MEASURED_SCAN_TOKENS_OUT) / 1_000_000
    # A band, not an upper bound: the estimator is calibrated on one book and cannot
    # guarantee it exceeds the actual on another. This catches a skew, not a miss.
    assert 0.9 * actual <= estimated <= 1.25 * actual, f"{estimated} vs {actual}"


def test_a_dropped_candidate_is_recorded_with_its_reason(tmp_path):
    """Dropping it from the index is the gate working. Writing it nowhere is the part
    ADR-0007 changes — the count alone cannot tell you the model started inventing spans.
    """
    summary = execute(
        [PAGE], _FakeClient([HALLUCINATED]), _ledger(tmp_path), load_scan_prompt("v1"), "v1"
    )

    assert summary.candidates == []
    assert len(summary.rejected) == 1
    dropped = summary.rejected[0]
    assert dropped.term == "Monad"
    assert dropped.reason is Rejection.EVIDENCE_NOT_ON_PAGE
    assert dropped.page_url == PAGE.url
    # The invented span is kept verbatim — when the reason is a hallucination, the text the
    # model fabricated is the whole reason to keep the row.
    assert dropped.evidence == "A monad is a monoid in the category of endofunctors."


def test_unverified_counts_exactly_the_recorded_rejections(tmp_path):
    """One source of truth: the printed count is derived from the list, not tallied beside
    it, so the summary line and the report cannot disagree about how many were rejected.
    """
    summary = execute(
        [PAGE], _FakeClient([HALLUCINATED]), _ledger(tmp_path), load_scan_prompt("v1"), "v1"
    )
    assert summary.unverified == len(summary.rejected) == 1


def test_a_verified_run_records_no_rejections(tmp_path):
    summary = execute([PAGE], _FakeClient([GOOD]), _ledger(tmp_path), load_scan_prompt("v1"), "v1")
    assert summary.rejected == []
    assert summary.unverified == 0


# --- resume must not lose what the first run paid for -----------------------------------

# Proposes a DIFFERENT term from `GOOD`, with a span that is genuinely on PAGE2, so a lost
# page is visible as a missing term rather than hidden by a duplicate slug.
GOOD_OTHER_TERM = (
    '{"terms": [{"term": "Base case", "aliases": [], '
    '"evidence": "Recursion is a technique where a function calls itself.", '
    '"confidence": 0.7}]}'
)


def test_a_resumed_scan_still_indexes_the_page_the_first_run_paid_for(tmp_path):
    """The silent half of the defect: a partial resume writes a partial index.

    The ledger's job is "never pay twice". It is not "forget what the first payment bought".
    A page already `ok` is skipped at run.py:111 before `attempt()` runs, so its verified
    candidates never reach `summary.candidates` — and the index is built from that list.
    """
    ledger = _ledger(tmp_path)
    first = execute([PAGE], _FakeClient([GOOD]), ledger, load_scan_prompt("v1"), "v1")
    assert [c.term for c in first.candidates] == ["Recursion"]

    resumed = execute(
        [PAGE, PAGE2], _FakeClient([GOOD_OTHER_TERM]), ledger, load_scan_prompt("v1"), "v1"
    )
    assert resumed.skipped == 1  # PAGE was already paid for
    assert resumed.ok == 1  # only PAGE2 was scanned

    # Asserted on the rebuild path, not on `summary.candidates`: the summary is honestly
    # a per-run accumulator. What must describe the whole book is the index.
    rebuilt = terms_from_ledger(ledger.records())
    assert sorted(t.term for t in rebuilt) == ["Base case", "Recursion"]


def test_a_second_scan_is_free_and_reproduces_the_index(tmp_path):
    """The loud half, and the guarantee the generator already has.

    `glossary-gen` re-runs free and rebuilds the identical CSV because `write_csv` reads
    `ledger.records()` — the durable, complete record. The scanner builds its index from an
    in-memory per-run accumulator instead, so a fully-resumed scan produces nothing at all
    and `index_payload` raises rather than writing a book's index.
    """
    ledger = _ledger(tmp_path)
    first = execute(
        [PAGE, PAGE2], _FakeClient([GOOD, GOOD_OTHER_TERM]), ledger, load_scan_prompt("v1"), "v1"
    )
    second = execute([PAGE, PAGE2], _FakeClient([]), ledger, load_scan_prompt("v1"), "v1")

    assert second.skipped == 2  # free, as intended
    assert first.ok == 2
    assert [t.term for t in terms_from_ledger(ledger.records())] == ["Base case", "Recursion"]


def test_a_row_from_before_candidate_storage_is_rescanned(tmp_path):
    """The compatibility rule. An `ok` row that cannot say what its page yielded is not
    done: re-paying for it once is the only way to rebuild a correct index, and the
    alternative is emitting a partial one forever.
    """
    path = tmp_path / "scan.jsonl"
    # Exactly what the pre-fix writer produced: no `candidates` key at all.
    old_row = {
        "subject": slugify(PAGE.url),
        "page_url": PAGE.url,
        "prompt_version": "v1",
        "model": "fake-model",
        "generated_at": "2026-08-16T00:00:00Z",
        "status": "ok",
        "n_proposed": 1,
        "n_verified": 1,
    }
    path.write_text(json.dumps(old_row) + "\n", encoding="utf-8")

    ledger = Ledger(path, record_cls=ScanRecord, is_done=is_rebuildable)
    summary = execute([PAGE], _FakeClient([GOOD]), ledger, load_scan_prompt("v1"), "v1")

    assert summary.skipped == 0  # re-scanned rather than trusted
    assert summary.ok == 1
    assert [t.term for t in terms_from_ledger(ledger.records())] == ["Recursion"]


def test_a_page_that_genuinely_found_nothing_is_never_rescanned(tmp_path):
    """The other side of the same rule, and why `None` and `[]` must stay distinct.

    A page scanned to completion that defined no terms is a complete answer. Inferring
    staleness from `n_verified == 0` instead would make it indistinguishable from a pre-fix
    row and re-pay for every term-free page on every resume, forever.
    """
    path = tmp_path / "scan.jsonl"
    first = Ledger(path, record_cls=ScanRecord, is_done=is_rebuildable)
    execute([PAGE], _FakeClient(['{"terms": []}']), first, load_scan_prompt("v1"), "v1")

    resumed = Ledger(path, record_cls=ScanRecord, is_done=is_rebuildable)
    summary = execute([PAGE], _FakeClient([]), resumed, load_scan_prompt("v1"), "v1")
    assert summary.skipped == 1  # free, and correctly so


def test_an_empty_page_is_never_rescanned_either(tmp_path):
    """A contentless page (Index, Licensing) is scanned without a model call and yields
    nothing. That is also a complete answer, so its row stores `[]`, not `None`.
    """
    path = tmp_path / "scan.jsonl"
    first = Ledger(path, record_cls=ScanRecord, is_done=is_rebuildable)
    execute([EMPTY_PAGE], _FakeClient([]), first, load_scan_prompt("v1"), "v1")

    resumed = Ledger(path, record_cls=ScanRecord, is_done=is_rebuildable)
    summary = execute([EMPTY_PAGE], _FakeClient([]), resumed, load_scan_prompt("v1"), "v1")
    assert summary.skipped == 1


def test_the_stale_note_stops_firing_once_a_page_has_been_rescanned(tmp_path):
    """The ledger is append-only, so a re-scanned page keeps its old row beside the new one.
    Counting rows would announce "N pages must be re-scanned" forever on a ledger where
    nothing needs it — the note would outlive the condition it reports.
    """
    path = tmp_path / "scan.jsonl"
    old_row = {
        "subject": slugify(PAGE.url),
        "page_url": PAGE.url,
        "prompt_version": "v1",
        "model": "fake-model",
        "generated_at": "2026-08-16T00:00:00Z",
        "status": "ok",
        "n_proposed": 1,
        "n_verified": 1,
    }
    path.write_text(json.dumps(old_row) + "\n", encoding="utf-8")

    ledger = Ledger(path, record_cls=ScanRecord, is_done=is_rebuildable)
    assert stale_page_count(ledger.records()) == 1  # before: one page to re-scan

    execute([PAGE], _FakeClient([GOOD]), ledger, load_scan_prompt("v1"), "v1")

    after = Ledger(path, record_cls=ScanRecord, is_done=is_rebuildable)
    assert len(after.records()) == 2  # the old row is still there
    assert stale_page_count(after.records()) == 0  # but the page no longer needs scanning


# --- the book's own glossary page -------------------------------------------

GLOSSARY_PAGE = Page(
    url="https://eng.libretexts.org/back-matter/glossary",
    blocks=(
        Block(kind="heading", text="Glossary"),
        Block(kind="paragraph", text="A technique where a function calls itself."),
    ),
)


def test_the_books_own_glossary_page_is_recorded_without_paying_for_it(tmp_path):
    """It has blocks, so the empty-page path does not catch it, and every one of them
    is a definition whose term `parse_page` dropped. Measured: 100 such paragraphs cost
    2,580 input tokens and returned 0 candidates. The row is still written, and `ok`,
    for two reasons — a resumed run must not re-pay for it, and `harvest_glossary
    --scan` reads its page list to find the very page the glossary is on.
    """
    client = _FakeClient([])
    ledger = _ledger(tmp_path)

    summary = execute(
        [GLOSSARY_PAGE],
        client,
        ledger,
        load_scan_prompt("v1"),
        "v1",
        glossary_pages={GLOSSARY_PAGE.url},
    )

    assert client.calls == 0
    assert (summary.ok, summary.glossary_pages, summary.empty_pages) == (1, 1, 0)
    record = ledger.records()[0]
    assert (record.status, record.n_proposed, record.tokens_in) == ("ok", 0, 0)
    assert [r.page_url for r in ledger.records()] == [GLOSSARY_PAGE.url]


def test_a_page_not_named_a_glossary_is_still_scanned(tmp_path):
    """The skip is by URL, and only the URLs `collect_pages` recognised."""
    summary = execute(
        [PAGE],
        _FakeClient([GOOD]),
        _ledger(tmp_path),
        load_scan_prompt("v1"),
        "v1",
        glossary_pages={GLOSSARY_PAGE.url},
    )

    assert (summary.ok, summary.glossary_pages) == (1, 0)
