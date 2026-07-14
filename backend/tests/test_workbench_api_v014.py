from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def _start_agent_run() -> dict[str, object]:
    response = client.post(
        "/insilicopop/agent/run",
        data={"query": "plan PCA and ADMIXTURE", "memory_mode": "compact"},
        files={
            "metadata_file": ("metadata.csv", b"sample_id,population\nS1,A\n", "text/csv"),
            "vcf_file": ("cohort.vcf.gz", b"##fileformat=VCFv4.2\n", "application/gzip"),
        },
    )
    assert response.status_code == 200
    return response.json()


def test_existing_agent_run_endpoint_still_generates_mock_run_metadata():
    body = _start_agent_run()

    assert body["run_id"]
    assert body["workflow_selection"]["workflow_family"] == "vcf_population_structure"
    assert body["llm_provider"] == "mock"
    assert body["external_llm_called"] is False
    assert body["external_tools_executed"] is False


def test_generated_run_appears_in_listing_and_detail():
    body = _start_agent_run()
    run_id = body["run_id"]

    listing = client.get("/insilicopop/agent/runs")
    assert listing.status_code == 200
    runs = listing.json()
    summary = next(item for item in runs if item["run_id"] == run_id)
    assert summary["workflow_family"] == body["workflow_selection"]["workflow_family"]
    assert summary["llm_provider"] == "mock"
    assert summary["external_llm_called"] is False
    assert summary["external_tools_executed"] is False
    assert summary["has_final_report"] is True
    assert summary["has_reproducibility_bundle"] is True

    detail = client.get(f"/insilicopop/agent/runs/{run_id}")
    assert detail.status_code == 200
    detail_body = detail.json()
    assert detail_body["run_id"] == run_id
    assert detail_body["current_step"] == body["final_state"]["current_step"]
    assert detail_body["selected_recipe"]["recipe_id"] == "vcf_population_structure_basic"
    assert detail_body["selected_recipe_id"] == "vcf_population_structure_basic"
    assert detail_body["claim_audit"]["selected_recipe_id"] == "vcf_population_structure_basic"
    assert detail_body["results_audit"] is None
    assert detail_body["data_governance_audit"]["human_review_required"] is True
    assert detail_body["metadata_registry_audit"]["human_review_required"] is True
    assert detail_body["evidence_retrieval"]["local_only"] is True
    assert detail_body["evidence_retrieval_mode"] == "deterministic_keyword_fallback"
    assert detail_body["orchestration_trace"]["orchestration_enabled"] is True
    assert detail_body["orchestration_backend"]
    assert detail_body["orchestration_node_count"] >= 1
    assert detail_body["orchestration_safety_flags"]["autonomous_tool_execution"] is False
    assert detail_body["research_lane"] == "population_genetics"
    assert "final_report.md" in detail_body["artifact_names"]
    assert detail_body["artifact_count"] >= 10


def test_artifact_listing_report_workflow_selection_and_reproducibility_endpoints():
    body = _start_agent_run()
    run_id = body["run_id"]

    artifacts = client.get(f"/insilicopop/agent/runs/{run_id}/artifacts")
    assert artifacts.status_code == 200
    artifact_names = {item["artifact_name"] for item in artifacts.json()}
    assert "agent_state.json" in artifact_names
    assert "final_report.md" in artifact_names
    assert "workflow_selection.json" in artifact_names
    assert "reproducibility/selected_recipe.json" in artifact_names
    assert "reproducibility/claim_audit.json" in artifact_names
    assert "reproducibility/data_governance_audit.json" in artifact_names
    assert "reproducibility/metadata_registry_audit.json" in artifact_names
    assert "reproducibility/evidence_retrieval.json" in artifact_names
    assert "reproducibility/orchestration_trace.json" in artifact_names
    assert "reproducibility/results_audit.json" not in artifact_names
    assert "reproducibility/runtime_lock.json" in artifact_names

    report = client.get(f"/insilicopop/agent/runs/{run_id}/report")
    assert report.status_code == 200
    assert report.json()["artifact_name"] == "final_report.md"
    assert "# InSilicoPop Agent Run Report" in report.json()["content"]

    workflow_selection = client.get(f"/insilicopop/agent/runs/{run_id}/workflow-selection")
    assert workflow_selection.status_code == 200
    assert workflow_selection.json() == body["workflow_selection"]

    reproducibility = client.get(f"/insilicopop/agent/runs/{run_id}/reproducibility")
    assert reproducibility.status_code == 200
    repro_body = reproducibility.json()
    assert repro_body["generated"] is True
    assert set(repro_body["files"]) == {
        "reproducibility/input_inventory.json",
        "reproducibility/workflow_selection.json",
        "reproducibility/command_previews.sh",
        "reproducibility/command_previews.yaml",
        "reproducibility/selected_recipe.json",
        "reproducibility/claim_audit.json",
        "reproducibility/data_governance_audit.json",
        "reproducibility/metadata_registry_audit.json",
        "reproducibility/evidence_retrieval.json",
        "reproducibility/orchestration_trace.json",
        "reproducibility/guardrail_decisions.json",
        "reproducibility/provenance_index.json",
        "reproducibility/runtime_lock.json",
        "reproducibility/checksums.sha256",
    }
    assert repro_body["runtime_lock"]["llm_provider"] == "mock"
    assert repro_body["runtime_lock"]["selected_recipe_id"] == "vcf_population_structure_basic"
    assert repro_body["runtime_lock"]["external_llm_called"] is False
    assert repro_body["runtime_lock"]["external_tools_executed"] is False
    assert repro_body["runtime_lock"]["orchestration_backend"]


def test_artifact_endpoint_reads_allowed_generated_and_reproducibility_artifacts():
    body = _start_agent_run()
    run_id = body["run_id"]

    state = client.get(f"/insilicopop/agent/runs/{run_id}/artifacts/agent_state.json")
    assert state.status_code == 200
    state_body = state.json()
    assert state_body["artifact_name"] == "agent_state.json"
    assert state_body["content"]["run_id"] == run_id
    assert state_body["content"]["llm_provider"] == "mock"
    assert state_body["content"]["external_llm_called"] is False
    assert state_body["content"]["external_tools_executed"] is False

    runtime_lock = client.get(f"/insilicopop/agent/runs/{run_id}/artifacts/reproducibility/runtime_lock.json")
    assert runtime_lock.status_code == 200
    assert runtime_lock.json()["content"]["run_id"] == run_id

    selected_recipe = client.get(f"/insilicopop/agent/runs/{run_id}/artifacts/reproducibility/selected_recipe.json")
    assert selected_recipe.status_code == 200
    assert selected_recipe.json()["content"]["recipe_id"] == "vcf_population_structure_basic"
    assert selected_recipe.json()["content"]["dry_run_only"] is True

    claim_audit = client.get(f"/insilicopop/agent/runs/{run_id}/artifacts/reproducibility/claim_audit.json")
    assert claim_audit.status_code == 200
    assert claim_audit.json()["content"]["selected_recipe_id"] == "vcf_population_structure_basic"
    assert claim_audit.json()["content"]["human_review_required"] is True

    data_governance_audit = client.get(f"/insilicopop/agent/runs/{run_id}/artifacts/reproducibility/data_governance_audit.json")
    assert data_governance_audit.status_code == 200
    assert data_governance_audit.json()["content"]["human_review_required"] is True
    assert data_governance_audit.json()["content"]["dataset_terms_verified"] is False

    metadata_registry_audit = client.get(f"/insilicopop/agent/runs/{run_id}/artifacts/reproducibility/metadata_registry_audit.json")
    assert metadata_registry_audit.status_code == 200
    assert metadata_registry_audit.json()["content"]["human_review_required"] is True
    assert metadata_registry_audit.json()["content"]["clinical_decision_made"] is False

    evidence_retrieval = client.get(f"/insilicopop/agent/runs/{run_id}/artifacts/reproducibility/evidence_retrieval.json")
    assert evidence_retrieval.status_code == 200
    assert evidence_retrieval.json()["content"]["local_only"] is True
    assert evidence_retrieval.json()["content"]["external_call_made"] is False

    orchestration_trace = client.get(f"/insilicopop/agent/runs/{run_id}/artifacts/reproducibility/orchestration_trace.json")
    assert orchestration_trace.status_code == 200
    assert orchestration_trace.json()["content"]["orchestration_enabled"] is True
    assert orchestration_trace.json()["content"]["safety_flags"]["external_api_call_made"] is False


def test_artifact_endpoint_rejects_path_traversal_and_arbitrary_filesystem_paths():
    body = _start_agent_run()
    run_id = body["run_id"]

    traversal = client.get(f"/insilicopop/agent/runs/{run_id}/artifacts/reproducibility/%2E%2E/agent_state.json")
    assert traversal.status_code == 403

    arbitrary = client.get(f"/insilicopop/agent/runs/{run_id}/artifacts/C:%5CWindows%5Cwin.ini")
    assert arbitrary.status_code == 403


def test_missing_run_and_missing_artifact_return_controlled_not_found():
    missing_run = client.get("/insilicopop/agent/runs/not-a-real-run")
    assert missing_run.status_code == 404
    assert missing_run.json()["detail"] == "agent run not found"

    body = _start_agent_run()
    run_id = body["run_id"]
    blocked_actions = Path(body["generated_files"]["blocked_actions"]["absolute_path"])
    blocked_actions.unlink()

    missing_artifact = client.get(f"/insilicopop/agent/runs/{run_id}/artifacts/blocked_actions.md")
    assert missing_artifact.status_code == 404
    assert missing_artifact.json()["detail"] == "agent artifact not found"
