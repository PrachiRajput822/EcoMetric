"""Plotly chart specifications for each tool result.

The backend returns data and structure only. The frontend applies theme colours, so charts
follow light and dark mode.
"""

from __future__ import annotations

from typing import Any

from .data.store import Dataset
from .tools.registry import ToolResult
from .verify.text import fmt, month, period_text


def _axis_title(ds: Dataset, col: str, lang: str, suffix: str = "") -> str:
    unit = ds.profile.columns[col].unit
    label = ds.profile.label(col, lang)
    return f"{label}{suffix}" + (f" ({unit})" if unit else "")


def build_chart(ds: Dataset, r: ToolResult, lang: str = "en") -> dict[str, Any] | None:
    p = ds.profile
    when = period_text(r.period_start, r.period_end, lang)
    outliers = {(o["entity"], o["period"]) for o in ds.health.get("outliers", []) if o["column"] == r.metric}

    if r.tool in ("rank_entities", "compare_entities", "normalize_by"):
        rows = [x for x in r.table if x.get("value") is not None]
        if not rows:
            return None
        rows = list(reversed(rows))  # Plotly draws horizontal bars bottom-up; keep the answer on top.
        highlight = str(r.table[0]["entity"]) if r.tool != "compare_entities" else str(r.headline["high"]["entity"])
        percent = r.tool == "normalize_by" and r.headline.get("as_percent")
        if r.tool == "normalize_by":
            per = p.columns[r.denominator].per_label or p.label(r.denominator)
            if lang == "hi":
                per = p.columns[r.denominator].per_label_hi or per
            x_title = (f"{p.label(r.metric, lang)} / {p.label(r.denominator, lang)} (%)" if percent
                       else _axis_title(ds, r.metric, lang, f" {'प्रति' if lang == 'hi' else 'per'} {per}"))
        else:
            x_title = _axis_title(ds, r.metric, lang)
        return {
            "kind": "bar",
            "data": [{
                "type": "bar", "orientation": "h",
                "y": [str(x["entity"]) for x in rows],
                "x": [x["value"] for x in rows],
                "text": [fmt(x["value"]) + ("%" if percent else "") for x in rows],
                "textposition": "auto",
                "hovertemplate": "%{y}: %{text}<extra></extra>",
                "highlight": [str(x["entity"]) == highlight for x in rows],
            }],
            "layout": {"title": {"text": when}, "xaxis": {"title": {"text": x_title}, "rangemode": "tozero"},
                       "yaxis": {"automargin": True}, "height": max(260, 60 + 44 * len(rows))},
        }

    if r.tool == "trend_over_time":
        ent = r.args.get("entity")
        xs = [month(x["period"], lang, short=True) for x in r.table]
        ys = [x["value"] for x in r.table]
        flagged = [bool(ent) and (ent, x["period"]) in outliers for x in r.table]
        return {
            "kind": "line",
            "data": [{
                "type": "scatter", "mode": "lines+markers", "x": xs, "y": ys, "connectgaps": False,
                "name": ent or p.label(r.metric, lang),
                "text": [fmt(v) for v in ys], "hovertemplate": "%{x}: %{text}<extra></extra>",
                "flagged": flagged,
            }],
            "layout": {"title": {"text": (ent + " · " if ent else "") + when},
                       "yaxis": {"title": {"text": _axis_title(ds, r.metric, lang)}, "rangemode": "tozero"},
                       "height": 320},
        }

    if r.tool == "aggregate_total" and r.table and "period" in r.table[0]:
        return {
            "kind": "bar",
            "data": [{
                "type": "bar", "x": [month(x["period"], lang, short=True) for x in r.table],
                "y": [x["value"] for x in r.table], "text": [fmt(x["value"]) for x in r.table],
                "textposition": "auto", "hovertemplate": "%{x}: %{text}<extra></extra>",
                "highlight": [False for _ in r.table],
            }],
            "layout": {"title": {"text": ("Monthly breakdown · " if lang != "hi" else "मासिक विवरण · ") + when},
                       "yaxis": {"title": {"text": _axis_title(ds, r.metric, lang)}, "rangemode": "tozero"},
                       "height": 300},
        }
    return None
