import httpx
import pytest

from glossary_gen.llm import (
    GeminiClient,
    LLMResult,
    LLMStructuredOutputError,
    LLMTransportError,
    OpenAICompatClient,
    ProviderChain,
    RawResult,
    extract_json,
    parse_entry,
)
from glossary_gen.models import GlossaryEntry

VALID_JSON = (
    '{"definition": "A function calling itself.", "category": "Functions", '
    '"context": "c", "example": "e", "related": ["Base case"], "aliases": []}'
)


class FakeClient:
    def __init__(self, name, model, results):
        self.name = name
        self.model = model
        self._results = list(results)
        self.calls = 0

    def complete(self, prompt):
        self.calls += 1
        outcome = self._results.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def make_result(provider="fake"):
    return LLMResult(
        entry=GlossaryEntry(definition="d"), model="m", provider=provider, tokens_in=1, tokens_out=2
    )


def test_parse_entry_accepts_plain_json():
    entry = parse_entry(VALID_JSON)
    assert entry.definition == "A function calling itself."
    assert entry.related == ["Base case"]


def test_parse_entry_accepts_fenced_json():
    entry = parse_entry(f"```json\n{VALID_JSON}\n```")
    assert entry.definition.startswith("A function")


def test_parse_entry_rejects_non_json():
    with pytest.raises(LLMStructuredOutputError, match="no JSON"):
        parse_entry("I'm afraid I can't do that.")


def test_parse_entry_rejects_schema_violation():
    with pytest.raises(LLMStructuredOutputError, match="schema"):
        parse_entry('{"category": "Functions"}')


def test_chain_returns_first_success():
    first = FakeClient("a", "m1", [make_result("a")])
    second = FakeClient("b", "m2", [make_result("b")])
    result = ProviderChain([first, second]).complete("prompt")
    assert result.provider == "a"
    assert second.calls == 0


def test_chain_falls_through_on_transport_error():
    first = FakeClient("a", "m1", [LLMTransportError("429 rate limited")])
    second = FakeClient("b", "m2", [make_result("b")])
    result = ProviderChain([first, second]).complete("prompt")
    assert result.provider == "b"


def test_chain_raises_when_all_providers_fail():
    first = FakeClient("a", "m1", [LLMTransportError("boom")])
    second = FakeClient("b", "m2", [LLMTransportError("bang")])
    with pytest.raises(LLMTransportError, match="all providers failed"):
        ProviderChain([first, second]).complete("prompt")


def test_chain_requires_at_least_one_client():
    with pytest.raises(ValueError, match="at least one"):
        ProviderChain([])


def test_openai_compat_client_posts_and_parses():
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": VALID_JSON}}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 7},
            },
        )

    client = OpenAICompatClient(
        base_url="http://localhost:11434/v1",
        model="llama3.1",
        api_key=None,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = client.complete("prompt")

    assert captured["url"].endswith("/chat/completions")
    assert result.tokens_in == 11
    assert result.tokens_out == 7
    assert result.provider == "openai-compat"


def test_openai_compat_client_maps_429_to_transport_error():
    client = OpenAICompatClient(
        base_url="http://localhost:11434/v1",
        model="llama3.1",
        api_key=None,
        client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(429))),
    )
    with pytest.raises(LLMTransportError, match="429"):
        client.complete("prompt")


def test_openai_compat_client_maps_non_json_200_to_structured_output_error():
    client = OpenAICompatClient(
        base_url="http://localhost:11434/v1",
        model="llama3.1",
        api_key=None,
        client=httpx.Client(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, text="not json"))
        ),
    )
    with pytest.raises(LLMStructuredOutputError):
        client.complete("prompt")


def test_gemini_client_posts_and_parses():
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        captured["api_key_header"] = request.headers.get("x-goog-api-key")
        return httpx.Response(
            200,
            json={
                "candidates": [{"content": {"parts": [{"text": VALID_JSON}]}}],
                "usageMetadata": {"promptTokenCount": 13, "candidatesTokenCount": 9},
            },
        )

    client = GeminiClient(
        api_key="test-key",
        model="gemini-3.5-flash",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = client.complete("prompt")

    assert captured["url"].endswith(":generateContent")
    assert captured["api_key_header"] == "test-key"
    assert result.entry.definition == "A function calling itself."
    assert result.tokens_in == 13
    assert result.tokens_out == 9
    assert result.provider == "gemini"


def test_gemini_client_maps_429_to_transport_error():
    client = GeminiClient(
        api_key="test-key",
        client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(429))),
    )
    with pytest.raises(LLMTransportError, match="429"):
        client.complete("prompt")


def test_gemini_client_maps_unexpected_shape_to_structured_output_error():
    client = GeminiClient(
        api_key="test-key",
        client=httpx.Client(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"candidates": []}))
        ),
    )
    with pytest.raises(LLMStructuredOutputError):
        client.complete("prompt")


def test_gemini_client_maps_non_json_200_to_structured_output_error():
    client = GeminiClient(
        api_key="test-key",
        client=httpx.Client(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, text="not json"))
        ),
    )
    with pytest.raises(LLMStructuredOutputError):
        client.complete("prompt")


def test_extract_json_strips_a_code_fence():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_finds_a_bare_object_in_prose():
    assert extract_json('Sure!\n{"a": 1}\nHope that helps') == {"a": 1}


def test_extract_json_rejects_a_reply_with_no_object():
    with pytest.raises(LLMStructuredOutputError):
        extract_json("no json here")


def test_gemini_complete_raw_returns_text_and_usage(monkeypatch):
    import httpx

    from glossary_gen.llm import GeminiClient

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "candidates": [{"content": {"parts": [{"text": '{"terms": []}'}]}}],
                "usageMetadata": {"promptTokenCount": 11, "candidatesTokenCount": 3},
            },
        )

    client = GeminiClient(api_key="k", client=httpx.Client(transport=httpx.MockTransport(handler)))
    raw = client.complete_raw("prompt")

    assert isinstance(raw, RawResult)
    assert raw.text == '{"terms": []}'
    assert (raw.tokens_in, raw.tokens_out) == (11, 3)
    assert raw.provider == "gemini"
