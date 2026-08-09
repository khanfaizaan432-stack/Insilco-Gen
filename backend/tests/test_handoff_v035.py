from __future__ import annotations

import json
import hashlib
import re
import shutil
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

import app.main as main_module
from app.insilicopop.agent.loop import AgentLoop
from app.insilicopop.agent.workbench import WorkbenchRunStore
from app.insilicopop.cli import main as cli_main
from app.insilicopop.clinical import (
    apply_handoff_action,
    build_clinical_case_full_bundle,
    build_clinical_case_result_evidence_bundle,
    build_clinical_case_specialist_agent_bundle,
    build_clinical_case_strategy_bundle,
    build_clinical_case_v034_bundle,
    build_clinical_case_v035_bundle,
    run_canonical_handoff_journey,
)
from app.insilicopop.clinical.handoff_models import (
    ExternalHandoffEvent,
    HandoffReviewAction,
    HandoffWorkspaceResult,
)
try:
    from backend.tests.test_v0311_workbench_dom import _javascript_function
except ModuleNotFoundError:
    from tests.test_v0311_workbench_dom import _javascript_function


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = REPO_ROOT / "examples" / "insilicopop_demo" / "canonical_v035_case.json"
EXPECTED_OUTPUT_PATH = (
    REPO_ROOT / "examples" / "insilicopop_demo" / "expected_v035_demo_output.json"
)


def _fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _submit(
    workspace: HandoffWorkspaceResult,
    *,
    action_id: str,
    action: str,
    target_id: str | None = None,
    before_value=None,
    after_value=None,
    resolution_note: str | None = None,
    external_event: ExternalHandoffEvent | None = None,
) -> HandoffWorkspaceResult:
    request = HandoffReviewAction(
        action_id=action_id,
        action=action,
        target_id=target_id,
        reviewer_id="TEST-REVIEWER",
        reviewer_role="synthetic_handoff_reviewer",
        timestamp="deterministic",
        expected_revision=workspace.revision,
        expected_snapshot_hash=workspace.snapshot_hash,
        before_value=before_value,
        after_value=after_value,
        resolution_note=resolution_note,
        external_event=external_event,
        notes="Bounded v0.35 test action.",
    )
    updated, result = apply_handoff_action(workspace, request)
    assert result.result_status.value == "applied", result.message
    return updated


def _assert_receipt_and_packet_sync(workspace: HandoffWorkspaceResult) -> None:
    receipt = workspace.handoff_receipt
    packet = workspace.handoff_packet
    assert receipt.handoff_state == workspace.status
    assert receipt.packet_id == packet.packet_id
    assert receipt.packet_sha256 == packet.packet_sha256
    receipt_payload = receipt.model_dump(mode="json")
    receipt_digest = receipt_payload.copy()
    receipt_digest["receipt_sha256"] = ""
    assert receipt.receipt_sha256 == hashlib.sha256(
        json.dumps(receipt_digest, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()
    packet_payload = packet.model_dump(mode="json")
    packet_digest = packet_payload.copy()
    packet_digest["packet_sha256"] = ""
    assert packet.packet_sha256 == hashlib.sha256(
        json.dumps(packet_digest, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()
    reloaded = HandoffWorkspaceResult.model_validate_json(
        json.dumps(workspace.model_dump(mode="json"), sort_keys=True)
    )
    assert reloaded.handoff_receipt == receipt
    assert reloaded.handoff_packet == packet


def _render_handoff_dom(workspace: HandoffWorkspaceResult, tmp_path: Path) -> str:
    node = shutil.which("node")
    assert node is not None, "Node.js is required for the Workbench DOM contract test"
    ui = TestClient(main_module.app).get("/insilicopop/workbench").text
    functions = "\n".join(
        _javascript_function(ui, name)
        for name in (
            "escapeHtml",
            "handoffStatusClass",
            "handoffDisplay",
            "handoffListValue",
            "renderHandoffStageDetail",
            "renderHandoffWorkspace",
        )
    )
    stage_order = [
        "referral",
        "clinical_history",
        "phenotype_hpo",
        "pedigree_family",
        "previous_investigations",
        "readiness",
        "test_strategy",
        "external_checkpoint",
        "result_intake",
        "qc_assay_scope",
        "candidate_analysis",
        "evidence",
        "candidate_acmg",
        "synthesis_critics",
        "draft_report",
        "human_review",
        "external_handoff",
        "reanalysis",
    ]
    script = f"""
const targets = {{
  "handoff-workspace": {{className: "", textContent: "", innerHTML: ""}},
  "handoff-stage-detail": {{className: "", textContent: "", innerHTML: ""}}
}};
globalThis.document = {{
  getElementById: (id) => targets[id] || null,
  querySelectorAll: () => []
}};
let activeHandoffRunId = null;
let activeHandoffWorkspace = null;
const HANDOFF_STAGE_ORDER = Object.freeze({json.dumps(stage_order)});
{functions}
function handoffControl(action, label, options = {{}}) {{
  const targetSelect = options.targetSelect ? ` data-handoff-target-select="${{escapeHtml(options.targetSelect)}}"` : "";
  const disabled = options.disabled ? " disabled" : "";
  return `<button type="button" data-handoff-action="${{escapeHtml(action)}}"${{targetSelect}}${{disabled}}>${{escapeHtml(label)}}</button>`;
}}
renderHandoffWorkspace({json.dumps(workspace.model_dump(mode="json"))}, "TEST-RUN");
process.stdout.write(targets["handoff-workspace"].innerHTML);
"""
    script_path = tmp_path / "render-handoff-workspace.js"
    script_path.write_text(script, encoding="utf-8")
    return subprocess.run(
        [node, str(script_path)],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    ).stdout


def test_v035_adds_width_ten_without_changing_frozen_legacy_widths():
    payload = _fixture()
    assert len(build_clinical_case_full_bundle(payload)) == 5
    assert len(build_clinical_case_strategy_bundle(payload)) == 6
    assert len(build_clinical_case_result_evidence_bundle(payload)) == 7
    assert len(build_clinical_case_specialist_agent_bundle(payload)) == 8
    assert len(build_clinical_case_v034_bundle(payload)) == 9

    bundle = build_clinical_case_v035_bundle(payload)
    assert len(bundle) == 10
    assert bundle[8].schema_version == "0.34"
    assert bundle[9].schema_version == "0.35"
    assert bundle[9].handoff_state.value == "assembled"


def test_canonical_fixture_and_cli_summary_are_deterministic(capsys):
    first = build_clinical_case_v035_bundle(_fixture())[9]
    second = build_clinical_case_v035_bundle(_fixture())[9]
    assert first is not None and second is not None
    assert first.model_dump(mode="json") == second.model_dump(mode="json")

    assert cli_main(["v035-demo", "--fixture", str(FIXTURE_PATH)]) == 0
    actual = json.loads(capsys.readouterr().out)
    expected = json.loads(EXPECTED_OUTPUT_PATH.read_text(encoding="utf-8"))
    assert actual == expected


def test_handoff_snapshot_exposes_frozen_stage_manifest_and_safety_boundary():
    workspace = build_clinical_case_v035_bundle(_fixture())[9]
    assert workspace is not None
    assert [stage.stage_id for stage in workspace.case_stages] == [
        "referral",
        "clinical_history",
        "phenotype_hpo",
        "pedigree_family",
        "previous_investigations",
        "readiness",
        "test_strategy",
        "external_checkpoint",
        "result_intake",
        "qc_assay_scope",
        "candidate_analysis",
        "evidence",
        "candidate_acmg",
        "synthesis_critics",
        "draft_report",
        "human_review",
        "external_handoff",
        "reanalysis",
    ]
    assert len(workspace.artifact_manifest) == 9
    assert len(workspace.handoff_packet.artifact_manifest) == 9
    assert workspace.report_status == "draft_not_clinically_approved"
    assert workspace.human_review_required is True
    assert workspace.research_use_only is True
    assert workspace.clinical_approval_granted is False
    assert workspace.external_llm_called is False
    assert workspace.external_tools_executed is False


def test_v035_preserves_clinical_safety_blocks_and_rejects_direct_identifiers():
    payload = _fixture()
    payload["requested_actions"] = [
        "diagnosis",
        "recommend treatment",
        "assign final ACMG classification",
    ]
    bundle = build_clinical_case_v035_bundle(payload)
    assert bundle[0].intake_completeness == "blocked"
    assert {
        "diagnosis_request",
        "treatment_request",
        "final_classification_request",
    } <= {item.code for item in bundle[0].policy_blocks}
    assert bundle[9] is not None
    assert any(item.code == "diagnosis_request" for item in bundle[9].blockers)
    assert bundle[9].diagnosis_made is False
    assert bundle[9].treatment_recommendation_made is False
    assert bundle[9].final_acmg_classification_made is False

    safety_blocker = next(item for item in bundle[9].blockers if item.code == "diagnosis_request")
    reviewed = _submit(bundle[9], action_id="SAFETY-START-REVIEW", action="start_human_review")
    safety_action = HandoffReviewAction(
        action_id="SAFETY-RESOLVE-DIAGNOSIS",
        action="resolve_blocker",
        target_id=safety_blocker.blocker_id,
        reviewer_id="TEST-REVIEWER",
        reviewer_role="synthetic_handoff_reviewer",
        timestamp="deterministic",
        expected_revision=reviewed.revision,
        expected_snapshot_hash=reviewed.snapshot_hash,
        before_value="open",
        after_value="Human reviewer noted the prohibited request.",
        resolution_note="Human reviewer noted the prohibited request.",
    )
    _, safety_result = apply_handoff_action(reviewed, safety_action)
    assert safety_result.result_status.value == "rejected"
    assert safety_result.rejection_reason.value == "safety_boundary"

    with pytest.raises(ValueError, match="reviewer_id"):
        HandoffReviewAction(
            action_id="DIRECT-ID-ACTION",
            action="start_human_review",
            reviewer_id="reviewer@example.org",
            reviewer_role="clinical_research_reviewer",
        )


def test_handoff_actions_reject_stale_and_terminal_mutations_atomically():
    workspace = build_clinical_case_v035_bundle(_fixture())[9]
    assert workspace is not None

    start = HandoffReviewAction(
        action_id="REVIEW-START-1",
        action="start_human_review",
        reviewer_id="reviewer-1",
        reviewer_role="clinical_research_reviewer",
        expected_revision=workspace.revision,
        expected_snapshot_hash=workspace.snapshot_hash,
        notes="Begin bounded human review.",
    )
    reviewed, start_result = apply_handoff_action(workspace, start)
    assert start_result.result_status.value == "applied"
    assert reviewed.status.value == "under_human_review"
    assert reviewed.revision == 1

    stale = HandoffReviewAction(
        action_id="REVIEW-DEFER-STALE",
        action="defer",
        reviewer_id="reviewer-1",
        reviewer_role="clinical_research_reviewer",
        expected_revision=workspace.revision,
        expected_snapshot_hash=workspace.snapshot_hash,
    )
    after_stale, stale_result = apply_handoff_action(reviewed, stale)
    assert stale_result.result_status.value == "rejected"
    assert stale_result.rejection_reason.value == "stale_state"
    assert after_stale.status.value == "under_human_review"
    assert after_stale.revision == 2

    withdraw = HandoffReviewAction(
        action_id="REVIEW-WITHDRAW-1",
        action="withdraw",
        reviewer_id="reviewer-1",
        reviewer_role="clinical_research_reviewer",
        expected_revision=after_stale.revision,
        expected_snapshot_hash=after_stale.snapshot_hash,
        notes="Withdraw the draft handoff from review.",
    )
    withdrawn, withdraw_result = apply_handoff_action(after_stale, withdraw)
    assert withdraw_result.result_status.value == "applied"
    assert withdrawn.status.value == "withdrawn"

    terminal_attempt = HandoffReviewAction(
        action_id="REVIEW-START-TERMINAL",
        action="start_human_review",
        reviewer_id="reviewer-1",
        reviewer_role="clinical_research_reviewer",
        expected_revision=withdrawn.revision,
        expected_snapshot_hash=withdrawn.snapshot_hash,
    )
    terminal, terminal_result = apply_handoff_action(withdrawn, terminal_attempt)
    assert terminal_result.result_status.value == "rejected"
    assert terminal_result.rejection_reason.value == "terminal_state"
    assert terminal.status.value == "withdrawn"
    assert terminal.revision == withdrawn.revision + 1


def test_workbench_persists_handoff_actions_and_exposes_api_contract(tmp_path, monkeypatch):
    result = AgentLoop(generated_root=tmp_path).run(
        query="Run the canonical v0.35 structured handoff demonstration.",
        uploads={},
        clinical_case_intake=_fixture(),
    )
    run_id = result["run_id"]
    store = WorkbenchRunStore(generated_root=tmp_path)
    initial = store.handoff_workspace(run_id)
    action = HandoffReviewAction(
        action_id="API-REVIEW-START-1",
        action="start_human_review",
        reviewer_id="reviewer-1",
        reviewer_role="clinical_research_reviewer",
        expected_revision=initial.revision,
        expected_snapshot_hash=initial.snapshot_hash,
    )
    persisted = store.apply_handoff_action(run_id, action)
    assert persisted.action_result.result_status.value == "applied"
    assert persisted.handoff_workspace.status.value == "under_human_review"
    assert store.run_detail(run_id).handoff_state == "under_human_review"
    assert store.run_detail(run_id).handoff_revision == 1
    repro_dir = tmp_path / run_id / "reproducibility"
    for name in ("handoff_workspace.json", "handoff_packet.json", "handoff_receipt.json"):
        assert (repro_dir / name).is_file()
    checksums = (repro_dir / "checksums.sha256").read_text(encoding="utf-8")
    assert "reproducibility/handoff_workspace.json" in checksums
    assert "reproducibility/handoff_packet.json" in checksums
    assert "reproducibility/handoff_receipt.json" in checksums

    monkeypatch.setattr(main_module, "WorkbenchRunStore", lambda: WorkbenchRunStore(tmp_path))
    client = TestClient(main_module.app)
    handoff_response = client.get(f"/insilicopop/agent/runs/{run_id}/handoff")
    assert handoff_response.status_code == 200
    assert handoff_response.json()["status"] == "under_human_review"
    post_response = client.post(
        f"/insilicopop/agent/runs/{run_id}/handoff/actions",
        json={
            "action_id": "API-WITHDRAW-1",
            "action": "withdraw",
            "reviewer_id": "reviewer-1",
            "reviewer_role": "clinical_research_reviewer",
            "expected_revision": 1,
            "expected_snapshot_hash": persisted.handoff_workspace.snapshot_hash,
            "notes": "Withdraw the bounded draft after review.",
        },
    )
    assert post_response.status_code == 200
    assert post_response.json()["action_result"]["result_status"] == "applied"
    assert post_response.json()["handoff_workspace"]["status"] == "withdrawn"
    detail_response = client.get(f"/insilicopop/agent/runs/{run_id}")
    assert detail_response.status_code == 200
    assert detail_response.json()["handoff_workspace"]["status"] == "withdrawn"


def test_receipt_state_syncs_after_every_valid_action_and_survives_reconstruction():
    workspace = build_clinical_case_v035_bundle(_fixture())[9]
    assert workspace is not None
    packet_id = workspace.handoff_packet.packet_id
    packet_sha256 = workspace.handoff_packet.packet_sha256
    _assert_receipt_and_packet_sync(workspace)
    assert workspace.handoff_receipt.receipt_status.value == "not_issued"

    workspace = _submit(workspace, action_id="SYNC-START", action="start_human_review")
    _assert_receipt_and_packet_sync(workspace)
    for uncertainty in list(workspace.acknowledgement_required_uncertainties):
        workspace = _submit(
            workspace,
            action_id=f"SYNC-ACK-{uncertainty.uncertainty_id}",
            action="acknowledge_uncertainty",
            target_id=uncertainty.uncertainty_id,
            before_value=False,
        )
        _assert_receipt_and_packet_sync(workspace)
    for decision in list(workspace.pending_human_decisions):
        note = "Human reviewer recorded a bounded disposition; no clinical approval or final classification was made."
        workspace = _submit(
            workspace,
            action_id=f"SYNC-DECISION-{decision.decision_id}",
            action="resolve_pending_decision",
            target_id=decision.decision_id,
            before_value="pending",
            after_value=note,
            resolution_note=note,
        )
        _assert_receipt_and_packet_sync(workspace)
    for blocker in list(workspace.blockers):
        note = "Human reviewer confirmed the supplied wording is bounded context; no identity inference, diagnosis, treatment, test order, or final classification was made."
        workspace = _submit(
            workspace,
            action_id=f"SYNC-BLOCKER-{blocker.blocker_id}",
            action="resolve_blocker",
            target_id=blocker.blocker_id,
            before_value="open",
            after_value=note,
            resolution_note=note,
        )
        _assert_receipt_and_packet_sync(workspace)
    workspace = _submit(workspace, action_id="SYNC-READY", action="mark_ready_for_external_handoff")
    _assert_receipt_and_packet_sync(workspace)
    assert workspace.status.value == "ready_for_external_handoff"
    assert workspace.handoff_receipt.receipt_status.value == "not_issued"
    event = ExternalHandoffEvent(
        event_id="SYNC-EVENT",
        event_type="handoff_sent",
        timestamp="deterministic",
        reviewer_id="TEST-REVIEWER",
        reviewer_role="synthetic_handoff_reviewer",
        external_reference="SYNC-EXTERNAL",
        packet_sha256=workspace.handoff_packet.packet_sha256,
        notes="Synthetic bounded handoff event.",
    )
    workspace = _submit(
        workspace,
        action_id="SYNC-EXTERNAL",
        action="record_external_handoff",
        external_event=event,
    )
    _assert_receipt_and_packet_sync(workspace)
    assert workspace.handoff_receipt.receipt_status.value == "issued"
    assert workspace.handoff_receipt.external_event_id == "SYNC-EVENT"
    assert workspace.handoff_packet.packet_id == packet_id
    assert workspace.handoff_packet.packet_sha256 == packet_sha256
    assert workspace.audit_history[-1].event_type.value == "handoff_sent"


def test_manifest_hashes_match_exact_persisted_bytes_and_clean_reconstruction(tmp_path):
    result = AgentLoop(generated_root=tmp_path).run(
        query="Run the canonical v0.35 structured handoff demonstration.",
        uploads={},
        clinical_case_intake=_fixture(),
    )
    run_id = result["run_id"]
    run_dir = tmp_path / run_id
    workspace = WorkbenchRunStore(generated_root=tmp_path).handoff_workspace(run_id)
    manifest_hashes = {}
    for item in workspace.artifact_manifest:
        path = run_dir / item.artifact_name
        if item.available:
            assert path.is_file(), item.artifact_name
            file_bytes = path.read_bytes()
            assert hashlib.sha256(file_bytes).hexdigest() == item.sha256
            payload = json.loads(file_bytes.decode("utf-8"))
            canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
            assert hashlib.sha256(canonical).hexdigest() == item.canonical_payload_sha256
            manifest_hashes[item.artifact_name] = item.sha256
        else:
            assert item.sha256 is None
            assert item.digest_scope == "not_available"
            assert not path.exists()
    checksums = {}
    for line in (run_dir / "reproducibility" / "checksums.sha256").read_text(encoding="utf-8").splitlines():
        if "  " in line:
            digest, path = line.split("  ", 1)
            checksums[path] = digest
    assert all(checksums[path] == digest for path, digest in manifest_hashes.items())
    packet_payload = json.loads((run_dir / "reproducibility" / "handoff_packet.json").read_text(encoding="utf-8"))
    receipt_payload = json.loads((run_dir / "reproducibility" / "handoff_receipt.json").read_text(encoding="utf-8"))
    assert packet_payload["artifact_manifest"] == [item.model_dump(mode="json") for item in workspace.artifact_manifest]
    assert receipt_payload == workspace.handoff_receipt.model_dump(mode="json")
    reconstructed = HandoffWorkspaceResult.model_validate_json(
        (run_dir / "reproducibility" / "handoff_workspace.json").read_text(encoding="utf-8")
    )
    assert reconstructed == workspace
    provenance = json.loads((run_dir / "reproducibility" / "provenance_index.json").read_text(encoding="utf-8"))
    assert provenance["handoff_workspace"]["handoff_state"] == "assembled"
    assert provenance["handoff_packet"]["current_handoff_state"] == "assembled"


def test_uncertainty_acknowledgement_is_review_only_and_rejected_attempt_is_audited():
    workspace = build_clinical_case_v035_bundle(_fixture())[9]
    assert workspace is not None
    uncertainty_id = workspace.acknowledgement_required_uncertainties[0].uncertainty_id
    action = HandoffReviewAction(
        action_id="ACK-BEFORE-REVIEW",
        action="acknowledge_uncertainty",
        target_id=uncertainty_id,
        reviewer_id="TEST-REVIEWER",
        reviewer_role="synthetic_handoff_reviewer",
        timestamp="deterministic",
        expected_revision=workspace.revision,
        expected_snapshot_hash=workspace.snapshot_hash,
        before_value=False,
    )
    rejected, result = apply_handoff_action(workspace, action)
    assert result.result_status.value == "rejected"
    assert result.rejection_reason.value == "invalid_transition"
    assert rejected.status.value == "assembled"
    assert rejected.acknowledgement_required_uncertainties[0].acknowledged is False
    assert rejected.handoff_receipt.handoff_state.value == "assembled"
    assert rejected.audit_history[-1].event_type.value == "action_rejected"

    reviewed = _submit(rejected, action_id="ACK-START-REVIEW", action="start_human_review")
    acknowledged = _submit(
        reviewed,
        action_id="ACK-DURING-REVIEW",
        action="acknowledge_uncertainty",
        target_id=uncertainty_id,
        before_value=False,
    )
    assert acknowledged.acknowledgement_required_uncertainties[0].acknowledged is True
    assert acknowledged.handoff_receipt.handoff_state.value == "under_human_review"


def test_canonical_journey_reaches_external_handoff_without_clinical_approval():
    workspace = build_clinical_case_v035_bundle(_fixture())[9]
    assert workspace is not None
    final = run_canonical_handoff_journey(workspace)
    assert final.status.value == "externally_handed_off"
    assert final.review_readiness.ready_for_external_handoff is True
    assert final.review_readiness.open_blocker_count == 0
    assert final.review_readiness.unacknowledged_uncertainty_count == 0
    assert final.review_readiness.pending_human_decision_count == 0
    assert final.review_readiness.blocking_critic_count == 0
    assert final.handoff_receipt.receipt_status.value == "issued"
    assert final.handoff_receipt.handoff_state.value == "externally_handed_off"
    assert final.external_handoff_events[-1].event_id == "CANONICAL-HANDOFF-EVENT"
    ready_index = next(index for index, item in enumerate(final.audit_history) if item.event_type.value == "ready_for_external_handoff")
    sent_index = next(index for index, item in enumerate(final.audit_history) if item.event_type.value == "handoff_sent")
    assert ready_index < sent_index
    assert final.report_status == "draft_not_clinically_approved"
    assert final.clinical_approval_granted is False
    assert final.diagnosis_made is False
    assert final.treatment_recommendation_made is False
    assert final.final_acmg_classification_made is False
    assert final.external_tools_executed is False
    assert final.unrestricted_browsing_used is False


def test_workbench_dom_renders_v035_readiness_actions_states_and_integrity(tmp_path):
    initial = build_clinical_case_v035_bundle(_fixture())[9]
    assert initial is not None
    initial_html = _render_handoff_dom(initial, tmp_path)
    assert "18-stage case navigator" in initial_html
    assert "blocked" in initial_html
    assert "awaiting_human_input" in initial_html
    assert "draft_not_clinically_approved" in initial_html
    assert "Audit history" in initial_html
    assert "data-handoff-action=\"acknowledge_uncertainty\" data-handoff-target-select=\"handoff-uncertainty-target\" disabled" in initial_html

    reviewed = _submit(initial, action_id="DOM-START", action="start_human_review")
    reviewed_html = _render_handoff_dom(reviewed, tmp_path)
    assert "incomplete" in reviewed_html
    assert "data-handoff-action=\"acknowledge_uncertainty\" data-handoff-target-select=\"handoff-uncertainty-target\" disabled" not in reviewed_html
    assert "data-handoff-action=\"resolve_blocker\"" in reviewed_html
    assert "digest_scope" in reviewed_html or "Digest scope" in reviewed_html

    stale_action = HandoffReviewAction(
        action_id="DOM-STALE",
        action="defer",
        reviewer_id="TEST-REVIEWER",
        reviewer_role="synthetic_handoff_reviewer",
        timestamp="deterministic",
        expected_revision=initial.revision,
        expected_snapshot_hash=initial.snapshot_hash,
    )
    stale_workspace, stale_result = apply_handoff_action(reviewed, stale_action)
    assert stale_result.result_status.value == "rejected"
    stale_html = _render_handoff_dom(stale_workspace, tmp_path)
    assert "stale_state" in stale_html
    withdrawn = _submit(stale_workspace, action_id="DOM-WITHDRAW", action="withdraw")
    withdrawn_html = _render_handoff_dom(withdrawn, tmp_path)
    assert "withdrawn" in withdrawn_html
    assert "historical" in withdrawn_html
    assert "data-handoff-action=\"start_human_review\" disabled" in withdrawn_html

    final = run_canonical_handoff_journey(initial)
    final_html = _render_handoff_dom(final, tmp_path)
    assert "externally_handed_off" in final_html
    assert "receipt_status:</strong> issued" in final_html
    assert "CANONICAL-HANDOFF-EVENT" in final_html
    assert "completed_for_draft_use" in final_html
    assert "clinical_approval_granted</strong>false" in final_html
