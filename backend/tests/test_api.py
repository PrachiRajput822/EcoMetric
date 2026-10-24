from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def load(sample="campus_electricity"):
    r = client.post("/api/datasets/sample", json={"sample_id": sample})
    assert r.status_code == 200
    return r.json()["id"]


def test_status_and_samples():
    s = client.get("/api/status").json()
    assert s["resolved_auto"] == "rules"
    assert len(client.get("/api/samples").json()) == 6


def test_security_headers():
    r = client.get("/")
    assert r.status_code == 200
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-frame-options"] == "DENY"


def test_ask_flow_and_audit():
    ds = load()
    r = client.post("/api/ask", json={"dataset_id": ds, "question": "Which building is most efficient per occupant?"})
    body = r.json()
    assert r.status_code == 200
    assert body["calculation"]["cross_check"]["match"] is True
    assert body["chart"]["kind"] == "bar"
    assert client.get("/api/audit?limit=5").json()[0]["question"] == "Which building is most efficient per occupant?"


def test_hindi_answer():
    ds = load()
    r = client.post("/api/ask", json={"dataset_id": ds, "question": "सितंबर 2026 में सबसे ज्यादा बिजली किस भवन ने इस्तेमाल की?", "lang": "hi"})
    assert "Hostel B" in r.json()["answer"]["text"] and "सितंबर 2026" in r.json()["answer"]["text"]


def test_upload_and_ask_with_script_text_kept_as_data():
    csv = "month,site,litres\n2026-01,<script>x</script>,10\n2026-02,<script>x</script>,12\n2026-01,Pump B,8\n2026-02,Pump B,9\n"
    r = client.post("/api/datasets/upload", files={"file": ("water.csv", csv, "text/csv")})
    assert r.status_code == 200
    ds = r.json()["id"]
    a = client.post("/api/ask", json={"dataset_id": ds, "question": "Which site used the most litres?"}).json()
    assert a["status"] == "answered" and a["answer"]["headline"]["top"]["entity"] == "<script>x</script>"


def test_bad_requests():
    assert client.post("/api/ask", json={"dataset_id": "nothere", "question": "hi"}).status_code == 422
    assert client.post("/api/ask", json={"dataset_id": "abcdefabcdef", "question": "Which building?"}).status_code == 400
    assert client.post("/api/datasets/sample", json={"sample_id": "../etc/passwd"}).status_code == 422
    r = client.post("/api/datasets/upload", files={"file": ("x.exe", b"MZ", "application/octet-stream")})
    assert r.status_code == 400 and "Only .csv" in r.json()["detail"]
