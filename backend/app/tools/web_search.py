"""Web search tool for unknown-merchant lookup (capability #7).

Provider-agnostic and optional. If no provider/key is configured the tool
reports `available == False` and the agent degrades gracefully to an
LLM-only best guess (clearly labelled as such). Supported providers:
  * tavily  (https://tavily.com)
  * serpapi (https://serpapi.com)
"""
from __future__ import annotations

import httpx

from app.config import settings


class WebSearchResult:
    def __init__(self, available: bool, summary: str = "", sources: list[dict] | None = None):
        self.available = available
        self.summary = summary
        self.sources = sources or []

    def as_dict(self) -> dict:
        return {"available": self.available, "summary": self.summary,
                "sources": self.sources}


async def search_merchant(query: str) -> WebSearchResult:
    provider = settings.web_search_provider.lower()
    key = settings.web_search_api_key.strip()
    if provider == "none" or not key:
        return WebSearchResult(available=False)

    q = f"What is the merchant or charge '{query}'? Identify the company."
    try:
        if provider == "tavily":
            return await _tavily(q, key)
        if provider == "serpapi":
            return await _serpapi(query, key)
    except Exception as exc:  # network/parse failure -> graceful degrade
        return WebSearchResult(available=False, summary=f"search failed: {exc}")
    return WebSearchResult(available=False)


async def _tavily(query: str, key: str) -> WebSearchResult:
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(
            "https://api.tavily.com/search",
            json={"api_key": key, "query": query, "max_results": 4,
                  "include_answer": True},
        )
        resp.raise_for_status()
        data = resp.json()
    sources = [{"title": r.get("title"), "url": r.get("url")}
               for r in data.get("results", [])]
    return WebSearchResult(True, data.get("answer", ""), sources)


async def _serpapi(query: str, key: str) -> WebSearchResult:
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(
            "https://serpapi.com/search",
            params={"q": query, "api_key": key, "engine": "google"},
        )
        resp.raise_for_status()
        data = resp.json()
    organic = data.get("organic_results", [])[:4]
    summary = organic[0].get("snippet", "") if organic else ""
    sources = [{"title": r.get("title"), "url": r.get("link")} for r in organic]
    return WebSearchResult(True, summary, sources)
