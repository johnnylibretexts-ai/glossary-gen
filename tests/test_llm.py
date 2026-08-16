import httpx
import pytest

from glossary_gen.llm import (
    GeminiClient,
    LLMResult,
    LLMRetryableError,
    LLMStructuredOutputError,
    LLMTransportError,
    OpenAICompatClient,
    ProviderChain,
    RawResult,
    RetryingClient,
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


def test_gemini_client_marks_a_429_retryable():
    client = GeminiClient(
        api_key="test-key",
        client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(429))),
    )
    with pytest.raises(LLMRetryableError) as caught:
        client.complete("prompt")
    assert caught.value.status_code == 429
    # Still a transport error, so ProviderChain's fall-through needs no edit.
    assert isinstance(caught.value, LLMTransportError)


def test_gemini_client_leaves_a_401_unretryable():
    client = GeminiClient(
        api_key="test-key",
        client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(401))),
    )
    with pytest.raises(LLMTransportError) as caught:
        client.complete("prompt")
    assert not isinstance(caught.value, LLMRetryableError)


def test_openai_compat_client_marks_a_503_retryable():
    client = OpenAICompatClient(
        base_url="http://localhost:11434/v1",
        model="llama3.1",
        api_key=None,
        client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503))),
    )
    with pytest.raises(LLMRetryableError) as caught:
        client.complete("prompt")
    assert caught.value.status_code == 503


def test_client_reads_the_retry_hint_from_the_retry_after_header():
    client = OpenAICompatClient(
        base_url="http://localhost:11434/v1",
        model="llama3.1",
        api_key=None,
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(429, headers={"Retry-After": "17"})
            )
        ),
    )
    with pytest.raises(LLMRetryableError) as caught:
        client.complete("prompt")
    assert caught.value.retry_after == 17.0


def test_client_ignores_an_http_date_retry_after():
    client = OpenAICompatClient(
        base_url="http://localhost:11434/v1",
        model="llama3.1",
        api_key=None,
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(
                    429, headers={"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"}
                )
            )
        ),
    )
    with pytest.raises(LLMRetryableError) as caught:
        client.complete("prompt")
    assert caught.value.retry_after is None


def test_client_ignores_a_negative_retry_after():
    """A hint from a skewed clock is unreadable, not an instruction to sleep backwards."""
    client = OpenAICompatClient(
        base_url="http://localhost:11434/v1",
        model="llama3.1",
        api_key=None,
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(429, headers={"Retry-After": "-1"})
            )
        ),
    )
    with pytest.raises(LLMRetryableError) as caught:
        client.complete("prompt")
    assert caught.value.retry_after is None


GEMINI_QUOTA_ERROR = {
    "error": {
        "code": 429,
        "status": "RESOURCE_EXHAUSTED",
        "details": [
            {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "17s"},
        ],
    }
}


def test_gemini_client_reads_the_retry_hint_from_its_error_body():
    client = GeminiClient(
        api_key="test-key",
        client=httpx.Client(
            transport=httpx.MockTransport(lambda r: httpx.Response(429, json=GEMINI_QUOTA_ERROR))
        ),
    )
    with pytest.raises(LLMRetryableError) as caught:
        client.complete("prompt")
    assert caught.value.retry_after == 17.0


def test_gemini_client_prefers_the_header_over_the_error_body():
    client = GeminiClient(
        api_key="test-key",
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(429, headers={"Retry-After": "3"}, json=GEMINI_QUOTA_ERROR)
            )
        ),
    )
    with pytest.raises(LLMRetryableError) as caught:
        client.complete("prompt")
    assert caught.value.retry_after == 3.0


def test_gemini_client_ignores_a_negative_retry_delay():
    client = GeminiClient(
        api_key="test-key",
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(
                    429,
                    json={
                        "error": {
                            "details": [
                                {
                                    "@type": "type.googleapis.com/google.rpc.RetryInfo",
                                    "retryDelay": "-1s",
                                }
                            ]
                        }
                    },
                )
            )
        ),
    )
    with pytest.raises(LLMRetryableError) as caught:
        client.complete("prompt")
    assert caught.value.retry_after is None


def test_gemini_client_survives_a_429_with_no_hint_at_all():
    client = GeminiClient(
        api_key="test-key",
        client=httpx.Client(
            transport=httpx.MockTransport(lambda r: httpx.Response(429, text="upstream is down"))
        ),
    )
    with pytest.raises(LLMRetryableError) as caught:
        client.complete("prompt")
    assert caught.value.retry_after is None


class FakeRawClient:
    """A client whose `complete_raw` replays a scripted sequence of outcomes."""

    def __init__(self, outcomes, name="fake", model="fake-model"):
        self.name = name
        self.model = model
        self._outcomes = list(outcomes)
        self.requests = 0

    def complete_raw(self, prompt):
        self.requests += 1
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def complete(self, prompt):
        raw = self.complete_raw(prompt)
        return LLMResult(
            entry=parse_entry(raw.text),
            model=raw.model,
            provider=raw.provider,
            tokens_in=raw.tokens_in,
            tokens_out=raw.tokens_out,
        )


def make_raw(text=VALID_JSON):
    return RawResult(text=text, model="fake-model", provider="fake", tokens_in=1, tokens_out=2)


def rate_limited(retry_after=None):
    return LLMRetryableError("fake: HTTP 429", status_code=429, retry_after=retry_after)


class Recorder:
    """Stands in for `time.sleep` and the stderr writer: records, never performs."""

    def __init__(self):
        self.waits = []
        self.messages = []

    def sleep(self, seconds):
        self.waits.append(seconds)

    def report(self, message):
        self.messages.append(message)


def build_retrying(outcomes, **kwargs):
    recorder = Recorder()
    inner = FakeRawClient(outcomes, **kwargs)
    return RetryingClient(inner, sleep=recorder.sleep, report=recorder.report), inner, recorder


def test_retrying_client_waits_and_then_succeeds():
    client, inner, recorder = build_retrying([rate_limited(), make_raw()])
    result = client.complete_raw("prompt")
    assert result.text == VALID_JSON
    assert inner.requests == 2
    assert len(recorder.waits) == 1


def test_retrying_client_obeys_the_providers_hint_exactly():
    client, _, recorder = build_retrying([rate_limited(retry_after=17.0), make_raw()])
    client.complete_raw("prompt")
    assert recorder.waits == [17.0]


def test_retrying_client_backs_off_on_its_own_schedule_when_unhinted():
    client, _, recorder = build_retrying([rate_limited(), rate_limited(), make_raw()])
    client.complete_raw("prompt")
    first, second = recorder.waits
    # Jittered, so assert the band rather than the value; the second wait is the longer.
    assert 1.0 <= first <= 2.0
    assert 5.0 <= second <= 10.0


def test_retrying_client_refuses_a_hint_longer_than_the_cap():
    client, inner, recorder = build_retrying([rate_limited(retry_after=3600.0), make_raw()])
    with pytest.raises(LLMRetryableError):
        client.complete_raw("prompt")
    assert recorder.waits == []
    assert inner.requests == 1


def test_retrying_client_gives_up_after_three_requests():
    client, inner, recorder = build_retrying([rate_limited(), rate_limited(), rate_limited()])
    with pytest.raises(LLMRetryableError):
        client.complete_raw("prompt")
    assert inner.requests == 3
    assert len(recorder.waits) == 2


def test_retrying_client_does_not_retry_an_unretryable_transport_error():
    client, inner, recorder = build_retrying([LLMTransportError("fake: HTTP 401"), make_raw()])
    with pytest.raises(LLMTransportError):
        client.complete_raw("prompt")
    assert inner.requests == 1
    assert recorder.waits == []


def test_retrying_client_does_not_retry_a_malformed_reply():
    """Structured-output retries belong to generate_entry, and they do not sleep. ADR-0003."""
    client, inner, recorder = build_retrying([LLMStructuredOutputError("bad shape"), make_raw()])
    with pytest.raises(LLMStructuredOutputError):
        client.complete_raw("prompt")
    assert inner.requests == 1
    assert recorder.waits == []


def test_retrying_client_retries_complete_too():
    """The trap: a decorator delegating to the wrapped client's `complete` retries nothing."""
    client, inner, recorder = build_retrying([rate_limited(), make_raw()])
    result = client.complete("prompt")
    assert result.entry.definition == "A function calling itself."
    assert inner.requests == 2
    assert len(recorder.waits) == 1


def test_retrying_client_forwards_the_ledger_keys():
    client, _, _ = build_retrying([make_raw()], name="gemini", model="gemini-3.5-flash")
    assert client.name == "gemini"
    assert client.model == "gemini-3.5-flash"


def test_retrying_client_reports_each_wait():
    client, _, recorder = build_retrying([rate_limited(retry_after=5.0), make_raw()])
    client.complete_raw("prompt")
    assert len(recorder.messages) == 1
    assert "429" in recorder.messages[0]
    assert "5" in recorder.messages[0]


def test_chain_falls_through_after_a_wrapped_client_exhausts_its_retries():
    """A retryable error is still a transport error, so the chain is unchanged."""
    first, _, _ = build_retrying([rate_limited(), rate_limited(), rate_limited()], name="a")
    second = FakeRawClient([make_raw()], name="b")
    result = ProviderChain([first, second]).complete_raw("prompt")
    assert result.provider == "fake"
    assert second.requests == 1


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
