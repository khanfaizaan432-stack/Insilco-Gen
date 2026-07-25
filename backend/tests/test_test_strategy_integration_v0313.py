from __future__ import annotations

import copy
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from app.insilicopop.agent.loop import AgentLoop
from app.insilicopop.agent.workbench import WorkbenchRunStore
from app.insilicopop.clinical import build_clinical_case_strategy_bundle
from app.main import app
from backend.tests.test_test_strategy_workspace_v0313 import strategy_payload
from backend.tests.test_v0311_workbench_dom import _javascript_function


client = TestClient(app)


def test_run_writes_workspace_artifact_report_trace_checksum_provenance_and_lock(tmp_path):
    result = AgentLoop(generated_root=tmp_path).run(
        query="Prepare bounded staged test classes for clinician comparison",
        uploads={},
        clinical_case_intake=strategy_payload(),
    )
    repro = Path(result["reproducibility_bundle"]["path"])
    artifact = repro / "test_strategy_workspace.json"
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    report = Path(result["generated_files"]["final_report"]["absolute_path"]).read_text(encoding="utf-8")
    lock = json.loads((repro / "runtime_lock.json").read_text(encoding="utf-8"))
    provenance = json.loads((repro / "provenance_index.json").read_text(encoding="utf-8"))
    checksums = (repro / "checksums.sha256").read_text(encoding="utf-8")

    assert payload["schema_version"] == "0.31.3"
    assert {item["status"] for item in payload["options"]} == {"proposed_not_approved"}
    assert "## Staged Test-Strategy Workspace" in report
    assert "Every option is proposed, not approved" in report
    assert "test_approved: `false`" in report
    assert "test_order_placed: `false`" in report
    assert "reproducibility/test_strategy_workspace.json" in checksums
    assert provenance["test_strategy_workspace"]["artifact_class"] == "deterministic_proposed_not_approved_test_strategy"
    assert lock["test_strategy_workspace_schema_version"] == "0.31.3"
    assert lock["test_strategy_workspace_algorithm_version"] == "insilicopop-staged-test-strategy-0.31.3"
    assert lock["test_strategy_generated"] is True
    assert lock["test_recommendation_made"] is False
    assert lock["test_order_placed"] is False
    event = next(item for item in result["agent_trace"] if item.get("event") == "staged_test_strategy_workspace_completed")
    assert event["option_statuses"] == ["proposed_not_approved", "proposed_not_approved"]
    assert event["test_approved"] is False
    assert result["external_llm_called"] is False
    assert result["external_tools_executed"] is False


def test_reordered_rule_inputs_produce_identical_strategy_artifact_bytes(tmp_path):
    payload = strategy_payload(mechanism="single_gene")
    extra = copy.deepcopy(payload["test_strategy_workspace"]["rule_inputs"][0])
    extra["rule_input_id"] = "RULE-MDT-2"
    extra["mechanism"] = "multidisciplinary_review"
    extra["rationale_exact"] = "Multidisciplinary comparison requested by the clinical reviewer."
    extra["trigger_facts"][0]["fact_id"] = "FACT-PH-2"
    payload["test_strategy_workspace"]["rule_inputs"].append(extra)
    first = AgentLoop(generated_root=tmp_path).run(query="strategy", uploads={}, clinical_case_intake=payload)
    reordered = copy.deepcopy(payload)
    reordered["test_strategy_workspace"]["rule_inputs"].reverse()
    second = AgentLoop(generated_root=tmp_path).run(query="strategy", uploads={}, clinical_case_intake=reordered)
    first_bytes = (Path(first["reproducibility_bundle"]["path"]) / "test_strategy_workspace.json").read_bytes()
    second_bytes = (Path(second["reproducibility_bundle"]["path"]) / "test_strategy_workspace.json").read_bytes()
    assert first_bytes == second_bytes
    assert hashlib.sha256(first_bytes).hexdigest() == hashlib.sha256(second_bytes).hexdigest()


def test_api_stored_run_allowlisted_artifact_and_workbench_expose_v0313():
    response = client.post(
        "/insilicopop/agent/run",
        data={
            "query": "Prepare proposed test classes",
            "clinical_case_intake": json.dumps(strategy_payload()),
            "llm_provider": "mock",
        },
    )
    assert response.status_code == 200
    body = response.json()
    detail_response = client.get(f"/insilicopop/agent/runs/{body['run_id']}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["test_strategy_workspace_status"] == "proposed_options_for_review"
    assert detail["test_strategy_proposed_option_count"] == 2
    assert detail["test_strategy_constrained_option_count"] == 1
    assert detail["test_strategy_rule_review_item_count"] == 0
    assert detail["test_strategy_workspace_artifact_available"] is True
    assert detail["test_strategy_workspace"]["all_options_proposed_not_approved"] is True
    artifact = client.get(
        f"/insilicopop/agent/runs/{body['run_id']}/artifacts/reproducibility/test_strategy_workspace.json"
    )
    assert artifact.status_code == 200
    assert artifact.json()["content"]["schema_version"] == "0.31.3"
    ui = client.get("/insilicopop/workbench").text
    assert "Staged Test-Strategy Workspace" in ui
    assert "renderTestStrategyWorkspace" in ui
    assert "Clinician comparison only" in ui
    assert "proposed_not_approved" in ui


def test_workbench_dom_renders_comparison_dimensions_and_safety_boundary():
    node = shutil.which("node")
    assert node is not None, "Node.js is required for the Workbench DOM contract test"
    ui = client.get("/insilicopop/workbench").text
    functions = "\n".join(
        _javascript_function(ui, name)
        for name in ("escapeHtml", "notAvailable", "renderTestStrategyWorkspace")
    )
    strategy = build_clinical_case_strategy_bundle(strategy_payload())[5].model_dump(mode="json")
    script = f"""
const target = {{className: "", textContent: "", innerHTML: ""}};
globalThis.document = {{getElementById: () => target}};
{functions}
renderTestStrategyWorkspace({json.dumps(strategy)});
process.stdout.write(target.innerHTML);
"""
    rendered = subprocess.run(
        [node, "-e", script], check=True, capture_output=True, text=True, timeout=15
    ).stdout
    for heading in (
        "Explicit supplied trigger facts",
        "What this class can generally detect",
        "Important blind spots",
        "Proband sample requirements",
        "Family-sample requirements",
        "Supplied availability and cost context",
        "Prerequisites",
        "Reasons to defer",
        "After a negative result",
    ):
        assert heading in rendered
    assert "proposed_not_approved" in rendered
    assert "test approved</strong>false" in rendered
    assert "test ordered</strong>false" in rendered
    assert "claim medical necessity" in rendered


def test_old_stored_runs_remain_readable_without_strategy_workspace(tmp_path):
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
    assert detail.test_strategy_workspace is None
    assert detail.test_strategy_workspace_status is None
    assert detail.test_strategy_proposed_option_count == 0
    assert detail.test_strategy_workspace_artifact_available is False
