from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_agent_memory_endpoint_all_works_and_generates_files():
    response = client.post(
        "/insilicopop/benchmark/agent-memory",
        json={"scenario": "all", "budget_chars": 1500, "memory_mode": "compact"},
    )

    assert response.status_code == 200
    body = response.json()
    assert "domain_aware_governed_memory" in body["results"]
    assert Path(body["generated_files"]["carried_memory_trace"]["absolute_path"]).exists()
    assert Path(body["generated_files"]["dropped_facts_log"]["absolute_path"]).exists()
    assert Path(body["generated_files"]["provenance_index"]["absolute_path"]).exists()


def test_governed_memory_beats_baselines_on_critical_recall():
    body = client.post(
        "/insilicopop/benchmark/agent-memory",
        json={"scenario": "all", "budget_chars": 1500, "memory_mode": "compact"},
    ).json()

    governed = body["results"]["domain_aware_governed_memory"]["aggregate"]["final_critical_fact_recall"]
    raw = body["results"]["raw_truncation_carried_memory"]["aggregate"]["final_critical_fact_recall"]
    naive = body["results"]["naive_summary_carried_memory"]["aggregate"]["final_critical_fact_recall"]
    assert governed >= raw
    assert governed >= naive

