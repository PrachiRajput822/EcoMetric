"""Shared types for planners: the components that turn a question into one tool call."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from ..data.profiler import Profile


class PlannerError(RuntimeError):
    """The planner could not produce a tool call (network error, no tool chosen, bad output)."""


@dataclass
class PlannedCall:
    tool: str
    args: dict[str, Any]
    planner: str  # gemini | ollama | rules
    model: str = ""
    raw: str = ""
    latency_ms: int = 0
    notes: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"tool": self.tool, "args": self.args, "planner": self.planner, "model": self.model,
                "latency_ms": self.latency_ms}


def build_system_prompt(profile: Profile) -> str:
    """Describe the dataset (never its rows) and the routing rules to the model."""
    lines = []
    for c, i in profile.columns.items():
        if i.role in ("id", "source", "other"):
            continue
        if i.role == "time":
            lines.append(f"- {c}: month column")
            continue
        if i.role == "entity":
            values = ", ".join(profile.entities.get(c, [])[:40])
            lines.append(f"- {c}: grouping column ({i.label}). Values: {values}")
            continue
        kind = "additive, use sum" if i.additive else "average or concentration, use avg, never sum"
        unit = f", unit {i.unit}" if i.unit else ""
        lines.append(f"- {c}: {i.label}{unit}; {i.role}; {kind}")
    periods = profile.periods
    year = periods[-1][:4] if periods else ""
    period_text = (f"Months available: {periods[0]} to {periods[-1]} (YYYY-MM). If a month has no year, use {year}."
                   if periods else "This dataset has no dates.")
    return f"""You are the question router for EcoMetric, a data assistant.
Answer every question by calling exactly one tool. Never calculate, estimate or write numbers yourself.
Tested code runs the tool and does all of the arithmetic.

Dataset: {profile.title} ({profile.source} data). {profile.description}
{period_text}
Columns:
{chr(10).join(lines)}

Routing rules:
1. Which, most, least, top, highest, lowest: rank_entities. Least or lowest means order asc.
2. Change, trend, over time, since, grew, fell: trend_over_time. For "since X" set only period_start.
3. Per occupant, per person, per capita, per household, per trip, per sq ft, efficiency, utilisation, rate or share:
   normalize_by. Most efficient means the lowest usage per unit, so order asc.
4. Two or more named entities: compare_entities.
5. Total, average, how much, how many: aggregate_total.
6. Last month, latest, this month or recent: latest_period true.
7. One specific month: set period_start and period_end to that month.
8. If the question needs data that is not in the columns above (for example cost, price, bill, tariff, emissions,
   or anything unrelated to this dataset), call cannot_answer and list the missing data. Never substitute another column.
9. Questions can be in English or Hindi. Copy column names and entity values exactly as listed above."""


_JSON_OBJ = re.compile(r"\{.*\}", re.S)
_GEMMA_CALL = re.compile(r"call:\s*([a-z_]+)\s*(\{.*\})", re.S)


def parse_text_call(text: str) -> tuple[str, dict[str, Any]] | None:
    """Recover a tool call written as text, either JSON or Gemma's native call:NAME{...} format."""
    if not text:
        return None
    m = _GEMMA_CALL.search(text)
    if m:
        try:
            return m.group(1), json.loads(m.group(2))
        except json.JSONDecodeError:
            pass
    m = _JSON_OBJ.search(text)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    name = obj.get("name") or obj.get("tool") or obj.get("function")
    args = obj.get("args") or obj.get("arguments") or obj.get("parameters") or {}
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            return None
    if isinstance(name, str) and isinstance(args, dict):
        return name, args
    return None
