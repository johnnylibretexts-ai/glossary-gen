import httpx
import pytest

from glossary_gen.cli import (
    RunSummary,
    actual_cost,
    build_parser,
    estimate_cost,
    execute,
    load_prices,
)
from glossary_gen.fetch import PageCache
from glossary_gen.generate import load_prompt
from glossary_gen.ledger import Ledger, LedgerRecord
from glossary_gen.llm import LLMResult, LLMTransportError, ProviderChain
from glossary_gen.models import GlossaryEntry, Term

HTML_HIT = "<html><body><p>Recursion is a technique.</p></body></html>"
HTML_MISS = "<html><body><p>Nothing relevant.</p></body></html>"


class StubClient:
    name = "stub"
    model = "test-model"

    def __init__(self, outcomes):
        self._outcomes = list(outcomes)
        self.calls = 0

    def complete(self, prompt):
        self.calls += 1
        outcome = self._outcomes.pop(0) if self._outcomes else self._default()
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    @staticmethod
    def _default():
        return LLMResult(
            entry=GlossaryEntry(definition="d"),
            model="test-model",
            provider="stub",
            tokens_in=10,
            tokens_out=5,
        )


class NamedModelStubClient:
    """An LLMClient stub with an independently settable `.model`, for testing chain
    fallback: the declared primary and the model that actually serves a call can differ.
    """

    def __init__(self, name, model, outcomes):
        self.name = name
        self.model = model
        self._outcomes = list(outcomes)
        self.calls = 0

    def complete(self, prompt):
        self.calls += 1
        outcome = self._outcomes.pop(0) if self._outcomes else self._default()
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def _default(self):
        return LLMResult(
            entry=GlossaryEntry(definition="d"),
            model=self.model,
            provider=self.name,
            tokens_in=10,
            tokens_out=5,
        )


def make_cache(tmp_path, routes):
    def handler(request):
        url = str(request.url)
        return httpx.Response(200, text=routes[url]) if url in routes else httpx.Response(404)

    return PageCache(tmp_path / "cache", httpx.Client(transport=httpx.MockTransport(handler)))


def term(slug, url):
    return Term(term="Recursion", slug=slug, aliases=(), pages=(url,))


def run_execute(tmp_path, terms, routes, client, **kwargs):
    return execute(
        terms,
        make_cache(tmp_path, routes),
        client,
        Ledger(tmp_path / "run.jsonl"),
        load_prompt("v1"),
        "v1",
        **kwargs,
    )


def test_successful_term_is_recorded_ok(tmp_path):
    routes = {"https://eng.libretexts.org/a": HTML_HIT}
    summary = run_execute(
        tmp_path, [term("t1", "https://eng.libretexts.org/a")], routes, StubClient([])
    )
    assert summary == RunSummary(
        ok=1, no_excerpt=0, fetch_error=0, llm_error=0, skipped=0, aborted=False
    )


def test_term_without_excerpt_costs_no_llm_call(tmp_path):
    routes = {"https://eng.libretexts.org/a": HTML_MISS}
    client = StubClient([])
    summary = run_execute(tmp_path, [term("t1", "https://eng.libretexts.org/a")], routes, client)
    assert summary.no_excerpt == 1
    assert client.calls == 0


def test_unfetchable_page_is_fetch_error(tmp_path):
    client = StubClient([])
    summary = run_execute(tmp_path, [term("t1", "https://eng.libretexts.org/gone")], {}, client)
    assert summary.fetch_error == 1
    assert client.calls == 0


def test_already_ledgered_term_is_skipped(tmp_path):
    routes = {"https://eng.libretexts.org/a": HTML_HIT}
    terms = [term("t1", "https://eng.libretexts.org/a")]
    first = StubClient([])
    execute(
        terms,
        make_cache(tmp_path, routes),
        first,
        Ledger(tmp_path / "run.jsonl"),
        load_prompt("v1"),
        "v1",
    )
    second = StubClient([])
    summary = execute(
        terms,
        make_cache(tmp_path, routes),
        second,
        Ledger(tmp_path / "run.jsonl"),
        load_prompt("v1"),
        "v1",
    )
    assert summary.skipped == 1
    assert second.calls == 0


def test_run_aborts_after_five_consecutive_provider_failures(tmp_path):
    routes = {f"https://eng.libretexts.org/p{i}": HTML_HIT for i in range(10)}
    terms = [term(f"t{i}", f"https://eng.libretexts.org/p{i}") for i in range(10)]
    client = StubClient([LLMTransportError("down")] * 10)
    summary = run_execute(tmp_path, terms, routes, client, max_consecutive_failures=5)
    assert summary.aborted is True
    assert client.calls == 5


def test_consecutive_failure_counter_resets_on_success(tmp_path):
    routes = {f"https://eng.libretexts.org/p{i}": HTML_HIT for i in range(6)}
    terms = [term(f"t{i}", f"https://eng.libretexts.org/p{i}") for i in range(6)]
    outcomes = [LLMTransportError("x")] * 4 + [StubClient._default()] + [LLMTransportError("x")] * 1
    client = StubClient(outcomes)
    summary = run_execute(tmp_path, terms, routes, client, max_consecutive_failures=5)
    assert summary.aborted is False
    assert summary.ok == 1


def test_estimate_cost_returns_none_for_unpriced_model():
    assert estimate_cost("mystery-model", 100, load_prices()) is None


def test_estimate_cost_scales_with_term_count():
    prices = load_prices()
    one = estimate_cost("gemini-3.5-flash", 1, prices)
    hundred = estimate_cost("gemini-3.5-flash", 100, prices)
    assert one is not None and hundred is not None
    assert hundred == pytest.approx(one * 100)


def test_actual_cost_returns_none_for_unpriced_model():
    assert actual_cost("mystery-model", 1_000, 1_000, load_prices()) is None


def test_actual_cost_scales_with_real_token_counts():
    prices = load_prices()
    small = actual_cost("gemini-3.5-flash", 100, 100, prices)
    large = actual_cost("gemini-3.5-flash", 1_000, 1_000, prices)
    assert small is not None and large is not None
    assert large == pytest.approx(small * 10)


def test_failed_term_is_retried_on_second_run(tmp_path):
    """A term that fails does not get treated as done — the resumability rule lives in
    Ledger.has(), which only counts `ok` records; execute() just consults it.
    """
    routes = {"https://eng.libretexts.org/a": HTML_HIT}
    terms = [term("t1", "https://eng.libretexts.org/a")]
    ledger_path = tmp_path / "run.jsonl"

    first = StubClient([LLMTransportError("down")])
    first_summary = execute(
        terms,
        make_cache(tmp_path, routes),
        first,
        Ledger(ledger_path),
        load_prompt("v1"),
        "v1",
    )
    assert first_summary.llm_error == 1
    assert first_summary.skipped == 0

    second = StubClient([])
    second_summary = execute(
        terms,
        make_cache(tmp_path, routes),
        second,
        Ledger(ledger_path),
        load_prompt("v1"),
        "v1",
    )
    assert second_summary.ok == 1
    assert second_summary.skipped == 0
    assert second.calls == 1


def test_budget_check_uses_actual_tokens_not_flat_estimate(tmp_path):
    """The mid-run budget check must price real accumulated tokens, not the flat
    per-term guess used for the pre-run estimate — otherwise it can only ever trip at
    the same term count the pre-run estimate already predicted.
    """
    routes = {f"https://eng.libretexts.org/p{i}": HTML_HIT for i in range(5)}
    terms = [term(f"t{i}", f"https://eng.libretexts.org/p{i}") for i in range(5)]

    def huge_result():
        return LLMResult(
            entry=GlossaryEntry(definition="d"),
            model="gemini-3.5-flash",
            provider="stub",
            tokens_in=1_000_000,
            tokens_out=1_000_000,
        )

    client = StubClient([huge_result() for _ in range(5)])
    client.model = "gemini-3.5-flash"  # a priced model

    # The flat, pre-run-style estimate for all 5 terms is well under $1 — if the
    # mid-run check still used it (flat-per-term * successes-so-far), it would never
    # trip across this whole run. Only real per-call token counts can trip it this fast.
    flat_five_term_estimate = estimate_cost("gemini-3.5-flash", 5, load_prices())
    assert flat_five_term_estimate < 1.0

    summary = run_execute(tmp_path, terms, routes, client, budget_usd=1.0)

    assert summary.aborted is True
    assert summary.ok == 1
    assert client.calls == 1


def test_ledger_records_declared_primary_even_when_fallback_serves(tmp_path):
    """Guards the property this task was explicitly warned about: `model` on the ledger
    row must stay the chain's declared primary (the resume key `Ledger.has()` looks
    up), even when a fallback client actually serves the call. `served_by_model` carries
    the model that really answered. This uses a real two-client ProviderChain and a real
    Ledger — not stubs of the chain's own resume-key logic — so reintroducing
    `model=result.model` in the ok branch would fail this test.
    """
    routes = {"https://eng.libretexts.org/a": HTML_HIT}
    terms = [term("t1", "https://eng.libretexts.org/a")]
    ledger_path = tmp_path / "run.jsonl"

    primary = NamedModelStubClient("primary", "primary-model", [LLMTransportError("down")])
    secondary = NamedModelStubClient("secondary", "secondary-model", [])
    chain = ProviderChain([primary, secondary])

    summary = execute(
        terms,
        make_cache(tmp_path, routes),
        chain,
        Ledger(ledger_path),
        load_prompt("v1"),
        "v1",
    )
    assert summary.ok == 1

    record = Ledger(ledger_path).records()[0]
    assert record.model == "primary-model"  # declared primary, unchanged by who served it
    assert record.served_by_model == "secondary-model"  # who actually answered

    # A fresh chain with the SAME declared primary must resume-skip, not regenerate.
    second_primary = NamedModelStubClient("primary", "primary-model", [])
    second_secondary = NamedModelStubClient("secondary", "secondary-model", [])
    second_chain = ProviderChain([second_primary, second_secondary])
    second_summary = execute(
        terms,
        make_cache(tmp_path, routes),
        second_chain,
        Ledger(ledger_path),
        load_prompt("v1"),
        "v1",
    )
    assert second_summary.skipped == 1
    assert second_primary.calls == 0
    assert second_secondary.calls == 0


def test_max_terms_zero_is_rejected_at_parse_time():
    """0 reads as "no limit" if left as a plain int — the opposite of what it should mean
    for a value this low — so the parser must reject it rather than running the whole book.
    """
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--input", "x.json", "--max-terms", "0"])


def test_max_terms_negative_is_rejected_at_parse_time():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--input", "x.json", "--max-terms", "-1"])


def test_max_terms_positive_is_accepted():
    args = build_parser().parse_args(["--input", "x.json", "--max-terms", "5"])
    assert args.max_terms == 5


def test_resumed_run_already_over_budget_aborts_without_calling_client(tmp_path):
    """The ceiling is total spend across resumes of this ledger, not per-invocation.
    A ledger that already holds enough `tokens_in`/`tokens_out` to exceed the budget
    (from a prior run, possibly on an unrelated term — the ledger is a single running
    total, not scoped per slug) must abort THIS run before doing any new work at all:
    no page fetch, no LLM call, for any term.
    """
    routes = {"https://eng.libretexts.org/a": HTML_HIT}
    terms = [term("t1", "https://eng.libretexts.org/a")]
    ledger_path = tmp_path / "run.jsonl"

    prior_ledger = Ledger(ledger_path)
    prior_ledger.append(
        LedgerRecord(
            subject="already-done",
            term="Already Done",
            prompt_version="v1",
            model="gemini-3.5-flash",
            generated_at="2026-08-01T00:00:00Z",
            status="ok",
            definition="d",
            tokens_in=1_000_000,
            tokens_out=1_000_000,
        )
    )

    client = StubClient([])
    client.model = "gemini-3.5-flash"  # a priced model
    summary = run_execute(tmp_path, terms, routes, client, budget_usd=1.0)

    assert summary.aborted is True
    assert summary.ok == 0
    assert client.calls == 0
