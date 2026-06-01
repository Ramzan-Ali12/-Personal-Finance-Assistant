"""Provider-agnostic LLM client.

Everything goes through an OpenAI-compatible Chat Completions API, which means
the exact same code works with OpenRouter, OpenAI, Together, Groq, a local
Ollama/LM Studio server, etc. — you only change `LLM_BASE_URL`, `LLM_API_KEY`
and the model names in `.env`.

Cost/latency strategy (a core evaluation point):
    * A cheap, fast model (`router_model`) is used for classification and
      short summaries.
    * A stronger model (`agent_model` / `vision_model`) is reserved for
      multi-step agentic reasoning and image understanding.
The caller picks the tier explicitly, so we never apply the heavy model to
work a cheap one can do.

If no API key is configured the client reports `available == False`. Callers
must then fall back to their own deterministic logic, so the whole product is
demoable offline with correct (if less fluent) answers.
"""
from __future__ import annotations

import json
from typing import Any

import httpx

from app.config import settings


class LLMUnavailable(RuntimeError):
    pass


class LLMClient:
    def __init__(self) -> None:
        self._base_url = settings.llm_base_url.rstrip("/")
        self._api_key = settings.llm_api_key.strip()
        self.router_model = settings.llm_router_model
        self.agent_model = settings.llm_agent_model
        self.vision_model = settings.llm_vision_model

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        # OpenRouter likes these for attribution; harmless elsewhere.
        if "openrouter" in self._base_url:
            headers["HTTP-Referer"] = "http://localhost"
            headers["X-Title"] = "Personal Finance Assistant"
        return headers

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 700,
        timeout: float = 40.0,
    ) -> str:
        """Single-shot chat completion returning assistant text."""
        if not self.available:
            raise LLMUnavailable("No LLM API key configured")

        payload = {
            "model": model or self.router_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{self._base_url}/chat/completions",
                headers=self._headers(),
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
        return data["choices"][0]["message"]["content"] or ""

    async def chat_json(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        max_tokens: int = 500,
    ) -> dict[str, Any]:
        """Chat completion whose content we parse as JSON (best-effort)."""
        text = await self.chat(
            messages, model=model, temperature=0.0, max_tokens=max_tokens
        )
        return _extract_json(text)

    async def vision(
        self,
        prompt: str,
        image_data_url: str,
        *,
        max_tokens: int = 800,
        timeout: float = 60.0,
    ) -> str:
        """Send an image + instruction to a vision-capable model."""
        if not self.available:
            raise LLMUnavailable("No LLM API key configured")
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_data_url}},
                ],
            }
        ]
        payload = {
            "model": self.vision_model,
            "messages": messages,
            "temperature": 0.0,
            "max_tokens": max_tokens,
        }
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{self._base_url}/chat/completions",
                headers=self._headers(),
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
        return data["choices"][0]["message"]["content"] or ""


def _extract_json(text: str) -> dict[str, Any]:
    """Pull the first JSON object out of an LLM response, tolerating prose/fences."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    return {}


# A process-wide singleton is fine: the client is stateless and httpx clients
# are created per-call.
llm = LLMClient()
