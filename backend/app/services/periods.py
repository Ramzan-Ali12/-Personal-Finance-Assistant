"""Natural-language -> date range resolution.

Turning phrases like "last month", "in March", "this year", "last 7 days"
into concrete (start, end) ranges is pure, deterministic logic — no reason to
spend an LLM call on it. The SQL handler uses this to scope aggregations.
"""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta

_MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
_MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})


@dataclass
class Period:
    start: date
    end: date
    label: str


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    last = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last)


def resolve_period(text: str, today: date | None = None) -> Period:
    """Best-effort period extraction. Defaults to the last 30 days."""
    today = today or date.today()
    t = text.lower()

    if "today" in t:
        return Period(today, today, "today")
    if "yesterday" in t:
        y = today - timedelta(days=1)
        return Period(y, y, "yesterday")

    # "last N days/weeks/months"
    m = re.search(r"last\s+(\d+)\s+(day|week|month)", t)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        days = n * {"day": 1, "week": 7, "month": 30}[unit]
        return Period(today - timedelta(days=days), today, f"last {n} {unit}s")

    if "last week" in t:
        return Period(today - timedelta(days=7), today, "last week")
    if "this week" in t:
        start = today - timedelta(days=today.weekday())
        return Period(start, today, "this week")

    if "last month" in t:
        first_this = today.replace(day=1)
        last_prev = first_this - timedelta(days=1)
        s, e = _month_bounds(last_prev.year, last_prev.month)
        return Period(s, e, "last month")
    if "this month" in t:
        s, _ = _month_bounds(today.year, today.month)
        return Period(s, today, "this month")

    if "last year" in t:
        return Period(date(today.year - 1, 1, 1), date(today.year - 1, 12, 31), "last year")
    if "this year" in t or "ytd" in t or "year to date" in t:
        return Period(date(today.year, 1, 1), today, "this year")

    # Named month, e.g. "in March" (assume most recent occurrence).
    for name, num in _MONTHS.items():
        if re.search(rf"\b{name}\b", t):
            year = today.year if num <= today.month else today.year - 1
            s, e = _month_bounds(year, num)
            return Period(s, e, name.capitalize())

    return Period(today - timedelta(days=30), today, "last 30 days")
