import pytest

from app.data.store import list_samples, store
from app.llm.base import parse_text_call
from app.llm.rules import RulePlanner
from app.tools.registry import ToolInputError, run_tool

rules = RulePlanner()


@pytest.mark.parametrize("question,tool,args", [
    ("Which building used the most electricity in September 2026?", "rank_entities",
     {"metric": "kwh", "order": "desc", "period_start": "2026-09", "period_end": "2026-09"}),
    ("How has Hostel B electricity changed since January?", "trend_over_time",
     {"metric": "kwh", "entity": "Hostel B", "period_start": "2026-01"}),
    ("Which building is most efficient per occupant?", "normalize_by", {"denominator": "occupancy", "order": "asc"}),
    ("Which building is least efficient per occupant?", "normalize_by", {"order": "desc"}),
    ("What was the electricity cost last month?", "cannot_answer", {}),
    ("What is the capital of France?", "cannot_answer", {}),
    ("सितंबर 2026 में सबसे ज्यादा बिजली किस भवन ने इस्तेमाल की?", "rank_entities", {"period_start": "2026-09"}),
    ("जनवरी से हॉस्टल बी की बिजली खपत कैसे बदली?", "trend_over_time", {"entity": "Hostel B", "period_start": "2026-01"}),
    ("पिछले महीने बिजली का बिल कितना था?", "cannot_answer", {}),
    ("Compare Hostel A and Hostel B electricity", "compare_entities", {"entities": ["Hostel A", "Hostel B"]}),
    ("Show the top 3 buildings by electricity in May 2026", "rank_entities", {"limit": 3, "period_start": "2026-05"}),
])
def test_rules_route_demo_questions(elec, question, tool, args):
    call = rules.plan(question, elec)
    assert call.tool == tool
    for k, v in args.items():
        assert call.args[k] == v


def test_every_sample_example_is_answerable():
    for s in list_samples():
        ds = store.load_sample(s["id"])
        for lang in ("en", "hi"):
            for q in ds.profile.examples.get(lang, []):
                call = rules.plan(q, ds)
                if call.tool == "cannot_answer":
                    assert "cost" in q.lower() or "बिल" in q
                    continue
                try:
                    run_tool(ds, call.tool, call.args)
                except ToolInputError as exc:  # pragma: no cover - shows which example broke
                    pytest.fail(f"{s['id']}: {q} -> {call.tool} {call.args}: {exc}")


@pytest.mark.parametrize("text,expected", [
    ('{"name": "rank_entities", "args": {"metric": "kwh"}}', ("rank_entities", {"metric": "kwh"})),
    ('Sure. {"tool": "trend_over_time", "arguments": "{\\"metric\\": \\"kwh\\"}"}', ("trend_over_time", {"metric": "kwh"})),
    ('<|tool_call>call:rank_entities{"metric": "kwh"}<tool_call|>', ("rank_entities", {"metric": "kwh"})),
    ("I think Hostel B used the most.", None),
])
def test_parse_text_call(text, expected):
    assert parse_text_call(text) == expected
