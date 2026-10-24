import pytest

from app.tools.registry import ToolInputError, build_tool_specs, run_tool


def test_rank_matches_manual_sum(elec):
    r = run_tool(elec, "rank_entities", {"metric": "kwh", "period_start": "2026-09", "period_end": "2026-09"})
    df = elec.df[elec.df["month"] == "2026-09"].groupby("building")["kwh"].sum().sort_values(ascending=False)
    assert r.table[0]["entity"] == df.index[0]
    assert r.table[0]["value"] == pytest.approx(df.iloc[0])
    assert r.cross_check["match"] is True
    assert r.rows_used == 6


def test_trend_since_month_runs_to_latest(elec):
    r = run_tool(elec, "trend_over_time", {"metric": "kwh", "entity": "hostel b", "period_start": "2026-01"})
    assert (r.period_start, r.period_end) == ("2026-01", "2026-09")
    assert r.headline["peak"]["period"] == "2026-07"
    assert r.headline["pct"] == pytest.approx((50313 - 36945) / 36945 * 100)


def test_normalize_skips_blank_rows_and_orders_ascending(elec):
    r = run_tool(elec, "normalize_by", {"metric": "kwh", "denominator": "occupancy", "order": "asc"})
    values = [x["value"] for x in r.table]
    assert values == sorted(values)
    assert r.rows_skipped == 1
    assert r.cross_check["match"]


def test_share_ratio_is_percent(waste):
    r = run_tool(waste, "normalize_by", {"metric": "segregated_kg", "denominator": "total_waste_kg", "order": "desc"})
    assert r.headline["as_percent"] is True
    assert 0 < r.table[0]["value"] <= 100


def test_concentrations_are_averaged_not_summed(air):
    r = run_tool(air, "aggregate_total", {"metric": "pm25", "agg": "sum"})
    assert r.args["agg"] == "avg"
    assert any(n["code"] == "non_additive" for n in r.notes)


def test_latest_period_note(elec):
    r = run_tool(elec, "compare_entities", {"metric": "kwh", "entities": ["Hostel A", "हॉस्टल बी"], "latest_period": True})
    assert r.entities == ["Hostel A", "Hostel B"]
    assert r.period_start == "2026-09"


@pytest.mark.parametrize("tool,args,code", [
    ("rank_entities", {"metric": "cost"}, "unknown_column"),
    ("rank_entities", {"metric": 'kwh"; DROP TABLE data; --'}, "unknown_column"),
    ("trend_over_time", {"metric": "kwh", "entity": "x' OR 1=1 --"}, "unknown_entity"),
    ("rank_entities", {"metric": "kwh", "period_start": "2025-01", "period_end": "2025-03"}, "period_out_of_range"),
    ("compare_entities", {"metric": "kwh", "entities": ["Hostel A"]}, "invalid_args"),
    ("drop_table", {}, "unknown_tool"),
    ("cannot_answer", {"reason": "no cost column"}, "model_refused"),
])
def test_invalid_calls_are_rejected(elec, tool, args, code):
    with pytest.raises(ToolInputError) as exc:
        run_tool(elec, tool, args)
    assert exc.value.code == code


def test_injection_text_never_reaches_sql(elec):
    with pytest.raises(ToolInputError):
        run_tool(elec, "rank_entities", {"metric": "kwh", "group_by": "building; DELETE FROM data"})
    assert len(elec.query("SELECT * FROM data")) == 54


def test_tool_specs_use_real_columns_only(elec):
    specs = {s["name"]: s for s in build_tool_specs(elec.profile)}
    metric_enum = specs["rank_entities"]["parameters"]["properties"]["metric"]["enum"]
    assert set(metric_enum) == {"kwh", "occupancy", "floor_area_sqft"}
    assert "cannot_answer" in specs
