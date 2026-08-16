import httpx
import pytest

from glossary_gen.cli import (
    RunSummary,
    actual_cost,
    build_client,
    build_parser,
    estimate_cost,
    execute,
    load_prices,
)
from glossary_gen.fetch import PageCache
from glossary_gen.generate import load_prompt
from glossary_gen.ledger import Ledger, LedgerRecord
from glossary_gen.llm import LLMResult, LLMTransportError, ProviderChain, RawResult
from glossary_gen.models import GlossaryEntry, Term

# Paragraphs are realistic length on purpose: `excerpts_for_term` refuses grounding
# under MIN_EXCERPT_CHARS, and a 24-character fixture paragraph was never a fair
# stand-in for a real book page.
_REAL_PARAGRAPH = (
    "Recursion is a technique where a function calls itself to solve a smaller "
    "instance of the same problem, continuing until it reaches a base case."
)
HTML_HIT = f"<html><body><p>{_REAL_PARAGRAPH}</p></body></html>"
HTML_MISS = "<html><body><p>Nothing relevant.</p></body></html>"


def _as_raw(outcome):
    """Render a scripted outcome as the reply a provider would actually have sent.

    The stubs script `LLMResult`s because that is what a test wants to say ("this term
    succeeds, billed 10/5"). `generate_entry` consumes `complete_raw`, so the scripted
    entry is serialised back to the JSON text a provider returns; an exception outcome
    is raised as-is.
    """
    if isinstance(outcome, Exception):
        raise outcome
    if isinstance(outcome, RawResult):
        return outcome  # scripted verbatim, for replies that must fail validation
    return RawResult(
        text=outcome.entry.model_dump_json(),
        model=outcome.model,
        provider=outcome.provider,
        tokens_in=outcome.tokens_in,
        tokens_out=outcome.tokens_out,
    )


class StubClient:
    name = "stub"
    model = "test-model"

    def __init__(self, outcomes):
        self._outcomes = list(outcomes)
        self.calls = 0

    def complete_raw(self, prompt):
        self.calls += 1
        return _as_raw(self._outcomes.pop(0) if self._outcomes else self._default())

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

    def complete_raw(self, prompt):
        self.calls += 1
        return _as_raw(self._outcomes.pop(0) if self._outcomes else self._default())

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


def test_a_term_with_no_excerpt_neither_trips_nor_clears_the_failure_counter(tmp_path):
    """A subject the model was never asked about says nothing about the model's health.

    The counter exists to stop paying a broken provider. A term whose pages yield no excerpt
    costs nothing and never reaches the client, so it must leave the count where it found it
    — not incrementing it (this is no provider failure) and not clearing it (this is no
    evidence the provider recovered). The same holds for an unfetchable page.

    Two failures either side of an excerpt-less term must therefore still stop on the third.
    Were the skip to clear the count, the run would pay for a fourth — which is exactly what
    a two-valued outcome would do, so this is pinned before the run is extracted rather than
    after.
    """
    routes = {f"https://eng.libretexts.org/p{i}": HTML_HIT for i in range(5)}
    routes["https://eng.libretexts.org/p2"] = HTML_MISS  # fetches fine, mentions no term
    terms = [term(f"t{i}", f"https://eng.libretexts.org/p{i}") for i in range(5)]
    client = StubClient([LLMTransportError("down")] * 4)

    summary = run_execute(tmp_path, terms, routes, client, max_consecutive_failures=3)

    assert summary.aborted is True
    assert summary.llm_error == 3
    assert summary.no_excerpt == 1
    assert client.calls == 3  # the fifth term was never reached


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


def _billed_garbage():
    """A reply the provider really sent and really billed for, that cannot validate."""
    return RawResult(
        text="not json", model="test-model", provider="stub", tokens_in=7, tokens_out=2
    )


def test_failed_term_records_what_its_attempts_cost(tmp_path):
    """An `llm_error` Attempt must carry the spend its attempts actually incurred.

    A zero here is not merely a missing datum. `execute` seeds its running total from
    `sum(r.tokens_in for r in ledger.records())` on every resume, so spend dropped here
    is invisible to `--budget-usd` for the life of the ledger. `scan_cli.execute` already
    records it. Three attempts at 7/2 apiece must land as 21/6.
    """
    cache = make_cache(tmp_path, {"https://eng.libretexts.org/a": HTML_HIT})
    client = StubClient([_billed_garbage(), _billed_garbage(), _billed_garbage()])
    ledger = Ledger(tmp_path / "run.jsonl")

    summary = execute(
        [term("recursion", "https://eng.libretexts.org/a")],
        cache,
        client,
        ledger,
        load_prompt("v1"),
        "v1",
    )

    assert summary.llm_error == 1
    record = ledger.records()[0]
    assert record.status == "llm_error"
    assert (record.tokens_in, record.tokens_out) == (21, 6)


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


def test_budget_ceiling_counts_spend_from_failed_terms(tmp_path):
    """Failed spend must charge against the ceiling within the run that incurred it.

    Recording it on the Attempt fixes resumed runs, since seeding sums the ledger. The
    running total is what stops the CURRENT run — and a failure that adds nothing to it
    lets a run which has already blown its ceiling carry on spending. Three attempts at
    1M/1M priced at gemini-3.5-flash is $8.40, well past the $1.00 ceiling, so the second
    term must never be attempted.
    """
    routes = {f"https://eng.libretexts.org/p{i}": HTML_HIT for i in range(2)}
    terms = [term(f"t{i}", f"https://eng.libretexts.org/p{i}") for i in range(2)]

    def huge_garbage():
        return RawResult(
            text="not json",
            model="gemini-3.5-flash",
            provider="stub",
            tokens_in=1_000_000,
            tokens_out=1_000_000,
        )

    # Six scripted replies: three for the first term, and three more the second term
    # would consume if the ceiling stayed blind to what the first one cost.
    client = StubClient([huge_garbage() for _ in range(6)])
    client.model = "gemini-3.5-flash"  # a priced model

    summary = execute(
        terms,
        make_cache(tmp_path, routes),
        client,
        Ledger(tmp_path / "run.jsonl"),
        load_prompt("v1"),
        "v1",
        budget_usd=1.0,
    )

    assert client.calls == 3
    assert summary.llm_error == 1
    assert summary.aborted is True


def test_budget_ceiling_trips_when_the_failing_term_is_the_last_one(tmp_path):
    """Going over must be reported even when there is no next term left to stop.

    The failure branch leans on the *next* iteration's top-of-loop check to notice the
    spend it just added, so a run whose final term blows the ceiling ends normally and
    `run()` exits 0 despite a ledger that shows the overspend. The success branch already
    checks at the bottom of the loop; this makes the two branches agree.
    """
    routes = {"https://eng.libretexts.org/a": HTML_HIT}

    def huge_garbage():
        return RawResult(
            text="not json",
            model="gemini-3.5-flash",
            provider="stub",
            tokens_in=1_000_000,
            tokens_out=1_000_000,
        )

    client = StubClient([huge_garbage() for _ in range(3)])
    client.model = "gemini-3.5-flash"  # a priced model

    summary = execute(
        [term("t0", "https://eng.libretexts.org/a")],  # the only term, and it fails
        make_cache(tmp_path, routes),
        client,
        Ledger(tmp_path / "run.jsonl"),
        load_prompt("v1"),
        "v1",
        budget_usd=1.0,
    )

    assert summary.llm_error == 1
    assert summary.aborted is True


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


def test_build_client_preserves_the_ledger_keys(monkeypatch):
    """Wrapping must not change `name`/`model` — they key every existing ledger."""
    monkeypatch.setenv("GLOSSARY_GEN_GEMINI_API_KEY", "test-key")
    monkeypatch.delenv("GLOSSARY_GEN_OPENAI_BASE_URL", raising=False)
    args = build_parser().parse_args(["--input", "index.json"])
    client = build_client(args)
    assert client.name == "gemini"
    assert client.model == "gemini-3.5-flash"


def test_build_client_wraps_every_provider_in_the_retry_policy(monkeypatch):
    """Pins the wiring itself: an unwrapped provider silently never backs off.

    Reaches into the chain because there is no public way to observe composition, and
    the alternative is that the one line carrying this whole change has no test.
    """
    monkeypatch.setenv("GLOSSARY_GEN_GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GLOSSARY_GEN_OPENAI_BASE_URL", "http://localhost:11434/v1")
    args = build_parser().parse_args(["--input", "index.json"])
    chain = build_client(args)
    assert [type(c).__name__ for c in chain._clients] == ["RetryingClient", "RetryingClient"]
