from __future__ import annotations

import json
import re
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


HANDOFF_SCHEMA_VERSION = "0.35"
HANDOFF_PACKET_VERSION = "insilicopop-handoff-packet-0.35.0"
HANDOFF_RECEIPT_VERSION = "insilicopop-handoff-receipt-0.35.0"
LOCAL_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"
SNAPSHOT_HASH_PATTERN = r"^[a-f0-9]{64}$"
_SENSITIVE_TEXT_PATTERN = re.compile(
    r"(?i)(?:"
    r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b|"
    r"(?:\+\d[\d ()-]{8,}\d|\b\d{10,15}\b)|"
    r"\b(?:medical record number|hospital number|patient name|date of birth)\s*[:=]|"
    r"\b(?:api[_ -]?key|access[_ -]?token|authorization|password|client[_ -]?secret)\s*[:=]|"
    r"\bbearer\s+[A-Za-z0-9._~-]+"
    r")"
)


class FrozenHandoffModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class HandoffState(str, Enum):
    ASSEMBLED = "assembled"
    UNDER_HUMAN_REVIEW = "under_human_review"
    READY_FOR_EXTERNAL_HANDOFF = "ready_for_external_handoff"
    EXTERNALLY_HANDED_OFF = "externally_handed_off"
    DEFERRED = "deferred"
    WITHDRAWN = "withdrawn"


# A descriptive alias keeps callers free to use either terminology.
HandoffStatus = HandoffState


class CaseStageStatus(str, Enum):
    NOT_STARTED = "not_started"
    AVAILABLE = "available"
    INCOMPLETE = "incomplete"
    BLOCKED = "blocked"
    AWAITING_HUMAN_INPUT = "awaiting_human_input"
    COMPLETED_FOR_DRAFT_USE = "completed_for_draft_use"
    HISTORICAL = "historical"
    SUPERSEDED = "superseded"


class HandoffActionType(str, Enum):
    START_HUMAN_REVIEW = "start_human_review"
    BEGIN_HUMAN_REVIEW = "start_human_review"
    ACKNOWLEDGE_UNCERTAINTY = "acknowledge_uncertainty"
    RESOLVE_PENDING_DECISION = "resolve_pending_decision"
    RESOLVE_BLOCKER = "resolve_blocker"
    MARK_READY_FOR_EXTERNAL_HANDOFF = "mark_ready_for_external_handoff"
    RECORD_EXTERNAL_HANDOFF = "record_external_handoff"
    DEFER = "defer"
    WITHDRAW = "withdraw"


class HandoffActionResultStatus(str, Enum):
    APPLIED = "applied"
    REJECTED = "rejected"


class HandoffRejectionReason(str, Enum):
    STALE_STATE = "stale_state"
    TERMINAL_STATE = "terminal_state"
    INVALID_TRANSITION = "invalid_transition"
    TARGET_REQUIRED = "target_required"
    TARGET_NOT_FOUND = "target_not_found"
    TARGET_ALREADY_RESOLVED = "target_already_resolved"
    READINESS_BLOCKED = "readiness_blocked"
    EXTERNAL_EVENT_REQUIRED = "external_event_required"
    INVALID_EXTERNAL_EVENT = "invalid_external_event"
    BEFORE_VALUE_MISMATCH = "before_value_mismatch"
    SAFETY_BOUNDARY = "safety_boundary"
    INVALID_ACTION = "invalid_action"


class HandoffEventType(str, Enum):
    ASSEMBLED = "assembled"
    REVIEW_STARTED = "review_started"
    UNCERTAINTY_ACKNOWLEDGED = "uncertainty_acknowledged"
    DECISION_RESOLVED = "decision_resolved"
    BLOCKER_RESOLVED = "blocker_resolved"
    READY_FOR_EXTERNAL_HANDOFF = "ready_for_external_handoff"
    HANDOFF_SENT = "handoff_sent"
    DEFERRED = "deferred"
    WITHDRAWN = "withdrawn"
    ACTION_REJECTED = "action_rejected"


class HandoffReceiptStatus(str, Enum):
    NOT_ISSUED = "not_issued"
    ISSUED = "issued"


class SourceClassification(str, Enum):
    SUPPLIED_FACT = "supplied_fact"
    NORMALIZED_FACT = "normalized_fact"
    DETERMINISTIC_FINDING = "deterministic_finding"
    RETRIEVED_EVIDENCE = "retrieved_evidence"
    MODEL_OR_SPECIALIST_PROPOSAL = "model_or_specialist_proposal"
    CANDIDATE_INTERPRETATION = "candidate_interpretation"
    EXTERNAL_ASSESSMENT = "external_assessment"
    HUMAN_DECISION = "human_decision"


class ReviewerReference(FrozenHandoffModel):
    reviewer_id: str = Field(min_length=1, max_length=120, pattern=LOCAL_ID_PATTERN)
    reviewer_role: str = Field(min_length=1, max_length=120)
    reference_type: Literal["pseudonymous_reviewer_reference"] = (
        "pseudonymous_reviewer_reference"
    )

    @model_validator(mode="after")
    def no_sensitive_reviewer_text(self) -> "ReviewerReference":
        _reject_sensitive_text(self.reviewer_id, "reviewer_id")
        _reject_sensitive_text(self.reviewer_role, "reviewer_role")
        return self


class ExternalCheckpoint(FrozenHandoffModel):
    checkpoint_id: str = Field(min_length=1, max_length=120, pattern=LOCAL_ID_PATTERN)
    status: Literal["not_recorded", "recorded", "needs_review"] = "not_recorded"
    reviewer_id: str | None = Field(default=None, max_length=120, pattern=LOCAL_ID_PATTERN)
    reviewer_role: str | None = Field(default=None, max_length=120)
    reference: str | None = Field(default=None, max_length=240)
    timestamp: str | None = Field(default=None, max_length=40)
    notes: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def no_sensitive_checkpoint_text(self) -> "ExternalCheckpoint":
        _reject_sensitive_text(self.reviewer_id, "reviewer_id")
        _reject_sensitive_text(self.reviewer_role, "reviewer_role")
        _reject_sensitive_text(self.reference, "reference")
        _reject_sensitive_text(self.notes, "notes")
        return self


class HandoffWorkspaceRequest(FrozenHandoffModel):
    schema_version: Literal["0.35"] = HANDOFF_SCHEMA_VERSION
    reviewer_references: list[ReviewerReference] = Field(default_factory=list, max_length=50)
    external_checkpoint: ExternalCheckpoint | None = None
    human_review_required: Literal[True] = True

    @model_validator(mode="after")
    def unique_reviewer_references(self) -> "HandoffWorkspaceRequest":
        ids = [item.reviewer_id for item in self.reviewer_references]
        if len(ids) != len(set(ids)):
            raise ValueError("reviewer references must be unique")
        return self


class HandoffBlocker(FrozenHandoffModel):
    blocker_id: str = Field(min_length=1, max_length=160, pattern=LOCAL_ID_PATTERN)
    code: str = Field(min_length=1, max_length=120, pattern=LOCAL_ID_PATTERN)
    message: str = Field(min_length=1, max_length=2000)
    source_artifact_ids: list[str] = Field(default_factory=list, max_length=50)
    source_fact_paths: list[str] = Field(default_factory=list, max_length=100)
    blocking: Literal[True] = True
    resolution_status: Literal["open", "resolved"] = "open"
    resolution_note: str | None = Field(default=None, max_length=2000)
    resolved_by: ReviewerReference | None = None
    resolved_action_id: str | None = Field(default=None, max_length=160)

    @model_validator(mode="after")
    def resolution_consistency(self) -> "HandoffBlocker":
        if self.resolution_status == "resolved" and (
            self.resolved_by is None or not self.resolved_action_id or not self.resolution_note
        ):
            raise ValueError("resolved blockers require reviewer, action, and resolution note")
        if self.resolution_status == "open" and (
            self.resolved_by is not None or self.resolved_action_id is not None
        ):
            raise ValueError("open blockers cannot contain resolved-by metadata")
        _reject_sensitive_text(self.resolution_note, "resolution_note")
        return self

    @model_validator(mode="after")
    def no_sensitive_blocker_text(self) -> "HandoffBlocker":
        _reject_sensitive_text(self.message, "message")
        return self


class HandoffUncertainty(FrozenHandoffModel):
    uncertainty_id: str = Field(min_length=1, max_length=160, pattern=LOCAL_ID_PATTERN)
    statement: str = Field(min_length=1, max_length=2000)
    source_artifact_ids: list[str] = Field(default_factory=list, max_length=50)
    source_fact_paths: list[str] = Field(default_factory=list, max_length=100)
    acknowledgement_required: Literal[True] = True
    acknowledged: bool = False
    acknowledged_by: ReviewerReference | None = None
    acknowledged_action_id: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def acknowledge_consistency(self) -> "HandoffUncertainty":
        if self.acknowledged and (self.acknowledged_by is None or not self.acknowledged_action_id):
            raise ValueError("acknowledged uncertainties require reviewer and action references")
        _reject_sensitive_text(self.statement, "statement")
        return self


class PendingHumanDecision(FrozenHandoffModel):
    decision_id: str = Field(min_length=1, max_length=160, pattern=LOCAL_ID_PATTERN)
    category: str = Field(min_length=1, max_length=120)
    question: str = Field(min_length=1, max_length=2000)
    target_artifact_ids: list[str] = Field(default_factory=list, max_length=50)
    status: Literal["pending", "resolved", "deferred"] = "pending"
    resolution_note: str | None = Field(default=None, max_length=2000)
    resolved_by: ReviewerReference | None = None
    resolved_action_id: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def resolution_consistency(self) -> "PendingHumanDecision":
        if self.status == "resolved" and (
            self.resolved_by is None or not self.resolved_action_id or not self.resolution_note
        ):
            raise ValueError("resolved decisions require reviewer, action, and resolution note")
        _reject_sensitive_text(self.question, "question")
        _reject_sensitive_text(self.resolution_note, "resolution_note")
        return self


class ExternalHandoffEvent(FrozenHandoffModel):
    event_id: str = Field(min_length=1, max_length=160, pattern=LOCAL_ID_PATTERN)
    event_type: Literal["handoff_sent", "handoff_received", "handoff_returned"] = "handoff_sent"
    timestamp: str = Field(default="not_recorded", max_length=40)
    reviewer_id: str = Field(min_length=1, max_length=120, pattern=LOCAL_ID_PATTERN)
    reviewer_role: str = Field(min_length=1, max_length=120)
    external_reference: str = Field(min_length=1, max_length=240, pattern=LOCAL_ID_PATTERN)
    packet_sha256: str = Field(pattern=SNAPSHOT_HASH_PATTERN)
    notes: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def no_sensitive_event_text(self) -> "ExternalHandoffEvent":
        for name in ("reviewer_id", "reviewer_role", "external_reference", "notes"):
            _reject_sensitive_text(getattr(self, name), name)
        return self


class HandoffArtifactManifestItem(FrozenHandoffModel):
    artifact_id: str = Field(min_length=1, max_length=160, pattern=LOCAL_ID_PATTERN)
    artifact_name: str = Field(min_length=1, max_length=240)
    artifact_type: str = Field(min_length=1, max_length=120)
    available: bool
    schema_version: str | None = Field(default=None, max_length=80)
    source_classification: SourceClassification
    sha256: str | None = Field(default=None, pattern=SNAPSHOT_HASH_PATTERN)
    canonical_payload_sha256: str = Field(default="0" * 64, pattern=SNAPSHOT_HASH_PATTERN)
    hash_algorithm: Literal["sha256"] = "sha256"
    digest_scope: Literal["file_bytes", "not_available"] = "file_bytes"
    media_type: Literal["application/json"] = "application/json"
    source_fact_paths: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def hash_consistency(self) -> "HandoffArtifactManifestItem":
        if self.available and (self.sha256 is None or self.digest_scope != "file_bytes"):
            raise ValueError("available artifacts require a file-byte SHA-256 digest")
        if not self.available and (self.sha256 is not None or self.digest_scope != "not_available"):
            raise ValueError("unavailable artifacts cannot claim a persisted file-byte digest")
        return self


class HandoffClaimPointer(FrozenHandoffModel):
    pointer_id: str = Field(min_length=1, max_length=160, pattern=LOCAL_ID_PATTERN)
    claim_id: str = Field(min_length=1, max_length=160, pattern=LOCAL_ID_PATTERN)
    artifact_id: str = Field(min_length=1, max_length=160, pattern=LOCAL_ID_PATTERN)
    evidence_ids: list[str] = Field(default_factory=list, max_length=500)
    source_fact_paths: list[str] = Field(default_factory=list, max_length=100)


class HandoffEvidencePointer(FrozenHandoffModel):
    pointer_id: str = Field(min_length=1, max_length=160, pattern=LOCAL_ID_PATTERN)
    evidence_id: str = Field(min_length=1, max_length=240, pattern=LOCAL_ID_PATTERN)
    artifact_id: str = Field(min_length=1, max_length=160, pattern=LOCAL_ID_PATTERN)
    role: Literal["supporting", "contradicting", "unresolved", "context_only", "excluded"]
    source_fact_paths: list[str] = Field(default_factory=list, max_length=100)


class ReviewReadiness(FrozenHandoffModel):
    ready_for_external_handoff: bool = False
    blocking_requirements: list[str] = Field(default_factory=list, max_length=100)
    open_blocker_count: int = Field(default=0, ge=0)
    unacknowledged_uncertainty_count: int = Field(default=0, ge=0)
    pending_human_decision_count: int = Field(default=0, ge=0)
    blocking_critic_count: int = Field(default=0, ge=0)
    unresolved_evidence_count: int = Field(default=0, ge=0)
    human_review_required: Literal[True] = True


class CaseStage(FrozenHandoffModel):
    stage_number: int = Field(ge=1, le=18)
    stage_id: str = Field(min_length=1, max_length=80, pattern=LOCAL_ID_PATTERN)
    label: str = Field(min_length=1, max_length=160)
    status: CaseStageStatus
    artifact_ids: list[str] = Field(default_factory=list, max_length=50)
    blocker_ids: list[str] = Field(default_factory=list, max_length=50)
    pending_decision_ids: list[str] = Field(default_factory=list, max_length=50)
    source_classifications: list[SourceClassification] = Field(default_factory=list, max_length=20)


class HandoffReviewAction(FrozenHandoffModel):
    action_id: str = Field(min_length=1, max_length=160, pattern=LOCAL_ID_PATTERN)
    action: HandoffActionType
    target_id: str | None = Field(default=None, max_length=160)
    reviewer_id: str = Field(min_length=1, max_length=120, pattern=LOCAL_ID_PATTERN)
    reviewer_role: str = Field(min_length=1, max_length=120)
    timestamp: str = Field(default="not_recorded", max_length=40)
    expected_revision: int | None = Field(default=None, ge=0)
    expected_snapshot_hash: str | None = Field(default=None, pattern=SNAPSHOT_HASH_PATTERN)
    before_value: Any = None
    after_value: Any = None
    resolution_note: str | None = Field(default=None, max_length=2000)
    external_event: ExternalHandoffEvent | None = None
    notes: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def bounded_and_safe(self) -> "HandoffReviewAction":
        for name, value in (
            ("before_value", self.before_value),
            ("after_value", self.after_value),
        ):
            if len(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)) > 30_000:
                raise ValueError(f"{name} must serialize to at most 30000 characters")
            _reject_sensitive_value(value, name)
        for name in ("reviewer_id", "reviewer_role", "resolution_note", "notes"):
            _reject_sensitive_text(getattr(self, name), name)
        return self


class HandoffReviewActionResult(FrozenHandoffModel):
    action_id: str = Field(min_length=1, max_length=160, pattern=LOCAL_ID_PATTERN)
    action: HandoffActionType
    result_status: HandoffActionResultStatus
    rejection_reason: HandoffRejectionReason | None = None
    message: str = Field(min_length=1, max_length=2000)
    current_status: HandoffState
    current_revision: int = Field(ge=0)
    current_snapshot_hash: str = Field(pattern=SNAPSHOT_HASH_PATTERN)
    authoritative_before: dict[str, Any] | None = None
    validated_after: dict[str, Any] | None = None
    reviewer_id: str
    reviewer_role: str
    timestamp: str

    @model_validator(mode="after")
    def consistent_result(self) -> "HandoffReviewActionResult":
        if self.result_status == HandoffActionResultStatus.APPLIED:
            if self.rejection_reason is not None or self.validated_after is None:
                raise ValueError("applied handoff results require validated after state")
        elif self.rejection_reason is None or self.validated_after is not None:
            raise ValueError("rejected handoff results require a reason and no after state")
        _reject_sensitive_text(self.message, "message")
        return self


class HandoffAuditEvent(FrozenHandoffModel):
    audit_id: str = Field(min_length=1, max_length=160, pattern=LOCAL_ID_PATTERN)
    event_type: HandoffEventType
    action_id: str | None = Field(default=None, max_length=160)
    result_status: HandoffActionResultStatus | None = None
    timestamp: str = Field(default="deterministic", max_length=40)
    from_status: HandoffState
    to_status: HandoffState
    revision: int = Field(ge=0)
    reviewer_id: str | None = Field(default=None, max_length=120)
    message: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def no_sensitive_audit_text(self) -> "HandoffAuditEvent":
        _reject_sensitive_text(self.reviewer_id, "reviewer_id")
        _reject_sensitive_text(self.message, "message")
        return self


class HandoffPacket(FrozenHandoffModel):
    packet_id: str = Field(min_length=1, max_length=160, pattern=LOCAL_ID_PATTERN)
    packet_version: Literal["insilicopop-handoff-packet-0.35.0"] = HANDOFF_PACKET_VERSION
    pseudonymous_case_id: str = Field(min_length=1, max_length=80, pattern=LOCAL_ID_PATTERN)
    report_status: Literal["draft_not_clinically_approved"] = "draft_not_clinically_approved"
    created_revision: int = Field(ge=0)
    artifact_manifest: list[HandoffArtifactManifestItem]
    source_hashes: dict[str, str]
    schema_versions: dict[str, str | None]
    claim_pointers: list[HandoffClaimPointer] = Field(default_factory=list)
    evidence_pointers: list[HandoffEvidencePointer] = Field(default_factory=list)
    packet_sha256: str = Field(pattern=SNAPSHOT_HASH_PATTERN)
    human_review_required: Literal[True] = True
    research_use_only: Literal[True] = True


class HandoffReceipt(FrozenHandoffModel):
    receipt_id: str = Field(min_length=1, max_length=160, pattern=LOCAL_ID_PATTERN)
    receipt_version: Literal["insilicopop-handoff-receipt-0.35.0"] = HANDOFF_RECEIPT_VERSION
    receipt_status: HandoffReceiptStatus
    packet_id: str = Field(min_length=1, max_length=160, pattern=LOCAL_ID_PATTERN)
    packet_sha256: str = Field(pattern=SNAPSHOT_HASH_PATTERN)
    handoff_state: HandoffState
    external_event_id: str | None = Field(default=None, max_length=160)
    reviewer_id: str | None = Field(default=None, max_length=120)
    reviewer_role: str | None = Field(default=None, max_length=120)
    external_reference: str | None = Field(default=None, max_length=240)
    issued_at: str | None = Field(default=None, max_length=40)
    receipt_sha256: str = Field(pattern=SNAPSHOT_HASH_PATTERN)
    report_status: Literal["draft_not_clinically_approved"] = "draft_not_clinically_approved"
    human_review_required: Literal[True] = True
    research_use_only: Literal[True] = True


class HandoffWorkspaceResult(FrozenHandoffModel):
    schema_version: Literal["0.35"] = HANDOFF_SCHEMA_VERSION
    handoff_version: Literal["insilicopop-structured-handoff-0.35.0"] = (
        "insilicopop-structured-handoff-0.35.0"
    )
    pseudonymous_case_id: str = Field(min_length=1, max_length=80, pattern=LOCAL_ID_PATTERN)
    status: HandoffState
    revision: int = Field(ge=0)
    snapshot_hash: str = Field(pattern=SNAPSHOT_HASH_PATTERN)
    case_stages: list[CaseStage] = Field(min_length=18, max_length=18)
    review_readiness: ReviewReadiness
    blockers: list[HandoffBlocker] = Field(default_factory=list, max_length=500)
    acknowledgement_required_uncertainties: list[HandoffUncertainty] = Field(
        default_factory=list, max_length=500
    )
    pending_human_decisions: list[PendingHumanDecision] = Field(default_factory=list, max_length=500)
    reviewer_references: list[ReviewerReference] = Field(default_factory=list, max_length=50)
    external_handoff_events: list[ExternalHandoffEvent] = Field(default_factory=list, max_length=100)
    requested_review_actions: list[HandoffReviewAction] = Field(default_factory=list, max_length=2000)
    applied_review_actions: list[HandoffReviewAction] = Field(default_factory=list, max_length=2000)
    review_action_results: list[HandoffReviewActionResult] = Field(default_factory=list, max_length=2000)
    audit_history: list[HandoffAuditEvent] = Field(default_factory=list, max_length=4000)
    artifact_manifest: list[HandoffArtifactManifestItem] = Field(min_length=9, max_length=9)
    source_hashes: dict[str, str]
    schema_versions: dict[str, str | None]
    claim_pointers: list[HandoffClaimPointer] = Field(default_factory=list, max_length=1000)
    evidence_pointers: list[HandoffEvidencePointer] = Field(default_factory=list, max_length=2000)
    handoff_packet: HandoffPacket
    handoff_receipt: HandoffReceipt
    report_status: Literal["draft_not_clinically_approved"] = "draft_not_clinically_approved"
    human_review_required: Literal[True] = True
    research_use_only: Literal[True] = True
    diagnosis_made: Literal[False] = False
    treatment_recommendation_made: Literal[False] = False
    final_acmg_classification_made: Literal[False] = False
    clinical_sign_out_made: Literal[False] = False
    external_llm_called: Literal[False] = False
    external_tools_executed: Literal[False] = False
    unrestricted_browsing_used: Literal[False] = False
    raw_genomic_files_parsed: Literal[False] = False
    clinical_approval_granted: Literal[False] = False

    @property
    def handoff_state(self) -> HandoffState:
        return self.status

    @model_validator(mode="after")
    def validate_frozen_shape(self) -> "HandoffWorkspaceResult":
        expected_ids = [
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
        actual_ids = [item.stage_id for item in self.case_stages]
        if actual_ids != expected_ids:
            raise ValueError("v0.35 case stages must use the frozen 18-stage order")
        action_ids = [item.action_id for item in self.requested_review_actions]
        if len(action_ids) != len(set(action_ids)):
            raise ValueError("requested handoff action identifiers must be unique")
        reviewer_ids = [item.reviewer_id for item in self.reviewer_references]
        if len(reviewer_ids) != len(set(reviewer_ids)):
            raise ValueError("handoff reviewer references must be unique")
        if self.handoff_receipt.handoff_state != self.status:
            raise ValueError("active handoff receipt state must match the workspace state")
        if (
            self.handoff_receipt.packet_id != self.handoff_packet.packet_id
            or self.handoff_receipt.packet_sha256 != self.handoff_packet.packet_sha256
        ):
            raise ValueError("active handoff receipt must reference the current packet")
        expected_receipt_status = (
            HandoffReceiptStatus.ISSUED
            if self.external_handoff_events
            else HandoffReceiptStatus.NOT_ISSUED
        )
        if self.handoff_receipt.receipt_status != expected_receipt_status:
            raise ValueError("active handoff receipt status must match external event history")
        return self


def _reject_sensitive_text(value: str | None, field_name: str) -> None:
    if value and _SENSITIVE_TEXT_PATTERN.search(value):
        raise ValueError(f"{field_name} must remain pseudonymous and redacted")


def _reject_sensitive_value(value: Any, field_name: str) -> None:
    if isinstance(value, str):
        _reject_sensitive_text(value, field_name)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key).lower().replace("-", "_")
            if any(
                marker in key_text
                for marker in ("api_key", "access_token", "authorization", "password", "secret")
            ):
                raise ValueError(f"{field_name} must not contain credentials or secrets")
            _reject_sensitive_value(item, f"{field_name}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _reject_sensitive_value(item, f"{field_name}[{index}]")
