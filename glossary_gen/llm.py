from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Protocol

import httpx
from pydantic import BaseModel, ValidationError

from glossary_gen.models import GlossaryEntry

RETRYABLE_STATUS = frozenset({408, 409, 429, 500, 502, 503, 504})
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)
_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


class LLMError(RuntimeError):
    """Base class for provider failures."""


class LLMTransportError(LLMError):
    """The provider could not be reached, or refused the request."""


class LLMStructuredOutputError(LLMError):
    """The provider replied, but not with a valid GlossaryEntry."""


class LLMResult(BaseModel):
    entry: GlossaryEntry
    model: str
    provider: str
    tokens_in: int = 0
    tokens_out: int = 0


class LLMClient(Protocol):
    name: str
    model: str

    def complete(self, prompt: str) -> LLMResult: ...


def parse_entry(raw: str) -> GlossaryEntry:
    """Extract and validate a GlossaryEntry from a model's raw text reply."""
    candidate = raw.strip()
    fenced = _FENCE.search(candidate)
    if fenced:
        candidate = fenced.group(1).strip()
    else:
        obj = _OBJECT.search(candidate)
        if obj:
            candidate = obj.group(0)
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise LLMStructuredOutputError(f"no JSON object in reply ({exc.msg})") from exc
    try:
        return GlossaryEntry.model_validate(payload)
    except ValidationError as exc:
        raise LLMStructuredOutputError(
            f"reply failed schema validation: {exc.error_count()} error(s)"
        ) from exc


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

    def complete(self, prompt: str) -> LLMResult:
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
            raise LLMTransportError(f"{self.name}: HTTP {response.status_code}")
        payload = response.json()
        try:
            text = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMStructuredOutputError(f"{self.name}: unexpected response shape") from exc
        usage = payload.get("usage") or {}
        return LLMResult(
            entry=parse_entry(text),
            model=self.model,
            provider=self.name,
            tokens_in=int(usage.get("prompt_tokens", 0)),
            tokens_out=int(usage.get("completion_tokens", 0)),
        )


class GeminiClient:
    """Google Generative Language API, generateContent."""

    name = "gemini"

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "gemini-flash-3.6",
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
        client: httpx.Client | None = None,
    ) -> None:
        self._api_key = api_key
        self.model = model
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=120.0)

    def complete(self, prompt: str) -> LLMResult:
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
            raise LLMTransportError(f"{self.name}: HTTP {response.status_code}")
        payload = response.json()
        try:
            text = payload["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMStructuredOutputError(f"{self.name}: unexpected response shape") from exc
        usage = payload.get("usageMetadata") or {}
        return LLMResult(
            entry=parse_entry(text),
            model=self.model,
            provider=self.name,
            tokens_in=int(usage.get("promptTokenCount", 0)),
            tokens_out=int(usage.get("candidatesTokenCount", 0)),
        )


class ProviderChain:
    """Try each client in order; fall through on transport failures."""

    def __init__(self, clients: Sequence[LLMClient]) -> None:
        if not clients:
            raise ValueError("ProviderChain needs at least one client")
        self._clients = list(clients)

    @property
    def model(self) -> str:
        return self._clients[0].model

    @property
    def name(self) -> str:
        return self._clients[0].name

    def complete(self, prompt: str) -> LLMResult:
        failures: list[str] = []
        for client in self._clients:
            try:
                return client.complete(prompt)
            except LLMTransportError as exc:
                failures.append(f"{client.name}: {exc}")
        raise LLMTransportError("all providers failed — " + "; ".join(failures))
