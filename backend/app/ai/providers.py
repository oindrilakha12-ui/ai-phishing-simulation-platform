"""LLM provider interface. AI_PROVIDER + API key env vars select a live provider; otherwise DEMO MODE.

Every call is prefixed with GUARDRAIL_PREFIX — callers cannot skip it.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.ai.prompts import GUARDRAIL_PREFIX
from app.core.config import get_settings


@dataclass
class LLMResult:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    model: str = ""


class LLMProvider:
    name = "base"

    def complete(self, system: str, user: str, max_tokens: int = 800) -> LLMResult:
        raise NotImplementedError


class OpenAIProvider(LLMProvider):
    name = "openai"

    def complete(self, system: str, user: str, max_tokens: int = 800) -> LLMResult:
        s = get_settings()
        start = time.perf_counter()
        r = httpx.post(f"{s.openai_base_url}/chat/completions", timeout=s.ai_timeout_seconds,
                       headers={"Authorization": f"Bearer {s.openai_api_key}"},
                       json={"model": s.openai_model, "max_tokens": max_tokens, "temperature": 0.2,
                             "messages": [{"role": "system", "content": GUARDRAIL_PREFIX + "\n\n" + system},
                                          {"role": "user", "content": user}]})
        r.raise_for_status()
        data = r.json()
        usage = data.get("usage", {})
        return LLMResult(data["choices"][0]["message"]["content"], usage.get("prompt_tokens", 0),
                         usage.get("completion_tokens", 0), (time.perf_counter() - start) * 1000, s.openai_model)


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def complete(self, system: str, user: str, max_tokens: int = 800) -> LLMResult:
        s = get_settings()
        start = time.perf_counter()
        r = httpx.post("https://api.anthropic.com/v1/messages", timeout=s.ai_timeout_seconds,
                       headers={"x-api-key": s.anthropic_api_key or "", "anthropic-version": "2023-06-01"},
                       json={"model": s.anthropic_model, "max_tokens": max_tokens,
                             "system": GUARDRAIL_PREFIX + "\n\n" + system,
                             "messages": [{"role": "user", "content": user}]})
        r.raise_for_status()
        data = r.json()
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        usage = data.get("usage", {})
        return LLMResult(text, usage.get("input_tokens", 0), usage.get("output_tokens", 0),
                         (time.perf_counter() - start) * 1000, s.anthropic_model)


def get_provider() -> LLMProvider | None:
    """Return the live provider, or None in DEMO MODE."""
    s = get_settings()
    if s.demo_mode:
        return None
    return OpenAIProvider() if s.ai_provider == "openai" else AnthropicProvider()


def parse_json(text: str) -> dict[str, Any]:
    """Pull the first JSON object out of a model reply (models sometimes wrap it in prose/fences)."""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("no JSON object in model output")
    return json.loads(m.group(0))
