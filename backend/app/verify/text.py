"""Formatting helpers shared by answers, caveats and charts (English and Hindi)."""

from __future__ import annotations

import math
from typing import Any

EN_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
             "November", "December"]
HI_MONTHS = ["जनवरी", "फरवरी", "मार्च", "अप्रैल", "मई", "जून", "जुलाई", "अगस्त", "सितंबर", "अक्टूबर", "नवंबर", "दिसंबर"]


def fmt(v: Any) -> str:
    """Format a number for display. Only values computed by tools are ever passed in."""
    if v is None:
        return "n/a"
    f = float(v)
    if math.isnan(f):
        return "n/a"
    a = abs(f)
    if f.is_integer() and a < 1e15:
        return f"{int(f):,}"
    if a >= 100:
        return f"{f:,.0f}"
    if a >= 10:
        return f"{f:,.1f}"
    return f"{f:,.2f}"


def month(period: str | None, lang: str = "en", short: bool = False) -> str:
    if not period or len(period) < 7:
        return period or ""
    y, m = period[:4], int(period[5:7])
    names = HI_MONTHS if lang == "hi" else EN_MONTHS
    name = names[m - 1]
    if short and lang != "hi":
        name = name[:3]
    return f"{name} {y}"


def period_text(start: str | None, end: str | None, lang: str = "en") -> str:
    if start is None:
        return "सभी महीनों" if lang == "hi" else "all months"
    if start == end:
        return month(start, lang)
    names = HI_MONTHS if lang == "hi" else EN_MONTHS
    joiner = " से " if lang == "hi" else " to "
    if start[:4] == end[:4]:
        return f"{names[int(start[5:7]) - 1]}{joiner}{month(end, lang)}"
    return f"{month(start, lang)}{joiner}{month(end, lang)}"


def join_list(items: list[str], lang: str = "en") -> str:
    items = [str(i) for i in items]
    if len(items) <= 1:
        return "".join(items)
    last = " और " if lang == "hi" else " and "
    return ", ".join(items[:-1]) + last + items[-1]


def unit_suffix(unit: str) -> str:
    return f" {unit}" if unit else ""
