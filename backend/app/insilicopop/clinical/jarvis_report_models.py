from __future__ import annotations

import json
import re
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


JARVIS_REPORT_SCHEMA_VERSION = "0.34"
JARVIS_BRIEFING_VERSION = "insilicopop-jarvis-briefing-0.34.0"
SYNTHESIS_VERSION = "insilicopop-source-grounded-synthesis-0.34.0"
CRITIC_SUITE_VERSION = "insilicopop-bounded-critic-suite-0.34.0"
REPORT_STUDIO_VERSION = "insilicopop-report-studio-0.34.0"
LOCAL_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"
_SENSITIVE_TEXT_PATTERN = re.compile(
    r"(?i)(?:"
    r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b|"
    r"(?:\+\d[\d ()-]{8,}\d|\b\d{10,15}\b)|"
    r"\b(?:medical record number|hospital number|patient name|date of birth)\s*[:=]|"
    r"\b(?:api[_ -]?key|access[_ -]?token|authorization|password|client[_ -]?secret)\s*[:=]|"
    r"\bbearer\s+[A-Za-z0-9._~-]+"
    r")"
)


class FrozenJarvisModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class ClaimOriginCategory(str, Enum):
    SUPPLIED_FACT = "supplied_fact"
    NORMALIZED_FACT = "normalized_fact"
    DETERMINISTIC_FINDING = "deterministic_finding"
    RETRIEVED_SOURCE_CLAIM = "retrieved_source_claim"
    SPECIALIST_AGENT_PROPOSAL = "specialist_agent_proposal"
    HUMAN_DECISION = "human_decision"


class ClaimSupportStatus(str, Enum):
    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    CONFLICTING = "conflicting"
    UNRESOLVED = "unresolved"
    UNSUPPORTED = "unsupported"


class ReportHumanReviewStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    EDITED = "edited"
    REJECTED = "rejected"
    MORE_INFORMATION_REQUESTED = "more_information_requested"


class CriticType(str, Enum):
    CITATION_SUPPORT = "citation_support"
    SCIENTIFIC_CONSISTENCY = "scientific_consistency"
    EVIDENCE_CONFLICT = "evidence_conflict"
    SAFETY_LANGUAGE = "safety_language"
    PRIVACY = "privacy"
    PROVENANCE = "provenance"


class CriticSeverity(str, Enum):
    INFORMATION = "information"
    WARNING = "warning"
    BLOCKING = "blocking"


class ReportReviewActionType(str, Enum):
    ACCEPT = "accept"
    EDIT = "edit"
    REJECT = "reject"
    REQUEST_MORE_INFORMATION = "request_more_information"


class ReportReviewActionResultStatus(str, Enum):
    APPLIED = "applied"
    REJECTED = "rejected"


class ReportReviewRejectionReason(str, Enum):
    TARGET_NOT_FOUND = "target_not_found"
    TARGET_TYPE_MISMATCH = "target_type_mismatch"
    BEFORE_VALUE_REQUIRED = "before_value_required"
    BEFORE_VALUE_MISMATCH = "before_value_mismatch"
    AFTER_VALUE_REQUIRED = "after_value_required"
    AFTER_VALUE_MISMATCH = "after_value_mismatch"
    INVALID_TRANSITION = "invalid_transition"
    INVALID_EDIT_PAYLOAD = "invalid_edit_payload"
    FORBIDDEN_EDIT = "forbidden_edit"
    UNSUPPORTED_CLAIM_REFERENCE = "unsupported_claim_reference"


class ProposedSynthesisClaim(FrozenJarvisModel):
    proposal_id: str = Field(min_length=1, max_length=100, pattern=LOCAL_ID_PATTERN)
    statement: str = Field(min_length=1, max_length=4000)
    source_fact_paths: list[str] = Field(default_factory=list, max_length=100)
    source_evidence_ids: list[str] = Field(default_factory=list, max_length=500)
    source_specialist_output_ids: list[str] = Field(default_factory=list, max_length=100)
    source_candidate_criterion_ids: list[str] = Field(default_factory=list, max_length=100)
    stated_support_status: ClaimSupportStatus = ClaimSupportStatus.UNRESOLVED
    uncertainty_language: str = Field(
        default="Proposed claim; support and wording require human review.",
        min_length=1,
        max_length=1000,
    )

    @model_validator(mode="after")
    def reject_sensitive_text(self) -> "ProposedSynthesisClaim":
        if _SENSITIVE_TEXT_PATTERN.search(
            f"{self.statement}\n{self.uncertainty_language}"
        ):
            raise ValueError(
                "proposed claims must not contain direct identifiers or secrets"
            )
        return self


class ReportHumanReviewAction(FrozenJarvisModel):
    action_id: str = Field(min_length=1, max_length=100, pattern=LOCAL_ID_PATTERN)
    action: ReportReviewActionType
    target_type: Literal["report_section"]
    target_id: str = Field(min_length=1, max_length=120, pattern=LOCAL_ID_PATTERN)
    reviewer_role: str = Field(min_length=1, max_length=120)
    reviewer_id: str | None = Field(default=None, max_length=120)
    timestamp: str = Field(min_length=1, max_length=40)
    before_value: Any = None
    after_value: Any = None
    notes: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def bounded_snapshots(self) -> "ReportHumanReviewAction":
        for label, value in (
            ("before_value", self.before_value),
            ("after_value", self.after_value),
        ):
            if len(
                json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
            ) > 30_000:
                raise ValueError(f"{label} must serialize to at most 30000 characters")
        review_text = json.dumps(
            {
                "before_value": self.before_value,
                "after_value": self.after_value,
                "notes": self.notes,
            },
            sort_keys=True,
            default=str,
        )
        if _SENSITIVE_TEXT_PATTERN.search(review_text):
            raise ValueError(
                "report review actions must not contain direct identifiers or secrets"
            )
        return self


class JarvisSynthesisReportWorkspaceRequest(FrozenJarvisModel):
    schema_version: Literal["0.34"] = JARVIS_REPORT_SCHEMA_VERSION
    proposed_claims: list[ProposedSynthesisClaim] = Field(
        default_factory=list, max_length=500
    )
    review_actions: list[ReportHumanReviewAction] = Field(
        default_factory=list, max_length=2000
    )
    human_review_required: Literal[True] = True

    @model_validator(mode="after")
    def unique_identifiers(self) -> "JarvisSynthesisReportWorkspaceRequest":
        proposal_ids = [item.proposal_id for item in self.proposed_claims]
        action_ids = [item.action_id for item in self.review_actions]
        if len(proposal_ids) != len(set(proposal_ids)):
            raise ValueError("proposed claim identifiers must be unique")
        if len(action_ids) != len(set(action_ids)):
            raise ValueError("report review action identifiers must be unique")
        return self


class JarvisBriefingItem(FrozenJarvisModel):
    briefing_item_id: str
    category: Literal[
        "current_case_state",
        "missing_information",
        "readiness_and_strategy",
        "result_and_evidence",
        "specialist_disagreement",
        "unresolved_conflict",
        "pending_human_decision",
        "limitation",
        "next_workflow_checkpoint",
    ]
    statement: str = Field(min_length=1, max_length=2000)
    source_fact_paths: list[str] = Field(default_factory=list)
    source_evidence_ids: list[str] = Field(default_factory=list)
    human_review_required: Literal[True] = True


class JarvisCaseBriefing(FrozenJarvisModel):
    briefing_id: str
    briefing_status: Literal["bounded_structured_briefing"] = (
        "bounded_structured_briefing"
    )
    items: list[JarvisBriefingItem]
    missing_information_count: int = 0
    unresolved_conflict_count: int = 0
    pending_human_decision_count: int = 0
    next_workflow_checkpoints: list[str] = Field(default_factory=list)
    general_assistant_mode: Literal[False] = False
    browsing_used: Literal[False] = False
    agents_spawned: Literal[False] = False
    evidence_modified: Literal[False] = False
    conclusions_approved: Literal[False] = False


class SynthesisClaim(FrozenJarvisModel):
    claim_id: str = Field(min_length=1, max_length=120, pattern=LOCAL_ID_PATTERN)
    statement: str = Field(min_length=1, max_length=4000)
    origin_category: ClaimOriginCategory
    support_status: ClaimSupportStatus
    uncertainty_language: str = Field(min_length=1, max_length=1000)
    source_fact_paths: list[str] = Field(default_factory=list, max_length=100)
    source_evidence_ids: list[str] = Field(default_factory=list, max_length=500)
    source_specialist_output_ids: list[str] = Field(default_factory=list, max_length=100)
    source_candidate_criterion_ids: list[str] = Field(
        default_factory=list, max_length=100
    )
    source_human_decision_ids: list[str] = Field(default_factory=list, max_length=100)
    human_review_status: ReportHumanReviewStatus = ReportHumanReviewStatus.PENDING
    eligible_for_report: bool = False
    proposal_status: Literal["proposed_not_approved"] = "proposed_not_approved"
    human_review_required: Literal[True] = True


class ClaimEvidenceDrillDown(FrozenJarvisModel):
    claim_id: str
    source_fact_paths: list[str] = Field(default_factory=list)
    evidence_ledger_entry_ids: list[str] = Field(default_factory=list)
    specialist_output_ids: list[str] = Field(default_factory=list)
    candidate_criterion_ids: list[str] = Field(default_factory=list)
    human_decision_ids: list[str] = Field(default_factory=list)
    support_status: ClaimSupportStatus
    conflict_visible: bool = False
    provenance_complete: bool = False


class CriticFinding(FrozenJarvisModel):
    critic_finding_id: str
    critic_type: CriticType
    severity: CriticSeverity
    code: str
    message: str = Field(min_length=1, max_length=2000)
    target_type: Literal[
        "workspace", "synthesis_claim", "report_section", "evidence_conflict"
    ]
    target_id: str
    source_ids: list[str] = Field(default_factory=list)
    proposed_correction: str | None = Field(default=None, max_length=2000)
    mutation_applied: Literal[False] = False
    human_review_required: Literal[True] = True


class CriticRun(FrozenJarvisModel):
    critic_run_id: str
    critic_type: CriticType
    status: Literal["completed_non_mutating"] = "completed_non_mutating"
    finding_ids: list[str] = Field(default_factory=list)
    mutation_applied: Literal[False] = False
    disputes_settled: Literal[False] = False
    conclusions_approved: Literal[False] = False


class DraftReportSection(FrozenJarvisModel):
    section_id: str = Field(min_length=1, max_length=120, pattern=LOCAL_ID_PATTERN)
    section_type: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=240)
    narrative: str = Field(min_length=1, max_length=20_000)
    claim_ids: list[str] = Field(default_factory=list, max_length=1000)
    citation_ids: list[str] = Field(default_factory=list, max_length=1000)
    narrative_status: Literal["draft_not_clinically_approved"] = (
        "draft_not_clinically_approved"
    )
    human_review_status: ReportHumanReviewStatus = ReportHumanReviewStatus.PENDING
    reviewer_notes: str | None = Field(default=None, max_length=2000)
    human_review_required: Literal[True] = True
    clinically_approved: Literal[False] = False


class ReportReviewActionResult(FrozenJarvisModel):
    action_id: str
    action: ReportReviewActionType
    target_type: Literal["report_section"]
    target_id: str
    result_status: ReportReviewActionResultStatus
    rejection_reason: ReportReviewRejectionReason | None = None
    message: str = Field(min_length=1, max_length=1000)
    authoritative_before: dict[str, Any] | None = None
    validated_after: dict[str, Any] | None = None
    reviewer_role: str
    reviewer_id: str | None = None
    timestamp: str

    @model_validator(mode="after")
    def consistent_result(self) -> "ReportReviewActionResult":
        if self.result_status == ReportReviewActionResultStatus.APPLIED:
            if self.rejection_reason is not None or self.validated_after is None:
                raise ValueError("applied review results require validated after state")
        elif self.rejection_reason is None or self.validated_after is not None:
            raise ValueError("rejected review results require a reason and no after state")
        return self


class JarvisReportReproducibility(FrozenJarvisModel):
    source_artifact_versions: dict[str, str]
    source_artifact_hashes: dict[str, str]
    synthesis_claim_ids: list[str]
    report_section_ids: list[str]
    critic_run_ids: list[str]
    critic_finding_ids: list[str]
    requested_review_actions: list[dict[str, Any]]
    applied_review_actions: list[dict[str, Any]]
    review_action_results: list[dict[str, Any]]
    workspace_hash: str


class JarvisSynthesisReportWorkspaceResult(FrozenJarvisModel):
    schema_version: Literal["0.34"] = JARVIS_REPORT_SCHEMA_VERSION
    briefing_version: Literal[
        "insilicopop-jarvis-briefing-0.34.0"
    ] = JARVIS_BRIEFING_VERSION
    synthesis_version: Literal[
        "insilicopop-source-grounded-synthesis-0.34.0"
    ] = SYNTHESIS_VERSION
    critic_suite_version: Literal[
        "insilicopop-bounded-critic-suite-0.34.0"
    ] = CRITIC_SUITE_VERSION
    report_studio_version: Literal[
        "insilicopop-report-studio-0.34.0"
    ] = REPORT_STUDIO_VERSION
    pseudonymous_case_id: str
    briefing: JarvisCaseBriefing
    synthesis_claims: list[SynthesisClaim]
    excluded_proposed_claims: list[SynthesisClaim]
    claim_evidence_drill_down: list[ClaimEvidenceDrillDown]
    critic_runs: list[CriticRun]
    critic_findings: list[CriticFinding]
    report_sections: list[DraftReportSection]
    cited_draft_narrative_section_id: str
    pending_human_decision_ids: list[str]
    requested_review_actions: list[ReportHumanReviewAction]
    applied_review_actions: list[ReportHumanReviewAction]
    review_action_results: list[ReportReviewActionResult]
    reproducibility: JarvisReportReproducibility
    provider: Literal["deterministic"] = "deterministic"
    model: Literal["bounded-template-synthesis"] = "bounded-template-synthesis"
    external_llm_called: Literal[False] = False
    external_tools_executed: Literal[False] = False
    unrestricted_browsing_used: Literal[False] = False
    agents_spawned: Literal[False] = False
    critics_mutated_sources: Literal[False] = False
    unsupported_claims_included_as_factual_conclusions: Literal[False] = False
    report_status: Literal["draft_not_clinically_approved"] = (
        "draft_not_clinically_approved"
    )
    human_review_required: Literal[True] = True
    research_use_only: Literal[True] = True
    diagnosis_made: Literal[False] = False
    treatment_recommendation_made: Literal[False] = False
    test_order_placed: Literal[False] = False
    final_acmg_classification_made: Literal[False] = False
    clinical_sign_out_made: Literal[False] = False
    causality_claim_made: Literal[False] = False
    recurrence_risk_calculated: Literal[False] = False
    penetrance_calculated: Literal[False] = False
