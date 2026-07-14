from pathlib import Path

from fastapi.testclient import TestClient

from app.insilicopop.benchmarks.runner import MemoryBenchmarkRunner
from app.main import app


client = TestClient(app)


def test_memory_benchmark_endpoint_all_works():
    response = client.post("/insilicopop/benchmark/memory", json={"scenario": "all", "token_budget": 1000})

    assert response.status_code == 200
    body = response.json()
    assert body["winner"] in body["results"]
    assert "domain_aware_compact" in body["results"]
    assert body["generated_files"]["method_comparison"]["created"] is True


def test_memory_benchmark_generated_files_exist(tmp_path):
    result = MemoryBenchmarkRunner(generated_root=tmp_path).run("admixture_underfit", 1000)

    assert Path(result["generated_files"]["benchmark_results"]["absolute_path"]).exists()
    assert Path(result["generated_files"]["method_comparison"]["absolute_path"]).exists()


def test_domain_aware_beats_raw_and_naive_on_critical_recall_in_most_scenarios(tmp_path):
    result = MemoryBenchmarkRunner(generated_root=tmp_path).run("all", 1000)

    domain = result["results"]["domain_aware_compact"]["aggregate"]["critical_fact_recall"]
    raw = result["results"]["raw_truncation"]["aggregate"]["critical_fact_recall"]
    naive = result["results"]["naive_summary"]["aggregate"]["critical_fact_recall"]
    assert domain >= raw
    assert domain >= naive
