"""Caveat engine: rule-based checks that run on every answer.

Caveats are never written by the model. Each one comes from a concrete check against the
dataset's health report, the tool's arguments or the calculation itself.
"""

from __future__ import annotations

from typing import Any

from ..data.store import Dataset
from ..tools.registry import REASONS_HI, ToolInputError, ToolResult
from .text import fmt, join_list, month, period_text, unit_suffix

SEVERITY_ORDER = {"blocking": 0, "warning": 1, "info": 2}


def _c(severity: str, code: str, en: str, hi: str) -> dict[str, Any]:
    return {"severity": severity, "code": code, "en": en, "hi": hi}


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def _in_range(period: str, start: str | None, end: str | None) -> bool:
    return start is None or (start <= period <= end)


def note_caveats(notes: list[dict[str, Any]], ds: Dataset) -> list[dict[str, Any]]:
    """Turn interpretation notes (from tools and the pipeline) into readable caveats."""
    p = ds.profile
    out = []
    for n in notes:
        code, a = n["code"], n.get("params", {})
        if code == "latest_period":
            out.append(_c("info", code, f"\"Last month\" was read as {month(a['period'])}, the latest month in the data.",
                          f"\"पिछला महीना\" को {month(a['period'], 'hi')} माना गया, जो डेटा का सबसे नया महीना है।"))
        elif code == "period_clamped":
            out.append(_c("info", code,
                          f"You asked for {period_text(a['requested_start'], a['requested_end'])}, but the data only covers "
                          f"{period_text(a['first'], a['last'])}, so only those months were used.",
                          f"आपने {period_text(a['requested_start'], a['requested_end'], 'hi')} पूछा, पर डेटा केवल "
                          f"{period_text(a['first'], a['last'], 'hi')} तक है, इसलिए केवल वही महीने लिए गए।"))
        elif code == "fuzzy_entity":
            out.append(_c("info", code, f"\"{a['given']}\" was matched to \"{a['used']}\".",
                          f"\"{a['given']}\" को \"{a['used']}\" माना गया।"))
        elif code == "non_additive":
            label = p.label(a["column"])
            out.append(_c("info", code, f"{label} is an average or concentration, so it was averaged rather than added up.",
                          f"{p.label(a['column'], 'hi')} एक औसत या सांद्रता है, इसलिए इसे जोड़ने के बजाय इसका औसत लिया गया।"))
        elif code == "planner_fallback":
            out.append(_c("info", code, f"The AI model was not available ({a['reason']}), so the rule-based parser chose the calculation.",
                          f"AI मॉडल उपलब्ध नहीं था ({a['reason']}), इसलिए नियम-आधारित पार्सर ने गणना चुनी।"))
        elif code == "planner_corrected":
            out.append(_c("info", code, f"The AI model's first choice could not be run ({a['reason']}), so the rule-based "
                          "parser chose the calculation instead.",
                          f"AI मॉडल का पहला चुनाव चलाया नहीं जा सका ({a['reason']}), इसलिए नियम-आधारित पार्सर ने गणना चुनी।"))
        elif code == "guard_money":
            out.append(_c("info", code, "The question asks about money, so EcoMetric refused instead of answering with a different column.",
                          "प्रश्न पैसे के बारे में है, इसलिए किसी दूसरे कॉलम से उत्तर देने के बजाय EcoMetric ने मना कर दिया।"))
    return out


def source_caveat(ds: Dataset, result: ToolResult | None) -> dict[str, Any]:
    sources = set()
    if result is not None:
        sources = {str(r.get(c)) for r in result.evidence_rows for c, i in ds.profile.columns.items()
                   if i.role == "source" and r.get(c) is not None}
    sources = sources or set(ds.profile.sources_in_data)
    en_map = {"synthetic": "synthetic sample data, not official figures", "official": "official records",
              "user-entered": "a user upload that has not been independently verified"}
    hi_map = {"synthetic": "सिंथेटिक नमूना डेटा, आधिकारिक आंकड़े नहीं", "official": "आधिकारिक रिकॉर्ड",
              "user-entered": "उपयोगकर्ता द्वारा अपलोड किया गया डेटा, जिसकी स्वतंत्र जांच नहीं हुई है"}
    en = "; ".join(en_map.get(s, s) for s in sorted(sources))
    hi = "; ".join(hi_map.get(s, s) for s in sorted(sources))
    return _c("info", "source", f"Data source: {en}.", f"डेटा स्रोत: {hi}।")


def result_caveats(ds: Dataset, r: ToolResult) -> list[dict[str, Any]]:
    p, h = ds.profile, ds.health
    out: list[dict[str, Any]] = []
    metric, denom, g = r.metric, r.denominator, r.entity_column
    cols = {c for c in (metric, denom) if c}
    label, label_hi = p.label(metric), p.label(metric, "hi")
    unit = p.columns[metric].unit if metric else ""
    single = r.period_start is not None and r.period_start == r.period_end

    if not r.cross_check.get("match", False):
        out.append(_c("blocking", "cross_check_failed",
                      "The DuckDB and pandas calculations did not agree, so this answer is withheld.",
                      "DuckDB और pandas की गणनाएं मेल नहीं खाईं, इसलिए यह उत्तर रोका गया है।"))

    # Which entities does this answer depend on?
    if r.tool == "trend_over_time" and r.args.get("entity"):
        scope = {r.args["entity"]}
    elif r.tool in ("compare_entities",) or (r.tool == "aggregate_total" and r.args.get("entities")):
        scope = set(r.entities)
    else:
        scope = set(p.entities.get(g, [])) if g else set()

    # Missing readings (absent rows or blank values) inside the period and scope.
    gaps: dict[str, list[str]] = {}
    for m in h.get("missing_rows", []):
        if m["entity"] in scope and _in_range(m["period"], r.period_start, r.period_end):
            gaps.setdefault(m["entity"], []).append(m["period"])
    for m in h.get("missing_cells", []):
        if m["column"] in cols and m["entity"] in scope and _in_range(m["period"], r.period_start, r.period_end):
            gaps.setdefault(m["entity"], []).append(m["period"])
    for ent, periods in sorted(gaps.items()):
        periods = sorted(set(periods))
        pe, ph = join_list([month(x) for x in periods]), join_list([month(x, "hi") for x in periods], "hi")
        if r.tool == "trend_over_time" and r.args.get("entity"):
            en = f"{ent} has no {label} reading for {pe}, so the line has a gap there."
            hi = f"{ent} के लिए {ph} में {label_hi} का मान उपलब्ध नहीं है, इसलिए रेखा में वहां खाली जगह है।"
        elif r.tool == "trend_over_time":
            en = f"The {pe} figure leaves out {ent}, which has no reading, so that month is understated."
            hi = f"{ph} के आंकड़े में {ent} शामिल नहीं है क्योंकि उसकी रीडिंग नहीं है, इसलिए वह महीना कम दिखता है।"
        elif r.tool == "normalize_by":
            en = f"{ent} is missing {label} or {p.label(denom)} for {pe}; those rows were skipped in its ratio."
            hi = (f"{ent} के लिए {ph} में {label_hi} या {p.label(denom, 'hi')} का मान उपलब्ध नहीं है; "
                  "उसके अनुपात में वे पंक्तियां छोड़ी गईं।")
        elif single:
            en = f"{ent} has no {label} reading for {pe}, so it is not included in this answer."
            hi = f"{ent} के लिए {ph} में {label_hi} का मान उपलब्ध नहीं है, इसलिए यह इस उत्तर में शामिल नहीं है।"
        else:
            en = f"{ent} is missing {label} for {pe}, so its figure covers fewer months and is understated."
            hi = f"{ent} के लिए {ph} में {label_hi} का मान उपलब्ध नहीं है, इसलिए उसका आंकड़ा कम महीनों का है और कम दिखता है।"
        out.append(_c("warning", "missing_reading", en, hi))

    # Unusual readings that feed into this answer.
    for o in h.get("outliers", []):
        if o["column"] in cols and o["entity"] in scope and _in_range(o["period"], r.period_start, r.period_end):
            u = unit_suffix(p.columns[o["column"]].unit)
            higher = o["typical"] is not None and o["value"] is not None and o["value"] > o["typical"]
            col_label, col_label_hi = p.label(o["column"]), p.label(o["column"], "hi")
            out.append(_c("warning", "outlier",
                          f"{o['entity']}'s {col_label} in {month(o['period'])} ({fmt(o['value'])}{u}) is far "
                          f"{'above' if higher else 'below'} its usual level (about {fmt(o['typical'])}{u}). "
                          "Check the meter or source before relying on it.",
                          f"{month(o['period'], 'hi')} में {o['entity']} की रीडिंग ({col_label_hi}: {fmt(o['value'])}{u}) सामान्य "
                          f"स्तर (लगभग {fmt(o['typical'])}{u}) से बहुत {'अधिक' if higher else 'कम'} है। भरोसा करने से पहले मीटर या "
                          "स्रोत जांचें।"))

    if r.tool == "normalize_by" and r.rows_skipped:
        rows_en = "1 row was" if r.rows_skipped == 1 else f"{r.rows_skipped} rows were"
        out.append(_c("info", "rows_skipped", f"{rows_en} skipped because a value needed for the ratio was blank.",
                      ("1 पंक्ति छोड़ी गई" if r.rows_skipped == 1 else f"{r.rows_skipped} पंक्तियां छोड़ी गईं")
                      + " क्योंकि अनुपात के लिए ज़रूरी मान खाली था।"))

    if r.tool == "trend_over_time":
        if metric and p.columns[metric].seasonal:
            out.append(_c("info", "seasonal", f"{_cap(label)} is seasonal. Compare the same months across years before calling "
                          "this a lasting change.",
                          f"{label_hi} पर मौसम का असर पड़ता है। इसे स्थायी बदलाव मानने से पहले अलग-अलग वर्षों के समान महीनों की "
                          "तुलना करें।"))
        for pw in h.get("period_wide", []):
            if pw["column"] == metric and _in_range(pw["period"], r.period_start, r.period_end):
                out.append(_c("info", "period_wide", f"{_cap(label)} changed sharply in {month(pw['period'])} for most "
                              f"{p.label(g)} entries (likely a holiday or closure), which affects month-to-month comparison.",
                              f"{month(pw['period'], 'hi')} में अधिकांश {p.label(g, 'hi')} के लिए {label_hi} में तेज़ बदलाव हुआ "
                              "(शायद छुट्टी या बंदी), जिससे महीने-दर-महीने तुलना प्रभावित होती है।"))

    if r.rows_used and r.rows_used < 3 and r.tool not in ("rank_entities", "compare_entities"):
        out.append(_c("info", "few_rows", f"Only {r.rows_used} readings were used, so treat this as indicative.",
                      f"केवल {r.rows_used} रीडिंग का उपयोग हुआ, इसलिए इसे केवल संकेत मानें।"))
    return out


def refusal_caveat(ds: Dataset, err: ToolInputError) -> dict[str, Any]:
    p = ds.profile
    metrics = [p.label(c) for c, i in p.columns.items() if i.kind == "number" and i.role in ("metric", "denominator")]
    metrics_hi = [p.label(c, "hi") for c, i in p.columns.items() if i.kind == "number" and i.role in ("metric", "denominator")]
    need = f" Needed: {join_list(err.missing_fields)}." if err.missing_fields else ""
    need_hi = (f" ज़रूरी: {join_list([REASONS_HI.get(f, f) for f in err.missing_fields], 'hi')}।"
               if err.missing_fields else "")
    fix = " To answer it, add that data to the file." if err.missing_fields else ""
    fix_hi = " इसका उत्तर देने के लिए वह डेटा फ़ाइल में जोड़ें।" if err.missing_fields else ""
    return _c("blocking", "cannot_answer",
              f"{err}{need}{fix} This dataset can answer questions about {join_list(metrics)}.",
              f"{err.hi}{need_hi}{fix_hi} यह डेटासेट {join_list(metrics_hi, 'hi')} से जुड़े प्रश्नों का उत्तर दे सकता है।")


def finalize(caveats: list[dict[str, Any]], lang: str) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Sort, de-duplicate, localise, and derive the confidence label."""
    seen, out = set(), []
    for c in sorted(caveats, key=lambda c: SEVERITY_ORDER[c["severity"]]):
        key = (c["code"], c["en"])
        if key in seen:
            continue
        seen.add(key)
        out.append({"severity": c["severity"], "code": c["code"], "message": c["hi"] if lang == "hi" else c["en"]})
    severities = {c["severity"] for c in out}
    if "blocking" in severities:
        level, en, hi = "cannot_answer", "Could not answer", "उत्तर नहीं दिया जा सका"
    elif "warning" in severities:
        level, en, hi = "partial", "Partial data", "आंशिक डेटा"
    else:
        level, en, hi = "verified", "Verified", "सत्यापित"
    return out, {"level": level, "label": hi if lang == "hi" else en}
