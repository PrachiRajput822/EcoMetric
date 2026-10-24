"""Pipeline behaviour, including Gemma 4 providers with mocked transports (no network)."""

import json
from types import SimpleNamespace

import httpx

from app.config import get_settings
from app.llm.base import PlannedCall, PlannerError
from app.llm.providers import GeminiPlanner, OllamaPlanner
from app.pipeline import Pipeline
from app.verify.answer import guard_narration


class FakePlanner:
    """Stands in for a Gemma 4 planner."""

    name = "gemini"
    model = "gemma-4-26b-a4b-it"

    def __init__(self, tool=None, args=None, narration=None, fail=False):
        self.tool, self.args, self.narration, self.fail = tool, args or {}, narration, fail

    def available(self):
        return True

    def plan(self, question, ds):
        if self.fail:
            raise PlannerError("Gemini API request failed: ConnectError")
        return PlannedCall(self.tool, self.args, "gemini", self.model)

    def narrate(self, prompt):
        return self.narration or ""


def make(planner):
    return Pipeline(get_settings(), gemini=planner, audit_enabled=False)


def test_demo_answers_and_confidence(elec):
    p = Pipeline(get_settings(), audit_enabled=False)
    r = p.ask(elec, "Which building used the most electricity in September 2026?")
    assert r["status"] == "answered" and r["confidence"]["level"] == "verified"
    assert r["answer"]["text"].startswith("Hostel B had the highest electricity use in September 2026: 50,313 kWh")
    r = p.ask(elec, "How has Hostel B electricity changed since January?")
    assert r["confidence"]["level"] == "partial"
    assert any(c["code"] == "outlier" for c in r["caveats"])
    r = p.ask(elec, "What was the electricity cost last month?")
    assert r["status"] == "cannot_answer" and r["calculation"] is None


def test_gemma_tool_call_is_used(elec):
    r = make(FakePlanner("rank_entities", {"metric": "kwh", "latest_period": True})).ask(elec, "top building last month", mode="gemini")
    assert r["plan"]["planner"] == "gemini"
    assert r["calculation"]["period"] == {"start": "2026-09", "end": "2026-09"}
    assert any(c["code"] == "latest_period" for c in r["caveats"])


def test_invalid_model_call_falls_back_to_rules(elec):
    r = make(FakePlanner("rank_entities", {"metric": "electricity_cost"})).ask(
        elec, "Which building used the most electricity in September 2026?", mode="gemini")
    assert r["plan"]["planner"] == "rules"
    assert r["plan"]["first_attempt"]["args"] == {"metric": "electricity_cost"}
    assert r["status"] == "answered"


def test_money_guard_overrides_model_substitution(elec):
    r = make(FakePlanner("aggregate_total", {"metric": "kwh"})).ask(elec, "What was the electricity bill last month?", mode="gemini")
    assert r["status"] == "cannot_answer"
    assert any(c["code"] == "guard_money" for c in r["caveats"])


def test_network_failure_falls_back(elec):
    r = make(FakePlanner(fail=True)).ask(elec, "Which building used the most electricity in September 2026?", mode="gemini")
    assert r["plan"]["planner"] == "rules" and r["status"] == "answered"
    assert any(c["code"] == "planner_fallback" for c in r["caveats"])


def test_narration_accepted_only_with_verified_numbers(elec):
    good = FakePlanner("rank_entities", {"metric": "kwh", "period_start": "2026-09", "period_end": "2026-09"},
                       narration="In September 2026, Hostel B used the most electricity: 50,313 kWh. Engineering Block was next at 49,031 kWh.")
    r = make(good).ask(elec, "q", mode="gemini")
    assert r["answer"]["narration"]["used"] is True
    bad = FakePlanner(good.tool, good.args, narration="Hostel B used about 51,000 kWh in September 2026.")
    r = make(bad).ask(elec, "q", mode="gemini")
    assert r["answer"]["narration"]["used"] is False
    assert r["answer"]["text"] == r["answer"]["verified_text"]


def test_guard_rules():
    v = "Hostel B had the highest electricity use in September 2026: 50,313 kWh."
    assert guard_narration("सितंबर २०२६ में Hostel B: 50,313 kWh", v, ["Hostel B"])[0]
    assert not guard_narration("Hostel B: 50,313 kWh, roughly 20% above average.", v, ["Hostel B"])[0]
    assert not guard_narration("Library used 50,313 kWh in September 2026.", v, ["Hostel B"])[0]


def test_gemini_planner_parses_function_call(elec, monkeypatch):
    fc = SimpleNamespace(name="trend_over_time", args={"metric": "kwh", "entity": "Hostel B"})
    calls = {}

    class Models:
        def generate_content(self, model, contents, config):
            calls["model"], calls["config"] = model, config
            return SimpleNamespace(function_calls=[fc], text="")

    planner = GeminiPlanner(get_settings(), client=SimpleNamespace(models=Models()))
    call = planner.plan("How has Hostel B changed?", elec)
    assert (call.tool, call.args["entity"]) == ("trend_over_time", "Hostel B")
    assert calls["model"] == "gemma-4-26b-a4b-it"
    names = [d.name for d in calls["config"].tools[0].function_declarations]
    assert "normalize_by" in names and "cannot_answer" in names


def test_ollama_planner_parses_tool_calls(elec):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "gemma4:e2b"}]})
        seen["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "normalize_by", "arguments": {"metric": "kwh", "denominator": "occupancy"}}}]}})

    planner = OllamaPlanner(get_settings(), transport=httpx.MockTransport(handler))
    assert planner.available()
    call = planner.plan("Most efficient building per occupant?", elec)
    assert call.tool == "normalize_by" and call.planner == "ollama"
    assert seen["payload"]["model"] == "gemma4:e2b" and seen["payload"]["tools"][0]["type"] == "function"
    assert seen["payload"]["messages"][0]["role"] == "system"
