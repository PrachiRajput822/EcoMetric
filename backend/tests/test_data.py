import pytest

from app.data.store import DatasetError, list_samples, parse_upload, store


def test_all_six_issue_areas_ship_with_samples():
    issues = {s["issue"] for s in list_samples()}
    assert issues == {"electricity", "water", "waste", "air", "mobility", "resources"}


def test_profile_detects_roles(elec):
    p = elec.profile
    assert p.time_column == "month"
    assert p.primary_entity == "building"
    assert p.primary_metric == "kwh"
    assert p.periods[0] == "2026-01" and p.periods[-1] == "2026-09"
    assert p.columns["occupancy"].role == "denominator"


def test_health_finds_planted_problems(elec, air, waste):
    assert {"entity": "Library", "period": "2026-06", "column": "kwh"} in elec.health["missing_cells"]
    assert any(o["entity"] == "Hostel B" and o["period"] == "2026-07" for o in elec.health["outliers"])
    assert any(o["entity"] == "Station Central" and o["period"] == "2026-08" for o in air.health["outliers"])
    assert {"entity": "Ward 3", "period": "2026-05"} in waste.health["missing_rows"]


def test_upload_infers_profile_without_dictionary():
    csv = b"Date,Ward,Waste KG,Households\n2026-01-15,Ward A,\"1,200\",300\n2026-02-15,Ward A,1100,300\n2026-01-15,Ward B,900,250\n"
    ds = store.load_upload("my data.csv", csv)
    p = ds.profile
    assert p.time_column == "Date"
    assert p.primary_entity == "Ward"
    assert p.columns["Waste KG"].kind == "number"
    assert p.columns["Households"].role == "denominator"
    assert p.sources_in_data == ["user-entered"]


@pytest.mark.parametrize("name,content,msg", [
    ("data.txt", b"a,b\n1,2", "Only .csv"),
    ("data.csv", b"   ", "empty"),
    ("data.csv", b"a\n" + b"1\n" * 10, None),
])
def test_upload_validation(name, content, msg):
    if msg is None:
        assert len(parse_upload(name, content)) == 10
    else:
        with pytest.raises(DatasetError, match=msg):
            parse_upload(name, content)


def test_upload_size_limit(monkeypatch):
    monkeypatch.setenv("MAX_UPLOAD_MB", "0.001")
    with pytest.raises(DatasetError, match="larger than"):
        parse_upload("big.csv", b"a,b\n" + b"1,2\n" * 1000)
