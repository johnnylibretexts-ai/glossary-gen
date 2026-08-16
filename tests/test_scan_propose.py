import pytest

from glossary_gen.llm import LLMStructuredOutputError, LLMTransportError, RawResult
from glossary_gen.models import Block, Page
from glossary_gen.scan.propose import (
    build_scan_prompt,
    load_scan_prompt,
    propose_terms,
    scan_prompt_versions,
)

PAGE = Page(
    url="https://eng.libretexts.org/x",
    blocks=(
        Block(kind="heading", text="Recursion"),
        Block(kind="paragraph", text="Recursion is a technique where a function calls itself."),
    ),
)


class _FakeClient:
    name = "fake"
    model = "fake-model"

    def __init__(self, replies):
        self._replies = list(replies)
        self.prompts = []

    def complete_raw(self, prompt):
        self.prompts.append(prompt)
        reply = self._replies.pop(0)
        if isinstance(reply, Exception):
            raise reply  # the provider went away on this attempt
        return RawResult(
            text=reply,
            model=self.model,
            provider=self.name,
            tokens_in=7,
            tokens_out=2,
        )


def test_scan_prompts_are_discovered_from_their_own_directory():
    assert "v1" in scan_prompt_versions()


def test_scan_prompts_are_not_offered_to_the_generator():
    from glossary_gen.generate import prompt_versions

    assert "v1" in prompt_versions()  # the generator's own v1
    assert "scan_v1" not in prompt_versions()


def test_build_scan_prompt_includes_the_page_url_and_text():
    prompt = build_scan_prompt(load_scan_prompt("v1"), PAGE)

    assert PAGE.url in prompt
    assert "a function calls itself" in prompt


def test_propose_terms_parses_a_valid_reply():
    client = _FakeClient(
        ['{"terms": [{"term": "Recursion", "evidence": "calls itself", "confidence": 0.9}]}']
    )

    candidates, raw = propose_terms(client, load_scan_prompt("v1"), PAGE)

    assert [c.term for c in candidates.terms] == ["Recursion"]
    assert raw.tokens_in == 7


def test_propose_terms_retries_malformed_output():
    client = _FakeClient(["not json", '{"terms": []}'])

    candidates, _ = propose_terms(client, load_scan_prompt("v1"), PAGE)

    assert candidates.terms == []
    assert len(client.prompts) == 2


def test_propose_terms_reports_what_every_attempt_cost_not_just_the_last():
    """A page that parsed on its third try still paid for the first two.

    `scan_cli.execute` charges the returned `RawResult` against the ceiling and writes it
    to an `ok` ledger row that later runs reseed from, so reporting only the winning
    attempt's tokens hides the rest permanently. Same defect the generator had.
    _FakeClient bills 7/2 per attempt; three attempts is 21/6.
    """
    client = _FakeClient(["nope", "still nope", '{"terms": []}'])

    _, raw = propose_terms(client, load_scan_prompt("v1"), PAGE)

    assert len(client.prompts) == 3
    assert (raw.tokens_in, raw.tokens_out) == (21, 6)


def test_propose_terms_gives_up_after_the_retry_budget():
    client = _FakeClient(["nope", "still nope", "nope again"])

    with pytest.raises(LLMStructuredOutputError):
        propose_terms(client, load_scan_prompt("v1"), PAGE)


def test_propose_terms_attaches_accumulated_tokens_to_the_raised_exception():
    # Every attempt reached `complete_raw` and got a real, billed reply back before
    # failing schema validation — that's real spend that must not vanish just because
    # the call ultimately raised. _FakeClient bills tokens_in=7/tokens_out=2 per call;
    # three attempts (the default retry budget) must sum to 21/6, not 0.
    client = _FakeClient(["nope", "still nope", "nope again"])

    with pytest.raises(LLMStructuredOutputError) as excinfo:
        propose_terms(client, load_scan_prompt("v1"), PAGE)

    assert len(client.prompts) == 3
    assert excinfo.value.tokens_in == 21
    assert excinfo.value.tokens_out == 6


def test_propose_terms_attaches_accumulated_tokens_to_a_mid_retry_transport_error():
    """An outage on the second attempt does not refund the first.

    Attempt one reached a reply and was billed 7/2 before the chain went down.
    `scan_cli.execute` reads the spend off the exception, so letting a transport error
    escape bare records a zero for a page that really cost something.
    """
    client = _FakeClient(["nope", LLMTransportError("all providers failed")])

    with pytest.raises(LLMTransportError) as excinfo:
        propose_terms(client, load_scan_prompt("v1"), PAGE)

    assert len(client.prompts) == 2
    assert (excinfo.value.tokens_in, excinfo.value.tokens_out) == (7, 2)


def test_propose_terms_rejects_a_bare_json_array():
    # extract_json's greedy `{.*}` fallback would strip the brackets off this and hand
    # PageCandidates just the inner object, which validates as a silently empty result.
    reply = '[{"term": "X", "evidence": "some evidence text here", "confidence": 0.5}]'
    client = _FakeClient([reply, reply, reply])

    with pytest.raises(LLMStructuredOutputError, match="JSON array"):
        propose_terms(client, load_scan_prompt("v1"), PAGE)

    assert len(client.prompts) == 3


def test_propose_terms_rejects_an_object_with_no_terms_key():
    reply = '{"candidates": []}'
    client = _FakeClient([reply, reply, reply])

    with pytest.raises(LLMStructuredOutputError, match="no 'terms' key"):
        propose_terms(client, load_scan_prompt("v1"), PAGE)

    assert len(client.prompts) == 3


def test_propose_terms_accepts_a_legitimate_empty_terms_reply():
    client = _FakeClient(['{"terms": []}'])

    candidates, _ = propose_terms(client, load_scan_prompt("v1"), PAGE)

    assert candidates.terms == []
    assert len(client.prompts) == 1
