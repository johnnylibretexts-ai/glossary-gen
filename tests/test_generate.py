import pytest

from glossary_gen.generate import build_prompt, generate_entry, load_prompt, prompt_versions
from glossary_gen.llm import (
    LLMResult,
    LLMStructuredOutputError,
    LLMTransportError,
    RawResult,
    parse_entry,
)
from glossary_gen.models import Excerpt, GlossaryEntry, Term

TERM = Term(term="Recursion", slug="recursion", aliases=("recursive",), pages=("https://a",))
EXCERPTS = [
    Excerpt(page_url="https://a", text="Recursion is a technique.", rank=1),
    Excerpt(page_url="https://b", text="A base case stops it.", rank=2),
]


class ScriptedClient:
    name = "scripted"
    model = "test-model"

    def __init__(self, outcomes):
        self._outcomes = list(outcomes)
        self.prompts = []

    def complete_raw(self, prompt):
        self.prompts.append(prompt)
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        # A non-exception outcome stands for a provider reply that parses cleanly, so
        # render the scripted entry back out as the JSON a provider would have sent.
        return RawResult(
            text=outcome.entry.model_dump_json(),
            model=outcome.model,
            provider=outcome.provider,
            tokens_in=outcome.tokens_in,
            tokens_out=outcome.tokens_out,
        )

    def complete(self, prompt):
        raw = self.complete_raw(prompt)
        return LLMResult(
            entry=parse_entry(raw.text),
            model=raw.model,
            provider=raw.provider,
            tokens_in=raw.tokens_in,
            tokens_out=raw.tokens_out,
        )


def ok_result():
    return LLMResult(
        entry=GlossaryEntry(definition="A function calling itself."),
        model="test-model",
        provider="scripted",
        tokens_in=10,
        tokens_out=5,
    )


class BillingClient:
    """A full `LLMClient` stand-in that bills for every attempt, like a real provider.

    `ScriptedClient` above raises pre-built exceptions and so can say nothing about
    spend. This one answers `complete_raw` with a real `RawResult` carrying token
    counts — 7 in / 2 out per attempt, matching `test_scan_propose.py`'s fake — and
    implements `complete` exactly as the shipped adapters do, so a test cannot pass
    merely because the stand-in happens to omit the method under discussion.
    """

    name = "billing"
    model = "test-model"

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

    def complete(self, prompt):
        raw = self.complete_raw(prompt)
        return LLMResult(
            entry=parse_entry(raw.text),
            model=raw.model,
            provider=raw.provider,
            tokens_in=raw.tokens_in,
            tokens_out=raw.tokens_out,
        )


def test_prompt_versions_lists_v1():
    assert "v1" in prompt_versions()


def test_load_prompt_reads_template():
    assert "TERM: {term}" in load_prompt("v1")


def test_load_prompt_rejects_unknown_version():
    with pytest.raises(FileNotFoundError):
        load_prompt("v99")


def test_load_prompt_rejects_path_traversal():
    with pytest.raises(ValueError, match="invalid prompt version"):
        load_prompt("../../etc/passwd")


def test_build_prompt_substitutes_term_aliases_and_excerpts():
    rendered = build_prompt(load_prompt("v1"), TERM, EXCERPTS)
    assert "TERM: Recursion" in rendered
    assert "recursive" in rendered
    assert "Recursion is a technique." in rendered
    assert "https://a" in rendered
    assert "{term}" not in rendered


def test_build_prompt_preserves_literal_json_braces():
    rendered = build_prompt(load_prompt("v1"), TERM, EXCERPTS)
    assert '"definition":' in rendered
    assert "{{" not in rendered


def test_build_prompt_handles_no_aliases():
    term = Term(term="Scope", slug="scope", aliases=(), pages=("https://a",))
    rendered = build_prompt(load_prompt("v1"), term, EXCERPTS)
    assert "KNOWN ALIASES: none" in rendered


def test_generate_entry_returns_result_on_first_success():
    client = ScriptedClient([ok_result()])
    result = generate_entry(client, load_prompt("v1"), TERM, EXCERPTS)
    assert result.entry.definition == "A function calling itself."
    assert len(client.prompts) == 1


def test_generate_entry_retries_structured_output_error():
    client = ScriptedClient([LLMStructuredOutputError("bad"), ok_result()])
    result = generate_entry(client, load_prompt("v1"), TERM, EXCERPTS, retries=2)
    assert result.entry.definition
    assert len(client.prompts) == 2


def test_generate_entry_gives_up_after_retries():
    client = ScriptedClient([LLMStructuredOutputError("bad")] * 3)
    with pytest.raises(LLMStructuredOutputError):
        generate_entry(client, load_prompt("v1"), TERM, EXCERPTS, retries=2)
    assert len(client.prompts) == 3


def test_generate_entry_does_not_retry_transport_error():
    client = ScriptedClient([LLMTransportError("429"), ok_result()])
    with pytest.raises(LLMTransportError):
        generate_entry(client, load_prompt("v1"), TERM, EXCERPTS, retries=2)
    assert len(client.prompts) == 1


def test_generate_entry_reports_what_every_attempt_cost_not_just_the_last():
    """A term that succeeded on its third try still paid for the first two.

    Reporting only the winning attempt's tokens writes an undercount into an `ok` ledger
    row — and `execute` reseeds its running total from those rows, so the shortfall is
    permanent for the life of the ledger. This is the retry-then-succeed path, which is
    far more common than giving up entirely. 7/2 per attempt, three attempts, 21/6.
    """
    client = BillingClient(["nope", "still nope", '{"definition": "Calls itself."}'])

    result = generate_entry(client, load_prompt("v1"), TERM, EXCERPTS)

    assert len(client.prompts) == 3
    assert result.entry.definition == "Calls itself."
    assert (result.tokens_in, result.tokens_out) == (21, 6)


def test_generate_entry_attaches_accumulated_tokens_to_the_raised_exception():
    # Every attempt reached the provider and got a real, billed reply back before failing
    # schema validation — that is spend already incurred, and it must survive the raise or
    # `--budget-usd` can never see it. Worse, `cli.execute` seeds its running total from
    # the ledger, so tokens lost here are lost on every later resume too.
    # `propose_terms` already behaves this way; this is the generator catching up.
    # BillingClient bills 7 in / 2 out per attempt, so three attempts must sum to 21 / 6.
    client = BillingClient(["nope", "still nope", "nope again"])

    with pytest.raises(LLMStructuredOutputError) as excinfo:
        generate_entry(client, load_prompt("v1"), TERM, EXCERPTS)

    assert len(client.prompts) == 3
    assert excinfo.value.tokens_in == 21
    assert excinfo.value.tokens_out == 6


def test_generate_entry_attaches_accumulated_tokens_to_a_mid_retry_transport_error():
    """An outage on the second attempt does not refund the first.

    Attempt one reached a reply and was billed 7/2; only then did the chain go down.
    Letting the transport error escape bare discards that spend, and `cli.execute`'s
    `getattr(exc, "tokens_in", 0)` then records a zero. A transport error on the FIRST
    attempt genuinely has nothing to attach — that case is covered above.
    """
    client = BillingClient(["nope", LLMTransportError("all providers failed")])

    with pytest.raises(LLMTransportError) as excinfo:
        generate_entry(client, load_prompt("v1"), TERM, EXCERPTS)

    assert len(client.prompts) == 2
    assert (excinfo.value.tokens_in, excinfo.value.tokens_out) == (7, 2)


def test_generate_entry_rejects_empty_excerpts():
    client = ScriptedClient([ok_result()])
    with pytest.raises(ValueError, match="no excerpts"):
        generate_entry(client, load_prompt("v1"), TERM, [])
    assert client.prompts == []
