"""Text embeddings with a dependency-free local fallback.

RAG over transaction history needs vectors. In production you'd call a real
embedding model (set EMBEDDINGS_API_KEY). For an offline-runnable demo we ship
a deterministic *hashing embedder*: it maps tokens into a fixed-dimension
bag-of-words vector and L2-normalizes it. It is not semantically rich, but it
is stable, free, fast, and good enough to demonstrate the retrieval pipeline.

The interface is identical in both modes, so swapping to a real model is a
config change, not a code change.
"""
from __future__ import annotations

import hashlib
import math
import re

import httpx

from app.config import settings

_TOKEN_RE = re.compile(r"[a-z0-9]+")
DIM = settings.embeddings_dim


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _local_embed(text: str) -> list[float]:
    vec = [0.0] * DIM
    for tok in _tokenize(text):
        h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
        idx = h % DIM
        sign = 1.0 if (h >> 8) % 2 == 0 else -1.0
        vec[idx] += sign
    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0:
        vec = [v / norm for v in vec]
    return vec


class Embedder:
    @property
    def uses_api(self) -> bool:
        return (
            settings.embeddings_provider != "local"
            and bool(settings.embeddings_api_key.strip())
        )

    async def embed(self, text: str) -> list[float]:
        text = (text or "").strip()
        if not text:
            return [0.0] * DIM
        if not self.uses_api:
            return _local_embed(text)
        return await self._api_embed(text)

    async def embed_many(self, texts: list[str]) -> list[list[float]]:
        if not self.uses_api:
            return [_local_embed(t) for t in texts]
        # API path: one request per call kept simple; batch in production.
        return [await self._api_embed(t) for t in texts]

    async def _api_embed(self, text: str) -> list[float]:
        url = settings.embeddings_base_url.rstrip("/") + "/embeddings"
        headers = {"Authorization": f"Bearer {settings.embeddings_api_key.strip()}"}
        payload = {"model": settings.embeddings_model, "input": text}
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
        vec = data["data"][0]["embedding"]
        # If the API dim differs from our column, truncate/pad to DIM so the
        # pgvector column stays consistent. (Document this in DECISIONS.md.)
        if len(vec) > DIM:
            vec = vec[:DIM]
        elif len(vec) < DIM:
            vec = vec + [0.0] * (DIM - len(vec))
        return vec


embedder = Embedder()
