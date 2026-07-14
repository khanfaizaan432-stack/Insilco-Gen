from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_benchmark_returns_all_domain_aware_modes():
    body = client.post("/insilicopop/benchmark/memory", json={"scenario": "all", "token_budget": 1000}).json()

    assert "domain_aware_verbose" in body["results"]
    assert "domain_aware_compact" in body["results"]
    assert "domain_aware_ultra_compact" in body["results"]
    assert body["winner"] in body["results"]


def test_compact_beats_raw_and_naive_on_critical_recall():
    body = client.post("/insilicopop/benchmark/memory", json={"scenario": "all", "token_budget": 1000}).json()

    compact = body["results"]["domain_aware_compact"]["aggregate"]["critical_fact_recall"]
    raw = body["results"]["raw_truncation"]["aggregate"]["critical_fact_recall"]
    naive = body["results"]["naive_summary"]["aggregate"]["critical_fact_recall"]
    assert compact >= raw
    assert compact >= naive


def test_oracle_has_worse_compression_than_compact_modes():
    body = client.post("/insilicopop/benchmark/memory", json={"scenario": "all", "token_budget": 1000}).json()

    oracle = body["results"]["oracle_full"]["aggregate"]["compression_ratio"]
    compact = body["results"]["domain_aware_compact"]["aggregate"]["compression_ratio"]
    ultra = body["results"]["domain_aware_ultra_compact"]["aggregate"]["compression_ratio"]
    assert oracle > compact
    assert oracle > ultra

