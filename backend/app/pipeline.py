"""The ask pipeline: question -> one tool call -> deterministic calculation -> caveats -> answer."""

from __future__ import annotations

import re
import time
from typing import Any

from .charts import build_chart
from .config import Settings, get_settings
from .data.store import Dataset
from .llm.base import PlannedCall, PlannerError
from .llm.providers import GeminiPlanner, OllamaPlanner
from .llm.rules import MONEY, RulePlanner, _has
from .tools.registry import MONEY_FIELD, MONEY_REASON, ToolInputError, ToolResult, note, run_tool
from .verify import audit
from .verify.answer import compose, guard_narration, narration_prompt, refusal_text, required_names
from .verify.caveats import finalize, note_caveats, refusal_caveat, result_caveats, source_caveat

MODES = ("auto", "gemini", "ollama", "rules")
PLANNER_LABELS = {"gemini": "Gemma 4 via Gemini API", "ollama": "Gemma 4 offline via Ollama", "rules": "Rule-based parser"}


class Pipeline:
    def __init__(self, settings: Settings | None = None, gemini: Any = None, ollama: Any = None, rules: Any = None,
                 audit_enabled: bool = True):
        self.settings = settings or get_settings()
        self.planners = {
            "gemini": gemini or GeminiPlanner(self.settings),
            "ollama": ollama or OllamaPlanner(self.settings),
            "rules": rules or RulePlanner(),
        }
        self.audit_enabled = audit_enabled

    # ------------------------------------------------------------------ status
    def status(self) -> dict[str, Any]:
        avail = {k: bool(p.available()) for k, p in self.planners.items()}
        return {
            "default_mode": self.settings.provider if self.settings.provider in MODES else "auto",
            "resolved_auto": self._auto_name(avail),
            "planners": [{"id": k, "label": PLANNER_LABELS[k], "available": avail[k],
                          "model": getattr(self.planners[k], "model", "")} for k in ("gemini", "ollama", "rules")],
            "narration": self.settings.narrate,
        }

    def _auto_name(self, avail: dict[str, bool] | None = None) -> str:
        pref = self.settings.provider
        if pref in ("gemini", "ollama", "rules"):
            return pref
        avail = avail or {}
        for name in ("gemini", "ollama"):
            ok = avail[name] if name in avail else self.planners[name].available()
            if ok:
                return name
        return "rules"

    def _choose(self, mode: str, notes: list[dict]) -> Any:
        mode = mode if mode in MODES else "auto"
        if mode == "auto":
            return self.planners[self._auto_name()]
        planner = self.planners[mode]
        if mode != "rules" and not planner.available():
            notes.append(note("planner_fallback", reason=f"{PLANNER_LABELS[mode]} is not configured or not running"))
            return self.planners["rules"]
        return planner

    # ------------------------------------------------------------------ ask
    def ask(self, ds: Dataset, question: str, lang: str = "en", mode: str = "auto") -> dict[str, Any]:
        t0 = time.perf_counter()
        lang = "hi" if lang == "hi" else "en"
        question = re.sub(r"\s+", " ", question).strip()
        notes: list[dict] = []
        rules = self.planners["rules"]
        planner = self._choose(mode, notes)

        try:
            plan: PlannedCall = planner.plan(question, ds)
        except PlannerError as exc:
            notes.append(note("planner_fallback", reason=str(exc)))
            plan = rules.plan(question, ds)
        first_attempt = None

        # Guard: a money question must never be answered with a usage column.
        money_cols = [c for c, i in ds.profile.columns.items() if i.kind == "number" and (
            i.unit.lower() in ("₹", "rs", "inr", "rupees") or any(k in c.lower() for k in ("cost", "price", "amount", "bill", "tariff")))]
        if plan.tool != "cannot_answer" and _has(" " + question.lower() + " ", MONEY) and not money_cols:
            notes.append(note("guard_money"))
            first_attempt = plan.to_dict()
            plan = PlannedCall(tool="cannot_answer", planner=plan.planner, model=plan.model,
                               args={"reason": MONEY_REASON, "missing_fields": [MONEY_FIELD]})

        result: ToolResult | None = None
        refusal: ToolInputError | None = None
        try:
            result = run_tool(ds, plan.tool, plan.args)
        except ToolInputError as exc:
            if plan.planner != "rules" and exc.code != "model_refused":
                notes.append(note("planner_corrected", reason=str(exc)))
                first_attempt = plan.to_dict()
                plan = rules.plan(question, ds)
                try:
                    result = run_tool(ds, plan.tool, plan.args)
                except ToolInputError as exc2:
                    refusal = exc2
            else:
                refusal = exc

        caveats = note_caveats(notes, ds)
        response: dict[str, Any] = {
            "question": question, "lang": lang,
            "dataset": {"id": ds.id, "title": ds.profile.title, "name": ds.name},
            "plan": {**plan.to_dict(), "planner_label": PLANNER_LABELS.get(plan.planner, plan.planner),
                     "first_attempt": first_attempt},
        }

        if result is None:
            assert refusal is not None
            caveats.append(refusal_caveat(ds, refusal))
            caveats.append(source_caveat(ds, None))
            items, confidence = finalize(caveats, lang)
            text = refusal_text(refusal.hi if lang == "hi" else str(refusal), lang)
            response.update({
                "status": "cannot_answer",
                "answer": {"text": text, "verified_text": text, "narration": {"used": False, "reason": "refusal"},
                           "missing_fields": refusal.missing_fields},
                "calculation": None, "chart": None, "caveats": items, "confidence": confidence,
            })
        else:
            for n in result.notes:
                notes.append(n)
            caveats = note_caveats(notes, ds) + result_caveats(ds, result) + [source_caveat(ds, result)]
            items, confidence = finalize(caveats, lang)
            verified = compose(result, ds.profile, lang)
            text, narration = verified, {"used": False, "reason": "not requested"}
            if confidence["level"] != "cannot_answer" and plan.planner in ("gemini", "ollama") and self.settings.narrate:
                text, narration = self._narrate(plan.planner, verified, lang, result)
            if confidence["level"] == "cannot_answer":
                text = verified = refusal_text("दो स्वतंत्र गणनाएं मेल नहीं खाईं।" if lang == "hi"
                                               else "The two independent calculations did not agree.", lang)
            response.update({
                "status": "answered" if confidence["level"] != "cannot_answer" else "cannot_answer",
                "answer": {"text": text, "verified_text": verified, "narration": narration,
                           "headline": result.headline, "table": result.table,
                           "metric": result.metric, "metric_label": ds.profile.label(result.metric, lang),
                           "unit": ds.profile.columns[result.metric].unit if result.metric else ""},
                "calculation": {
                    "tool": result.tool, "args": result.args, "method": result.method, "sql": result.sql,
                    "params": result.params, "cross_check": result.cross_check,
                    "rows_used": result.rows_used, "rows_skipped": result.rows_skipped,
                    "period": {"start": result.period_start, "end": result.period_end},
                    "evidence": {"rows": result.evidence_rows, "total": result.evidence_total,
                                 "shown": len(result.evidence_rows)},
                },
                "chart": build_chart(ds, result, lang) if confidence["level"] != "cannot_answer" else None,
                "caveats": items, "confidence": confidence,
            })

        response["timings"] = {"total_ms": int((time.perf_counter() - t0) * 1000), "planner_ms": plan.latency_ms}
        if self.audit_enabled:
            self._audit(ds, response)
        return response

    def _narrate(self, name: str, verified: str, lang: str, result: ToolResult) -> tuple[str, dict[str, Any]]:
        try:
            out = self.planners[name].narrate(narration_prompt(verified, lang))
        except Exception as exc:  # narration is optional; never fail the answer because of it
            return verified, {"used": False, "reason": f"narration failed ({type(exc).__name__})"}
        ok, why = guard_narration(out, verified, required_names(result))
        if ok:
            return out, {"used": True, "reason": "numbers checked against the verified answer"}
        return verified, {"used": False, "reason": f"model wording rejected: {why}"}

    def _audit(self, ds: Dataset, r: dict[str, Any]) -> None:
        calc = r.get("calculation") or {}
        try:
            audit.append({
                "dataset": ds.name, "dataset_id": ds.id, "question": r["question"], "lang": r["lang"],
                "planner": r["plan"]["planner"], "model": r["plan"]["model"], "tool": r["plan"]["tool"],
                "args": calc.get("args", r["plan"]["args"]), "sql": calc.get("sql"),
                "rows_used": calc.get("rows_used"), "rows_skipped": calc.get("rows_skipped"),
                "cross_check": (calc.get("cross_check") or {}).get("match"),
                "confidence": r["confidence"]["level"], "caveats": [c["code"] for c in r["caveats"]],
                "answer": r["answer"]["text"][:500],
            })
        except OSError:
            pass
