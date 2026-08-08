import pytest

from glossary_gen.generate import build_prompt, generate_entry, load_prompt, prompt_versions
from glossary_gen.llm import LLMResult, LLMStructuredOutputError, LLMTransportError
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

    def complete(self, prompt):
        self.prompts.append(prompt)
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def ok_result():
    return LLMResult(
        entry=GlossaryEntry(definition="A function calling itself."),
        model="test-model",
        provider="scripted",
        tokens_in=10,
        tokens_out=5,
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


def test_generate_entry_rejects_empty_excerpts():
    client = ScriptedClient([ok_result()])
    with pytest.raises(ValueError, match="no excerpts"):
        generate_entry(client, load_prompt("v1"), TERM, [])
    assert client.prompts == []
