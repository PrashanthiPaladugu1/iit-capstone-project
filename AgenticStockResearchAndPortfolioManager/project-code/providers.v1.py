"""Provider adapters: the ONLY module that talks to model services.

Agents, RAG and the UI never import an SDK or call HTTP themselves. They call the gateway, and the gateway
picks one of these adapters from the saved settings. Adding a provider means adding a class here.

Neutral formats used everywhere else in the app:
  message   {"role": "system|user|assistant|tool", "content": str}
            assistant with tools: {"role": "assistant", "content": str, "tool_calls": [call, ...]}
            tool result:          {"role": "tool", "tool_call_id": str, "name": str, "content": str}
  call      {"id": str, "name": str, "arguments": dict}
  tools     OpenAI style: {"type": "function", "function": {"name", "description", "parameters"}}

Verified against the live service: Ollama only (on 18 Nov 2026). The OpenAI-compatible and Hugging Face
adapters follow the public API shapes and are tested with mocked HTTP, not against the real services.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

import httpx


class ProviderError(RuntimeError):
    """A model call failed. The message never contains the API key."""


@dataclass
class ChatResult:
    text: str
    tool_calls: list[dict] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    total_ms: float = 0.0
    load_ms: float = 0.0
    eval_ms: float = 0.0
    tokens_estimated: bool = False
    provider: str = ""
    model: str = ""
    call_id: int | None = None


@dataclass
class EmbedResult:
    vectors: list[list[float]]
    tokens_in: int = 0
    total_ms: float = 0.0
    tokens_estimated: bool = False
    provider: str = ""
    model: str = ""
    call_id: int | None = None

    @property
    def dims(self) -> int:
        return len(self.vectors[0]) if self.vectors else 0


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _ns_to_ms(value: Any) -> float:
    return float(value or 0) / 1e6


def _loads(text: str) -> dict:
    try:
        value = json.loads(text) if text else {}
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


# --------------------------------------------------------------------------- message conversion
def _ollama_messages(messages: list[dict]) -> list[dict]:
    out = []
    for m in messages:
        if m["role"] == "assistant" and m.get("tool_calls"):
            out.append({
                "role": "assistant", "content": m.get("content", ""),
                "tool_calls": [{"function": {"name": c["name"], "arguments": c["arguments"]}} for c in m["tool_calls"]],
            })
        elif m["role"] == "tool":
            out.append({"role": "tool", "content": m["content"], "tool_name": m.get("name", "")})
        else:
            out.append({"role": m["role"], "content": m["content"]})
    return out


def _openai_messages(messages: list[dict]) -> list[dict]:
    out = []
    for m in messages:
        if m["role"] == "assistant" and m.get("tool_calls"):
            out.append({
                "role": "assistant", "content": m.get("content", "") or None,
                "tool_calls": [
                    {"id": c["id"], "type": "function",
                     "function": {"name": c["name"], "arguments": json.dumps(c["arguments"])}}
                    for c in m["tool_calls"]
                ],
            })
        elif m["role"] == "tool":
            out.append({"role": "tool", "tool_call_id": m.get("tool_call_id", ""), "content": m["content"]})
        else:
            out.append({"role": m["role"], "content": m["content"]})
    return out


# --------------------------------------------------------------------------- base
class BaseProvider:
    kind = "base"

    def __init__(self, base_url: str, api_key: str = "", timeout: float = 180.0,
                 transport: httpx.BaseTransport | None = None):
        if not base_url:
            raise ProviderError(f"{self.kind}: base URL is empty")
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = httpx.Client(base_url=base_url.rstrip("/") + "/", timeout=timeout,
                                    headers=headers, transport=transport)

    def _request(self, method: str, path: str, body: dict | None = None) -> tuple[Any, float]:
        started = time.perf_counter()
        try:
            response = self._client.request(method, path, json=body)
        except httpx.TimeoutException as exc:
            raise ProviderError(f"{self.kind}: timeout") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"{self.kind}: connection error ({type(exc).__name__})") from exc
        wall_ms = (time.perf_counter() - started) * 1000
        if response.status_code >= 400:
            raise ProviderError(f"{self.kind}: HTTP {response.status_code}: {response.text[:200]}")
        try:
            return response.json(), wall_ms
        except ValueError as exc:
            raise ProviderError(f"{self.kind}: reply is not JSON") from exc

    def chat(self, model: str, messages: list[dict], tools: list[dict] | None = None,
             params: dict | None = None) -> ChatResult:
        raise NotImplementedError

    def embed(self, model: str, texts: list[str]) -> EmbedResult:
        raise NotImplementedError


# --------------------------------------------------------------------------- Ollama
class OllamaProvider(BaseProvider):
    kind = "ollama"

    def chat(self, model, messages, tools=None, params=None):
        params = params or {}
        body: dict[str, Any] = {"model": model, "messages": _ollama_messages(messages), "stream": False}
        if tools:
            body["tools"] = tools
        if params.get("think") is False:
            body["think"] = False       # gemma4: skip the thinking phase for speed
        options = {k: params[k] for k in ("temperature", "num_ctx") if k in params}
        if "max_tokens" in params:
            options["num_predict"] = params["max_tokens"]
        if options:
            body["options"] = options
        data, wall = self._request("POST", "api/chat", body)
        message = data.get("message") or {}
        calls = []
        for i, tc in enumerate(message.get("tool_calls") or []):
            fn = tc.get("function") or {}
            args = fn.get("arguments") or {}
            calls.append({"id": tc.get("id") or f"call_{i}", "name": fn.get("name", ""),
                          "arguments": _loads(args) if isinstance(args, str) else args})
        return ChatResult(
            text=message.get("content") or "", tool_calls=calls,
            tokens_in=int(data.get("prompt_eval_count") or 0), tokens_out=int(data.get("eval_count") or 0),
            total_ms=_ns_to_ms(data.get("total_duration")) or wall,
            load_ms=_ns_to_ms(data.get("load_duration")), eval_ms=_ns_to_ms(data.get("eval_duration")),
            model=model)

    def embed(self, model, texts):
        data, wall = self._request("POST", "api/embed", {"model": model, "input": texts})
        return EmbedResult(vectors=data.get("embeddings") or [], tokens_in=int(data.get("prompt_eval_count") or 0),
                           total_ms=_ns_to_ms(data.get("total_duration")) or wall, model=model)


# --------------------------------------------------------------------------- OpenAI-compatible (used for the external API)
class OpenAICompatProvider(BaseProvider):
    kind = "openai_compat"
    chat_path = "chat/completions"
    embed_path = "embeddings"

    def chat(self, model, messages, tools=None, params=None):
        params = params or {}
        body: dict[str, Any] = {"model": model, "messages": _openai_messages(messages), "stream": False}
        if tools:
            body["tools"] = tools
        for key in ("temperature", "max_tokens"):
            if key in params:
                body[key] = params[key]
        data, wall = self._request("POST", self.chat_path, body)
        try:
            message = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(f"{self.kind}: unexpected chat reply") from exc
        calls = []
        for i, tc in enumerate(message.get("tool_calls") or []):
            fn = tc.get("function") or {}
            args = fn.get("arguments") or {}
            calls.append({"id": tc.get("id") or f"call_{i}", "name": fn.get("name", ""),
                          "arguments": _loads(args) if isinstance(args, str) else args})
        text = message.get("content") or ""
        usage = data.get("usage") or {}
        estimated = "prompt_tokens" not in usage
        tokens_in = int(usage.get("prompt_tokens") or sum(_estimate_tokens(str(m.get("content", ""))) for m in messages))
        tokens_out = int(usage.get("completion_tokens") or _estimate_tokens(text))
        return ChatResult(text=text, tool_calls=calls, tokens_in=tokens_in, tokens_out=tokens_out,
                          total_ms=wall, tokens_estimated=estimated, model=model)

    def embed(self, model, texts):
        data, wall = self._request("POST", self.embed_path, {"model": model, "input": texts})
        try:
            rows = sorted(data["data"], key=lambda r: r.get("index", 0))
            vectors = [r["embedding"] for r in rows]
        except (KeyError, TypeError) as exc:
            raise ProviderError(f"{self.kind}: unexpected embeddings reply") from exc
        usage = data.get("usage") or {}
        estimated = "prompt_tokens" not in usage
        return EmbedResult(vectors=vectors, total_ms=wall, model=model, tokens_estimated=estimated,
                           tokens_in=int(usage.get("prompt_tokens") or sum(_estimate_tokens(t) for t in texts)))


# --------------------------------------------------------------------------- Hugging Face Inference API
class HuggingFaceProvider(OpenAICompatProvider):
    """Hugging Face Inference Providers. Base URL default: https://router.huggingface.co
    Chat uses the OpenAI-compatible route. Embeddings use the feature-extraction pipeline."""
    kind = "huggingface"
    chat_path = "v1/chat/completions"

    def embed(self, model, texts):
        data, wall = self._request("POST", f"hf-inference/models/{model}/pipeline/feature-extraction",
                                   {"inputs": texts})
        if texts and isinstance(data, list) and data and isinstance(data[0], (int, float)):
            data = [data]                                   # single flat vector
        if not (isinstance(data, list) and all(isinstance(v, list) for v in data)):
            raise ProviderError("huggingface: unexpected embeddings reply")
        return EmbedResult(vectors=data, total_ms=wall, model=model, tokens_estimated=True,
                           tokens_in=sum(_estimate_tokens(t) for t in texts))


PROVIDER_KINDS: dict[str, type[BaseProvider]] = {
    "ollama": OllamaProvider,
    "openai_compat": OpenAICompatProvider,
    "huggingface": HuggingFaceProvider,
}


def build_provider(kind: str, base_url: str, api_key: str = "", timeout: float = 180.0,
                   transport: httpx.BaseTransport | None = None) -> BaseProvider:
    try:
        cls = PROVIDER_KINDS[kind]
    except KeyError as exc:
        raise ProviderError(f"unknown provider kind: {kind}") from exc
    return cls(base_url, api_key=api_key, timeout=timeout, transport=transport)
