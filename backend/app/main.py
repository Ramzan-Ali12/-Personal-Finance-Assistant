"""FastAPI application entrypoint."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, budgets, chat, context, imports, receipts, transactions
from app.config import settings
from app.db import init_db, pgvector_enabled


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create extension + tables on startup for a one-command local setup.
    # (Production: run Alembic migrations instead; see backend/alembic.)
    await init_db()
    yield


app = FastAPI(
    title="Personal Finance Assistant API",
    version="1.0.0",
    description="AI-driven, multi-user financial companion.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in (auth.router, transactions.router, budgets.router, receipts.router,
          imports.router, context.router, chat.router):
    app.include_router(r)


@app.get("/api/health", tags=["health"])
async def health():
    return {
        "status": "ok",
        "llm_mode": "live" if settings.llm_enabled else "mock",
        "embeddings": "api" if settings.embeddings_provider != "local" else "local",
        "pgvector": pgvector_enabled,
        "web_search": settings.web_search_provider,
    }
