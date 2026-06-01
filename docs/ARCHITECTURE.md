# Architecture

This document explains the system design and the reasoning behind it. The guiding
principle is **effort proportional to the task**: do the cheap, deterministic
thing whenever possible, and reserve LLM/vision spend for work that truly needs it.

## Request lifecycle (a chat message)

1. **Auth** — `get_current_user` resolves the JWT to a `User`. Every query is
   scoped by `user_id`, so users never see each other's data.
2. **Memory injection** — active `UserContext` rows are loaded and rendered into a
   compact system-prompt prefix (capability #10).
3. **Classification** — `router/intent.py`:
   - A keyword classifier returns an intent + confidence in microseconds.
   - If confidence ≥ 0.7 (the common case) we use it directly: **zero LLM cost.**
   - If it's unsure *and* a real LLM is configured, we spend one cheap model call
     to disambiguate. With no LLM we default to RAG/clarify.
4. **Dispatch** — `router/orchestrator.py` sends the request to exactly one handler.
5. **Compute** — the handler runs deterministic SQL/tools to produce *facts*.
6. **Narrate** — `router/narrate.py` turns the facts into plain English using the
   cheap model (or a deterministic fallback). The model is forbidden from
   inventing numbers; it only phrases the facts it's given.
7. **Log** — both turns are persisted to `chat_messages` with the route + tools used.

## Why four handlers?

The brief stresses these requests are *not the same kind of work*. Encoding that
directly:

- **SQL handler** (`handlers/sql_handler.py`) — quantitative questions and
  time comparisons. Pure aggregate queries over indexed columns. O(index scan),
  independent of model context. This is the workhorse and the cheapest path.
- **RAG handler** (`handlers/rag_handler.py`) — fuzzy/semantic questions. Embeds
  the query, pulls the **top-k** nearest transactions from pgvector, summarises
  only those. The prompt size is constant no matter how big the history is.
- **Agent handler** (`handlers/agent_handler.py`) — multi-faceted work:
  subscriptions, anomalies, budgets, cut-backs, and the genuinely multi-step
  **merchant lookup** (locate the charge → research it via web search → decide if
  it has enough → explain, with graceful recovery if a step is unavailable).
- **Vision handler** (`handlers/vision_handler.py`) — receipt understanding:
  extract structured JSON, validate, and either record the expense or flag a
  low-confidence result for user confirmation.

## The "large context" strategy (the crux)

A user can have years of transactions — far more than fits in any context window.
We never try. Two mechanisms keep the model's input small and constant:

1. **Aggregation in the database.** Totals, per-category breakdowns, monthly
   rollups, and baselines are computed by Postgres. The model sees a handful of
   numbers, not thousands of rows.
2. **Retrieval, not dumping.** For semantic questions, pgvector returns only the
   *k* most relevant transactions (default 12). The cosine-distance ordering is
   index-accelerated.

As data grows 10×–100×, the SQL stays index-bound and the retrieval prompt size
is unchanged. Latency and cost grow with *query complexity*, not *history size*.

## Model selection / cost control

| Work | Model tier | Rationale |
|------|-----------|-----------|
| Intent disambiguation | cheap (`router_model`) | tiny prompt, only when unsure |
| Phrasing answers | cheap | facts already computed |
| Agentic reasoning | strong (`agent_model`) | multi-step judgement |
| Receipt extraction | strong vision (`vision_model`) | image understanding |

Heuristic tools (categorisation, subscription/anomaly detection) use **no model
at all**, which is what keeps per-interaction cost low.

## Data model (Postgres + pgvector)

- `users` — accounts.
- `transactions` — signed `amount`, merchant/description/category, `source`,
  a `dedupe_hash` (unique per user → idempotent imports), and an `embedding`
  `vector` column for RAG.
- `budgets` — per-category or overall monthly/weekly limits.
- `user_context` — durable memory facts.
- `receipts` — uploaded receipts + extraction status.
- `chat_messages` — conversation log with the route/tools used.

Indexes on `(user_id, txn_date)` and `(user_id, category)` keep the aggregate
queries fast.

## Concurrency & multi-user

- Async stack end-to-end (FastAPI, asyncpg) with a bounded connection pool
  (`pool_size`/`max_overflow`) and `pool_pre_ping` to survive dropped connections.
- Per-request sessions; no shared mutable state.
- Strict `user_id` scoping on every query.

## Scaling further (not built, but where I'd go)

- **Cache** hot aggregates (e.g. monthly rollups) in Redis; invalidate on import.
- **Materialised views** or a rollup table for per-month/per-category totals.
- **Background workers** for embedding large imports and re-detecting
  subscriptions/anomalies off the request path.
- **Streaming** real model tokens for the chat endpoint when a live LLM is used.
- **Approximate vector index** (IVFFlat/HNSW) once the vector table is large.
