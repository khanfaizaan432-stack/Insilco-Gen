from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from app.insilicopop.clinical.handoff_models import (
    CaseStage,
    CaseStageStatus,
    ExternalCheckpoint,
    ExternalHandoffEvent,
    HandoffActionResultStatus,
    HandoffActionType,
    HandoffArtifactManifestItem,
    HandoffAuditEvent,
    HandoffBlocker,
    HandoffClaimPointer,
    HandoffEvidencePointer,
    HandoffEventType,
    HandoffPacket,
    HandoffReceipt,
    HandoffReceiptStatus,
    HandoffRejectionReason,
    HandoffReviewAction,
    HandoffReviewActionResult,
    HandoffState,
    HandoffUncertainty,
    HandoffWorkspaceRequest,
    HandoffWorkspaceResult,
    PendingHumanDecision,
    ReviewReadiness,
    ReviewerReference,
    SourceClassification,
)


STAGE_DEFINITIONS: tuple[tuple[str, str], ...] = (
    ("referral", "Referral"),
    ("clinical_history", "Clinical history"),
    ("phenotype_hpo", "Phenotype/HPO"),
    ("pedigree_family", "Pedigree/family"),
    ("previous_investigations", "Previous investigations"),
    ("readiness", "Readiness"),
    ("test_strategy", "Test strategy"),
    ("external_checkpoint", "External checkpoint"),
    ("result_intake", "Result intake"),
    ("qc_assay_scope", "QC/assay scope"),
    ("candidate_analysis", "Candidate analysis"),
    ("evidence", "Evidence"),
    ("candidate_acmg", "Candidate ACMG evidence"),
    ("synthesis_critics", "Synthesis/critics"),
    ("draft_report", "Draft report"),
    ("human_review", "Human review"),
    ("external_handoff", "External handoff"),
    ("reanalysis", "Reanalysis"),
)

_TERMINAL_STATES = {
    HandoffState.EXTERNALLY_HANDED_OFF,
    HandoffState.DEFERRED,
    HandoffState.WITHDRAWN,
}

_ALLOWED_TRANSITIONS: dict[HandoffState, set[HandoffState]] = {
    HandoffState.ASSEMBLED: {
        HandoffState.UNDER_HUMAN_REVIEW,
        HandoffState.DEFERRED,
        HandoffState.WITHDRAWN,
    },
    HandoffState.UNDER_HUMAN_REVIEW: {
        HandoffState.READY_FOR_EXTERNAL_HANDOFF,
        HandoffState.DEFERRED,
        HandoffState.WITHDRAWN,
    },
    HandoffState.READY_FOR_EXTERNAL_HANDOFF: {
        HandoffState.EXTERNALLY_HANDED_OFF,
        HandoffState.DEFERRED,
        HandoffState.WITHDRAWN,
    },
    HandoffState.EXTERNALLY_HANDED_OFF: set(),
    HandoffState.DEFERRED: set(),
    HandoffState.WITHDRAWN: set(),
}


def build_handoff_workspace(
    case: Any,
    *,
    intake: Any,
    phenotype_curation: Any,
    pedigree_audit: Any,
    variant_intelligence: Any,
    pretest_assessment: Any,
    test_strategy_workspace: Any,
    result_evidence_workspace: Any,
    specialist_agent_workspace: Any,
    jarvis_workspace: Any,
    handoff_request: HandoffWorkspaceRequest | None = None,
    result_gateway: Any = None,
) -> HandoffWorkspaceResult:
    """Build the deterministic v0.35 handoff over the frozen v0.34 artifacts."""

    handoff_request = handoff_request or HandoffWorkspaceRequest()
    artifact_items = [
            ("clinical_case_intake", intake, "clinical_case_intake.json", SourceClassification.SUPPLIED_FACT),
            ("phenotype_hpo_curation", phenotype_curation, "phenotype_hpo_curation.json", SourceClassification.DETERMINISTIC_FINDING),
            ("pedigree_inheritance_audit", pedigree_audit, "pedigree_inheritance_audit.json", SourceClassification.DETERMINISTIC_FINDING),
            ("variant_intelligence", variant_intelligence, "variant_intelligence.json", SourceClassification.NORMALIZED_FACT),
            ("pre_test_assessment", pretest_assessment, "pre_test_assessment.json", SourceClassification.DETERMINISTIC_FINDING),
            ("test_strategy_workspace", test_strategy_workspace, "test_strategy_workspace.json", SourceClassification.MODEL_OR_SPECIALIST_PROPOSAL),
            ("result_evidence_workspace", result_evidence_workspace, "result_evidence_workspace.json", SourceClassification.RETRIEVED_EVIDENCE),
            ("specialist_agent_workspace", specialist_agent_workspace, "specialist_agent_workspace.json", SourceClassification.MODEL_OR_SPECIALIST_PROPOSAL),
            ("jarvis_synthesis_report_workspace", jarvis_workspace, "jarvis_synthesis_report_workspace.json", SourceClassification.CANDIDATE_INTERPRETATION),
        ]
    artifacts = _artifact_manifest(artifact_items)
    source_hashes = {
        item.artifact_id: item.sha256
        for item in artifacts
        if item.available and item.sha256 is not None
    }
    schema_versions = {item.artifact_id: item.schema_version for item in artifacts}
    claim_pointers, evidence_pointers = _pointers(
        jarvis_workspace=jarvis_workspace,
        result_evidence_workspace=result_evidence_workspace,
    )
    blockers = _blockers(
        intake=intake,
        pretest_assessment=pretest_assessment,
        jarvis_workspace=jarvis_workspace,
        result_gateway=result_gateway,
    )
    uncertainties = _uncertainties(
        jarvis_workspace=jarvis_workspace,
        result_evidence_workspace=result_evidence_workspace,
    )
    pending_decisions = _pending_decisions(jarvis_workspace)
    readiness = _review_readiness(blockers, uncertainties, pending_decisions, jarvis_workspace, result_evidence_workspace)
    stages = _case_stages(
        case=case,
        intake=intake,
        phenotype_curation=phenotype_curation,
        pedigree_audit=pedigree_audit,
        pretest_assessment=pretest_assessment,
        test_strategy_workspace=test_strategy_workspace,
        result_evidence_workspace=result_evidence_workspace,
        result_gateway=result_gateway,
        specialist_agent_workspace=specialist_agent_workspace,
        jarvis_workspace=jarvis_workspace,
        external_checkpoint=handoff_request.external_checkpoint,
        blockers=blockers,
        pending_decisions=pending_decisions,
        status=HandoffState.ASSEMBLED,
        readiness=readiness,
    )

    packet = _make_packet(
        case_id=str(case.pseudonymous_case_id),
        artifacts=artifacts,
        source_hashes=source_hashes,
        schema_versions=schema_versions,
        claim_pointers=claim_pointers,
        evidence_pointers=evidence_pointers,
    )
    receipt = _make_receipt(packet=packet, status=HandoffState.ASSEMBLED)
    audit = HandoffAuditEvent(
        audit_id="HANDOFF-AUDIT-0000",
        event_type=HandoffEventType.ASSEMBLED,
        timestamp="deterministic",
        from_status=HandoffState.ASSEMBLED,
        to_status=HandoffState.ASSEMBLED,
        revision=0,
        message="Deterministic v0.35 handoff workspace assembled from the frozen v0.34 artifacts.",
    )
    workspace = HandoffWorkspaceResult(
        pseudonymous_case_id=str(case.pseudonymous_case_id),
        status=HandoffState.ASSEMBLED,
        revision=0,
        snapshot_hash="0" * 64,
        case_stages=stages,
        review_readiness=readiness,
        blockers=blockers,
        acknowledgement_required_uncertainties=uncertainties,
        pending_human_decisions=pending_decisions,
        reviewer_references=list(handoff_request.reviewer_references),
        external_handoff_events=[],
        requested_review_actions=[],
        applied_review_actions=[],
        review_action_results=[],
        audit_history=[audit],
        artifact_manifest=artifacts,
        source_hashes=source_hashes,
        schema_versions=schema_versions,
        claim_pointers=claim_pointers,
        evidence_pointers=evidence_pointers,
        handoff_packet=packet,
        handoff_receipt=receipt,
    )
    return _finalize(workspace)


def apply_handoff_action(
    workspace: HandoffWorkspaceResult,
    action: HandoffReviewAction,
) -> tuple[HandoffWorkspaceResult, HandoffReviewActionResult]:
    """Apply one typed human handoff action, recording rejected attempts safely."""

    old_status = workspace.status
    failure: HandoffRejectionReason | None = None
    message = ""
    if workspace.status in _TERMINAL_STATES:
        failure = HandoffRejectionReason.TERMINAL_STATE
        message = "The handoff is terminal; no further state mutation is permitted."
    elif action.expected_revision is not None and action.expected_revision != workspace.revision:
        failure = HandoffRejectionReason.STALE_STATE
        message = "The requested revision is stale; reload the handoff workspace before retrying."
    elif action.expected_snapshot_hash is not None and action.expected_snapshot_hash != workspace.snapshot_hash:
        failure = HandoffRejectionReason.STALE_STATE
        message = "The requested snapshot hash is stale; reload the handoff workspace before retrying."
    elif action.action_id in {item.action_id for item in workspace.requested_review_actions}:
        failure = HandoffRejectionReason.INVALID_ACTION
        message = "The handoff action identifier has already been recorded. Submit a new action identifier."

    if failure is None:
        try:
            candidate, event_type, message = _apply_action(workspace, action)
        except _Rejected as exc:
            failure = exc.reason
            message = exc.message
        else:
            return _record_action_result(
                workspace=candidate,
                action=action,
                old_status=old_status,
                event_type=event_type,
                result_status=HandoffActionResultStatus.APPLIED,
                rejection_reason=None,
                message=message,
            )

    candidate = _record_rejected_attempt(workspace, action, old_status, failure, message)
    return _record_action_result(
        workspace=candidate,
        action=action,
        old_status=old_status,
        event_type=HandoffEventType.ACTION_REJECTED,
        result_status=HandoffActionResultStatus.REJECTED,
        rejection_reason=failure or HandoffRejectionReason.INVALID_ACTION,
        message=message or "The handoff action was rejected.",
    )


def run_canonical_handoff_journey(workspace: HandoffWorkspaceResult) -> HandoffWorkspaceResult:
    """Run the deterministic synthetic v0.35 journey through the public action contract."""

    reviewer_id = "CANONICAL-REVIEWER"
    reviewer_role = "synthetic_handoff_reviewer"

    def submit(
        current: HandoffWorkspaceResult,
        *,
        action_id: str,
        action_type: HandoffActionType,
        target_id: str | None = None,
        before_value: Any = None,
        after_value: Any = None,
        resolution_note: str | None = None,
        external_event: ExternalHandoffEvent | None = None,
    ) -> HandoffWorkspaceResult:
        action = HandoffReviewAction(
            action_id=action_id,
            action=action_type,
            target_id=target_id,
            reviewer_id=reviewer_id,
            reviewer_role=reviewer_role,
            timestamp="deterministic",
            expected_revision=current.revision,
            expected_snapshot_hash=current.snapshot_hash,
            before_value=before_value,
            after_value=after_value,
            resolution_note=resolution_note,
            external_event=external_event,
            notes="Canonical synthetic journey; bounded human review action.",
        )
        updated, result = apply_handoff_action(current, action)
        if result.result_status != HandoffActionResultStatus.APPLIED:
            raise ValueError(f"Canonical v0.35 journey action was rejected: {result.message}")
        return updated

    current = submit(
        workspace,
        action_id="CANONICAL-REVIEW-START",
        action_type=HandoffActionType.START_HUMAN_REVIEW,
    )
    for uncertainty in current.acknowledgement_required_uncertainties:
        current = submit(
            current,
            action_id=f"CANONICAL-ACK-{_identifier(uncertainty.uncertainty_id)}",
            action_type=HandoffActionType.ACKNOWLEDGE_UNCERTAINTY,
            target_id=uncertainty.uncertainty_id,
            before_value=False,
        )
    for decision in current.pending_human_decisions:
        current = submit(
            current,
            action_id=f"CANONICAL-DECISION-{_identifier(decision.decision_id)}",
            action_type=HandoffActionType.RESOLVE_PENDING_DECISION,
            target_id=decision.decision_id,
            before_value="pending",
            after_value="Human reviewer recorded a bounded disposition for this draft review question; no clinical approval or final classification was made.",
            resolution_note="Human reviewer recorded a bounded disposition for this draft review question; no clinical approval or final classification was made.",
        )
    for blocker in current.blockers:
        current = submit(
            current,
            action_id=f"CANONICAL-BLOCKER-{_identifier(blocker.blocker_id)}",
            action_type=HandoffActionType.RESOLVE_BLOCKER,
            target_id=blocker.blocker_id,
            before_value="open",
            after_value="Human reviewer confirmed the supplied wording is descriptive context only; no identity, paternity, inheritance, diagnosis, treatment, test order, or final classification was inferred.",
            resolution_note="Human reviewer confirmed the supplied wording is descriptive context only; no identity, paternity, inheritance, diagnosis, treatment, test order, or final classification was inferred.",
        )
    current = submit(
        current,
        action_id="CANONICAL-MARK-READY",
        action_type=HandoffActionType.MARK_READY_FOR_EXTERNAL_HANDOFF,
    )
    event = ExternalHandoffEvent(
        event_id="CANONICAL-HANDOFF-EVENT",
        event_type="handoff_sent",
        timestamp="deterministic",
        reviewer_id=reviewer_id,
        reviewer_role=reviewer_role,
        external_reference="CANONICAL-EXTERNAL-REFERENCE",
        packet_sha256=current.handoff_packet.packet_sha256,
        notes="Synthetic handoff event recorded for deterministic demonstration; not clinical approval.",
    )
    return submit(
        current,
        action_id="CANONICAL-RECORD-HANDOFF",
        action_type=HandoffActionType.RECORD_EXTERNAL_HANDOFF,
        external_event=event,
    )


class _Rejected(Exception):
    def __init__(self, reason: HandoffRejectionReason, message: str) -> None:
        self.reason = reason
        self.message = message
        super().__init__(message)


def _apply_action(
    workspace: HandoffWorkspaceResult,
    action: HandoffReviewAction,
) -> tuple[HandoffWorkspaceResult, HandoffEventType, str]:
    status = workspace.status
    next_status = status
    event_type = HandoffEventType.REVIEW_STARTED
    message = "Handoff review action applied."
    updates: dict[str, Any] = {}
    external_event: ExternalHandoffEvent | None = None

    if action.action in {HandoffActionType.START_HUMAN_REVIEW, HandoffActionType.BEGIN_HUMAN_REVIEW}:
        _require_transition(status, HandoffState.UNDER_HUMAN_REVIEW)
        next_status = HandoffState.UNDER_HUMAN_REVIEW
        event_type = HandoffEventType.REVIEW_STARTED
        message = "Human review has started; the result remains a draft."
    elif action.action == HandoffActionType.ACKNOWLEDGE_UNCERTAINTY:
        _require_human_review(status)
        _require_target(action)
        target_index = _find_uncertainty(workspace, action.target_id or "")
        if target_index is None:
            raise _Rejected(HandoffRejectionReason.TARGET_NOT_FOUND, "The uncertainty target was not found.")
        target = workspace.acknowledgement_required_uncertainties[target_index]
        if target.acknowledged:
            raise _Rejected(HandoffRejectionReason.TARGET_ALREADY_RESOLVED, "The uncertainty is already acknowledged.")
        if action.before_value is not None and action.before_value is not False:
            raise _Rejected(HandoffRejectionReason.BEFORE_VALUE_MISMATCH, "The uncertainty acknowledgement state is stale.")
        reviewer = ReviewerReference(reviewer_id=action.reviewer_id, reviewer_role=action.reviewer_role)
        updated = target.model_copy(
            update={
                "acknowledged": True,
                "acknowledged_by": reviewer,
                "acknowledged_action_id": action.action_id,
            }
        )
        uncertainties = list(workspace.acknowledgement_required_uncertainties)
        uncertainties[target_index] = updated
        updates["acknowledgement_required_uncertainties"] = uncertainties
        event_type = HandoffEventType.UNCERTAINTY_ACKNOWLEDGED
        message = "The uncertainty was acknowledged by the pseudonymous reviewer."
    elif action.action == HandoffActionType.RESOLVE_PENDING_DECISION:
        _require_target(action)
        target_index = _find_decision(workspace, action.target_id or "")
        if target_index is None:
            raise _Rejected(HandoffRejectionReason.TARGET_NOT_FOUND, "The pending decision target was not found.")
        target = workspace.pending_human_decisions[target_index]
        if target.status != "pending":
            raise _Rejected(HandoffRejectionReason.TARGET_ALREADY_RESOLVED, "The pending decision is already resolved.")
        note = action.resolution_note or _text_after_value(action.after_value)
        if not note:
            raise _Rejected(HandoffRejectionReason.INVALID_ACTION, "A human resolution note is required.")
        reviewer = ReviewerReference(reviewer_id=action.reviewer_id, reviewer_role=action.reviewer_role)
        updated = target.model_copy(
            update={
                "status": "resolved",
                "resolution_note": note,
                "resolved_by": reviewer,
                "resolved_action_id": action.action_id,
            }
        )
        decisions = list(workspace.pending_human_decisions)
        decisions[target_index] = updated
        updates["pending_human_decisions"] = decisions
        event_type = HandoffEventType.DECISION_RESOLVED
        message = "The pending human decision was resolved and retained in the audit history."
    elif action.action == HandoffActionType.RESOLVE_BLOCKER:
        _require_human_review(status)
        _require_target(action)
        target_index = _find_blocker(workspace, action.target_id or "")
        if target_index is None:
            raise _Rejected(HandoffRejectionReason.TARGET_NOT_FOUND, "The blocker target was not found.")
        target = workspace.blockers[target_index]
        if target.resolution_status != "open":
            raise _Rejected(HandoffRejectionReason.TARGET_ALREADY_RESOLVED, "The blocker is already resolved.")
        if target.code.endswith("_request"):
            raise _Rejected(
                HandoffRejectionReason.SAFETY_BOUNDARY,
                "Safety-policy blockers cannot be cleared by a handoff action; remove the prohibited request and rebuild the draft.",
            )
        if action.before_value is not None and action.before_value != "open":
            raise _Rejected(HandoffRejectionReason.BEFORE_VALUE_MISMATCH, "The blocker resolution state is stale.")
        note = action.resolution_note or _text_after_value(action.after_value)
        if not note:
            raise _Rejected(HandoffRejectionReason.INVALID_ACTION, "A human resolution note is required.")
        reviewer = ReviewerReference(reviewer_id=action.reviewer_id, reviewer_role=action.reviewer_role)
        updated = target.model_copy(
            update={
                "resolution_status": "resolved",
                "resolution_note": note,
                "resolved_by": reviewer,
                "resolved_action_id": action.action_id,
            }
        )
        blockers = list(workspace.blockers)
        blockers[target_index] = updated
        updates["blockers"] = blockers
        event_type = HandoffEventType.BLOCKER_RESOLVED
        message = "The blocker was resolved by a human reviewer; bounded facts and safety limits remain unchanged."
    elif action.action == HandoffActionType.MARK_READY_FOR_EXTERNAL_HANDOFF:
        _require_transition(status, HandoffState.READY_FOR_EXTERNAL_HANDOFF)
        if not workspace.review_readiness.ready_for_external_handoff:
            raise _Rejected(
                HandoffRejectionReason.READINESS_BLOCKED,
                "The handoff remains blocked by unresolved requirements, uncertainties, or decisions.",
            )
        next_status = HandoffState.READY_FOR_EXTERNAL_HANDOFF
        event_type = HandoffEventType.READY_FOR_EXTERNAL_HANDOFF
        message = "The handoff is ready for external handoff; this is not clinical approval."
    elif action.action == HandoffActionType.RECORD_EXTERNAL_HANDOFF:
        _require_transition(status, HandoffState.EXTERNALLY_HANDED_OFF)
        event = action.external_event
        if event is None:
            raise _Rejected(HandoffRejectionReason.EXTERNAL_EVENT_REQUIRED, "An external handoff event is required.")
        if event.event_type != "handoff_sent" or event.packet_sha256 != workspace.handoff_packet.packet_sha256:
            raise _Rejected(HandoffRejectionReason.INVALID_EXTERNAL_EVENT, "The external event must reference the current handoff packet.")
        next_status = HandoffState.EXTERNALLY_HANDED_OFF
        updates["external_handoff_events"] = [*workspace.external_handoff_events, event]
        external_event = event
        event_type = HandoffEventType.HANDOFF_SENT
        message = "The handoff event was recorded; the packet remains explicitly non-clinical."
    elif action.action == HandoffActionType.DEFER:
        _require_transition(status, HandoffState.DEFERRED)
        next_status = HandoffState.DEFERRED
        event_type = HandoffEventType.DEFERRED
        message = "The handoff was deferred; its audit history is retained."
    elif action.action == HandoffActionType.WITHDRAW:
        _require_transition(status, HandoffState.WITHDRAWN)
        next_status = HandoffState.WITHDRAWN
        event_type = HandoffEventType.WITHDRAWN
        message = "The handoff was withdrawn; its audit history is retained."
    else:
        raise _Rejected(HandoffRejectionReason.INVALID_ACTION, "The handoff action is not supported.")

    reviewer = ReviewerReference(reviewer_id=action.reviewer_id, reviewer_role=action.reviewer_role)
    reviewers = list(workspace.reviewer_references)
    if action.reviewer_id not in {item.reviewer_id for item in reviewers}:
        reviewers.append(reviewer)
    new_revision = workspace.revision + 1
    requested = [*workspace.requested_review_actions, action]
    applied = [*workspace.applied_review_actions, action]
    provisional = workspace.model_copy(
        update={
            **updates,
            "status": next_status,
            "revision": new_revision,
            "requested_review_actions": requested,
            "applied_review_actions": applied,
            "reviewer_references": reviewers,
        }
    )
    provisional = _synchronize_active_receipt(provisional, event=external_event)
    readiness = _readiness_after_action(
        workspace,
        provisional.blockers,
        provisional.acknowledgement_required_uncertainties,
        provisional.pending_human_decisions,
    )
    audit = HandoffAuditEvent(
        audit_id=f"HANDOFF-AUDIT-{new_revision:04d}",
        event_type=event_type,
        action_id=action.action_id,
        result_status=HandoffActionResultStatus.APPLIED,
        timestamp=action.timestamp,
        from_status=status,
        to_status=next_status,
        revision=new_revision,
        reviewer_id=action.reviewer_id,
        message=message,
    )
    provisional = provisional.model_copy(
        update={
            "review_readiness": readiness,
            "case_stages": _refresh_stage_statuses(provisional.case_stages, next_status, readiness),
            "audit_history": [*provisional.audit_history, audit],
        }
    )
    return _finalize(provisional), event_type, message


def _record_rejected_attempt(
    workspace: HandoffWorkspaceResult,
    action: HandoffReviewAction,
    old_status: HandoffState,
    reason: HandoffRejectionReason | None,
    message: str,
) -> HandoffWorkspaceResult:
    new_revision = workspace.revision + 1
    reviewer = ReviewerReference(reviewer_id=action.reviewer_id, reviewer_role=action.reviewer_role)
    reviewers = list(workspace.reviewer_references)
    if action.reviewer_id not in {item.reviewer_id for item in reviewers}:
        reviewers.append(reviewer)
    audit = HandoffAuditEvent(
        audit_id=f"HANDOFF-AUDIT-{new_revision:04d}",
        event_type=HandoffEventType.ACTION_REJECTED,
        action_id=action.action_id,
        result_status=HandoffActionResultStatus.REJECTED,
        timestamp=action.timestamp,
        from_status=old_status,
        to_status=old_status,
        revision=new_revision,
        reviewer_id=action.reviewer_id,
        message=message,
    )
    requested = list(workspace.requested_review_actions)
    if action.action_id not in {item.action_id for item in requested}:
        requested.append(action)
    return _finalize(
        workspace.model_copy(
            update={
                "revision": new_revision,
                "requested_review_actions": requested,
                "reviewer_references": reviewers,
                "audit_history": [*workspace.audit_history, audit],
            }
        )
    )


def _readiness_after_action(
    workspace: HandoffWorkspaceResult,
    blockers: list[HandoffBlocker],
    uncertainties: list[HandoffUncertainty],
    decisions: list[PendingHumanDecision],
) -> ReviewReadiness:
    """Recompute mutable review counts while preserving immutable-source findings."""

    readiness = _review_readiness(blockers, uncertainties, decisions, None, None)
    blocking_critics = sum(
        1
        for item in blockers
        if item.resolution_status == "open" and item.code == "blocking_critic_finding"
    )
    unresolved_evidence = workspace.review_readiness.unresolved_evidence_count
    requirements = list(readiness.blocking_requirements)
    if blocking_critics and "address_blocking_critics" not in requirements:
        requirements.append("address_blocking_critics")
    if unresolved_evidence and "review_unresolved_evidence" not in requirements:
        requirements.append("review_unresolved_evidence")
    return readiness.model_copy(
        update={
            "blocking_requirements": requirements,
            "blocking_critic_count": blocking_critics,
            "unresolved_evidence_count": unresolved_evidence,
            "ready_for_external_handoff": (
                readiness.ready_for_external_handoff
                and blocking_critics == 0
                and unresolved_evidence == 0
            ),
        }
    )


def _record_action_result(
    *,
    workspace: HandoffWorkspaceResult,
    action: HandoffReviewAction,
    old_status: HandoffState,
    event_type: HandoffEventType,
    result_status: HandoffActionResultStatus,
    rejection_reason: HandoffRejectionReason | None,
    message: str,
) -> tuple[HandoffWorkspaceResult, HandoffReviewActionResult]:
    authoritative_before = {
        "status": old_status.value,
        "revision": workspace.revision - 1,
    }
    validated_after = (
        {
            "status": workspace.status.value,
            "revision": workspace.revision,
            "snapshot_hash": workspace.snapshot_hash,
        }
        if result_status == HandoffActionResultStatus.APPLIED
        else None
    )
    result = HandoffReviewActionResult(
        action_id=action.action_id,
        action=action.action,
        result_status=result_status,
        rejection_reason=rejection_reason,
        message=message,
        current_status=workspace.status,
        current_revision=workspace.revision,
        current_snapshot_hash=workspace.snapshot_hash,
        authoritative_before=authoritative_before,
        validated_after=validated_after,
        reviewer_id=action.reviewer_id,
        reviewer_role=action.reviewer_role,
        timestamp=action.timestamp,
    )
    final = _finalize(
        workspace.model_copy(update={"review_action_results": [*workspace.review_action_results, result]})
    )
    return final, result.model_copy(update={"current_snapshot_hash": final.snapshot_hash})


def _artifact_manifest(items: tuple[tuple[str, Any, str, SourceClassification], ...]) -> list[HandoffArtifactManifestItem]:
    manifest: list[HandoffArtifactManifestItem] = []
    for artifact_id, value, filename, classification in items:
        payload = _dump(value)
        available = value is not None
        manifest.append(
            HandoffArtifactManifestItem(
                artifact_id=artifact_id,
                artifact_name=f"reproducibility/{filename}",
                artifact_type=artifact_id,
                available=available,
                schema_version=payload.get("schema_version") if isinstance(payload, dict) else None,
                source_classification=classification,
                sha256=_file_sha256(payload) if available else None,
                canonical_payload_sha256=_sha256(payload),
                digest_scope="file_bytes" if available else "not_available",
                source_fact_paths=[f"{artifact_id}.schema_version"],
            )
        )
    return manifest


def _pointers(*, jarvis_workspace: Any, result_evidence_workspace: Any) -> tuple[list[HandoffClaimPointer], list[HandoffEvidencePointer]]:
    claims: list[HandoffClaimPointer] = []
    evidence: list[HandoffEvidencePointer] = []
    jarvis = _dump(jarvis_workspace) or {}
    result_evidence = _dump(result_evidence_workspace) or {}
    for claim in jarvis.get("synthesis_claims", []) or []:
        if not isinstance(claim, dict) or not claim.get("claim_id"):
            continue
        evidence_ids = sorted(
            set(claim.get("supporting_evidence_ids", []) or [])
            | set(claim.get("contradicting_evidence_ids", []) or [])
            | set(claim.get("unresolved_evidence_ids", []) or [])
        )
        claims.append(
            HandoffClaimPointer(
                pointer_id=f"claim-pointer-{claim['claim_id']}",
                claim_id=str(claim["claim_id"]),
                artifact_id="jarvis_synthesis_report_workspace",
                evidence_ids=[str(item) for item in evidence_ids],
                source_fact_paths=[str(item) for item in claim.get("source_fact_paths", []) or []],
            )
        )
        for role, field in (
            ("supporting", "supporting_evidence_ids"),
            ("contradicting", "contradicting_evidence_ids"),
            ("unresolved", "unresolved_evidence_ids"),
        ):
            for evidence_id in claim.get(field, []) or []:
                evidence.append(
                    HandoffEvidencePointer(
                        pointer_id=f"evidence-pointer-{claim['claim_id']}-{evidence_id}-{role}",
                        evidence_id=str(evidence_id),
                        artifact_id="result_evidence_workspace",
                        role=role,
                        source_fact_paths=[str(item) for item in claim.get("source_fact_paths", []) or []],
                    )
                )
    for entry in result_evidence.get("ledger_entries", []) or []:
        if not isinstance(entry, dict):
            continue
        evidence_id = entry.get("evidence_id") or entry.get("ledger_entry_id") or entry.get("entry_id")
        if not evidence_id:
            continue
        if any(item.evidence_id == str(evidence_id) for item in evidence):
            continue
        evidence.append(
            HandoffEvidencePointer(
                pointer_id=f"evidence-pointer-{evidence_id}-ledger",
                evidence_id=str(evidence_id),
                artifact_id="result_evidence_workspace",
                role="context_only" if entry.get("conflict_detected") else "supporting",
                source_fact_paths=["result_evidence_workspace.ledger_entries"],
            )
        )
    return claims, evidence


def _blockers(*, intake: Any, pretest_assessment: Any, jarvis_workspace: Any, result_gateway: Any = None) -> list[HandoffBlocker]:
    blockers: list[HandoffBlocker] = []
    intake_data = _dump(intake) or {}
    for category, field in (
        ("validation_error", "validation_errors"),
        ("policy_block", "policy_blocks"),
        ("missing_information", "missing_information"),
    ):
        for index, issue in enumerate(intake_data.get(field, []) or []):
            issue = issue if isinstance(issue, dict) else {"message": str(issue)}
            issue_id = issue.get("code") or f"{category}-{index + 1}"
            blockers.append(
                HandoffBlocker(
                    blocker_id=_identifier(f"blocker-{category}-{issue_id}-{index}"),
                    code=_identifier(str(issue_id)),
                    message=str(issue.get("message", "Human review is required.")),
                    source_artifact_ids=["clinical_case_intake"],
                    source_fact_paths=[f"clinical_case_intake.{field}.{index}"],
                )
            )
    pretest = _dump(pretest_assessment) or {}
    for index, item in enumerate(pretest.get("open_missing_information", []) or []):
        item = item if isinstance(item, dict) else {"message": str(item)}
        blockers.append(
            HandoffBlocker(
                blocker_id=f"blocker-pretest-{index + 1}",
                code="pretest_open_missing_information",
                message=str(item.get("message") or item.get("detail") or "Pre-test information remains open."),
                source_artifact_ids=["pre_test_assessment"],
                source_fact_paths=[f"pre_test_assessment.open_missing_information.{index}"],
            )
        )
    jarvis = _dump(jarvis_workspace) or {}
    for index, finding in enumerate(jarvis.get("critic_findings", []) or []):
        finding = finding if isinstance(finding, dict) else {}
        if str(finding.get("severity", "")).lower() != "blocking":
            continue
        blockers.append(
            HandoffBlocker(
                blocker_id=f"blocker-critic-{finding.get('finding_id') or index + 1}",
                code="blocking_critic_finding",
                message=str(finding.get("message") or finding.get("finding") or "A blocking critic finding requires review."),
                source_artifact_ids=["jarvis_synthesis_report_workspace"],
                source_fact_paths=[f"jarvis_synthesis_report_workspace.critic_findings.{index}"],
            )
        )
    gateway = _dump(result_gateway) or {}
    if str(gateway.get("package_status", "")).lower() in {"blocked", "rejected", "failed", "stale"}:
        blockers.append(
            HandoffBlocker(
                blocker_id="blocker-result-gateway-package",
                code="result_gateway_package_blocked",
                message="The supplied result package gateway is blocked or stale and requires reviewer resolution before downstream use.",
                source_artifact_ids=["clinical_case_intake"],
                source_fact_paths=["clinical_case_intake.result_gateway.package_status"],
            )
        )
    return _dedupe_blockers(blockers)


def _uncertainties(*, jarvis_workspace: Any, result_evidence_workspace: Any) -> list[HandoffUncertainty]:
    jarvis = _dump(jarvis_workspace) or {}
    uncertainties: list[HandoffUncertainty] = []
    for index, section in enumerate(jarvis.get("report_sections", []) or []):
        if not isinstance(section, dict):
            continue
        section_kind = str(section.get("section_type") or section.get("section_kind") or "").lower()
        if "limitation" not in section_kind and "missing" not in section_kind and "unresolved" not in section_kind:
            continue
        statement = str(section.get("narrative") or section.get("title") or "A report limitation remains for human review.")
        uncertainties.append(
            HandoffUncertainty(
                uncertainty_id=_identifier(f"uncertainty-{section.get('section_id') or index + 1}"),
                statement=statement[:2000],
                source_artifact_ids=["jarvis_synthesis_report_workspace"],
                source_fact_paths=[f"jarvis_synthesis_report_workspace.report_sections.{index}"],
            )
        )
    if not uncertainties:
        result_evidence_data = _dump(result_evidence_workspace) or {}
        unresolved = sum(
            1
            for item in result_evidence_data.get("ledger_entries", []) or []
            if isinstance(item, dict) and str(item.get("state", "")).lower() in {"unresolved", "conflicting", "not_assessed"}
        )
        statement = (
            "The supplied evidence remains bounded by its recorded scope and requires human acknowledgement."
            if unresolved
            else "The aggregate is a deterministic research-use draft and requires human acknowledgement before external handoff."
        )
        uncertainties.append(
            HandoffUncertainty(
                uncertainty_id="uncertainty-draft-scope",
                statement=statement,
                source_artifact_ids=["jarvis_synthesis_report_workspace", "result_evidence_workspace"],
                source_fact_paths=["jarvis_synthesis_report_workspace.report_status"],
            )
        )
    return _dedupe_uncertainties(uncertainties)


def _pending_decisions(jarvis_workspace: Any) -> list[PendingHumanDecision]:
    jarvis = _dump(jarvis_workspace) or {}
    decisions: list[PendingHumanDecision] = []
    for index, decision_id in enumerate(jarvis.get("pending_human_decision_ids", []) or []):
        decisions.append(
            PendingHumanDecision(
                decision_id=_identifier(str(decision_id)),
                category="report_review",
                question=f"Resolve the pending human review decision {decision_id} before external handoff.",
                target_artifact_ids=["jarvis_synthesis_report_workspace"],
            )
        )
    if not decisions:
        decisions.append(
            PendingHumanDecision(
                decision_id="decision-draft-review",
                category="report_review",
                question="Confirm that the draft report, provenance, limitations, and handoff packet are ready for external review.",
                target_artifact_ids=["jarvis_synthesis_report_workspace", "handoff_packet"],
            )
        )
    return _dedupe_decisions(decisions)


def _review_readiness(
    blockers: list[HandoffBlocker],
    uncertainties: list[HandoffUncertainty],
    decisions: list[PendingHumanDecision],
    jarvis_workspace: Any,
    result_evidence_workspace: Any,
) -> ReviewReadiness:
    open_blockers = [item for item in blockers if item.resolution_status == "open"]
    unacknowledged = [item for item in uncertainties if not item.acknowledged]
    pending = [item for item in decisions if item.status == "pending"]
    jarvis = _dump(jarvis_workspace) or {}
    blocking_critics = sum(
        1 for item in jarvis.get("critic_findings", []) or [] if isinstance(item, dict) and str(item.get("severity", "")).lower() == "blocking"
    )
    evidence = _dump(result_evidence_workspace) or {}
    unresolved_evidence = sum(
        1
        for item in evidence.get("ledger_entries", []) or []
        if isinstance(item, dict) and str(item.get("state", "")).lower() in {"unresolved", "conflicting", "not_assessed"}
    )
    requirements: list[str] = []
    if open_blockers:
        requirements.append("resolve_open_blockers")
    if unacknowledged:
        requirements.append("acknowledge_uncertainties")
    if pending:
        requirements.append("resolve_pending_human_decisions")
    if blocking_critics:
        requirements.append("address_blocking_critics")
    if unresolved_evidence:
        requirements.append("review_unresolved_evidence")
    return ReviewReadiness(
        ready_for_external_handoff=not (open_blockers or unacknowledged or pending or blocking_critics or unresolved_evidence),
        blocking_requirements=requirements,
        open_blocker_count=len(open_blockers),
        unacknowledged_uncertainty_count=len(unacknowledged),
        pending_human_decision_count=len(pending),
        blocking_critic_count=blocking_critics,
        unresolved_evidence_count=unresolved_evidence,
    )


def _case_stages(
    *,
    case: Any,
    intake: Any,
    phenotype_curation: Any,
    pedigree_audit: Any,
    pretest_assessment: Any,
    test_strategy_workspace: Any,
    result_evidence_workspace: Any,
    result_gateway: Any,
    specialist_agent_workspace: Any,
    jarvis_workspace: Any,
    external_checkpoint: ExternalCheckpoint | None,
    blockers: list[HandoffBlocker],
    pending_decisions: list[PendingHumanDecision],
    status: HandoffState,
    readiness: ReviewReadiness,
) -> list[CaseStage]:
    intake_data = _dump(intake) or {}
    case_data = _dump(case) or {}
    has_context = bool(case_data.get("global_intake_context") or case_data.get("provenance") or case_data.get("case_label"))
    has_pedigree = bool(_dump(pedigree_audit) or case_data.get("pedigree"))
    has_results = bool(_dump(result_evidence_workspace) or _dump(result_gateway))
    gateway_data = _dump(result_gateway) or {}
    gateway_blocked = str(gateway_data.get("package_status", "")).lower() in {"blocked", "rejected", "failed", "stale"}
    has_qc_or_assay = bool(gateway_data.get("qc") or gateway_data.get("coverage") or gateway_data.get("assay_scope"))
    candidate_analysis_data = intake_data.get("candidate_analysis") or {}
    has_candidates = bool(
        candidate_analysis_data.get("ranked_candidates")
        or (_dump(specialist_agent_workspace) or {}).get("candidate_criteria")
    )
    has_jarvis = bool(_dump(jarvis_workspace))
    component_status = {
        "referral": _available_status(has_context),
        "clinical_history": _available_status(has_context),
        "phenotype_hpo": _artifact_status(phenotype_curation, bool(intake_data.get("validation_errors"))),
        "pedigree_family": _available_status(has_pedigree),
        "previous_investigations": _available_status(bool(pretest_assessment or has_results)),
        "readiness": _artifact_status(pretest_assessment, False),
        "test_strategy": _artifact_status(test_strategy_workspace, False),
        "external_checkpoint": (
            CaseStageStatus.COMPLETED_FOR_DRAFT_USE
            if external_checkpoint and external_checkpoint.status == "recorded"
            else CaseStageStatus.AWAITING_HUMAN_INPUT
            if external_checkpoint and external_checkpoint.status == "needs_review"
            else CaseStageStatus.AVAILABLE
        ),
        "result_intake": CaseStageStatus.BLOCKED if gateway_blocked else _available_status(has_results),
        "qc_assay_scope": CaseStageStatus.BLOCKED if gateway_blocked else CaseStageStatus.COMPLETED_FOR_DRAFT_USE if has_qc_or_assay else CaseStageStatus.NOT_STARTED,
        "candidate_analysis": _available_status(has_candidates or bool(candidate_analysis_data)),
        "evidence": _available_status(has_results),
        "candidate_acmg": _available_status(has_candidates),
        "synthesis_critics": _artifact_status(jarvis_workspace, False),
        "draft_report": _artifact_status(jarvis_workspace, False),
        "human_review": CaseStageStatus.AWAITING_HUMAN_INPUT,
        "external_handoff": CaseStageStatus.BLOCKED,
        "reanalysis": CaseStageStatus.NOT_STARTED,
    }
    stages = [
        CaseStage(
            stage_number=index,
            stage_id=stage_id,
            label=label,
            status=component_status[stage_id],
            artifact_ids=_stage_artifacts(stage_id, intake, phenotype_curation, pedigree_audit, pretest_assessment, test_strategy_workspace, result_evidence_workspace, result_gateway, specialist_agent_workspace, jarvis_workspace),
            blocker_ids=[item.blocker_id for item in blockers if _stage_has_artifact(stage_id, item.source_artifact_ids)],
            pending_decision_ids=[item.decision_id for item in pending_decisions if stage_id in {"human_review", "external_handoff"}],
            source_classifications=_stage_classifications(stage_id, gateway_present=result_gateway is not None),
        )
        for index, (stage_id, label) in enumerate(STAGE_DEFINITIONS, start=1)
    ]
    return _refresh_stage_statuses(stages, status, readiness)


def _refresh_stage_statuses(stages: list[CaseStage], status: HandoffState, readiness: ReviewReadiness) -> list[CaseStage]:
    refreshed = list(stages)
    human_index = next(index for index, item in enumerate(refreshed) if item.stage_id == "human_review")
    external_index = next(index for index, item in enumerate(refreshed) if item.stage_id == "external_handoff")
    if status in {HandoffState.DEFERRED, HandoffState.WITHDRAWN}:
        refreshed[human_index] = refreshed[human_index].model_copy(update={"status": CaseStageStatus.HISTORICAL})
        refreshed[external_index] = refreshed[external_index].model_copy(update={"status": CaseStageStatus.HISTORICAL})
    elif status == HandoffState.EXTERNALLY_HANDED_OFF:
        refreshed[human_index] = refreshed[human_index].model_copy(update={"status": CaseStageStatus.COMPLETED_FOR_DRAFT_USE})
        refreshed[external_index] = refreshed[external_index].model_copy(update={"status": CaseStageStatus.COMPLETED_FOR_DRAFT_USE})
    elif status == HandoffState.READY_FOR_EXTERNAL_HANDOFF:
        refreshed[human_index] = refreshed[human_index].model_copy(update={"status": CaseStageStatus.COMPLETED_FOR_DRAFT_USE})
        refreshed[external_index] = refreshed[external_index].model_copy(update={"status": CaseStageStatus.AVAILABLE})
    elif status == HandoffState.UNDER_HUMAN_REVIEW:
        refreshed[human_index] = refreshed[human_index].model_copy(update={"status": CaseStageStatus.INCOMPLETE})
        refreshed[external_index] = refreshed[external_index].model_copy(
            update={"status": CaseStageStatus.AVAILABLE if readiness.ready_for_external_handoff else CaseStageStatus.BLOCKED}
        )
    else:
        refreshed[human_index] = refreshed[human_index].model_copy(update={"status": CaseStageStatus.AWAITING_HUMAN_INPUT})
        refreshed[external_index] = refreshed[external_index].model_copy(update={"status": CaseStageStatus.BLOCKED})
    return refreshed


def _stage_artifacts(stage_id: str, *components: Any) -> list[str]:
    gateway_present = len(components) > 6 and components[6] is not None
    candidate_analysis_present = bool(
        (_dump(components[0]) or {}).get("candidate_analysis")
    ) if components else False
    mapping = {
        "referral": ["clinical_case_intake"],
        "clinical_history": ["clinical_case_intake"],
        "phenotype_hpo": ["clinical_case_intake", "phenotype_hpo_curation"],
        "pedigree_family": ["clinical_case_intake", "pedigree_inheritance_audit"],
        "previous_investigations": ["pre_test_assessment", "result_evidence_workspace"],
        "readiness": ["pre_test_assessment"],
        "test_strategy": ["test_strategy_workspace"],
        "external_checkpoint": [],
        "result_intake": ["result_evidence_workspace"],
        "qc_assay_scope": [],
        # Preserve the frozen v0.35 manifest for legacy specialist-only runs;
        # v0.37 adds the embedded intake artifact when candidate analysis is
        # actually present in the typed intake result.
        "candidate_analysis": [
            "clinical_case_intake",
            "specialist_agent_workspace",
        ] if candidate_analysis_present else ["specialist_agent_workspace"],
        "evidence": ["result_evidence_workspace"],
        "candidate_acmg": ["specialist_agent_workspace"],
        "synthesis_critics": ["jarvis_synthesis_report_workspace"],
        "draft_report": ["jarvis_synthesis_report_workspace"],
        "human_review": ["jarvis_synthesis_report_workspace", "handoff_workspace"],
        "external_handoff": ["handoff_packet", "handoff_receipt"],
        "reanalysis": [],
    }
    artifacts = list(mapping.get(stage_id, []))
    if gateway_present and stage_id in {"result_intake", "qc_assay_scope"}:
        artifacts.append("clinical_case_intake")
    return artifacts


def _stage_classifications(stage_id: str, *, gateway_present: bool = False) -> list[SourceClassification]:
    if stage_id in {"referral", "clinical_history", "pedigree_family", "previous_investigations"}:
        return [SourceClassification.SUPPLIED_FACT]
    if stage_id in {"phenotype_hpo", "readiness", "evidence", "synthesis_critics", "draft_report"}:
        return [SourceClassification.DETERMINISTIC_FINDING]
    if stage_id == "result_intake":
        return [SourceClassification.SUPPLIED_FACT, SourceClassification.DETERMINISTIC_FINDING] if gateway_present else [SourceClassification.DETERMINISTIC_FINDING]
    if stage_id == "qc_assay_scope":
        return [SourceClassification.SUPPLIED_FACT, SourceClassification.DETERMINISTIC_FINDING] if gateway_present else []
    if stage_id in {"test_strategy", "candidate_analysis", "candidate_acmg"}:
        return [SourceClassification.MODEL_OR_SPECIALIST_PROPOSAL, SourceClassification.CANDIDATE_INTERPRETATION]
    if stage_id == "external_checkpoint":
        return [SourceClassification.EXTERNAL_ASSESSMENT]
    if stage_id in {"human_review", "external_handoff"}:
        return [SourceClassification.HUMAN_DECISION]
    return []


def _stage_has_artifact(stage_id: str, artifact_ids: list[str]) -> bool:
    expected = set(_stage_artifacts(stage_id))
    if stage_id in {"result_intake", "qc_assay_scope"}:
        expected.add("clinical_case_intake")
    return bool(expected & set(artifact_ids))


def _artifact_status(value: Any, blocked: bool) -> CaseStageStatus:
    if value is None:
        return CaseStageStatus.AVAILABLE
    if blocked:
        return CaseStageStatus.BLOCKED
    return CaseStageStatus.COMPLETED_FOR_DRAFT_USE


def _available_status(available: bool) -> CaseStageStatus:
    return CaseStageStatus.COMPLETED_FOR_DRAFT_USE if available else CaseStageStatus.INCOMPLETE


def _make_packet(*, case_id: str, artifacts: list[HandoffArtifactManifestItem], source_hashes: dict[str, str], schema_versions: dict[str, str | None], claim_pointers: list[HandoffClaimPointer], evidence_pointers: list[HandoffEvidencePointer]) -> HandoffPacket:
    provisional = HandoffPacket(
        packet_id=f"HANDOFF-PACKET-{case_id}",
        pseudonymous_case_id=case_id,
        created_revision=0,
        artifact_manifest=artifacts,
        source_hashes=source_hashes,
        schema_versions=schema_versions,
        claim_pointers=claim_pointers,
        evidence_pointers=evidence_pointers,
        packet_sha256="0" * 64,
    )
    return provisional.model_copy(
        update={
            "packet_sha256": _sha256(
                _dump(provisional.model_copy(update={"packet_sha256": ""}))
            )
        }
    )


def _make_receipt(*, packet: HandoffPacket, status: HandoffState, event: ExternalHandoffEvent | None = None) -> HandoffReceipt:
    issued = event is not None
    provisional = HandoffReceipt(
        receipt_id=f"RECEIPT-{packet.pseudonymous_case_id}",
        receipt_status=HandoffReceiptStatus.ISSUED if issued else HandoffReceiptStatus.NOT_ISSUED,
        packet_id=packet.packet_id,
        packet_sha256=packet.packet_sha256,
        handoff_state=status,
        external_event_id=event.event_id if event else None,
        reviewer_id=event.reviewer_id if event else None,
        reviewer_role=event.reviewer_role if event else None,
        external_reference=event.external_reference if event else None,
        issued_at=event.timestamp if event else None,
        receipt_sha256="0" * 64,
    )
    return provisional.model_copy(
        update={
            "receipt_sha256": _sha256(
                _dump(provisional.model_copy(update={"receipt_sha256": ""}))
            )
        }
    )


def _synchronize_active_receipt(
    workspace: HandoffWorkspaceResult,
    *,
    event: ExternalHandoffEvent | None = None,
) -> HandoffWorkspaceResult:
    """Keep the persisted active receipt aligned with every accepted action."""

    return workspace.model_copy(
        update={
            "handoff_receipt": _make_receipt(
                packet=workspace.handoff_packet,
                status=workspace.status,
                event=event,
            )
        }
    )


def _require_transition(current: HandoffState, target: HandoffState) -> None:
    if target not in _ALLOWED_TRANSITIONS.get(current, set()):
        raise _Rejected(
            HandoffRejectionReason.INVALID_TRANSITION,
            f"Transition from {current.value} to {target.value} is not permitted.",
        )


def _require_human_review(status: HandoffState) -> None:
    if status != HandoffState.UNDER_HUMAN_REVIEW:
        raise _Rejected(
            HandoffRejectionReason.INVALID_TRANSITION,
            "This review action is permitted only while human review is active.",
        )


def _require_target(action: HandoffReviewAction) -> None:
    if not action.target_id:
        raise _Rejected(HandoffRejectionReason.TARGET_REQUIRED, "This handoff action requires a target identifier.")


def _find_uncertainty(workspace: HandoffWorkspaceResult, target_id: str) -> int | None:
    for index, item in enumerate(workspace.acknowledgement_required_uncertainties):
        if item.uncertainty_id == target_id:
            return index
    return None


def _find_decision(workspace: HandoffWorkspaceResult, target_id: str) -> int | None:
    for index, item in enumerate(workspace.pending_human_decisions):
        if item.decision_id == target_id:
            return index
    return None


def _find_blocker(workspace: HandoffWorkspaceResult, target_id: str) -> int | None:
    for index, item in enumerate(workspace.blockers):
        if item.blocker_id == target_id:
            return index
    return None


def _text_after_value(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, dict):
        for key in ("resolution_note", "note", "decision"):
            item = value.get(key)
            if isinstance(item, str) and item.strip():
                return item.strip()
    return None


def _finalize(workspace: HandoffWorkspaceResult) -> HandoffWorkspaceResult:
    blank = workspace.model_copy(update={"snapshot_hash": "0" * 64})
    return blank.model_copy(update={"snapshot_hash": _snapshot_hash(blank)})


def _snapshot_hash(workspace: HandoffWorkspaceResult) -> str:
    payload = _dump(workspace)
    if isinstance(payload, dict):
        payload["snapshot_hash"] = "0" * 64
        # Action results report this hash; excluding them avoids a self-referential digest.
        payload["review_action_results"] = []
    return _sha256(payload)


def _dump(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return json.loads(json.dumps(value, sort_keys=True, default=str))
    return value


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def _json_file_bytes(value: Any) -> bytes:
    """Match reproducibility._write_json: UTF-8 JSON, sorted keys, two-space indent, no newline."""

    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True, default=str).encode("utf-8")


def _file_sha256(value: Any) -> str:
    return hashlib.sha256(_json_file_bytes(value)).hexdigest()


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _identifier(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.:-]+", "-", value).strip("-")
    return normalized[:150] or "item"


def _dedupe_blockers(items: list[HandoffBlocker]) -> list[HandoffBlocker]:
    unique: dict[str, HandoffBlocker] = {}
    for item in items:
        unique.setdefault(item.blocker_id, item)
    return list(unique.values())


def _dedupe_uncertainties(items: list[HandoffUncertainty]) -> list[HandoffUncertainty]:
    unique: dict[str, HandoffUncertainty] = {}
    for item in items:
        unique.setdefault(item.uncertainty_id, item)
    return list(unique.values())


def _dedupe_decisions(items: list[PendingHumanDecision]) -> list[PendingHumanDecision]:
    unique: dict[str, PendingHumanDecision] = {}
    for item in items:
        unique.setdefault(item.decision_id, item)
    return list(unique.values())
