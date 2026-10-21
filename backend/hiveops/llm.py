"""LLM providers behind one interface, with tool calling and cost accounting.

* ``AnthropicProvider``: Claude via the Anthropic SDK.
* ``OpenAICompatProvider``: any OpenAI-compatible /chat/completions endpoint
  (OpenAI, Azure OpenAI, Ollama, Groq, vLLM, LM Studio…).
* ``SimProvider``: a deterministic, offline simulated LLM so the whole platform
  runs (and is testable) without an API key. It is clearly labelled in the UI.

Messages use one internal format:
  {"role": "user"|"assistant"|"tool", "content": str,
   "tool_calls": [ToolCall...], "tool_call_id": str, "name": str}
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from .config import Settings

# USD per million tokens (input, output). Unknown models are priced at 0.
PRICES: dict[str, tuple[float, float]] = {
    "claude-haiku": (1.0, 5.0),
    "claude-sonnet": (3.0, 15.0),
    "claude-opus": (5.0, 25.0),
    "gpt-4o-mini": (0.15, 0.6),
    "gpt-4o": (2.5, 10.0),
    "hive-sim": (0.8, 4.0),  # simulated: priced like a small model so dashboards are meaningful
}


def price(model: str, tokens_in: int, tokens_out: int) -> float:
    for prefix, (p_in, p_out) in PRICES.items():
        if model.startswith(prefix):
            return (tokens_in * p_in + tokens_out * p_out) / 1_000_000
    return 0.0


@dataclass
class ToolCall:
    name: str
    args: dict[str, Any]
    id: str = field(default_factory=lambda: f"call_{uuid.uuid4().hex[:12]}")


@dataclass
class LLMResult:
    text: str
    tool_calls: list[ToolCall]
    tokens_in: int
    tokens_out: int
    latency_ms: int
    model: str

    @property
    def cost(self) -> float:
        return price(self.model, self.tokens_in, self.tokens_out)


class Provider(Protocol):
    name: str
    model: str
    simulated: bool

    async def complete(
        self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]], agent: str | None = None
    ) -> LLMResult: ...


class LLMError(RuntimeError):
    pass


# ------------------------------------------------------------- Anthropic


class AnthropicProvider:
    name = "anthropic"
    simulated = False

    def __init__(self, api_key: str, model: str):
        from anthropic import AsyncAnthropic

        self.client = AsyncAnthropic(api_key=api_key, max_retries=3)
        self.model = model

    @staticmethod
    def _convert(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for m in messages:
            if m["role"] == "tool":
                block = {"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": m["content"]}
                if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
                    out[-1]["content"].append(block)
                else:
                    out.append({"role": "user", "content": [block]})
            elif m["role"] == "assistant":
                blocks: list[dict[str, Any]] = []
                if m.get("content"):
                    blocks.append({"type": "text", "text": m["content"]})
                for tc in m.get("tool_calls", []):
                    blocks.append({"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.args})
                out.append({"role": "assistant", "content": blocks or [{"type": "text", "text": ""}]})
            else:
                out.append({"role": "user", "content": m["content"]})
        return out

    async def complete(self, system, messages, tools, agent=None) -> LLMResult:
        started = time.perf_counter()
        try:
            resp = await self.client.messages.create(
                model=self.model,
                max_tokens=2048,
                system=system,
                messages=self._convert(messages),
                tools=[{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]} for t in tools] or [],
            )
        except Exception as exc:  # network, auth, rate limits after retries
            raise LLMError(f"Anthropic API error: {exc}") from exc
        text_ = "".join(b.text for b in resp.content if b.type == "text")
        calls = [ToolCall(b.name, dict(b.input), b.id) for b in resp.content if b.type == "tool_use"]
        return LLMResult(
            text_,
            calls,
            resp.usage.input_tokens,
            resp.usage.output_tokens,
            int((time.perf_counter() - started) * 1000),
            self.model,
        )


# ------------------------------------------------------- OpenAI-compatible


class OpenAICompatProvider:
    name = "openai"
    simulated = False

    def __init__(self, api_key: str | None, base_url: str, model: str):
        self.model = model
        self.client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
            timeout=120,
        )

    @staticmethod
    def _convert(system: str, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = [{"role": "system", "content": system}]
        for m in messages:
            if m["role"] == "assistant":
                msg: dict[str, Any] = {"role": "assistant", "content": m.get("content") or None}
                if m.get("tool_calls"):
                    msg["tool_calls"] = [
                        {"id": tc.id, "type": "function", "function": {"name": tc.name, "arguments": json.dumps(tc.args)}}
                        for tc in m["tool_calls"]
                    ]
                out.append(msg)
            elif m["role"] == "tool":
                out.append({"role": "tool", "tool_call_id": m["tool_call_id"], "content": m["content"]})
            else:
                out.append({"role": "user", "content": m["content"]})
        return out

    async def complete(self, system, messages, tools, agent=None) -> LLMResult:
        started = time.perf_counter()
        body: dict[str, Any] = {"model": self.model, "messages": self._convert(system, messages)}
        if tools:
            body["tools"] = [{"type": "function", "function": t} for t in tools]
        for attempt in range(3):
            try:
                resp = await self.client.post("/chat/completions", json=body)
                if resp.status_code in (429, 500, 502, 503) and attempt < 2:
                    await asyncio.sleep(2**attempt)
                    continue
                resp.raise_for_status()
                break
            except httpx.HTTPError as exc:
                if attempt == 2:
                    raise LLMError(f"OpenAI-compatible API error: {exc}") from exc
                await asyncio.sleep(2**attempt)
        data = resp.json()
        choice = data["choices"][0]["message"]
        calls = []
        for tc in choice.get("tool_calls") or []:
            try:
                args = json.loads(tc["function"]["arguments"] or "{}")
            except json.JSONDecodeError:
                args = {}
            calls.append(ToolCall(tc["function"]["name"], args, tc["id"]))
        usage = data.get("usage") or {}
        return LLMResult(
            choice.get("content") or "",
            calls,
            usage.get("prompt_tokens", 0),
            usage.get("completion_tokens", 0),
            int((time.perf_counter() - started) * 1000),
            self.model,
        )


def create_provider(settings: Settings) -> Provider:
    from .sim import SimProvider

    choice = settings.llm_provider
    if choice == "auto":
        if settings.anthropic_api_key:
            choice = "anthropic"
        elif settings.openai_api_key or settings.openai_base_url != Settings.openai_base_url:
            choice = "openai"
        else:
            choice = "sim"
    if choice == "anthropic":
        if not settings.anthropic_api_key:
            raise RuntimeError("LLM_PROVIDER=anthropic needs ANTHROPIC_API_KEY")
        return AnthropicProvider(settings.anthropic_api_key, settings.anthropic_model)
    if choice == "openai":
        return OpenAICompatProvider(settings.openai_api_key, settings.openai_base_url, settings.openai_model)
    return SimProvider(delay=settings.sim_delay)
