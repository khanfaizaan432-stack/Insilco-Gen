from __future__ import annotations

import importlib.util
import socket
from pathlib import Path

from fastapi.testclient import TestClient

from app.insilicopop.agent.loop import AgentLoop
from app.main import app


client = TestClient(app)


def test_langgraph_unavailable_uses_deterministic_fallback(monkeypatch, tmp_path):
    original_find_spec = importlib.util.find_spec

    def fake_find_spec(name: str, *args, **kwargs):
        if name.startswith("langgraph"):
            return None
        return original_find_spec(name, *args, **kwargs)

    monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)

    result = AgentLoop(generated_root=tmp_path).run(
        query="Plan local evidence-supported population genetics workflow.",
        uploads={"vcf_file": {"filename": "cohort.vcf.gz", "content": b"##fileformat=VCFv4.2\n"}},
        memory_mode="compact",
    )
    trace = result["orchestration_trace"]

    assert trace["langgraph_available"] is False
    assert trace["fallback_used"] is True
    assert trace["orchestration_backend"] == "deterministic_controlled_graph"
    assert trace["safety_flags"]["external_api_call_made"] is False


def test_orchestration_layer_does_not_make_network_calls(monkeypatch, tmp_path):
    def blocked_network_call(*args, **kwargs):
        raise AssertionError("unexpected network call")

    monkeypatch.setattr(socket, "create_connection", blocked_network_call)

    result = AgentLoop(generated_root=tmp_path).run(
        query="Retrieve local guidance for metadata completeness.",
        uploads={"metadata_file": {"filename": "metadata.csv", "content": b"sample_id,population\nS1,A\n"}},
        memory_mode="compact",
    )

    assert result["orchestration_trace"]["safety_flags"]["external_api_call_made"] is False
    assert result["evidence_retrieval"]["external_call_made"] is False


def test_workbench_api_and_ui_surface_orchestration_status():
    response = client.post(
        "/insilicopop/agent/run",
        data={"query": "plan PCA and ADMIXTURE", "memory_mode": "compact"},
        files={"vcf_file": ("cohort.vcf.gz", b"##fileformat=VCFv4.2\n", "application/gzip")},
    )
    assert response.status_code == 200
    run_id = response.json()["run_id"]

    detail = client.get(f"/insilicopop/agent/runs/{run_id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["orchestration_backend"]
    assert body["orchestration_node_count"] >= 1
    assert body["orchestration_trace"]["safety_flags"]["autonomous_tool_execution"] is False

    artifact = client.get(f"/insilicopop/agent/runs/{run_id}/artifacts/reproducibility/orchestration_trace.json")
    assert artifact.status_code == 200
    assert artifact.json()["content"]["safety_flags"]["raw_genomic_files_parsed"] is False

    ui = client.get("/insilicopop/workbench")
    assert ui.status_code == 200
    assert "Controlled orchestration preview" in ui.text
    assert "renderOrchestrationTrace" in ui.text


def test_empty_input_run_still_gets_controlled_trace(tmp_path):
    result = AgentLoop(generated_root=tmp_path).run(
        query="Plan a safe local workflow.",
        uploads={},
        memory_mode="compact",
    )

    assert result["orchestration_trace"]["orchestration_enabled"] is True
    assert "intake_interpretation" in result["orchestration_trace"]["graph_nodes_executed"]
    assert result["orchestration_trace"]["safety_flags"]["human_review_required"] is True
