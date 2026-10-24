"""Answer text built from tool results, plus a numeric guard for optional model narration.

Every number in an answer comes from a ToolResult. If the model is asked to reword an answer,
its text is accepted only when each number it contains matches one in the verified answer.
"""

from __future__ import annotations

import re
from typing import Any

from ..data.profiler import Profile
from ..tools.registry import ToolResult
from .text import fmt, join_list, month, period_text, unit_suffix


def _per_label(p: Profile, col: str, lang: str) -> str:
    info = p.columns[col]
    if lang == "hi":
        return info.per_label_hi or info.label_hi or info.label
    return info.per_label or info.label


def compose(r: ToolResult, p: Profile, lang: str = "en") -> str:
    hi = lang == "hi"
    m = r.metric
    label = p.label(m, lang)
    u = unit_suffix(p.columns[m].unit)
    when = period_text(r.period_start, r.period_end, lang)
    h = r.headline

    if r.tool == "rank_entities":
        top, second = h["top"], h.get("second")
        avg = h["agg"] == "avg"
        if hi:
            word = "सबसे अधिक" if h["order"] == "desc" else "सबसे कम"
            text = f"{when} में {word} {'औसत ' if avg else ''}{label}: {top['entity']}, {fmt(top['value'])}{u}।"
            if second:
                text += f" दूसरे स्थान पर: {second['entity']}, {fmt(second['value'])}{u}।"
        else:
            word = "highest" if h["order"] == "desc" else "lowest"
            text = f"{top['entity']} had the {word} {'average ' if avg else ''}{label} in {when}: {fmt(top['value'])}{u}."
            if second:
                text += f" Next was {second['entity']} with {fmt(second['value'])}{u}."
        return text

    if r.tool == "trend_over_time":
        first, last, peak = h["first"], h["last"], h["peak"]
        ent = h.get("entity")
        pct = h.get("pct")
        up = h["change"] > 0
        if hi:
            subject = f"{ent}, {label}" if ent else (f"कुल {label}" if h["agg"] == "sum" else f"औसत {label}")
            text = (f"{subject}: {month(first['period'], 'hi')} में {fmt(first['value'])}{u}, "
                    f"{month(last['period'], 'hi')} में {fmt(last['value'])}{u}।")
            if h["change"] == 0:
                text += " कुल मिलाकर कोई बदलाव नहीं।"
            else:
                pct_txt = f"{fmt(abs(pct))}% की " if pct is not None else ""
                text += f" कुल बदलाव: {pct_txt}{'वृद्धि' if up else 'कमी'} ({fmt(abs(h['change']))}{u})।"
            text += f" सबसे अधिक मान: {month(peak['period'], 'hi')}, {fmt(peak['value'])}{u}।"
        else:
            subject = f"{ent}'s {label}" if ent else (f"Total {label}" if h["agg"] == "sum" else f"Average {label}")
            text = (f"{subject} went from {fmt(first['value'])}{u} in {month(first['period'])} to "
                    f"{fmt(last['value'])}{u} in {month(last['period'])}")
            if h["change"] == 0:
                text += ", with no overall change."
            else:
                pct_txt = f" of {fmt(abs(pct))}%" if pct is not None else ""
                text += f", {'an increase' if up else 'a decrease'}{pct_txt} ({fmt(abs(h['change']))}{u})."
            text += f" The highest month was {month(peak['period'])} at {fmt(peak['value'])}{u}."
        return text

    if r.tool == "compare_entities":
        hi_e, lo_e = h["high"], h["low"]
        avg = h["agg"] == "avg"
        rows = [x for x in r.table if x["value"] is not None]
        if len(rows) == 2:
            pct = f" ({fmt(h['pct'])}%)" if h.get("pct") is not None else ""
            if hi:
                return (f"{when} में {'औसत ' if avg else ''}{label}: {hi_e['entity']} {fmt(hi_e['value'])}{u}, "
                        f"{lo_e['entity']} {fmt(lo_e['value'])}{u}। {hi_e['entity']} का आंकड़ा {fmt(h['diff'])}{u}{pct} अधिक है।")
            return (f"In {when}, {hi_e['entity']} had {fmt(hi_e['value'])}{u} of {'average ' if avg else ''}{label}, "
                    f"{fmt(h['diff'])}{u}{pct} more than {lo_e['entity']} ({fmt(lo_e['value'])}{u}).")
        parts = [f"{x['entity']} {fmt(x['value'])}{u}" for x in rows]
        if hi:
            return (f"{when} में {label}: {join_list(parts, 'hi')}। सबसे अधिक {hi_e['entity']} और सबसे कम {lo_e['entity']}।")
        return f"{label.capitalize()} in {when}: {join_list(parts)}. {hi_e['entity']} is highest and {lo_e['entity']} is lowest."

    if r.tool == "aggregate_total":
        v, agg = h["value"], h["agg"]
        ents = h.get("entities") or []
        scope_en = f" for {join_list(ents)}" if ents else ""
        scope_hi = f" {join_list(ents, 'hi')} के लिए" if ents else ""
        if hi:
            word = {"sum": "कुल", "avg": "औसत मासिक", "max": "सबसे अधिक मासिक", "min": "सबसे कम मासिक", "count": "रीडिंग की संख्या,"}[agg]
            unit = "" if agg == "count" else u
            return f"{when} में{scope_hi} {word} {label}: {fmt(v)}{unit} ({r.rows_used} रीडिंग से)।"
        word = {"sum": "Total", "avg": "Average monthly", "max": "Highest monthly", "min": "Lowest monthly",
                "count": "Number of readings of"}[agg]
        unit = "" if agg == "count" else u
        return f"{word} {label}{scope_en} in {when}: {fmt(v)}{unit}, from {r.rows_used} readings."

    if r.tool == "normalize_by":
        d = r.denominator
        top, last = h["top"], h["last"]
        per = _per_label(p, d, lang)
        dlabel = p.label(d, lang)
        if h["as_percent"]:
            if hi:
                word = "सबसे अधिक" if h["order"] == "desc" else "सबसे कम"
                text = f"{when} में {dlabel} में {label} का हिस्सा {word}: {top['entity']}, {fmt(top['value'])}%।"
                if last["entity"] != top["entity"]:
                    text += f" दूसरी ओर: {last['entity']}, {fmt(last['value'])}%।"
                return text
            word = "highest" if h["order"] == "desc" else "lowest"
            text = f"{top['entity']} has the {word} {label} as a share of {dlabel} in {when}: {fmt(top['value'])}%."
            if last["entity"] != top["entity"]:
                text += f" At the other end is {last['entity']} with {fmt(last['value'])}%."
            return text
        monthly = " per month" if h.get("multi_period") else ""
        monthly_hi = " प्रति माह" if h.get("multi_period") else ""
        if hi:
            word = "सबसे अधिक" if h["order"] == "desc" else "सबसे कम"
            text = f"{when} में प्रति {per} {word} {label}: {top['entity']}, {fmt(top['value'])}{u} प्रति {per}{monthly_hi}।"
            if last["entity"] != top["entity"]:
                text += f" दूसरी ओर: {last['entity']}, {fmt(last['value'])}{u} प्रति {per}।"
            return text
        word = "highest" if h["order"] == "desc" else "lowest"
        text = (f"{top['entity']} has the {word} {label} per {per} in {when}: {fmt(top['value'])}{u} per {per}{monthly}.")
        if last["entity"] != top["entity"]:
            text += f" At the other end is {last['entity']} with {fmt(last['value'])}{u} per {per}."
        return text

    return ""


def refusal_text(message: str, lang: str = "en") -> str:
    if lang == "hi":
        return f"लोड किए गए डेटा से इसका उत्तर नहीं दिया जा सकता। {message}"
    return f"This cannot be answered from the loaded data. {message}"


# --------------------------------------------------------------------------- narration guard

_DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
_NUM = re.compile(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?")


def numbers_in(text: str) -> list[float]:
    out = []
    for m in _NUM.finditer(text.translate(_DEVANAGARI_DIGITS)):
        try:
            out.append(float(m.group(0).replace(",", "")))
        except ValueError:
            continue
    return out


def narration_prompt(verified: str, lang: str) -> str:
    language = "Hindi" if lang == "hi" else "English"
    return (f"Rewrite the verified answer below in simple, friendly {language} for a non-technical reader, in at most "
            "three short sentences. Keep every number exactly as written. Do not add any new number, estimate, cause, "
            "advice or opinion. Return only the rewritten answer.\n\nVerified answer: " + verified)


def guard_narration(narrated: str, verified: str, required_names: list[str]) -> tuple[bool, str]:
    """Accept model wording only if it introduces no new numbers and keeps the key facts."""
    text = (narrated or "").strip()
    if not text:
        return False, "empty response"
    if len(text) > 700:
        return False, "response too long"
    allowed = numbers_in(verified)
    for n in numbers_in(text):
        if not any(abs(n - a) <= max(0.5, abs(a) * 0.005) for a in allowed):
            return False, f"introduced a number not in the verified answer ({n:g})"
    key = numbers_in(verified)[:1]
    found = numbers_in(text)
    if key and not any(abs(key[0] - f) <= max(0.5, abs(key[0]) * 0.005) for f in found):
        return False, "dropped the main figure"
    for name in required_names:
        if name and name.lower() not in text.lower():
            return False, f"dropped '{name}'"
    return True, "ok"


def required_names(r: ToolResult) -> list[str]:
    h = r.headline
    if r.tool in ("rank_entities", "normalize_by"):
        return [str(h["top"]["entity"])]
    if r.tool == "compare_entities":
        return [str(h["high"]["entity"])]
    if r.tool == "trend_over_time" and h.get("entity"):
        return [str(h["entity"])]
    return []
