from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from app.insilicopop.agent.loop import AgentLoop
from app.insilicopop.agent.workbench import WorkbenchRunStore
from app.insilicopop.clinical import (
    build_clinical_case_full_bundle,
    build_clinical_case_result_evidence_bundle,
    build_clinical_case_specialist_agent_bundle,
    build_clinical_case_strategy_bundle,
)
from app.main import app
from backend.tests.test_specialist_agents_v033 import _candidate_payload
from backend.tests.test_v0311_workbench_dom import _javascript_function


client = TestClient(app)


def test_frozen_bundle_widths_and_v033_additive_contract():
    payload, _ = _candidate_payload()
    assert len(build_clinical_case_full_bundle(payload)) == 5
    assert len(build_clinical_case_strategy_bundle(payload)) == 6
    assert len(build_clinical_case_result_evidence_bundle(payload)) == 7
    bundle = build_clinical_case_specialist_agent_bundle(payload)
    assert len(bundle) == 8
    assert bundle[7].schema_version == "0.33"


def test_run_integrates_report_trace_reproducibility_lock_state_and_checksums(tmp_path):
    payload, _ = _candidate_payload()
    result = AgentLoop(generated_root=tmp_path).run(
        query="Run bounded synthetic specialist review",
        uploads={},
        clinical_case_intake=payload,
    )
    repro = Path(result["reproducibility_bundle"]["path"])
    artifact = repro / "specialist_agent_workspace.json"
    workspace = json.loads(artifact.read_text(encoding="utf-8"))
    report = Path(result["generated_files"]["final_report"]["absolute_path"]).read_text(
        encoding="utf-8"
    )
    lock = json.loads((repro / "runtime_lock.json").read_text(encoding="utf-8"))
    provenance = json.loads((repro / "provenance_index.json").read_text(encoding="utf-8"))
    orchestration = json.loads(
        (repro / "orchestration_trace.json").read_text(encoding="utf-8")
    )
    checksums = (repro / "checksums.sha256").read_text(encoding="utf-8")
    state = json.loads(
        Path(result["generated_files"]["agent_state"]["absolute_path"]).read_text(
            encoding="utf-8"
        )
    )

    assert workspace["schema_version"] == "0.33"
    assert len(workspace["approved_registry"]) == 8
    assert len(workspace["agent_outputs"]) == 1
    assert workspace["agent_outputs"][0]["proposal_status"] == "proposed_not_approved"
    assert workspace["candidate_criteria"][0]["candidate_status"] == "candidate_only"
    assert workspace["applied_review_actions"] == []
    assert workspace["review_action_results"] == []
    assert workspace["recursive_spawning_used"] is False
    assert workspace["majority_vote_used"] is False
    assert "## Specialist Agents and Candidate ACMG Workspace" in report
    assert "Accepted for discussion does not mean criterion satisfied" in report
    assert "reproducibility/specialist_agent_workspace.json" in checksums
    assert provenance["specialist_agent_workspace"]["artifact_class"] == (
        "bounded_proposed_not_approved_specialist_and_candidate_workspace"
    )
    assert lock["agent_registry_version"] == "insilicopop-specialist-agent-registry-0.33.0"
    assert lock["enabled_specialist_agents"]
    assert lock["specialist_agent_task_ids"]
    assert lock["specialist_agent_input_hashes"]
    assert lock["specialist_agent_output_hashes"]
    assert lock["candidate_criterion_ids"]
    assert lock["candidate_criterion_vocabulary_version"]
    assert lock["specialist_agent_external_llm_called"] is False
    assert lock["specialist_agent_external_tools_executed"] is False
    assert lock["specialist_applied_human_review_actions"] == []
    assert lock["specialist_human_review_action_results"] == []
    assert orchestration["specialist_agent_trace"]
    assert state["specialist_agent_workspace"]["schema_version"] == "0.33"
    trace_events = {item["event"] for item in result["agent_trace"]}
    for event in (
        "spawn_request",
        "registry_entry",
        "task_envelope",
        "input_hash",
        "agent_start",
        "agent_steps",
        "tool_calls",
        "provider_calls",
        "budget_events",
        "output_validation",
        "safety_validation",
        "agent_output",
        "candidate_acmg_proposals",
        "human_review_actions",
        "disagreement_groups",
        "stop_reason",
    ):
        assert event in trace_events
    assert result["external_llm_called"] is False
    assert result["external_tools_executed"] is False


def test_api_stored_run_and_allowlisted_artifact_expose_v033():
    payload, _ = _candidate_payload()
    payload["specialist_agent_workspace"]["review_actions"] = [
        {
            "action_id": "API-UNKNOWN-OUTPUT",
            "action": "accept_agent_output_for_discussion",
            "target_type": "agent_output",
            "target_id": "OUTPUT-DOES-NOT-EXIST",
            "reviewer_role": "clinical_research_reviewer",
            "timestamp": "2026-03-01T00:00:00Z",
            "before_value": {"human_review_status": "pending"},
            "after_value": {"human_review_status": "accepted_for_discussion"},
        }
    ]
    response = client.post(
        "/insilicopop/agent/run",
        data={
            "query": "Synthetic v0.33 specialist workspace",
            "clinical_case_intake": json.dumps(payload),
            "llm_provider": "mock",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["specialist_agent_workspace"]["schema_version"] == "0.33"
    detail_response = client.get(f"/insilicopop/agent/runs/{body['run_id']}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["specialist_agent_spawn_request_count"] == 1
    assert detail["specialist_agent_output_count"] == 1
    assert detail["specialist_agent_review_ready_output_count"] == 1
    assert detail["candidate_acmg_evidence_count"] == 1
    assert detail["specialist_applied_review_action_count"] == 0
    assert detail["specialist_rejected_review_action_count"] == 1
    assert detail["specialist_agent_workspace_artifact_available"] is True
    assert detail["specialist_agent_workspace"]["schema_version"] == "0.33"
    artifact = client.get(
        f"/insilicopop/agent/runs/{body['run_id']}/artifacts/reproducibility/specialist_agent_workspace.json"
    )
    assert artifact.status_code == 200
    content = artifact.json()["content"]
    assert content["agent_outputs"][0]["external_llm_called"] is False
    assert content["agent_outputs"][0]["external_tools_executed"] is False
    assert content["applied_review_actions"] == []
    assert content["review_action_results"][0]["result_status"] == "rejected"
    assert content["review_action_results"][0]["rejection_reason"] == "target_not_found"


def test_workbench_dom_renders_required_state_and_safety_labels(tmp_path):
    node = shutil.which("node")
    assert node is not None, "Node.js is required for the Workbench DOM contract test"
    payload, _ = _candidate_payload()
    payload["specialist_agent_workspace"]["review_actions"] = [
        {
            "action_id": "DOM-UNKNOWN-OUTPUT",
            "action": "reject_agent_output",
            "target_type": "agent_output",
            "target_id": "OUTPUT-DOES-NOT-EXIST",
            "reviewer_role": "clinical_research_reviewer",
            "timestamp": "2026-03-01T00:00:00Z",
            "before_value": {"human_review_status": "pending"},
            "after_value": {"human_review_status": "rejected"},
        }
    ]
    workspace = build_clinical_case_specialist_agent_bundle(payload)[7].model_dump(
        mode="json"
    )
    ui = client.get("/insilicopop/workbench").text
    functions = "\n".join(
        _javascript_function(ui, name)
        for name in (
            "escapeHtml",
            "notAvailable",
            "asJson",
            "renderSpecialistAgentWorkspace",
        )
    )
    script = f"""
const target = {{className: "", textContent: "", innerHTML: ""}};
globalThis.document = {{getElementById: () => target}};
{functions}
renderSpecialistAgentWorkspace({json.dumps(workspace)});
process.stdout.write(target.innerHTML);
"""
    script_path = tmp_path / "render-specialist-workspace.js"
    script_path.write_text(script, encoding="utf-8")
    rendered = subprocess.run(
        [node, str(script_path)],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    ).stdout
    for term in (
        "Specialist agent",
        "Bounded task",
        "Approved registry",
        "Reviewed evidence inputs",
        "Proposed agent output",
        "Candidate ACMG evidence",
        "Candidate only",
        "Requires review",
        "External ACMG assessment",
        "Human decision required",
        "source_reported",
        "ledger_verified",
        "agent_generated",
        "candidate_only",
        "human_reviewed",
        "external_assessment",
        "Rejected or stale review attempts",
        "rejected review attempt",
        "target_not_found",
    ):
        assert term in rendered
    for forbidden in (
        "Autonomous diagnosis",
        "Pathogenic according to InSilicoPop",
        "Criterion confirmed",
        "Causative variant",
        "Clinically approved",
        "Treatment recommendation",
        "Test ordered",
    ):
        assert forbidden not in rendered


def test_old_stored_runs_remain_readable_without_specialist_workspace(tmp_path):
    old_run = tmp_path / "old-run"
    old_run.mkdir()
    (old_run / "agent_state.json").write_text(
        json.dumps(
            {
                "run_id": "old-run",
                "workflow_selection": {"workflow_family": "clinical_case_intake"},
                "llm_provider": "mock",
                "external_llm_called": False,
                "external_tools_executed": False,
            }
        ),
        encoding="utf-8",
    )
    detail = WorkbenchRunStore(generated_root=tmp_path).run_detail("old-run")
    assert detail.specialist_agent_workspace is None
    assert detail.specialist_agent_output_count == 0
    assert detail.candidate_acmg_evidence_count == 0
    assert detail.specialist_agent_workspace_artifact_available is False


def test_specialist_artifact_contains_no_secret_or_machine_path(tmp_path):
    payload, _ = _candidate_payload()
    result = AgentLoop(generated_root=tmp_path).run(
        query="Synthetic bounded specialist evidence",
        uploads={},
        clinical_case_intake=payload,
    )
    artifact = Path(result["reproducibility_bundle"]["path"]) / "specialist_agent_workspace.json"
    text = artifact.read_text(encoding="utf-8").lower()
    for forbidden in (
        "api_key",
        "bearer ",
        "access_token",
        "client_secret",
        "pytest-tmp",
    ):
        assert forbidden not in text
    assert re.search(r"[a-z]:\\\\[^\"\\s]", text) is None
