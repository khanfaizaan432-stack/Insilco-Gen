from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from app.insilicopop.agent.loop import AgentLoop
from app.insilicopop.agent.workbench import WorkbenchRunStore
from app.insilicopop.clinical import build_clinical_case_v034_bundle
from app.main import app
from backend.tests.test_specialist_agents_v033 import _candidate_payload
from backend.tests.test_v0311_workbench_dom import _javascript_function


client = TestClient(app)


def _payload() -> dict:
    payload, _ = _candidate_payload()
    payload["jarvis_synthesis_report_workspace"] = {
        "schema_version": "0.34",
        "human_review_required": True,
    }
    return payload


def test_agent_run_writes_report_trace_reproducibility_and_stored_run(tmp_path):
    result = AgentLoop(generated_root=tmp_path).run(
        query="Bounded v0.34 synthesis and report drafting",
        uploads={},
        clinical_case_intake=_payload(),
    )
    run_dir = tmp_path / result["run_id"]
    repro = run_dir / "reproducibility"
    workspace_path = repro / "jarvis_synthesis_report_workspace.json"
    assert workspace_path.is_file()
    workspace = json.loads(workspace_path.read_text(encoding="utf-8"))
    report = (run_dir / "final_report.md").read_text(encoding="utf-8")
    lock = json.loads((repro / "runtime_lock.json").read_text(encoding="utf-8"))
    provenance = json.loads(
        (repro / "provenance_index.json").read_text(encoding="utf-8")
    )
    checksums = (repro / "checksums.sha256").read_text(encoding="utf-8")
    state = json.loads((run_dir / "agent_state.json").read_text(encoding="utf-8"))

    assert workspace["schema_version"] == "0.34"
    assert len(workspace["critic_runs"]) == 6
    assert workspace["report_status"] == "draft_not_clinically_approved"
    assert workspace["critics_mutated_sources"] is False
    assert "## JARVIS Synthesis, Critics, and Report Studio" in report
    assert "draft_not_clinically_approved" in report
    assert "reproducibility/jarvis_synthesis_report_workspace.json" in checksums
    assert provenance["jarvis_synthesis_report_workspace"]["artifact_class"] == (
        "bounded_source_grounded_draft_report_workspace"
    )
    assert lock["jarvis_report_schema_version"] == "0.34"
    assert lock["jarvis_synthesis_claim_ids"]
    assert len(lock["jarvis_critic_run_ids"]) == 6
    assert lock["jarvis_report_section_ids"]
    assert lock["jarvis_external_llm_called"] is False
    assert lock["jarvis_external_tools_executed"] is False
    assert lock["jarvis_critics_mutated_sources"] is False
    assert state["jarvis_synthesis_report_workspace"]["schema_version"] == "0.34"
    assert any(
        item["event"] == "jarvis_synthesis_report_workspace_completed"
        for item in result["agent_trace"]
    )

    detail = WorkbenchRunStore(generated_root=tmp_path).run_detail(result["run_id"])
    assert detail.jarvis_briefing_item_count > 0
    assert detail.synthesis_claim_count > 0
    assert detail.critic_finding_count > 0
    assert detail.draft_report_section_count == 15
    assert detail.jarvis_synthesis_report_workspace_artifact_available is True
    artifact = WorkbenchRunStore(generated_root=tmp_path).read_artifact(
        result["run_id"],
        "reproducibility/jarvis_synthesis_report_workspace.json",
    )
    assert artifact.content["schema_version"] == "0.34"


def test_api_response_exposes_v034_aggregate():
    response = client.post(
        "/insilicopop/agent/run",
        data={
            "query": "Bounded v0.34 aggregate",
            "clinical_case_intake": json.dumps(_payload()),
            "llm_provider": "mock",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["jarvis_synthesis_report_workspace"]["schema_version"] == "0.34"
    detail = client.get(f"/insilicopop/agent/runs/{body['run_id']}").json()
    assert detail["synthesis_claim_count"] > 0
    assert detail["draft_report_section_count"] == 15
    assert detail["jarvis_synthesis_report_workspace_artifact_available"] is True


def test_workbench_dom_renders_briefing_claims_critics_report_and_review_states(
    tmp_path,
):
    node = shutil.which("node")
    assert node is not None, "Node.js is required for the Workbench DOM contract test"
    workspace = build_clinical_case_v034_bundle(_payload())[8].model_dump(
        mode="json"
    )
    ui = client.get("/insilicopop/workbench").text
    functions = "\n".join(
        _javascript_function(ui, name)
        for name in (
            "escapeHtml",
            "notAvailable",
            "asJson",
            "renderJarvisSynthesisReportWorkspace",
        )
    )
    script = f"""
const target = {{className: "", textContent: "", innerHTML: ""}};
globalThis.document = {{getElementById: () => target}};
{functions}
renderJarvisSynthesisReportWorkspace({json.dumps(workspace)});
process.stdout.write(target.innerHTML);
"""
    script_path = tmp_path / "render-jarvis-workspace.js"
    script_path.write_text(script, encoding="utf-8")
    rendered = subprocess.run(
        [node, str(script_path)],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    ).stdout
    for term in (
        "Bounded JARVIS",
        "Current case briefing",
        "Source-grounded scientific synthesis",
        "Non-mutating critic findings",
        "Cited draft report",
        "draft_not_clinically_approved",
        "Claim-to-evidence drill-down",
        "Rejected or stale review attempts",
        "human review required",
        "critics mutated evidence",
    ):
        assert term in rendered
    for forbidden in (
        "Clinically approved: true",
        "critics mutated evidence</strong>true",
        "Autonomous diagnosis",
        "Test ordered",
    ):
        assert forbidden not in rendered


def test_old_stored_runs_remain_readable_without_v034_workspace(tmp_path):
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
    assert detail.jarvis_synthesis_report_workspace is None
    assert detail.synthesis_claim_count == 0
    assert detail.critic_finding_count == 0
    assert detail.jarvis_synthesis_report_workspace_artifact_available is False
