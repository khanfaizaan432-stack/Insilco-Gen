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
    build_clinical_case_strategy_bundle,
)
from app.main import app
from backend.tests.test_result_evidence_workspace_v032 import workspace_payload
from backend.tests.test_v0311_workbench_dom import _javascript_function


client = TestClient(app)


def test_frozen_bundle_widths_and_new_additive_bundle_are_preserved():
    payload = workspace_payload()
    assert len(build_clinical_case_full_bundle(payload)) == 5
    assert len(build_clinical_case_strategy_bundle(payload)) == 6
    result_bundle = build_clinical_case_result_evidence_bundle(payload)
    assert len(result_bundle) == 7
    assert result_bundle[6].schema_version == "0.32"


def test_agent_run_integrates_report_trace_reproducibility_lock_and_checksums(tmp_path):
    result = AgentLoop(generated_root=tmp_path).run(
        query="Record synthetic external result and retrieve bounded fixture evidence",
        uploads={},
        clinical_case_intake=workspace_payload(),
    )
    repro = Path(result["reproducibility_bundle"]["path"])
    artifact = repro / "result_evidence_workspace.json"
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    report = Path(result["generated_files"]["final_report"]["absolute_path"]).read_text(encoding="utf-8")
    lock = json.loads((repro / "runtime_lock.json").read_text(encoding="utf-8"))
    provenance = json.loads((repro / "provenance_index.json").read_text(encoding="utf-8"))
    checksums = (repro / "checksums.sha256").read_text(encoding="utf-8")
    state = json.loads(Path(result["generated_files"]["agent_state"]["absolute_path"]).read_text(encoding="utf-8"))

    assert payload["schema_version"] == "0.32"
    assert payload["normalization_rules"] == ["NORM-001"]
    assert len(payload["ledger_entries"]) == 1
    assert payload["generated_summaries"][0]["summary_status"] == "proposed_not_approved"
    assert "## Result and Evidence Workspace" in report
    assert "records source statements and does not assign ACMG criteria" in report
    assert "final_acmg_classification_made: `false`" in report
    assert "reproducibility/result_evidence_workspace.json" in checksums
    assert provenance["result_evidence_workspace"]["artifact_class"] == "immutable_source_linked_result_and_evidence_workspace"
    assert lock["result_intake_version"] == "insilicopop-result-intake-0.32.0"
    assert lock["normalization_version"] == "insilicopop-result-normalization-0.32.0"
    assert lock["normalization_rules"] == ["NORM-001"]
    assert lock["source_document_hashes"] == ["a" * 64]
    assert lock["retrieval_source_versions"] == {"FixtureDB": "2026.1"}
    assert len(lock["raw_response_hashes"]) == 1
    assert len(lock["ledger_entry_ids"]) == 1
    assert lock["result_evidence_external_llm_called"] is False
    assert lock["result_evidence_byok_used"] is False
    assert state["result_evidence_workspace"]["schema_version"] == "0.32"
    event = next(
        item for item in result["agent_trace"] if item.get("event") == "result_evidence_workspace_completed"
    )
    assert event["retrieval_states"] == ["completed"]
    assert event["final_acmg_classification_made"] is False
    assert result["external_llm_called"] is False
    assert result["external_tools_executed"] is False


def test_api_stored_run_and_allowlisted_artifact_expose_v032():
    response = client.post(
        "/insilicopop/agent/run",
        data={
            "query": "Synthetic v0.32 result evidence workspace",
            "clinical_case_intake": json.dumps(workspace_payload()),
            "llm_provider": "mock",
        },
    )
    assert response.status_code == 200
    body = response.json()
    detail_response = client.get(f"/insilicopop/agent/runs/{body['run_id']}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["result_intake_count"] == 1
    assert detail["result_finding_count"] == 1
    assert detail["result_normalization_status_counts"] == {"normalized": 1}
    assert detail["result_retrieval_status_counts"] == {"completed": 1}
    assert detail["evidence_ledger_entry_count"] == 1
    assert detail["result_evidence_workspace_artifact_available"] is True
    assert detail["result_evidence_workspace"]["schema_version"] == "0.32"
    artifact = client.get(
        f"/insilicopop/agent/runs/{body['run_id']}/artifacts/reproducibility/result_evidence_workspace.json"
    )
    assert artifact.status_code == 200
    content = artifact.json()["content"]
    assert content["ledger_entries"][0]["source_statement"]
    assert content["external_llm_called"] is False


def test_workbench_dom_renders_state_separation_and_safety_terms():
    node = shutil.which("node")
    assert node is not None, "Node.js is required for the Workbench DOM contract test"
    ui = client.get("/insilicopop/workbench").text
    functions = "\n".join(
        _javascript_function(ui, name)
        for name in ("escapeHtml", "notAvailable", "asJson", "renderResultEvidenceWorkspace")
    )
    workspace = build_clinical_case_result_evidence_bundle(workspace_payload())[6].model_dump(mode="json")
    script = f"""
const target = {{className: "", textContent: "", innerHTML: ""}};
globalThis.document = {{getElementById: () => target}};
{functions}
renderResultEvidenceWorkspace({json.dumps(workspace)});
process.stdout.write(target.innerHTML);
"""
    rendered = subprocess.run(
        [node, "-e", script], check=True, capture_output=True, text=True, timeout=15
    ).stdout
    for term in (
        "Source report and result metadata",
        "Reported finding",
        "Normalized representation",
        "External laboratory classification",
        "Human-reviewed query",
        "Evidence ledger",
        "Source statement",
        "Proposed evidence summary",
        "System-generated summary",
        "External interpretation",
        "Requires review",
        "No records returned",
        "Source unavailable",
        "source_reported",
        "normalized",
        "system_generated",
        "human_reviewed",
        "external_decision",
    ):
        assert term in rendered
    for forbidden in (
        "Confirmed diagnosis",
        "Causative variant",
        "Pathogenic according to InSilicoPop",
        "ACMG criteria met",
        "Final classification",
        "Treatment implication",
        "Disease excluded",
    ):
        assert forbidden not in rendered


def test_old_stored_runs_remain_readable_without_result_workspace(tmp_path):
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
                "clinical_case_intake": {
                    "schema_version": "0.27",
                    "intake_completeness": "complete",
                    "policy_blocks": [],
                },
            }
        ),
        encoding="utf-8",
    )
    detail = WorkbenchRunStore(generated_root=tmp_path).run_detail("old-run")
    assert detail.result_evidence_workspace is None
    assert detail.result_intake_count == 0
    assert detail.result_finding_count == 0
    assert detail.evidence_ledger_entry_count == 0
    assert detail.result_evidence_workspace_artifact_available is False


def test_result_workspace_contains_no_secret_or_machine_specific_path(tmp_path):
    result = AgentLoop(generated_root=tmp_path).run(
        query="Synthetic bounded evidence",
        uploads={},
        clinical_case_intake=workspace_payload(),
    )
    artifact = Path(result["reproducibility_bundle"]["path"]) / "result_evidence_workspace.json"
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
