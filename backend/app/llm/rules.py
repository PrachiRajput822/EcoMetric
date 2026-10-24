"""Rule-based planner.

Used when no model is reachable, or when the model's tool call fails validation. It covers common
question shapes in English and Hindi. It is deliberately conservative: when a question does not
match the dataset it refuses instead of guessing.
"""

from __future__ import annotations

import re
from typing import Any

from ..data.profiler import Profile
from ..data.store import Dataset
from ..tools.registry import MONEY_FIELD, MONEY_REASON, MONTH_LOOKUP
from .base import PlannedCall

HI_MONTHS = {"जनवरी": 1, "फरवरी": 2, "फ़रवरी": 2, "मार्च": 3, "अप्रैल": 4, "मई": 5, "जून": 6, "जुलाई": 7,
             "अगस्त": 8, "सितंबर": 9, "सितम्बर": 9, "अक्टूबर": 10, "नवंबर": 11, "नवम्बर": 11, "दिसंबर": 12, "दिसम्बर": 12}

MONEY = ["cost", "costs", "price", "bill", "bills", "tariff", "rupee", "rupees", "rs", "inr", "expense", "expenses",
         "spend", "spent", "money", "₹", "लागत", "बिल", "खर्च", "रुपये", "रुपए", "कीमत", "पैसे"]
TREND = ["trend", "change", "changed", "changes", "changing", "over time", "since", "growth", "grew", "grown",
         "increase", "increased", "decrease", "decreased", "rise", "rose", "fall", "fell", "month by month",
         "बदल", "रुझान", "बढ़", "घट", "बढ़ा", "घटा"]
RANK_HIGH = ["most", "highest", "top", "largest", "biggest", "maximum", "max", "worst", "more", "सबसे ज्यादा",
             "सबसे ज़्यादा", "सबसे अधिक", "अधिकतम", "ज्यादा", "अधिक"]
RANK_LOW = ["least", "lowest", "smallest", "minimum", "min", "best", "fewest", "less", "सबसे कम", "न्यूनतम", "कम"]
EFFICIENT = ["efficient", "efficiency", "कुशल"]
RATIO = ["per", "प्रति", "utilisation", "utilization", "rate", "share", "percent", "percentage", "proportion",
         "ratio", "per capita", "उपयोग दर", "दर", "प्रतिशत"]
COMPARE = ["compare", "comparison", "vs", "versus", "difference between", "तुलना", "मुकाबला"]
TOTAL = ["total", "sum", "overall", "altogether", "how much", "how many", "combined", "कुल", "कितना", "कितनी", "कितने"]
AVERAGE = ["average", "mean", "avg", "typical", "औसत"]
WHICH = ["which", "who", "where", "कौन", "किस", "किसने", "किसकी", "किसका"]
LATEST = ["last month", "latest", "this month", "recent month", "most recent", "previous month", "पिछले महीने",
          "पिछला महीना", "इस महीने", "हाल के महीने"]


def _has(text: str, words: list[str]) -> bool:
    return any(_find(text, w) for w in words)


def _find(text: str, word: str) -> bool:
    w = word.lower()
    if not w:
        return False
    if re.search(r"[a-z0-9]", w):
        return re.search(rf"(?<![a-z0-9]){re.escape(w)}(?![a-z0-9])", text) is not None
    return w in text  # Devanagari and symbols: substring match


def _score_column(text: str, profile: Profile, col: str) -> int:
    info = profile.columns[col]
    terms = {col.lower(), col.lower().replace("_", " "), info.label.lower()} | {k.lower() for k in info.keywords}
    if info.label_hi:
        terms.add(info.label_hi)
    return sum(len(t) for t in terms if t and _find(text, t))


def _entities_in(text: str, profile: Profile) -> tuple[str | None, list[str]]:
    found: list[tuple[int, str, str]] = []
    for col in profile.entity_columns:
        values = profile.entities.get(col, [])
        two_word = {}
        for v in values:
            key = " ".join(v.lower().split()[:2])
            two_word[key] = two_word.get(key, 0) + 1
        for v in values:
            phrases = {v.lower(), *[a.lower() for a in profile.entity_aliases.get(v, [])]}
            key = " ".join(v.lower().split()[:2])
            if two_word.get(key) == 1 and len(key) > 3:
                phrases.add(key)
            for ph in phrases:
                pos = _pos(text, ph)
                if pos is not None:
                    found.append((pos, col, v))
                    break
    if not found:
        return None, []
    found.sort()
    col = found[0][1]
    return col, list(dict.fromkeys(v for _, c, v in found if c == col))


def _pos(text: str, phrase: str) -> int | None:
    if re.search(r"[a-z0-9]", phrase):
        m = re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", text)
    else:
        i = text.find(phrase)
        return i if i >= 0 else None
    return m.start() if m else None


def _months_in(text: str, default_year: str) -> list[tuple[int, str, bool]]:
    """Return (position, YYYY-MM, preceded_by_since) for each month mentioned."""
    out = []
    names = {**{k: v for k, v in MONTH_LOOKUP.items()}}
    for m in re.finditer(r"\b(\d{4})-(\d{1,2})\b", text):
        if 1 <= int(m.group(2)) <= 12:
            out.append((m.start(), f"{m.group(1)}-{int(m.group(2)):02d}", _since_before(text, m.start())))
    for name, num in names.items():
        for m in re.finditer(rf"(?<![a-z]){name}\.?(?![a-z])(?:,?\s*(\d{{4}}))?", text):
            if name == "may" and not (m.group(1) or re.search(r"(in|since|from|of|during)\s+$", text[:m.start()])):
                continue  # "may" is usually a verb
            year = m.group(1) or default_year
            out.append((m.start(), f"{year}-{num:02d}", _since_before(text, m.start())))
    for name, num in HI_MONTHS.items():
        for m in re.finditer(rf"{name}(?:\s*(\d{{4}}))?(\s*से)?", text):
            year = m.group(1) or default_year
            out.append((m.start(), f"{year}-{num:02d}", bool(m.group(2))))
    out.sort()
    dedup: dict[int, tuple[int, str, bool]] = {}
    for item in out:
        dedup.setdefault(item[0], item)
    return list(dedup.values())


def _since_before(text: str, pos: int) -> bool:
    return re.search(r"(since|from|starting|after)\s+(the\s+)?(start\s+of\s+)?$", text[:pos]) is not None


class RulePlanner:
    name = "rules"
    model = "rule-based parser"

    def available(self) -> bool:
        return True

    def plan(self, question: str, ds: Dataset) -> PlannedCall:
        p = ds.profile
        text = " " + re.sub(r"\s+", " ", question.lower().replace("?", " ").replace("!", " ")).strip() + " "
        numeric = [c for c, i in p.columns.items() if i.kind == "number" and i.role in ("metric", "denominator")]

        def call(tool: str, **args: Any) -> PlannedCall:
            clean = {k: v for k, v in args.items() if v not in (None, [], "")}
            return PlannedCall(tool=tool, args=clean, planner=self.name, model=self.model)

        # 1. Money questions need a money column.
        money_cols = [c for c, i in p.columns.items() if i.kind == "number" and (
            i.unit.lower() in ("₹", "rs", "inr", "rupees") or any(k in c.lower() for k in ("cost", "price", "amount", "bill", "tariff")))]
        if _has(text, MONEY) and not money_cols:
            return call("cannot_answer", reason=MONEY_REASON, missing_fields=[MONEY_FIELD])

        # 2. Metric and denominator.
        scores = {c: _score_column(text, p, c) for c in numeric}
        metric_scores = {c: s for c, s in scores.items() if s and p.columns[c].role == "metric"}
        metric = max(metric_scores, key=metric_scores.get) if metric_scores else None
        if metric is None:
            any_scores = {c: s for c, s in scores.items() if s}
            if any_scores and not _has(text, RATIO + EFFICIENT):
                metric = max(any_scores, key=any_scores.get)
        metric_named = metric is not None
        metric = metric or p.primary_metric
        if metric is None:
            return call("cannot_answer", reason="This dataset has no numeric column to analyse.")

        ent_col, entities = _entities_in(text, p)
        wants_ratio = _has(text, RATIO) or _has(text, EFFICIENT)
        denominator = None
        if wants_ratio:
            denoms = [c for c in numeric if c != metric and scores.get(c)]
            denoms.sort(key=lambda c: (p.columns[c].role != "denominator", -scores[c]))
            denominator = denoms[0] if denoms else None
            if denominator is None and _has(text, ["rate", "share", "percent", "percentage", "proportion", "प्रतिशत", "दर"]):
                same_unit = [c for c in numeric if c != metric and p.columns[c].unit and p.columns[c].unit == p.columns[metric].unit]
                same_unit.sort(key=lambda c: c != p.primary_metric)
                denominator = same_unit[0] if same_unit else None
            if denominator is None and _has(text, EFFICIENT):
                denoms = [c for c in numeric if p.columns[c].role == "denominator"]
                denominator = denoms[0] if denoms else None

        matched_anything = (metric_named or entities or denominator or _has(text, TREND + RANK_HIGH + RANK_LOW + TOTAL
                                                                             + AVERAGE + WHICH + COMPARE))
        if not matched_anything:
            return call("cannot_answer", reason=f"The question does not mention anything in the {p.title} dataset.")

        # 3. Period.
        year = p.periods[-1][:4] if p.periods else "2026"
        months = _months_in(text, year)
        period: dict[str, Any] = {}
        if _has(text, LATEST):
            period = {"latest_period": True}
        elif months:
            since = any(s for _, _, s in months)
            ms = sorted(m for _, m, _ in months)
            if since and len(ms) == 1:
                period = {"period_start": ms[0]}
            elif len(ms) >= 2:
                period = {"period_start": ms[0], "period_end": ms[-1]}
            else:
                period = {"period_start": ms[0], "period_end": ms[0]}
        else:
            ym = re.search(r"(?<!\d)(20\d{2})(?!\d)", text)
            if ym:
                period = {"period_start": ym.group(1)}

        agg = "avg" if _has(text, AVERAGE) else None
        low = _has(text, RANK_LOW) and not _has(text, ["सबसे ज्यादा", "सबसे अधिक"])
        top_n = re.search(r"\btop\s+(\d{1,2})\b", text)
        limit = int(top_n.group(1)) if top_n else None

        # 4. Intent.
        if _has(text, TREND) and not _has(text, COMPARE):
            return call("trend_over_time", metric=metric, entity=entities[0] if entities else None,
                        entity_column=ent_col if entities else None, agg=agg, **period)
        if denominator:
            if _has(text, EFFICIENT):
                order = "desc" if low else "asc"  # "least efficient" means the highest usage per unit
            else:
                order = "asc" if low else "desc"
            return call("normalize_by", metric=metric, denominator=denominator, group_by=ent_col, order=order,
                        limit=limit, **period)
        if len(entities) >= 2 or (_has(text, COMPARE) and entities):
            if len(entities) >= 2:
                return call("compare_entities", metric=metric, entities=entities, group_by=ent_col, agg=agg, **period)
        if _has(text, TOTAL + AVERAGE) and not _has(text, WHICH):
            return call("aggregate_total", metric=metric, agg=agg or "sum", entities=entities,
                        entity_column=ent_col if entities else None, **period)
        if _has(text, WHICH + RANK_HIGH + RANK_LOW):
            return call("rank_entities", metric=metric, order="asc" if low else "desc", agg=agg, limit=limit, **period)
        if entities:
            return call("aggregate_total", metric=metric, agg=agg or "sum", entities=entities, entity_column=ent_col, **period)
        return call("rank_entities", metric=metric, order="desc", agg=agg, limit=limit, **period)

    def narrate(self, prompt: str) -> str:  # pragma: no cover - rules never narrate
        raise NotImplementedError
