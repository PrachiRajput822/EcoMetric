"""Dataset profiling and health checks.

The profile is the only description of the data the language model ever sees: column
names, roles, units, entity values and the period range. Raw rows are never sent.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
import pandas as pd

PERIOD_COL = "__period"
TIME_NAME_HINTS = ("month", "date", "period", "time", "day", "week")
DENOMINATOR_HINTS = ("occupan", "population", "household", "area", "capacity", "available", "students",
                     "residents", "trips", "seats", "headcount")
NON_ADDITIVE_HINTS = ("pm", "aqi", "temperature", "temp", "rate", "percent", "pct", "ratio", "avg", "mean",
                      "index", "concentration", "humidity", "ph", "no2", "so2", "co2_ppm")
MAX_ENTITY_VALUES = 200


@dataclass
class ColumnInfo:
    name: str
    kind: str  # number | text | time
    role: str  # time | entity | metric | denominator | id | source | other
    label: str
    label_hi: str = ""
    unit: str = ""
    per_label: str = ""
    per_label_hi: str = ""
    additive: bool = True
    seasonal: bool = False
    keywords: list[str] = field(default_factory=list)
    missing: int = 0
    distinct: int = 0
    min: Any = None
    max: Any = None


@dataclass
class Profile:
    title: str
    title_hi: str
    issue: str
    source: str
    description: str
    time_column: str | None
    entity_columns: list[str]
    primary_metric: str | None
    periods: list[str]
    columns: dict[str, ColumnInfo]
    entities: dict[str, list[str]]
    entity_aliases: dict[str, list[str]]
    examples: dict[str, list[str]]
    row_count: int
    sources_in_data: list[str]

    # Convenience accessors -------------------------------------------------
    @property
    def primary_entity(self) -> str | None:
        return self.entity_columns[0] if self.entity_columns else None

    def numeric_columns(self) -> list[str]:
        return [c.name for c in self.columns.values() if c.kind == "number" and c.role in ("metric", "denominator")]

    def label(self, column: str, lang: str = "en") -> str:
        info = self.columns.get(column)
        if not info:
            return column
        return (info.label_hi or info.label) if lang == "hi" else info.label

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["primary_entity"] = self.primary_entity
        return d


def _json_safe(v: Any) -> Any:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return float(v)
    if isinstance(v, (pd.Timestamp,)):
        return v.isoformat()
    return v


def parse_periods(series: pd.Series) -> pd.Series:
    """Convert a time column to YYYY-MM strings; unparseable values become NA."""
    text = series.astype("string").str.strip()
    # Fast path for values already in YYYY-MM form.
    ym = text.str.fullmatch(r"\d{4}-\d{1,2}")
    parsed = pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns]")
    if ym.fillna(False).any():
        parsed.loc[ym.fillna(False)] = pd.to_datetime(text[ym.fillna(False)] + "-01", errors="coerce", format="%Y-%m-%d")
    rest = ~ym.fillna(False)
    if rest.any():
        parsed.loc[rest] = pd.to_datetime(text[rest], errors="coerce", dayfirst=True, format="mixed")
    out = parsed.dt.strftime("%Y-%m")
    return out.astype("string")


def _is_time_like(name: str, series: pd.Series) -> bool:
    if pd.api.types.is_datetime64_any_dtype(series):
        return True
    lowered = name.lower()
    if not any(h in lowered for h in TIME_NAME_HINTS):
        return False
    sample = series.dropna().head(200)
    if sample.empty:
        return False
    return parse_periods(sample).notna().mean() >= 0.9


def _coerce_numeric_text(df: pd.DataFrame) -> pd.DataFrame:
    """Turn text columns that are almost entirely numbers (e.g. '1,200') into numbers."""
    for col in df.columns:
        s = df[col]
        if pd.api.types.is_numeric_dtype(s) or pd.api.types.is_datetime64_any_dtype(s):
            continue
        non_null = s.dropna()
        if non_null.empty:
            continue
        cleaned = non_null.astype("string").str.replace(",", "", regex=False).str.strip()
        nums = pd.to_numeric(cleaned, errors="coerce")
        if nums.notna().mean() >= 0.95 and not any(h in col.lower() for h in TIME_NAME_HINTS):
            df[col] = pd.to_numeric(s.astype("string").str.replace(",", "", regex=False).str.strip(), errors="coerce")
    return df


def _default_keywords(name: str, label: str) -> list[str]:
    words = set(re.split(r"[_\s]+", name.lower())) | set(re.split(r"\s+", label.lower()))
    return sorted(w for w in words if len(w) > 2)


def profile_dataframe(df: pd.DataFrame, meta: dict | None = None, default_source: str = "user-entered") -> tuple[pd.DataFrame, Profile]:
    """Return a copy of df with a derived period column, plus its Profile.

    `meta` is an optional data dictionary (as shipped with the sample datasets). Without it,
    roles and labels are inferred from column names and types.
    """
    meta = meta or {}
    df = _coerce_numeric_text(df.copy())
    col_meta: dict[str, dict] = meta.get("columns", {})

    # --- time column ---------------------------------------------------------
    time_col = meta.get("time_column")
    if time_col not in df.columns:
        time_col = next((c for c in df.columns if _is_time_like(c, df[c])), None)
    if time_col:
        df[PERIOD_COL] = parse_periods(df[time_col])
    else:
        df[PERIOD_COL] = pd.Series(pd.NA, index=df.index, dtype="string")
    periods = sorted(p for p in df[PERIOD_COL].dropna().unique().tolist())

    # --- roles ---------------------------------------------------------------
    n = len(df)
    columns: dict[str, ColumnInfo] = {}
    entity_cols: list[str] = list(meta.get("entity_columns", []))
    for col in df.columns:
        if col == PERIOD_COL:
            continue
        s = df[col]
        m = col_meta.get(col, {})
        is_num = pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s)
        kind = "time" if col == time_col else ("number" if is_num else "text")
        lowered = col.lower()
        role = m.get("role")
        if not role:
            if col == time_col:
                role = "time"
            elif lowered in ("data_source", "source"):
                role = "source"
            elif is_num:
                if lowered.endswith("_id") or lowered == "id":
                    role = "id"
                else:
                    role = "denominator" if any(h in lowered for h in DENOMINATOR_HINTS) else "metric"
            else:
                distinct = s.nunique(dropna=True)
                if lowered.endswith("id") or (distinct == n and n > 20):
                    role = "id"
                elif distinct <= MAX_ENTITY_VALUES:
                    role = "entity"
                else:
                    role = "other"
        if role == "entity" and col not in entity_cols:
            entity_cols.append(col)
        label = m.get("label") or col.replace("_", " ")
        additive = m.get("additive")
        if additive is None:
            additive = not any(re.search(rf"(^|_){h}", lowered) for h in NON_ADDITIVE_HINTS)
        info = ColumnInfo(
            name=col, kind=kind, role=role, label=label, label_hi=m.get("label_hi", ""), unit=m.get("unit", ""),
            per_label=m.get("per_label", ""), per_label_hi=m.get("per_label_hi", ""), additive=bool(additive),
            seasonal=bool(m.get("seasonal", False)), keywords=m.get("keywords") or _default_keywords(col, label),
            missing=int(s.isna().sum()), distinct=int(s.nunique(dropna=True)),
        )
        if kind == "number" and s.notna().any():
            info.min, info.max = _json_safe(s.min()), _json_safe(s.max())
        columns[col] = info

    entity_cols = [c for c in entity_cols if c in columns]
    entities = {c: sorted(str(v) for v in df[c].dropna().unique().tolist())[:MAX_ENTITY_VALUES] for c in entity_cols}
    metrics = [c for c, i in columns.items() if i.kind == "number" and i.role == "metric"]
    primary = meta.get("primary_metric") if meta.get("primary_metric") in columns else (metrics[0] if metrics else None)
    source_col = next((c for c, i in columns.items() if i.role == "source"), None)
    sources = sorted(str(v) for v in df[source_col].dropna().unique()) if source_col else [meta.get("source", default_source)]

    profile = Profile(
        title=meta.get("title", "Uploaded dataset"), title_hi=meta.get("title_hi", ""), issue=meta.get("issue", "custom"),
        source=meta.get("source", default_source), description=meta.get("description", ""), time_column=time_col,
        entity_columns=entity_cols, primary_metric=primary, periods=periods, columns=columns, entities=entities,
        entity_aliases=meta.get("entity_aliases", {}), examples=meta.get("examples", {}), row_count=n,
        sources_in_data=sources,
    )
    return df, profile


# --------------------------------------------------------------------------- health


def _robust_outliers(values: pd.Series, threshold: float = 3.5, min_rel_dev: float = 0.25) -> pd.Series:
    """Modified z-score (Iglewicz and Hoaglin) plus a minimum relative deviation from the median,
    so ordinary month-to-month noise in very stable series is not flagged."""
    clean = values.dropna()
    mask = pd.Series(False, index=values.index)
    if len(clean) < 5:
        return mask
    median = clean.median()
    mad = (clean - median).abs().median()
    if mad == 0:
        return mask
    z = 0.6745 * (values - median) / mad
    rel = (values - median).abs() / abs(median) if median else pd.Series(float("inf"), index=values.index)
    return (z.abs() > threshold) & (rel >= min_rel_dev)


def _count(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _examples(items: list[dict[str, Any]], limit: int = 3) -> str:
    parts = [" ".join(str(i[k]) for k in ("entity", "period", "column") if i.get(k)) for i in items[:limit]]
    more = f" and {len(items) - limit} more" if len(items) > limit else ""
    return ", ".join(parts) + more


def health_check(df: pd.DataFrame, profile: Profile) -> dict[str, Any]:
    """Find data-quality problems before any question is answered."""
    issues: list[dict[str, Any]] = []
    entity = profile.primary_entity
    periods = profile.periods
    numeric = [c for c, i in profile.columns.items() if i.kind == "number" and i.role in ("metric", "denominator")]
    metrics = [c for c, i in profile.columns.items() if i.kind == "number" and i.role == "metric"]

    missing_rows: list[dict[str, str]] = []
    missing_cells: list[dict[str, str]] = []
    outliers: list[dict[str, Any]] = []
    period_wide: list[dict[str, Any]] = []

    if profile.time_column is None:
        issues.append({"severity": "warning", "code": "no_time_column",
                       "message": "No date or month column was recognised, so time-based questions are disabled."})
    else:
        unparsed = int(df[PERIOD_COL].isna().sum() - df[profile.time_column].isna().sum())
        if unparsed > 0:
            issues.append({"severity": "warning", "code": "unparsed_dates",
                           "message": f"{unparsed} rows have a {profile.time_column} value that could not be read as a date."})

    if entity and periods:
        present = set(map(tuple, df[[entity, PERIOD_COL]].dropna().astype(str).itertuples(index=False, name=None)))
        for e in profile.entities.get(entity, []):
            for p in periods:
                if (e, p) not in present:
                    missing_rows.append({"entity": e, "period": p})
        dup = df.dropna(subset=[entity, PERIOD_COL]).duplicated(subset=[entity, PERIOD_COL], keep=False)
        if dup.any() and profile.time_column:
            issues.append({"severity": "warning", "code": "duplicates",
                           "message": f"{int(dup.sum())} rows share the same {entity} and month, so totals may double count."})

    for col in numeric:
        null_rows = df[df[col].isna()]
        for _, r in null_rows.iterrows():
            missing_cells.append({"entity": str(r[entity]) if entity else "", "period": str(r[PERIOD_COL]) if pd.notna(r[PERIOD_COL]) else "",
                                  "column": col})
        neg = int((df[col] < 0).sum())
        if neg:
            issues.append({"severity": "warning", "code": "negative", "message": f"{neg} negative values in {col}."})

    if entity and periods:
        for col in metrics:
            flagged: list[dict[str, Any]] = []
            values = df[col].astype("float64")
            # Detrended view: each reading relative to the median of all entities in the same month.
            # This removes seasonality, so a spike in a low-season month is still caught.
            period_median = values.groupby(df[PERIOD_COL]).transform("median")
            detrended = values / period_median.where(period_median != 0)
            use_detrended = len(profile.entities.get(entity, [])) >= 3
            for e, g in df.groupby(entity, sort=True):
                g = g.sort_values(PERIOD_COL)
                mask = _robust_outliers(g[col].astype("float64"))
                if use_detrended:
                    mask = mask | _robust_outliers(detrended.loc[g.index], min_rel_dev=0.5)
                typical = float(g[col].median()) if g[col].notna().any() else None
                for idx in g.index[mask.reindex(g.index, fill_value=False)]:
                    flagged.append({"entity": str(e), "period": str(df.at[idx, PERIOD_COL]), "column": col,
                                    "value": _json_safe(df.at[idx, col]), "typical": typical})
            # A change that hits at least half the entities in the same month is a period-wide event
            # (for example a vacation), not a faulty reading.
            n_entities = max(1, len(profile.entities.get(entity, [])))
            by_period: dict[str, list[dict]] = {}
            for f in flagged:
                by_period.setdefault(f["period"], []).append(f)
            for p, items in by_period.items():
                if len(items) >= max(2, n_entities / 2):
                    period_wide.append({"period": p, "column": col, "entities": [i["entity"] for i in items]})
                else:
                    outliers.extend(items)

    if missing_rows:
        issues.append({"severity": "warning", "code": "missing_rows",
                       "message": _count(len(missing_rows), f"{entity}-month combination has", f"{entity}-month combinations have")
                       + " no row at all: " + _examples(missing_rows) + ".",
                       "details": missing_rows[:20]})
    if missing_cells:
        issues.append({"severity": "warning", "code": "missing_values",
                       "message": _count(len(missing_cells), "numeric reading is", "numeric readings are") + " blank: "
                       + _examples(missing_cells) + ".", "details": missing_cells[:20]})
    if outliers:
        issues.append({"severity": "warning", "code": "outliers",
                       "message": _count(len(outliers), "reading is", "readings are") + " far outside the usual range: "
                       + _examples(outliers) + ".", "details": outliers[:20]})
    for pw in period_wide:
        issues.append({"severity": "info", "code": "period_wide_change",
                       "message": f"{profile.label(pw['column']).capitalize()} changed sharply in {pw['period']} for "
                                  f"{len(pw['entities'])} of {len(profile.entities.get(entity, []))} {entity} entries "
                                  "(a period-wide event such as a holiday), so these are not treated as faulty readings."})
    issues.append({"severity": "info", "code": "source",
                   "message": "Data source: " + ", ".join(profile.sources_in_data) + "."})

    return {
        "summary": {"rows": profile.row_count, "columns": len(profile.columns), "periods": len(periods),
                    "first_period": periods[0] if periods else None, "last_period": periods[-1] if periods else None,
                    "entities": len(profile.entities.get(entity, [])) if entity else 0},
        "issues": issues,
        "missing_rows": missing_rows,
        "missing_cells": missing_cells,
        "outliers": outliers,
        "period_wide": period_wide,
    }
