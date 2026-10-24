"""Deterministic analysis tools.

The language model never calculates anything. It only picks one of these tools and fills in
its arguments. Every argument is validated against the dataset profile, every SQL identifier
comes from that profile (never from model text) and every value is a bound parameter.
Each result is computed twice, once in DuckDB and once in pandas, and the two must agree.
"""

from __future__ import annotations

import difflib
import math
import re
from dataclasses import dataclass, field
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from ..data.profiler import PERIOD_COL, Profile
from ..data.store import Dataset, _records

MONTHS_EN = ["january", "february", "march", "april", "may", "june", "july", "august", "september",
             "october", "november", "december"]
MONTH_LOOKUP = {**{m: i + 1 for i, m in enumerate(MONTHS_EN)}, **{m[:3]: i + 1 for i, m in enumerate(MONTHS_EN)},
                "sept": 9}
EVIDENCE_LIMIT = 200

MONEY_REASON = "The dataset has no cost, price or tariff column, so money cannot be calculated."
MONEY_FIELD = "cost or tariff (₹ per unit)"
REASONS_HI = {
    MONEY_REASON: "डेटा में लागत, कीमत या टैरिफ का कोई कॉलम नहीं है, इसलिए पैसे की गणना नहीं हो सकती।",
    MONEY_FIELD: "लागत या टैरिफ (₹ प्रति यूनिट)",
}


class ToolInputError(ValueError):
    """Arguments that cannot be answered from the data. The message is shown to the user."""

    def __init__(self, message: str, missing_fields: list[str] | None = None, code: str = "invalid_input",
                 hi: str | None = None):
        super().__init__(message)
        self.missing_fields = missing_fields or []
        self.code = code
        self.hi = hi or message


# --------------------------------------------------------------------------- argument models

AGG_ALIASES = {"average": "avg", "mean": "avg", "total": "sum", "maximum": "max", "minimum": "min",
               "highest": "max", "lowest": "min", "avg": "avg", "sum": "sum", "max": "max", "min": "min", "count": "count"}
ORDER_ALIASES = {"descending": "desc", "highest": "desc", "most": "desc", "desc": "desc", "top": "desc",
                 "ascending": "asc", "lowest": "asc", "least": "asc", "asc": "asc", "bottom": "asc"}


def _blank_to_none(v: Any) -> Any:
    if isinstance(v, str) and v.strip().lower() in ("", "none", "null", "all", "any"):
        return None
    return v


class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


class PeriodArgs(_Base):
    period_start: str | None = None
    period_end: str | None = None
    latest_period: bool = False

    _blank = field_validator("period_start", "period_end", mode="before")(_blank_to_none)


class RankArgs(PeriodArgs):
    metric: str
    group_by: str | None = None
    agg: Literal["sum", "avg", "max", "min"] = "sum"
    order: Literal["desc", "asc"] = "desc"
    limit: int = Field(10, ge=1, le=50)

    _g = field_validator("group_by", mode="before")(_blank_to_none)

    @field_validator("agg", mode="before")
    @classmethod
    def _agg(cls, v: Any) -> Any:
        return AGG_ALIASES.get(str(v).lower(), v) if v is not None else "sum"

    @field_validator("order", mode="before")
    @classmethod
    def _order(cls, v: Any) -> Any:
        return ORDER_ALIASES.get(str(v).lower(), v) if v is not None else "desc"


class TrendArgs(PeriodArgs):
    metric: str
    entity: str | None = None
    entity_column: str | None = None
    agg: Literal["sum", "avg", "max", "min"] = "sum"

    _e = field_validator("entity", "entity_column", mode="before")(_blank_to_none)
    _agg = field_validator("agg", mode="before")(lambda v: AGG_ALIASES.get(str(v).lower(), v) if v is not None else "sum")


class CompareArgs(PeriodArgs):
    metric: str
    entities: list[str] = Field(min_length=2, max_length=10)
    group_by: str | None = None
    agg: Literal["sum", "avg", "max", "min"] = "sum"

    _g = field_validator("group_by", mode="before")(_blank_to_none)
    _agg = field_validator("agg", mode="before")(lambda v: AGG_ALIASES.get(str(v).lower(), v) if v is not None else "sum")


class AggregateArgs(PeriodArgs):
    metric: str
    agg: Literal["sum", "avg", "max", "min", "count"] = "sum"
    entities: list[str] = Field(default_factory=list, max_length=20)
    entity_column: str | None = None

    _g = field_validator("entity_column", mode="before")(_blank_to_none)
    _agg = field_validator("agg", mode="before")(lambda v: AGG_ALIASES.get(str(v).lower(), v) if v is not None else "sum")


class NormalizeArgs(PeriodArgs):
    metric: str
    denominator: str
    group_by: str | None = None
    order: Literal["asc", "desc"] = "asc"
    limit: int = Field(10, ge=1, le=50)

    _g = field_validator("group_by", mode="before")(_blank_to_none)
    _order = field_validator("order", mode="before")(lambda v: ORDER_ALIASES.get(str(v).lower(), v) if v is not None else "asc")


class CannotAnswerArgs(_Base):
    reason: str = Field(min_length=1, max_length=400)
    missing_fields: list[str] = Field(default_factory=list, max_length=10)


ARG_MODELS: dict[str, type[_Base]] = {
    "rank_entities": RankArgs,
    "trend_over_time": TrendArgs,
    "compare_entities": CompareArgs,
    "aggregate_total": AggregateArgs,
    "normalize_by": NormalizeArgs,
    "cannot_answer": CannotAnswerArgs,
}


def validate_args(tool: str, args: dict[str, Any]) -> _Base:
    model = ARG_MODELS.get(tool)
    if model is None:
        raise ToolInputError(f"Unknown analysis tool '{tool}'.", code="unknown_tool")
    try:
        return model.model_validate(args or {})
    except ValidationError as exc:
        first = exc.errors()[0]
        loc = ".".join(str(x) for x in first.get("loc", []))
        raise ToolInputError(f"Invalid value for '{loc}': {first.get('msg')}.", code="invalid_args") from exc


# --------------------------------------------------------------------------- tool schemas for the model


def build_tool_specs(profile: Profile) -> list[dict[str, Any]]:
    """JSON-schema function declarations, with enums limited to this dataset's real columns."""
    metrics = [c for c, i in profile.columns.items() if i.kind == "number" and i.role in ("metric", "denominator")]
    denominators = [c for c, i in profile.columns.items() if i.kind == "number" and i.role == "denominator"] or metrics
    entity_cols = profile.entity_columns or []
    all_entities = sorted({v for vals in profile.entities.values() for v in vals})[:150]
    period_props = {
        "period_start": {"type": "string", "description": "First month to include, format YYYY-MM. For one month, set period_start and period_end to the same month. For 'since X', set only period_start."},
        "period_end": {"type": "string", "description": "Last month to include, format YYYY-MM. Omit for all months."},
        "latest_period": {"type": "boolean", "description": "True when the user says last month, latest, recent or this month."},
    }
    metric_prop = {"type": "string", "enum": metrics, "description": "Numeric column to analyse."}
    group_prop = {"type": "string", "enum": entity_cols, "description": "Column whose values are compared (for example building)."}
    entity_prop = {"type": "string", "enum": all_entities} if all_entities else {"type": "string"}
    agg_prop = {"type": "string", "enum": ["sum", "avg", "max", "min"],
                "description": "Use sum for totals of additive quantities; avg for concentrations, rates or averages."}

    specs = [
        {"name": "rank_entities",
         "description": "Rank entities (buildings, wards, stations, routes) by a metric. Use for which/most/least/top questions.",
         "parameters": {"type": "object", "properties": {
             "metric": metric_prop, "group_by": group_prop, "agg": agg_prop,
             "order": {"type": "string", "enum": ["desc", "asc"], "description": "desc for most/highest, asc for least/lowest."},
             "limit": {"type": "integer", "description": "How many to return, default 10."}, **period_props},
             "required": ["metric"]}},
        {"name": "trend_over_time",
         "description": "Show how a metric changed month by month, for one entity or for all combined. Use for change, trend, since, over time.",
         "parameters": {"type": "object", "properties": {
             "metric": metric_prop, "entity": {**entity_prop, "description": "One entity to follow. Omit for all combined."},
             "entity_column": group_prop, "agg": agg_prop, **period_props}, "required": ["metric"]}},
        {"name": "compare_entities",
         "description": "Compare a metric between two or more named entities.",
         "parameters": {"type": "object", "properties": {
             "metric": metric_prop, "entities": {"type": "array", "items": entity_prop, "description": "Entities to compare."},
             "group_by": group_prop, "agg": agg_prop, **period_props}, "required": ["metric", "entities"]}},
        {"name": "aggregate_total",
         "description": "One number: total, average, maximum, minimum or count of a metric, optionally for some entities.",
         "parameters": {"type": "object", "properties": {
             "metric": metric_prop, "agg": {"type": "string", "enum": ["sum", "avg", "max", "min", "count"]},
             "entities": {"type": "array", "items": entity_prop, "description": "Limit to these entities. Omit for all."},
             "entity_column": group_prop, **period_props}, "required": ["metric"]}},
        {"name": "normalize_by",
         "description": "Fair comparison: metric divided by a denominator (per occupant, per household, per trip, utilisation). "
                        "Use for efficiency, per person, per capita, per sq ft, rate or share questions. "
                        "Most efficient means lowest usage per unit, so order asc.",
         "parameters": {"type": "object", "properties": {
             "metric": metric_prop, "denominator": {"type": "string", "enum": denominators, "description": "Column to divide by."},
             "group_by": group_prop, "order": {"type": "string", "enum": ["asc", "desc"]},
             "limit": {"type": "integer"}, **period_props}, "required": ["metric", "denominator"]}},
        {"name": "cannot_answer",
         "description": "Use when the question needs data that is not in the dataset (for example cost when there is no cost "
                        "or tariff column), or is not about this data. Never guess.",
         "parameters": {"type": "object", "properties": {
             "reason": {"type": "string", "description": "Short reason in plain language."},
             "missing_fields": {"type": "array", "items": {"type": "string"}, "description": "Data that would be needed."}},
             "required": ["reason"]}},
    ]
    for s in specs:  # never offer enums that would be empty
        for prop in s["parameters"]["properties"].values():
            if "enum" in prop and not prop["enum"]:
                prop.pop("enum")
            if prop.get("type") == "array" and "enum" in prop.get("items", {}) and not prop["items"]["enum"]:
                prop["items"].pop("enum")
    return specs


# --------------------------------------------------------------------------- resolution helpers


def q(name: str) -> str:
    """Quote an identifier. Callers must pass a name that was validated against the profile."""
    return '"' + name.replace('"', '""') + '"'


def note(code: str, **params: Any) -> dict[str, Any]:
    return {"code": code, "params": params}


def resolve_column(profile: Profile, name: str | None, *, numeric: bool = False, what: str = "column") -> str:
    if not name:
        raise ToolInputError(f"No {what} was given.", code="missing_column")
    cols = profile.columns
    candidates = [c for c, i in cols.items() if (not numeric or (i.kind == "number" and i.role in ("metric", "denominator")))]
    key = name.strip().lower()
    for c in candidates:
        if c.lower() == key or cols[c].label.lower() == key or (cols[c].label_hi and cols[c].label_hi == name.strip()):
            return c
    for c in candidates:
        if key in [k.lower() for k in cols[c].keywords]:
            return c
    raise ToolInputError(f"The dataset has no {what} called '{name}'.", missing_fields=[name], code="unknown_column",
                         hi=f"डेटा में '{name}' नाम का कोई कॉलम नहीं है।")


def resolve_entity_column(profile: Profile, name: str | None) -> str:
    if name:
        col = resolve_column(profile, name, what="grouping column")
        if col not in profile.entity_columns:
            raise ToolInputError(f"'{name}' cannot be used to group the data.", code="bad_group")
        return col
    if not profile.primary_entity:
        raise ToolInputError("The dataset has no column to group by (such as building or ward).", code="no_entity")
    return profile.primary_entity


def resolve_entities(profile: Profile, column: str, values: list[str], notes: list[dict]) -> list[str]:
    known = profile.entities.get(column, [])
    lower = {v.lower(): v for v in known}
    aliases = {a.lower(): canon for canon, al in profile.entity_aliases.items() for a in al}
    out: list[str] = []
    for raw in values:
        v = str(raw).strip()
        k = v.lower()
        if k in lower:
            out.append(lower[k])
            continue
        if k in aliases and aliases[k] in known:
            out.append(aliases[k])
            continue
        match = difflib.get_close_matches(k, list(lower), n=1, cutoff=0.8)
        if match:
            out.append(lower[match[0]])
            notes.append(note("fuzzy_entity", given=v, used=lower[match[0]]))
            continue
        raise ToolInputError(f"'{v}' is not a {column} in this dataset. Known values: {', '.join(known[:12])}.",
                             missing_fields=[v], code="unknown_entity",
                             hi=f"'{v}' इस डेटा में नहीं है। उपलब्ध मान: {', '.join(known[:12])}।")
    return list(dict.fromkeys(out))


def parse_period_text(text: str) -> tuple[str, str] | None:
    """Parse '2026-09', '2026-9', 'September 2026', 'Sep 2026' or '2026' into a (start, end) month range."""
    t = text.strip().lower()
    m = re.fullmatch(r"(\d{4})-(\d{1,2})(?:-\d{1,2})?", t)
    if m and 1 <= int(m.group(2)) <= 12:
        p = f"{m.group(1)}-{int(m.group(2)):02d}"
        return p, p
    m = re.fullmatch(r"([a-z]+)\.?,?\s+(\d{4})", t) or re.fullmatch(r"(\d{4})\s+([a-z]+)", t)
    if m:
        a, b = m.groups()
        name, year = (a, b) if a.isalpha() else (b, a)
        if name in MONTH_LOOKUP:
            p = f"{year}-{MONTH_LOOKUP[name]:02d}"
            return p, p
    m = re.fullmatch(r"(\d{4})", t)
    if m:
        return f"{t}-01", f"{t}-12"
    return None


def resolve_period(profile: Profile, args: PeriodArgs, notes: list[dict]) -> tuple[str | None, str | None]:
    periods = profile.periods
    wants_period = args.latest_period or args.period_start or args.period_end
    if not periods:
        if wants_period:
            raise ToolInputError("This dataset has no dates, so it cannot be filtered by month.", code="no_time")
        return None, None
    first, last = periods[0], periods[-1]
    if args.latest_period:
        notes.append(note("latest_period", period=last))
        return last, last
    start = end = None
    if args.period_start:
        r = parse_period_text(args.period_start)
        if not r:
            raise ToolInputError(f"Could not read the month '{args.period_start}'. Use YYYY-MM.", code="bad_period")
        start = r[0]
        # A whole year given alone means that year; a single month given alone means "from that month on".
        end = r[1] if (not args.period_end and r[0] != r[1]) else None
    if args.period_end:
        r = parse_period_text(args.period_end)
        if not r:
            raise ToolInputError(f"Could not read the month '{args.period_end}'. Use YYYY-MM.", code="bad_period")
        end = r[1]
    start, end = start or first, end or last
    if start > end:
        start, end = end, start
    if end < first or start > last:
        raise ToolInputError(f"There is no data for {start} to {end}. The data covers {first} to {last}.",
                             code="period_out_of_range",
                             hi=f"{start} से {end} का कोई डेटा नहीं है। डेटा {first} से {last} तक है।")
    if start < first or end > last:
        notes.append(note("period_clamped", requested_start=start, requested_end=end, first=first, last=last))
        start, end = max(start, first), min(end, last)
    return start, end


def _period_where(start: str | None, end: str | None) -> tuple[list[str], list[Any]]:
    if start is None:
        return ["TRUE"], []
    return [f"{PERIOD_COL} BETWEEN ? AND ?"], [start, end]


def _num(v: Any) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def _close(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-6)


# --------------------------------------------------------------------------- results


@dataclass
class ToolResult:
    tool: str
    args: dict[str, Any]
    sql: str = ""
    params: list[Any] = field(default_factory=list)
    table: list[dict[str, Any]] = field(default_factory=list)
    headline: dict[str, Any] = field(default_factory=dict)
    rows_used: int = 0
    rows_skipped: int = 0
    evidence_rows: list[dict[str, Any]] = field(default_factory=list)
    evidence_total: int = 0
    period_start: str | None = None
    period_end: str | None = None
    entity_column: str | None = None
    metric: str | None = None
    denominator: str | None = None
    entities: list[str] = field(default_factory=list)
    cross_check: dict[str, Any] = field(default_factory=dict)
    notes: list[dict[str, Any]] = field(default_factory=list)
    method: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


def _agg_sql(agg: str, col: str) -> str:
    return {"sum": "SUM", "avg": "AVG", "max": "MAX", "min": "MIN", "count": "COUNT"}[agg] + f"({q(col)})"


def _pandas_filter(ds: Dataset, start: str | None, end: str | None, col: str | None = None,
                   values: list[str] | None = None) -> pd.DataFrame:
    df = ds.df
    mask = pd.Series(True, index=df.index)
    if start is not None:
        mask &= df[PERIOD_COL].between(start, end)
    if col and values:
        mask &= df[col].astype("string").isin(values)
    return df[mask.fillna(False)]


def _pandas_agg(series: pd.Series, agg: str) -> float | None:
    s = series.dropna().astype("float64")
    if agg == "count":
        return float(len(s))
    if s.empty:
        return None
    return float({"sum": s.sum, "avg": s.mean, "max": s.max, "min": s.min}[agg]())


def _evidence(ds: Dataset, where: list[str], params: list[Any], cols: list[str], order: list[str]) -> tuple[list[dict], int]:
    p = ds.profile
    keep = [c for c in p.columns if p.columns[c].role in ("id", "time", "source")]
    show = list(dict.fromkeys([c for c in keep if p.columns[c].role == "id"] + [c for c in keep if p.columns[c].role == "time"]
                              + cols + [c for c in keep if p.columns[c].role == "source"]))
    sql = f"SELECT {', '.join(q(c) for c in show)} FROM data WHERE {' AND '.join(where)}"
    if order:
        sql += " ORDER BY " + ", ".join(order)
    total = int(ds.query(f"SELECT COUNT(*) AS n FROM data WHERE {' AND '.join(where)}", params)["n"].iloc[0])
    rows = ds.query(sql + f" LIMIT {EVIDENCE_LIMIT}", params)
    return _records(rows), total


def _display_sql(sql: str, params: list[Any]) -> str:
    """Readable SQL with parameters shown inline (display only, never executed)."""
    out = sql
    for p in params:
        lit = str(p) if isinstance(p, (int, float)) else "'" + str(p).replace("'", "''") + "'"
        out = out.replace("?", lit, 1)
    return out


def _check_metric(ds: Dataset, metric: str, agg: str, notes: list[dict]) -> str:
    info = ds.profile.columns[metric]
    if agg == "sum" and not info.additive:
        notes.append(note("non_additive", column=metric))
        return "avg"
    return agg


# --------------------------------------------------------------------------- tools


def rank_entities(ds: Dataset, a: RankArgs) -> ToolResult:
    p, notes = ds.profile, []
    metric = resolve_column(p, a.metric, numeric=True, what="metric")
    g = resolve_entity_column(p, a.group_by)
    agg = _check_metric(ds, metric, a.agg, notes)
    start, end = resolve_period(p, a, notes)
    where, params = _period_where(start, end)
    order = "DESC" if a.order == "desc" else "ASC"
    sql = (f"SELECT {q(g)} AS entity, {_agg_sql(agg, metric)} AS value, COUNT({q(metric)}) AS rows_used "
           f"FROM data WHERE {' AND '.join(where)} GROUP BY {q(g)} HAVING COUNT({q(metric)}) > 0 "
           f"ORDER BY value {order}, entity ASC LIMIT ?")
    run_params = params + [a.limit]
    table = _records(ds.query(sql, run_params))
    if not table:
        raise ToolInputError("No readings were found for that period.", code="no_rows",
                             hi="उस अवधि के लिए कोई रीडिंग नहीं मिली।")
    totals = ds.query(f"SELECT COUNT({q(metric)}) AS used, COUNT(*) - COUNT({q(metric)}) AS skipped FROM data "
                      f"WHERE {' AND '.join(where)}", params).iloc[0]

    sub = _pandas_filter(ds, start, end)
    pdv = {str(k): _pandas_agg(v, agg) for k, v in sub.groupby(g)[metric] if v.notna().any()}
    match = all(_close(row["value"], pdv.get(str(row["entity"]))) for row in table)
    ev, ev_total = _evidence(ds, where, params, [g, metric], [q(g), PERIOD_COL])
    return ToolResult(
        tool="rank_entities", args={"metric": metric, "group_by": g, "agg": agg, "order": a.order, "limit": a.limit,
                                    "period_start": start, "period_end": end},
        sql=_display_sql(sql, run_params), params=run_params, table=table,
        headline={"top": table[0], "second": table[1] if len(table) > 1 else None, "count": len(table), "agg": agg,
                  "order": a.order, "last": table[-1]},
        rows_used=int(totals["used"]), rows_skipped=int(totals["skipped"]), evidence_rows=ev, evidence_total=ev_total,
        period_start=start, period_end=end, entity_column=g, metric=metric, entities=[str(r["entity"]) for r in table],
        cross_check={"engine": "pandas", "match": match, "compared": len(table)}, notes=notes,
        method=f"{agg.upper()}({metric}) grouped by {g}, sorted {a.order}",
    )


def trend_over_time(ds: Dataset, a: TrendArgs) -> ToolResult:
    p, notes = ds.profile, []
    if not p.periods:
        raise ToolInputError("This dataset has no dates, so trends cannot be calculated.", code="no_time")
    metric = resolve_column(p, a.metric, numeric=True, what="metric")
    g = resolve_entity_column(p, a.entity_column) if (a.entity or a.entity_column) else p.primary_entity
    entity = resolve_entities(p, g, [a.entity], notes)[0] if a.entity else None
    agg = _check_metric(ds, metric, a.agg, notes)
    start, end = resolve_period(p, a, notes)
    where, params = _period_where(start, end)
    if entity is not None:
        where.append(f"CAST({q(g)} AS VARCHAR) = ?")
        params.append(entity)
    sql = (f"SELECT {PERIOD_COL} AS period, {_agg_sql(agg, metric)} AS value, COUNT({q(metric)}) AS rows_used, "
           f"COUNT(*) - COUNT({q(metric)}) AS rows_skipped FROM data WHERE {' AND '.join(where)} "
           f"GROUP BY {PERIOD_COL} ORDER BY {PERIOD_COL}")
    table = _records(ds.query(sql, params))
    points = [r for r in table if r["value"] is not None]
    if len(points) < 2:
        raise ToolInputError("At least two months with data are needed to describe a trend.", code="too_few_points",
                             hi="रुझान बताने के लिए कम से कम दो महीनों का डेटा चाहिए।")
    first, last = points[0], points[-1]
    change = last["value"] - first["value"]
    pct = (change / first["value"] * 100) if first["value"] else None
    peak = max(points, key=lambda r: r["value"])
    low = min(points, key=lambda r: r["value"])

    sub = _pandas_filter(ds, start, end, g if entity else None, [entity] if entity else None)
    pdv = {str(k): _pandas_agg(v, agg) for k, v in sub.groupby(PERIOD_COL)[metric]}
    match = all(_close(r["value"], pdv.get(str(r["period"]))) for r in table)
    ev, ev_total = _evidence(ds, where, params, [g, metric] if g else [metric], [PERIOD_COL])
    return ToolResult(
        tool="trend_over_time", args={"metric": metric, "entity": entity, "entity_column": g, "agg": agg,
                                      "period_start": start, "period_end": end},
        sql=_display_sql(sql, params), params=params, table=table,
        headline={"first": first, "last": last, "change": change, "pct": pct, "peak": peak, "low": low, "agg": agg,
                  "entity": entity, "points": len(points)},
        rows_used=sum(int(r["rows_used"]) for r in table), rows_skipped=sum(int(r["rows_skipped"]) for r in table),
        evidence_rows=ev, evidence_total=ev_total, period_start=start, period_end=end, entity_column=g, metric=metric,
        entities=[entity] if entity else list(p.entities.get(g, [])) if g else [],
        cross_check={"engine": "pandas", "match": match, "compared": len(table)}, notes=notes,
        method=f"{agg.upper()}({metric}) per month" + (f" for {g} = {entity}" if entity else " for all entities combined"),
    )


def compare_entities(ds: Dataset, a: CompareArgs) -> ToolResult:
    p, notes = ds.profile, []
    metric = resolve_column(p, a.metric, numeric=True, what="metric")
    g = resolve_entity_column(p, a.group_by)
    entities = resolve_entities(p, g, a.entities, notes)
    if len(entities) < 2:
        raise ToolInputError("Name at least two different entities to compare.", code="too_few_entities")
    agg = _check_metric(ds, metric, a.agg, notes)
    start, end = resolve_period(p, a, notes)
    where, params = _period_where(start, end)
    where.append(f"CAST({q(g)} AS VARCHAR) IN ({', '.join('?' for _ in entities)})")
    params += entities
    sql = (f"SELECT {q(g)} AS entity, {_agg_sql(agg, metric)} AS value, COUNT({q(metric)}) AS rows_used "
           f"FROM data WHERE {' AND '.join(where)} GROUP BY {q(g)} ORDER BY value DESC NULLS LAST, entity ASC")
    table = _records(ds.query(sql, params))
    valued = [r for r in table if r["value"] is not None]
    if len(valued) < 2:
        raise ToolInputError("Not enough readings for those entities in that period.", code="no_rows")
    hi, lo = valued[0], valued[-1]
    diff = hi["value"] - lo["value"]
    totals = ds.query(f"SELECT COUNT({q(metric)}) AS used, COUNT(*) - COUNT({q(metric)}) AS skipped FROM data "
                      f"WHERE {' AND '.join(where)}", params).iloc[0]
    sub = _pandas_filter(ds, start, end, g, entities)
    pdv = {str(k): _pandas_agg(v, agg) for k, v in sub.groupby(g)[metric]}
    match = all(_close(r["value"], pdv.get(str(r["entity"]))) for r in table)
    ev, ev_total = _evidence(ds, where, params, [g, metric], [q(g), PERIOD_COL])
    return ToolResult(
        tool="compare_entities", args={"metric": metric, "entities": entities, "group_by": g, "agg": agg,
                                       "period_start": start, "period_end": end},
        sql=_display_sql(sql, params), params=params, table=table,
        headline={"high": hi, "low": lo, "diff": diff, "pct": (diff / lo["value"] * 100) if lo["value"] else None,
                  "agg": agg, "missing": [e for e in entities if e not in {str(r["entity"]) for r in valued}]},
        rows_used=int(totals["used"]), rows_skipped=int(totals["skipped"]), evidence_rows=ev, evidence_total=ev_total,
        period_start=start, period_end=end, entity_column=g, metric=metric, entities=entities,
        cross_check={"engine": "pandas", "match": match, "compared": len(table)}, notes=notes,
        method=f"{agg.upper()}({metric}) for {', '.join(entities)}",
    )


def aggregate_total(ds: Dataset, a: AggregateArgs) -> ToolResult:
    p, notes = ds.profile, []
    metric = resolve_column(p, a.metric, numeric=True, what="metric")
    agg = _check_metric(ds, metric, a.agg, notes)
    start, end = resolve_period(p, a, notes)
    where, params = _period_where(start, end)
    g, entities = None, []
    if a.entities:
        g = resolve_entity_column(p, a.entity_column)
        entities = resolve_entities(p, g, a.entities, notes)
        where.append(f"CAST({q(g)} AS VARCHAR) IN ({', '.join('?' for _ in entities)})")
        params += entities
    w = " AND ".join(where)
    sql = (f"SELECT {_agg_sql(agg, metric)} AS value, COUNT({q(metric)}) AS rows_used, "
           f"COUNT(*) - COUNT({q(metric)}) AS rows_skipped FROM data WHERE {w}")
    row = _records(ds.query(sql, params))[0]
    if row["value"] is None or not row["rows_used"]:
        raise ToolInputError("No readings were found for that selection.", code="no_rows",
                             hi="उस चयन के लिए कोई रीडिंग नहीं मिली।")
    breakdown = []
    if p.periods:
        breakdown = _records(ds.query(f"SELECT {PERIOD_COL} AS period, {_agg_sql(agg, metric)} AS value FROM data "
                                      f"WHERE {w} GROUP BY {PERIOD_COL} ORDER BY {PERIOD_COL}", params))
    sub = _pandas_filter(ds, start, end, g, entities or None)
    match = _close(row["value"], _pandas_agg(sub[metric], agg))
    ev, ev_total = _evidence(ds, where, params, ([g] if g else ([p.primary_entity] if p.primary_entity else [])) + [metric],
                             [PERIOD_COL])
    return ToolResult(
        tool="aggregate_total", args={"metric": metric, "agg": agg, "entities": entities, "entity_column": g,
                                      "period_start": start, "period_end": end},
        sql=_display_sql(sql, params), params=params, table=breakdown or [row],
        headline={"value": row["value"], "agg": agg, "entities": entities},
        rows_used=int(row["rows_used"]), rows_skipped=int(row["rows_skipped"]), evidence_rows=ev, evidence_total=ev_total,
        period_start=start, period_end=end, entity_column=g or p.primary_entity, metric=metric,
        entities=entities or (list(p.entities.get(p.primary_entity, [])) if p.primary_entity else []),
        cross_check={"engine": "pandas", "match": match, "compared": 1}, notes=notes,
        method=f"{agg.upper()}({metric})" + (f" for {', '.join(entities)}" if entities else " across all rows"),
    )


def normalize_by(ds: Dataset, a: NormalizeArgs) -> ToolResult:
    p, notes = ds.profile, []
    metric = resolve_column(p, a.metric, numeric=True, what="metric")
    denom = resolve_column(p, a.denominator, numeric=True, what="denominator")
    if metric == denom:
        raise ToolInputError("The metric and the denominator must be different columns.", code="same_columns")
    if not p.columns[metric].additive:
        raise ToolInputError(f"{p.label(metric)} is an average or concentration, so it cannot be divided per "
                             f"{p.label(denom)}.", code="non_additive_ratio")
    g = resolve_entity_column(p, a.group_by)
    start, end = resolve_period(p, a, notes)
    where, params = _period_where(start, end)
    mu, du = p.columns[metric].unit, p.columns[denom].unit
    as_percent = bool(mu) and mu == du
    scale = "100.0 * " if as_percent else ""
    order = "DESC" if a.order == "desc" else "ASC"
    w = " AND ".join(where)
    sql = (f"SELECT {q(g)} AS entity, SUM({q(metric)}) AS metric_total, SUM({q(denom)}) AS denominator_total, "
           f"{scale}SUM({q(metric)}) / NULLIF(SUM({q(denom)}), 0) AS value, COUNT(*) AS rows_used FROM data "
           f"WHERE {w} AND {q(metric)} IS NOT NULL AND {q(denom)} IS NOT NULL GROUP BY {q(g)} "
           f"HAVING SUM({q(denom)}) > 0 ORDER BY value {order}, entity ASC LIMIT ?")
    run_params = params + [a.limit]
    table = _records(ds.query(sql, run_params))
    if not table:
        raise ToolInputError("No rows have both values needed for this ratio.", code="no_rows")
    totals = ds.query(f"SELECT COUNT(*) FILTER (WHERE {q(metric)} IS NOT NULL AND {q(denom)} IS NOT NULL) AS used, "
                      f"COUNT(*) FILTER (WHERE {q(metric)} IS NULL OR {q(denom)} IS NULL) AS skipped FROM data WHERE {w}",
                      params).iloc[0]
    sub = _pandas_filter(ds, start, end).dropna(subset=[metric, denom])
    grouped = sub.groupby(g)[[metric, denom]].sum()
    pdv = {str(k): (100.0 if as_percent else 1.0) * float(r[metric]) / float(r[denom]) for k, r in grouped.iterrows() if r[denom]}
    match = all(_close(r["value"], pdv.get(str(r["entity"]))) for r in table)
    ev, ev_total = _evidence(ds, where, params, [g, metric, denom], [q(g), PERIOD_COL])
    multi = start != end if start else True
    return ToolResult(
        tool="normalize_by", args={"metric": metric, "denominator": denom, "group_by": g, "order": a.order,
                                   "limit": a.limit, "period_start": start, "period_end": end},
        sql=_display_sql(sql, run_params), params=run_params, table=table,
        headline={"top": table[0], "last": table[-1], "order": a.order, "as_percent": as_percent, "multi_period": multi},
        rows_used=int(totals["used"]), rows_skipped=int(totals["skipped"]), evidence_rows=ev, evidence_total=ev_total,
        period_start=start, period_end=end, entity_column=g, metric=metric, denominator=denom,
        entities=[str(r["entity"]) for r in table],
        cross_check={"engine": "pandas", "match": match, "compared": len(table)}, notes=notes,
        method=(f"100 x SUM({metric}) / SUM({denom})" if as_percent else f"SUM({metric}) / SUM({denom})") + f" per {g}",
    )


TOOLS = {
    "rank_entities": rank_entities,
    "trend_over_time": trend_over_time,
    "compare_entities": compare_entities,
    "aggregate_total": aggregate_total,
    "normalize_by": normalize_by,
}


def run_tool(ds: Dataset, tool: str, args: dict[str, Any]) -> ToolResult:
    """Validate arguments and run one analysis tool. Raises ToolInputError when it cannot be answered."""
    parsed = validate_args(tool, args)
    if tool == "cannot_answer":
        raise ToolInputError(parsed.reason, missing_fields=list(parsed.missing_fields), code="model_refused",
                             hi=REASONS_HI.get(parsed.reason, parsed.reason))
    return TOOLS[tool](ds, parsed)
