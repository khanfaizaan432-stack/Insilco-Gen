from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.insilicopop.agent.loop import AgentLoop
from app.insilicopop.agent.workbench import WorkbenchRunStore
from app.main import app
from backend.tests.test_pretest_assessment_v0312 import complete_case


client = TestClient(app)


def test_run_writes_assessment_artifact_report_trace_checksum_and_runtime_lock(tmp_path):
    result = AgentLoop(generated_root=tmp_path).run(
        query="Structure the supplied referral and pre-test assessment",
        uploads={},
        clinical_case_intake=complete_case(),
    )
    repro = Path(result["reproducibility_bundle"]["path"])
    artifact = repro / "pre_test_assessment.json"
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    report = Path(result["generated_files"]["final_report"]["absolute_path"]).read_text(encoding="utf-8")
    lock = json.loads((repro / "runtime_lock.json").read_text(encoding="utf-8"))
    provenance = json.loads((repro / "provenance_index.json").read_text(encoding="utf-8"))
    checksums = (repro / "checksums.sha256").read_text(encoding="utf-8")
    trace = result["agent_trace"]

    assert payload["assessment_outcome"] == "ready_for_test_strategy_review"
    assert "## Referral and Pre-Test Clinical Assessment" in report
    assert "No test strategy was generated" in report
    assert "test_strategy_generated: `false`" in report
    assert "reproducibility/pre_test_assessment.json" in checksums
    assert lock["pre_test_assessment_schema_version"] == "0.31.2"
    assert lock["pre_test_assessment_algorithm_version"] == "insilicopop-referral-pretest-assessment-0.31.2"
    assert lock["pre_test_assessment_outcome"] == "ready_for_test_strategy_review"
    assert lock["test_strategy_generated"] is False
    assert lock["test_order_placed"] is False
    assert provenance["pre_test_assessment"]["human_review_required"] is True
    event = next(item for item in trace if item.get("event") == "referral_pretest_assessment_completed")
    assert event["test_strategy_generated"] is False
    assert event["test_order_placed"] is False


def test_reordered_input_produces_identical_assessment_artifact_bytes(tmp_path):
    payload = complete_case()
    additional = copy.deepcopy(payload["pre_test_assessment"]["previous_investigations"][0])
    additional["investigation_id"] = "INV-1"
    payload["pre_test_assessment"]["previous_investigations"].append(additional)
    first = AgentLoop(generated_root=tmp_path).run(query="pre-test assessment", uploads={}, clinical_case_intake=payload)
    reordered = copy.deepcopy(payload)
    reordered["pre_test_assessment"]["previous_investigations"].reverse()
    second = AgentLoop(generated_root=tmp_path).run(query="pre-test assessment", uploads={}, clinical_case_intake=reordered)
    first_bytes = (Path(first["reproducibility_bundle"]["path"]) / "pre_test_assessment.json").read_bytes()
    second_bytes = (Path(second["reproducibility_bundle"]["path"]) / "pre_test_assessment.json").read_bytes()
    assert first_bytes == second_bytes
    assert hashlib.sha256(first_bytes).hexdigest() == hashlib.sha256(second_bytes).hexdigest()


def test_pretest_lane_bypasses_external_retrieval_llm_tools_and_raw_parsers(tmp_path, monkeypatch):
    import app.insilicopop.agent.loop as loop_module

    def forbidden(*args, **kwargs):
        raise AssertionError("forbidden subsystem called")

    monkeypatch.setattr(loop_module, "retrieve_evidence", forbidden)
    monkeypatch.setattr(loop_module, "build_llm_provider", forbidden)
    monkeypatch.setattr(loop_module.InSilicoPopAuditService, "run", forbidden)
    monkeypatch.setattr(loop_module.ToolRouter, "run", forbidden, raising=False)
    result = AgentLoop(generated_root=tmp_path).run(
        query="pre-test assessment",
        uploads={},
        clinical_case_intake=complete_case(),
    )
    assessment = result["pre_test_assessment"]
    assert result["external_llm_called"] is False
    assert result["external_tools_executed"] is False
    assert assessment["external_api_call_made"] is False
    assert assessment["external_llm_called"] is False
    assert assessment["external_tools_executed"] is False
    assert assessment["raw_genomic_files_parsed"] is False


def test_api_stored_run_allowlisted_artifact_and_workbench_expose_v0312():
    response = client.post(
        "/insilicopop/agent/run",
        data={
            "query": "Structure referral and pre-test assessment",
            "clinical_case_intake": json.dumps(complete_case()),
            "llm_provider": "mock",
        },
    )
    assert response.status_code == 200
    body = response.json()
    detail_response = client.get(f"/insilicopop/agent/runs/{body['run_id']}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["pre_test_assessment_outcome"] == "ready_for_test_strategy_review"
    assert detail["pre_test_open_missing_information_count"] == 0
    assert detail["pre_test_linkage_issue_count"] == 0
    assert detail["pre_test_assessment_artifact_available"] is True
    assert detail["pre_test_assessment"]["test_strategy_generated"] is False
    artifact = client.get(f"/insilicopop/agent/runs/{body['run_id']}/artifacts/reproducibility/pre_test_assessment.json")
    assert artifact.status_code == 200
    assert artifact.json()["content"]["schema_version"] == "0.31.2"
    ui = client.get("/insilicopop/workbench").text
    assert "Referral and Pre-Test Assessment Workspace" in ui
    assert "renderPreTestAssessment" in ui
    assert "does not recommend WES, WGS, or any other test" in ui


def test_old_stored_runs_remain_readable_without_pretest_assessment(tmp_path):
    old_run = tmp_path / "old-run"
    old_run.mkdir()
    (old_run / "agent_state.json").write_text(
        json.dumps(
            {
                "run_id": "old-run",
                "query": "old synthetic run",
                "workflow_selection": {"workflow_family": "clinical_case_intake"},
                "llm_provider": "mock",
                "external_llm_called": False,
                "external_tools_executed": False,
                "clinical_case_intake": {"schema_version": "0.27", "intake_completeness": "complete", "policy_blocks": []},
            }
        ),
        encoding="utf-8",
    )
    detail = WorkbenchRunStore(generated_root=tmp_path).run_detail("old-run")
    assert detail.pre_test_assessment is None
    assert detail.pre_test_assessment_outcome is None
    assert detail.pre_test_assessment_artifact_available is False
