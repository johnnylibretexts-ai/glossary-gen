import pytest

from glossary_gen.llm import LLMStructuredOutputError, RawResult
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
        return RawResult(
            text=self._replies.pop(0),
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


def test_propose_terms_gives_up_after_the_retry_budget():
    client = _FakeClient(["nope", "still nope", "nope again"])

    with pytest.raises(LLMStructuredOutputError):
        propose_terms(client, load_scan_prompt("v1"), PAGE)
