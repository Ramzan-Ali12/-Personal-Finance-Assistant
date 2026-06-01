"""Shared result type returned by every handler."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class HandlerResult:
    answer: str
    route: str
    data: dict[str, Any] = field(default_factory=dict)
    used_tools: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
