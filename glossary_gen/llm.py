from __future__ import annotations

import json
import random
import re
import sys
import time
from collections.abc import Callable, Sequence
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, ValidationError

from glossary_gen.fetch import RETRYABLE_STATUS
from glossary_gen.models import GlossaryEntry

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)
_OBJECT = re.compile(r"\{.*\}", re.DOTALL)

# The ceiling on ONE `complete_raw`, not on one subject. `generate_entry` and
# `propose_candidates` each call `complete_raw` up to three times to retry a malformed reply,
# and every one of those calls enters a fresh retry loop here — so a single subject can cost
# up to 3 x MAX_REQUESTS requests against one provider. That multiplication is accepted
# rather than bounded; ADR-0003 says why.
MAX_REQUESTS = 3
# A hint longer than this is refused rather than waited out.
MAX_WAIT_SECONDS = 60.0
# The unhinted schedule, one entry per retry — so MAX_REQUESTS - 1 of them.
BACKOFF_SECONDS = (2.0, 10.0)
_JITTER = (0.5, 1.0)


class LLMError(RuntimeError):
    """Base class for provider failures."""


class LLMTransportError(LLMError):
    """The provider could not be reached, or refused the request."""


class LLMRetryableError(LLMTransportError):
    """The provider refused this request, but the same request may work shortly.

    A subclass rather than a flag on `LLMTransportError` so `ProviderChain` needs no edit:
    a retryable refusal *is* a transport failure, so the existing fall-through still
    catches it, while `RetryingClient` can select for it by type. Which statuses qualify
    is decided once, where the error is raised, rather than at every place one is caught.
    """

    def __init__(self, message: str, *, status_code: int, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        # How long the provider asked us to wait, when it said so. None means it didn't.
        self.retry_after = retry_after


class LLMStructuredOutputError(LLMError):
    """The provider replied, but not with a valid GlossaryEntry."""


class LLMResult(BaseModel):
    entry: GlossaryEntry
    model: str
    provider: str
    tokens_in: int = 0
    tokens_out: int = 0


class RawResult(BaseModel):
    """An unparsed provider reply plus its accounting, before schema validation.

    `complete()` is this plus a `GlossaryEntry` validation. The scanner needs the same
    call with a different schema, so the transport half is exposed on its own rather
    than making `LLMResult` generic over its payload.
    """

    text: str
    model: str
    provider: str
    tokens_in: int = 0
    tokens_out: int = 0


class LLMClient(Protocol):
    name: str
    model: str

    def complete(self, prompt: str) -> LLMResult: ...

    def complete_raw(self, prompt: str) -> RawResult: ...


def extract_json(raw: str) -> Any:
    """Pull a JSON value out of a model reply that may be fenced or wrapped in prose."""
    candidate = raw.strip()
    fenced = _FENCE.search(candidate)
    if fenced:
        candidate = fenced.group(1).strip()
    else:
        obj = _OBJECT.search(candidate)
        if obj:
            candidate = obj.group(0)
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise LLMStructuredOutputError(f"no JSON object in reply ({exc.msg})") from exc


def parse_entry(raw: str) -> GlossaryEntry:
    """Extract and validate a GlossaryEntry from a model's raw text reply."""
    payload = extract_json(raw)
    try:
        return GlossaryEntry.model_validate(payload)
    except ValidationError as exc:
        raise LLMStructuredOutputError(
            f"reply failed schema validation: {exc.error_count()} error(s)"
        ) from exc


def _usable(seconds: float) -> float | None:
    """A hint is only a hint if it is a non-negative number of seconds.

    A negative delay — a proxy computing `Retry-After` from a skewed clock — is unreadable
    in exactly the way an HTTP date is, and is treated the same way: no hint, fall through
    to the schedule. Passed on, it would reach `time.sleep`, which raises a `ValueError`
    that no layer of this tool catches: it escapes `generate_entry`, the run, and the CLI,
    killing the process before a single row is written.
    """
    return seconds if seconds >= 0 else None


def _header_hint(response: httpx.Response) -> float | None:
    """Seconds from a `Retry-After` header, or None.

    Only the delta-seconds form is honoured. `Retry-After` may also carry an HTTP date,
    but a misparsed date yields a nonsense sleep, and JSON APIs rarely send one — an
    unreadable hint is treated as no hint, which falls through to the backoff schedule.
    """
    raw = response.headers.get("Retry-After")
    if raw is None:
        return None
    try:
        seconds = float(raw.strip())
    except ValueError:
        return None
    return _usable(seconds)


def _google_retry_info(response: httpx.Response) -> float | None:
    """Seconds from a `google.rpc.RetryInfo` block in a Google API error body, or None.

    Google's generative-language API answers an exhausted quota with `RESOURCE_EXHAUSTED`
    and puts the delay here — often without sending a `Retry-After` header at all — so
    ignoring the body would mean ignoring the hint from the one provider we are actually
    rate-limited by.
    """
    try:
        payload = response.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    details = (payload.get("error") or {}).get("details")
    if not isinstance(details, list):
        return None
    for detail in details:
        if not isinstance(detail, dict):
            continue
        delay = detail.get("retryDelay")
        if isinstance(delay, str) and delay.endswith("s"):
            try:
                return _usable(float(delay[:-1]))
            except ValueError:
                return None
    return None


def refusal(
    provider: str, response: httpx.Response, *, body_hint: float | None = None
) -> LLMTransportError:
    """Classify a non-200 reply: retryable, or not.

    Reuses `fetch.RETRYABLE_STATUS` rather than restating it. A 503 from a model endpoint
    is as transient as a 503 from a page server, and one definition of "retryable" is one
    thing to keep correct.

    The client passes `body_hint` because only it knows its provider's error dialect —
    the same reason each client already knows where its own token counts live. The header
    wins when both are present: it is the standard mechanism, and a provider that sends
    both means the same thing by them.
    """
    status = response.status_code
    message = f"{provider}: HTTP {status}"
    if status not in RETRYABLE_STATUS:
        return LLMTransportError(message)
    hint = _header_hint(response)
    if hint is None:
        hint = body_hint
    return LLMRetryableError(message, status_code=status, retry_after=hint)


class OpenAICompatClient:
    """Any OpenAI-compatible chat endpoint: Ollama, vLLM, LM Studio."""

    name = "openai-compat"

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str | None,
        client: httpx.Client | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self.model = model
        self._api_key = api_key
        self._client = client or httpx.Client(timeout=120.0)

    def complete_raw(self, prompt: str) -> RawResult:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        body = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
        }
        try:
            response = self._client.post(
                f"{self._base_url}/chat/completions", json=body, headers=headers, timeout=120.0
            )
        except httpx.HTTPError as exc:
            raise LLMTransportError(f"{self.name}: transport error ({exc})") from exc
        if response.status_code != 200:
            raise refusal(self.name, response)
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise LLMStructuredOutputError(f"{self.name}: response body is not JSON") from exc
        try:
            text = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMStructuredOutputError(f"{self.name}: unexpected response shape") from exc
        usage = payload.get("usage") or {}
        return RawResult(
            text=text,
            model=self.model,
            provider=self.name,
            tokens_in=int(usage.get("prompt_tokens", 0)),
            tokens_out=int(usage.get("completion_tokens", 0)),
        )

    def complete(self, prompt: str) -> LLMResult:
        raw = self.complete_raw(prompt)
        return LLMResult(
            entry=parse_entry(raw.text),
            model=raw.model,
            provider=raw.provider,
            tokens_in=raw.tokens_in,
            tokens_out=raw.tokens_out,
        )


class GeminiClient:
    """Google Generative Language API, generateContent."""

    name = "gemini"

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "gemini-3.7-flash",
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
        client: httpx.Client | None = None,
    ) -> None:
        self._api_key = api_key
        self.model = model
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=120.0)

    def complete_raw(self, prompt: str) -> RawResult:
        url = f"{self._base_url}/models/{self.model}:generateContent"
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"},
        }
        try:
            response = self._client.post(
                url, json=body, headers={"x-goog-api-key": self._api_key}, timeout=120.0
            )
        except httpx.HTTPError as exc:
            raise LLMTransportError(f"{self.name}: transport error ({exc})") from exc
        if response.status_code != 200:
            raise refusal(self.name, response, body_hint=_google_retry_info(response))
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise LLMStructuredOutputError(f"{self.name}: response body is not JSON") from exc
        try:
            text = payload["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMStructuredOutputError(f"{self.name}: unexpected response shape") from exc
        usage = payload.get("usageMetadata") or {}
        return RawResult(
            text=text,
            model=self.model,
            provider=self.name,
            tokens_in=int(usage.get("promptTokenCount", 0)),
            tokens_out=int(usage.get("candidatesTokenCount", 0)),
        )

    def complete(self, prompt: str) -> LLMResult:
        raw = self.complete_raw(prompt)
        return LLMResult(
            entry=parse_entry(raw.text),
            model=raw.model,
            provider=raw.provider,
            tokens_in=raw.tokens_in,
            tokens_out=raw.tokens_out,
        )


def _to_stderr(message: str) -> None:
    print(message, file=sys.stderr)


class RetryingClient:
    """Wraps one client, waiting out refusals it is told are temporary.

    Composition, not inheritance: a new provider gets this policy by being wrapped in
    `build_client`, and never has to know the policy exists. See ADR-0003 for why the
    sleep lives at this boundary and not in the retry loops above it.

    `sleep` and `report` are injected so the schedule can be asserted by a test that
    takes no time and prints nothing — a test that really waited a minute is a test
    nobody would run.
    """

    def __init__(
        self,
        client: LLMClient,
        *,
        sleep: Callable[[float], None] = time.sleep,
        report: Callable[[str], None] = _to_stderr,
    ) -> None:
        self._client = client
        self._sleep = sleep
        self._report = report

    @property
    def name(self) -> str:
        """Forwarded verbatim: this is a ledger key, and changing it strands every ledger."""
        return self._client.name

    @property
    def model(self) -> str:
        """Forwarded verbatim: this is a ledger key, and changing it strands every ledger."""
        return self._client.model

    def _wait_before_retry(self, exc: LLMRetryableError, request_index: int) -> float | None:
        """How long to wait before the next request, or None to stop trying.

        A hint we were given is obeyed exactly — the server knows when its window
        reopens and we do not. A hint beyond the cap is not waited out: it says the quota
        is not returning within this run, so the subject fails now and the run's failure
        counter can end things, rather than the tool appearing to hang for hours.
        """
        if exc.retry_after is not None:
            return exc.retry_after if exc.retry_after <= MAX_WAIT_SECONDS else None
        # Unhinted: brief patience, jittered so concurrent runs don't retry in lockstep.
        # Deliberately short of a full quota window — see ADR-0003.
        return BACKOFF_SECONDS[request_index] * random.uniform(*_JITTER)

    def complete_raw(self, prompt: str) -> RawResult:
        for request_index in range(MAX_REQUESTS):
            try:
                return self._client.complete_raw(prompt)
            except LLMRetryableError as exc:
                if request_index == MAX_REQUESTS - 1:
                    raise
                wait = self._wait_before_retry(exc, request_index)
                if wait is None:
                    raise
                self._report(
                    f"{self.name}: refused (HTTP {exc.status_code}), waiting {wait:.1f}s "
                    f"before request {request_index + 2}/{MAX_REQUESTS}"
                )
                self._sleep(wait)
        raise AssertionError("unreachable: the final request either returns or raises")

    def complete(self, prompt: str) -> LLMResult:
        # Built from *this* class's retried `complete_raw`, never the wrapped client's
        # `complete` — delegating there reaches the unretried transport and the backoff
        # silently never fires, while every unit test still passes.
        raw = self.complete_raw(prompt)
        return LLMResult(
            entry=parse_entry(raw.text),
            model=raw.model,
            provider=raw.provider,
            tokens_in=raw.tokens_in,
            tokens_out=raw.tokens_out,
        )


class ProviderChain:
    """Try each client in order; fall through on transport failures."""

    def __init__(self, clients: Sequence[LLMClient]) -> None:
        if not clients:
            raise ValueError("ProviderChain needs at least one client")
        self._clients = list(clients)

    @property
    def model(self) -> str:
        """The chain's declared primary model — a stable ledger resume key.

        This is always the first client's model, regardless of which client
        actually served a given `complete()` call (you can't know that until
        after you've already paid for the call). For the model that actually
        served a specific result, use that result's `LLMResult.model`.
        """
        return self._clients[0].model

    @property
    def name(self) -> str:
        """The chain's declared primary provider name — a stable ledger resume key.

        This is always the first client's name, regardless of which client
        actually served a given `complete()` call. For the provider that
        actually served a specific result, use that result's `LLMResult.provider`.
        """
        return self._clients[0].name

    def complete(self, prompt: str) -> LLMResult:
        failures: list[str] = []
        for client in self._clients:
            try:
                return client.complete(prompt)
            except LLMTransportError as exc:
                failures.append(f"{client.name}: {exc}")
        raise LLMTransportError("all providers failed — " + "; ".join(failures))

    def complete_raw(self, prompt: str) -> RawResult:
        failures: list[str] = []
        for client in self._clients:
            try:
                return client.complete_raw(prompt)
            except LLMTransportError as exc:
                failures.append(f"{client.name}: {exc}")
        raise LLMTransportError("all providers failed — " + "; ".join(failures))
