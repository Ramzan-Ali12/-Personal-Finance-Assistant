"""Turn computed facts into plain-English answers.

Hard rule: *numbers come from our SQL/tools, words come from the LLM*. We pass
the model only the small, already-computed facts and forbid it from inventing
figures. With no LLM available we return a deterministic fallback string, so
answers stay correct (if less fluent) offline.
"""
from __future__ import annotations

import json

from app.llm.client import llm

_SYSTEM = (
    "You are a concise, friendly personal-finance assistant. Answer the user "
    "using ONLY the facts in the provided JSON. Never invent numbers. If the "
    "facts are empty or insufficient, say so plainly. Keep it short (2-4 "
    "sentences) unless a list is clearly warranted. Use the user's currency."
)


async def narrate(
    user_message: str,
    facts: dict,
    fallback: str,
    context_prefix: str = "",
    max_tokens: int = 350,
) -> str:
    if not llm.available:
        return fallback

    system = _SYSTEM
    if context_prefix:
        system += "\n\n" + context_prefix

    try:
        return await llm.chat(
            messages=[
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": (
                        f"User asked: {user_message}\n\n"
                        f"Facts (JSON):\n{json.dumps(facts, default=str)}\n\n"
                        "Write the answer."
                    ),
                },
            ],
            model=llm.router_model,  # cheap model is plenty for phrasing
            max_tokens=max_tokens,
            temperature=0.3,
        )
    except Exception:
        return fallback
