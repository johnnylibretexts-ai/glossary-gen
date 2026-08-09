from glossary_gen.ledger import Ledger
from glossary_gen.llm import LLMTransportError, RawResult
from glossary_gen.models import Block, Page
from glossary_gen.scan.models import ScanRecord
from glossary_gen.scan.propose import load_scan_prompt
from glossary_gen.scan_cli import estimate_scan_cost, execute

PAGE = Page(
    url="https://eng.libretexts.org/a",
    blocks=(
        Block(kind="heading", text="Recursion"),
        Block(kind="paragraph", text="Recursion is a technique where a function calls itself."),
    ),
)
# A distinct URL (and therefore a distinct ledger slug) from PAGE. A real book never
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
# Licensing" — see the 136-page measurement in scan/content.py): its container held
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
    return Ledger(tmp_path / "scan.jsonl", record_cls=ScanRecord)


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
    # First page's 3 failed attempts cost (300*0.3 + 60*2.5) / 1e6 = $0.00024 — comfortably
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


def test_estimate_scan_cost_returns_none_for_an_unpriced_model():
    assert estimate_scan_cost("no-such-model", 100, {}) is None
