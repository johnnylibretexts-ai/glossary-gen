import httpx
import pytest

from glossary_gen.cli import RunSummary, estimate_cost, execute, load_prices
from glossary_gen.fetch import PageCache
from glossary_gen.generate import load_prompt
from glossary_gen.ledger import Ledger
from glossary_gen.llm import LLMResult, LLMTransportError
from glossary_gen.models import Book, GlossaryEntry, Term

BOOK = Book(library="eng", cover_id="1", book_id="b", title="T", index_url="https://i")
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
        BOOK,
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
        BOOK,
        make_cache(tmp_path, routes),
        first,
        Ledger(tmp_path / "run.jsonl"),
        load_prompt("v1"),
        "v1",
    )
    second = StubClient([])
    summary = execute(
        terms,
        BOOK,
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
    one = estimate_cost("gemini-flash-3.6", 1, prices)
    hundred = estimate_cost("gemini-flash-3.6", 100, prices)
    assert one is not None and hundred is not None
    assert hundred == pytest.approx(one * 100)
