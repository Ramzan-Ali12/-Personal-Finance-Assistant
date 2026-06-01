# Decisions, trade-offs & assumptions

A focused log of the choices that shaped the build and what I traded away.

## Stack choices

- **FastAPI + async SQLAlchemy/SQLModel + asyncpg.** Chosen for genuine
  concurrency (the brief explicitly cares about many simultaneous users) and a
  low-ceremony, typed developer experience. SQLModel gives Pydantic + ORM models
  in one place.
- **PostgreSQL + pgvector (single store).** Avoids running a separate vector DB.
  One system serves both the relational aggregates (the cheap, common path) and
  semantic retrieval (the RAG path). Operationally simpler and cheaper.
- **Provider-agnostic LLM via an OpenAI-compatible client.** The original design
  hard-coded Anthropic models. No Anthropic key was available and provider
  flexibility was requested, so model choice is **configuration**, and the same
  code targets OpenRouter / OpenAI / Together / Ollama. A **mock fallback** means
  the app runs and is testable with no key at all.
- **Self-hosted JWT auth (passlib + python-jose).** The brief calls auth a
  commodity and *encourages* managed providers. I kept it in-repo so the project
  is runnable offline with no external signup. It's isolated in `app/auth/`, so
  swapping in Clerk/Auth0/Supabase means changing only `security.py`/`deps.py`.

## Algorithmic choices

- **Cheap-first routing.** A keyword classifier handles the common phrasings for
  free; the LLM is only consulted when the rules are unsure. Trade-off: rules can
  occasionally misroute unusual phrasings — mitigated by LLM escalation when a key
  is present, and by RAG/clarify fallbacks when not.
- **Numbers from SQL, words from the LLM.** The narration layer is forbidden from
  inventing figures. This is the main defence against hallucinated financial data.
- **Heuristic detection (subscriptions/anomalies/categorisation).** Fast, free,
  and transparent. Trade-off: less flexible than an LLM classifier; novel patterns
  may be missed. Acceptable because these run on every row / on demand and must be
  cheap. The thresholds are centralised and easy to tune.
- **Anomalies are per-user relative.** A z-score against the user's own
  category history, not a global rule, so "unusual" means unusual *for them*.

## Embeddings

- Ships with a **dependency-free local hashing embedder** so RAG works offline.
  It captures lexical overlap, not deep semantics. Setting `EMBEDDINGS_*` swaps in
  a real model with no code change. If the API embedding dimension differs from the
  `EMBEDDINGS_DIM` column, vectors are truncated/padded to keep the pgvector column
  consistent (documented limitation; pick a matching dim in production).

## Receipts / vision

- The model is asked to self-report **confidence** and **issues** (blur, missing
  total, language). Missing/low-confidence totals are **not auto-booked** — the
  assistant asks the user to confirm. The raw receipt row is always saved first so
  an upload is never lost, even if extraction fails.

## API / UX

- `POST /api/chat` (JSON) is the primary path used by the UI for reliability; an
  SSE `/api/chat/stream` is provided to honour the streaming design. SSE replays a
  fully-computed answer (works identically in mock and live modes) rather than
  streaming raw tokens — a deliberate simplicity/robustness trade-off.

## Assumptions written down

- Amount sign convention normalised at ingest: **negative = spend, positive = income**.
- A "subscription" = ≥3 charges at a stable cadence (weekly/biweekly/monthly) with
  low amount variance.
- Monthly is the default budget/comparison period.
- The mock-bank generator stands in for a real bank connector and intentionally
  injects recurring charges, salary, and a couple of anomalies for demoing.

## Known limitations / intentionally skipped (time-boxed)

- No Redis cache / rollup tables yet (design noted in ARCHITECTURE.md).
- No background job queue; embedding happens inline on import (fine for sample
  sizes, would move off-request at scale).
- Web search ships disabled; it's pluggable (`tavily`/`serpapi`).
- Auth lacks refresh tokens, email verification, and password reset.
- The local embedder limits RAG quality until a real embedding model is configured.
```
