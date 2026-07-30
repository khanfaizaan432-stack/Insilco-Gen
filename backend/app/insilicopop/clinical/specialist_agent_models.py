from __future__ import annotations

import json
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


SPECIALIST_AGENT_SCHEMA_VERSION = "0.33"
AGENT_REGISTRY_VERSION = "insilicopop-specialist-agent-registry-0.33.0"
AGENT_CONTROLLER_VERSION = "insilicopop-bounded-agent-controller-0.33.0"
AGENT_OUTPUT_VALIDATOR_VERSION = "insilicopop-agent-output-validator-0.33.0"
AGENT_SAFETY_POLICY_VERSION = "insilicopop-specialist-agent-safety-0.33.0"
CANDIDATE_RULESET_VERSION = "insilicopop-candidate-acmg-organizer-0.33.0"
CANDIDATE_VOCABULARY_VERSION = "insilicopop-acmg-amp-code-vocabulary-0.33.0"
LOCAL_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"


class FrozenSpecialistModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class AgentRole(str, Enum):
    PRE_TEST_STRATEGY_REVIEW = "pre_test_strategy_review"
    GENE_DISEASE_EVIDENCE = "gene_disease_evidence"
    VARIANT_DATABASE_EVIDENCE = "variant_database_evidence"
    LITERATURE_EVIDENCE = "literature_evidence"
    POPULATION_FREQUENCY_EVIDENCE = "population_frequency_evidence"
    CANDIDATE_ACMG_EVIDENCE = "candidate_acmg_evidence"
    EVIDENCE_CONFLICT_REVIEWER = "evidence_conflict_reviewer"
    SAFETY_PROVENANCE_AUDITOR = "safety_provenance_auditor"


class AgentTaskType(str, Enum):
    REVIEW_PRE_TEST_STRATEGY = "review_pre_test_strategy"
    REVIEW_GENE_DISEASE_EVIDENCE = "review_gene_disease_evidence"
    REVIEW_VARIANT_DATABASE_EVIDENCE = "review_variant_database_evidence"
    REVIEW_LITERATURE_EVIDENCE = "review_literature_evidence"
    REVIEW_POPULATION_FREQUENCY_EVIDENCE = "review_population_frequency_evidence"
    PROPOSE_CANDIDATE_ACMG_EVIDENCE = "propose_candidate_acmg_evidence"
    REVIEW_EVIDENCE_CONFLICT = "review_evidence_conflict"
    AUDIT_AGENT_OUTPUT = "audit_agent_output"


class AgentExecutionStatus(str, Enum):
    NOT_STARTED = "not_started"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    BLOCKED_BY_POLICY = "blocked_by_policy"
    REQUIRES_RULE_REVIEW = "requires_rule_review"
    BUDGET_EXHAUSTED = "budget_exhausted"
    TIMED_OUT = "timed_out"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    TOOL_UNAVAILABLE = "tool_unavailable"
    INVALID_OUTPUT = "invalid_output"
    CANCELLED = "cancelled"
    FAILED = "failed"


class TaskApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    REQUIRES_REVIEW = "requires_review"


class SpawnRequestedBy(str, Enum):
    HUMAN_REVIEWER = "human_reviewer"
    CENTRAL_CONTROLLER = "central_controller"
    SPECIALIST_AGENT = "specialist_agent"


class CandidateCriterionCode(str, Enum):
    PVS1 = "PVS1"
    PS1 = "PS1"
    PS2 = "PS2"
    PS3 = "PS3"
    PS4 = "PS4"
    PM1 = "PM1"
    PM2 = "PM2"
    PM3 = "PM3"
    PM4 = "PM4"
    PM5 = "PM5"
    PM6 = "PM6"
    PP1 = "PP1"
    PP2 = "PP2"
    PP3 = "PP3"
    PP4 = "PP4"
    PP5 = "PP5"
    BA1 = "BA1"
    BS1 = "BS1"
    BS2 = "BS2"
    BS3 = "BS3"
    BS4 = "BS4"
    BP1 = "BP1"
    BP2 = "BP2"
    BP3 = "BP3"
    BP4 = "BP4"
    BP5 = "BP5"
    BP6 = "BP6"
    BP7 = "BP7"


class CandidateStatus(str, Enum):
    CANDIDATE_ONLY = "candidate_only"
    INSUFFICIENT_SUPPORT = "insufficient_support"
    CONFLICTING_SUPPORT = "conflicting_support"
    NOT_APPLICABLE = "not_applicable"
    REQUIRES_RULE_REVIEW = "requires_rule_review"
    REJECTED_BY_REVIEWER = "rejected_by_reviewer"
    ACCEPTED_FOR_DISCUSSION = "accepted_for_discussion"
    DEFERRED = "deferred"


class SpecialistReviewStatus(str, Enum):
    UNREVIEWED = "unreviewed"
    PENDING = "pending"
    ACCEPTED_FOR_DISCUSSION = "accepted_for_discussion"
    EDITED = "edited"
    REJECTED = "rejected"
    DEFERRED = "deferred"
    MORE_INFORMATION_REQUESTED = "more_information_requested"
    NOT_APPLICABLE = "not_applicable"
    CONFLICTING = "conflicting"


class SpecialistReviewActionType(str, Enum):
    APPROVE_AGENT_TASK = "approve_agent_task"
    REJECT_AGENT_TASK = "reject_agent_task"
    CANCEL_AGENT_TASK = "cancel_agent_task"
    RERUN_WITH_SAME_INPUTS = "rerun_with_same_inputs"
    RERUN_WITH_EDITED_INPUTS = "rerun_with_edited_inputs"
    ACCEPT_AGENT_OUTPUT_FOR_DISCUSSION = "accept_agent_output_for_discussion"
    EDIT_AGENT_OUTPUT = "edit_agent_output"
    REJECT_AGENT_OUTPUT = "reject_agent_output"
    DEFER_AGENT_OUTPUT = "defer_agent_output"
    REQUEST_MORE_INFORMATION = "request_more_information"
    ACCEPT_CANDIDATE_FOR_DISCUSSION = "accept_candidate_for_discussion"
    EDIT_CANDIDATE = "edit_candidate"
    REJECT_CANDIDATE = "reject_candidate"
    MARK_CANDIDATE_NOT_APPLICABLE = "mark_candidate_not_applicable"
    MARK_CANDIDATE_CONFLICTING = "mark_candidate_conflicting"
    DEFER_CANDIDATE = "defer_candidate"
    RECORD_EXTERNAL_ACMG_ASSESSMENT = "record_external_acmg_assessment"
    RECORD_EXTERNAL_CLASSIFICATION = "record_external_classification"


class SpecialistReviewActionResultStatus(str, Enum):
    APPLIED = "applied"
    REJECTED = "rejected"


class SpecialistReviewRejectionReason(str, Enum):
    TARGET_NOT_FOUND = "target_not_found"
    TARGET_TYPE_MISMATCH = "target_type_mismatch"
    ACTION_TARGET_MISMATCH = "action_target_mismatch"
    INVALID_TRANSITION = "invalid_transition"
    BEFORE_VALUE_REQUIRED = "before_value_required"
    BEFORE_VALUE_MISMATCH = "before_value_mismatch"
    AFTER_VALUE_REQUIRED = "after_value_required"
    AFTER_VALUE_MISMATCH = "after_value_mismatch"
    INVALID_EDIT_PAYLOAD = "invalid_edit_payload"
    FORBIDDEN_EDIT = "forbidden_edit"


class BudgetProfile(FrozenSpecialistModel):
    profile_id: str = Field(default="bounded_default", min_length=1, max_length=80, pattern=LOCAL_ID_PATTERN)
    maximum_steps: int = Field(default=4, ge=1, le=100)
    maximum_calls: int = Field(default=1, ge=0, le=100)
    maximum_tokens: int = Field(default=2000, ge=1, le=1_000_000)
    maximum_cost: float = Field(default=0.0, ge=0, le=10_000)
    maximum_runtime_seconds: float = Field(default=10.0, gt=0, le=3600)


class SpecialistAgentDefinition(FrozenSpecialistModel):
    agent_id: str = Field(min_length=1, max_length=100, pattern=LOCAL_ID_PATTERN)
    agent_version: str = Field(min_length=1, max_length=80)
    display_name: str = Field(min_length=1, max_length=160)
    agent_role: AgentRole
    description: str = Field(min_length=1, max_length=1000)
    enabled: bool = True
    allowed_task_types: list[AgentTaskType] = Field(min_length=1, max_length=20)
    allowed_input_types: list[str] = Field(default_factory=list, max_length=30)
    allowed_evidence_domains: list[str] = Field(default_factory=list, max_length=30)
    allowed_tools: list[str] = Field(default_factory=list, max_length=20)
    allowed_source_types: list[str] = Field(default_factory=list, max_length=30)
    may_use_external_llm: bool = False
    may_use_local_retrieval: bool = False
    may_spawn_agents: Literal[False] = False
    maximum_steps: int = Field(ge=1, le=100)
    maximum_calls: int = Field(ge=0, le=100)
    maximum_tokens: int = Field(ge=1, le=1_000_000)
    maximum_cost: float = Field(ge=0, le=10_000)
    maximum_runtime_seconds: float = Field(gt=0, le=3600)
    required_output_schema: str
    fallback_policy: str
    safety_policy_version: Literal["insilicopop-specialist-agent-safety-0.33.0"] = AGENT_SAFETY_POLICY_VERSION
    registry_version: Literal["insilicopop-specialist-agent-registry-0.33.0"] = AGENT_REGISTRY_VERSION


class ProviderPolicy(FrozenSpecialistModel):
    provider: Literal["mock", "openai_compatible"] = "mock"
    model: str = Field(default="deterministic-specialist-fixture", min_length=1, max_length=160)
    external_llm_use_approved: bool = False
    session_valid: bool = False
    session_stale: bool = False
    provider_available: bool = True


class ToolPolicy(FrozenSpecialistModel):
    allowed_tools: list[str] = Field(default_factory=list, max_length=20)
    local_retrieval_allowed: bool = False
    unrestricted_web_allowed: Literal[False] = False
    arbitrary_tool_execution_allowed: Literal[False] = False


class SafetyPolicy(FrozenSpecialistModel):
    policy_version: Literal["insilicopop-specialist-agent-safety-0.33.0"] = AGENT_SAFETY_POLICY_VERSION
    diagnosis_allowed: Literal[False] = False
    treatment_recommendation_allowed: Literal[False] = False
    test_ordering_allowed: Literal[False] = False
    recurrence_risk_calculation_allowed: Literal[False] = False
    penetrance_calculation_allowed: Literal[False] = False
    hidden_relationship_inference_allowed: Literal[False] = False
    protected_attribute_inference_allowed: Literal[False] = False
    majority_vote_allowed: Literal[False] = False
    recursive_spawning_allowed: Literal[False] = False


class AgentSpawnRequest(FrozenSpecialistModel):
    spawn_request_id: str = Field(min_length=1, max_length=100, pattern=LOCAL_ID_PATTERN)
    case_id: str = Field(min_length=1, max_length=100, pattern=LOCAL_ID_PATTERN)
    requested_agent_id: str = Field(min_length=1, max_length=100, pattern=LOCAL_ID_PATTERN)
    requested_task_type: AgentTaskType
    requested_by: SpawnRequestedBy
    request_reason: str = Field(min_length=1, max_length=1000)
    structured_input_ids: list[str] = Field(default_factory=list, max_length=500)
    ledger_entry_ids: list[str] = Field(default_factory=list, max_length=1000)
    finding_ids: list[str] = Field(default_factory=list, max_length=500)
    strategy_option_ids: list[str] = Field(default_factory=list, max_length=500)
    conflict_group_ids: list[str] = Field(default_factory=list, max_length=500)
    human_review_status: TaskApprovalStatus = TaskApprovalStatus.PENDING
    budget_profile: BudgetProfile = Field(default_factory=BudgetProfile)
    provider_policy: ProviderPolicy = Field(default_factory=ProviderPolicy)
    created_at: str = Field(min_length=1, max_length=40)


class CandidateCriterionRequest(FrozenSpecialistModel):
    candidate_request_id: str = Field(min_length=1, max_length=100, pattern=LOCAL_ID_PATTERN)
    spawn_request_id: str = Field(min_length=1, max_length=100, pattern=LOCAL_ID_PATTERN)
    finding_id: str = Field(min_length=1, max_length=100, pattern=LOCAL_ID_PATTERN)
    criterion_code: CandidateCriterionCode
    criterion_family: str = Field(min_length=1, max_length=80)
    proposed_strength: str | None = Field(default=None, max_length=80)
    candidate_rule_id: str = Field(min_length=1, max_length=120, pattern=LOCAL_ID_PATTERN)
    candidate_rule_version: str = Field(min_length=1, max_length=120)
    source_ledger_entry_ids: list[str] = Field(default_factory=list, max_length=500)
    contradicting_ledger_entry_ids: list[str] = Field(default_factory=list, max_length=500)
    supporting_observations: list[str] = Field(default_factory=list, max_length=100)
    missing_prerequisites: list[str] = Field(default_factory=list, max_length=100)
    applicability_notes: list[str] = Field(default_factory=list, max_length=100)
    gene_disease_context: str | None = Field(default=None, max_length=1000)
    mechanism_context: str | None = Field(default=None, max_length=1000)
    inheritance_context: str | None = Field(default=None, max_length=1000)
    phenotype_context: str | None = Field(default=None, max_length=1000)
    technical_limitations: list[str] = Field(default_factory=list, max_length=100)


class SpecialistHumanReviewAction(FrozenSpecialistModel):
    action_id: str = Field(min_length=1, max_length=100, pattern=LOCAL_ID_PATTERN)
    action: SpecialistReviewActionType
    target_type: Literal["spawn_request", "agent_output", "candidate_criterion", "external_acmg_assessment"]
    target_id: str = Field(min_length=1, max_length=120, pattern=LOCAL_ID_PATTERN)
    reviewer_role: str = Field(min_length=1, max_length=120)
    reviewer_id: str | None = Field(default=None, max_length=120)
    timestamp: str = Field(min_length=1, max_length=40)
    before_value: Any = None
    after_value: Any = None
    notes: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def bounded_values(self) -> "SpecialistHumanReviewAction":
        for label, value in (
            ("before_value", self.before_value),
            ("after_value", self.after_value),
        ):
            if len(
                json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
            ) > 20_000:
                raise ValueError(f"{label} must serialize to at most 20000 characters")
        return self


class SpecialistReviewActionResult(FrozenSpecialistModel):
    action_id: str = Field(min_length=1, max_length=100, pattern=LOCAL_ID_PATTERN)
    action: SpecialistReviewActionType
    target_type: Literal[
        "spawn_request",
        "agent_output",
        "candidate_criterion",
        "external_acmg_assessment",
    ]
    target_id: str = Field(min_length=1, max_length=120, pattern=LOCAL_ID_PATTERN)
    result_status: SpecialistReviewActionResultStatus
    rejection_reason: SpecialistReviewRejectionReason | None = None
    message: str = Field(min_length=1, max_length=500)
    authoritative_before: dict[str, Any] | None = None
    validated_after: dict[str, Any] | None = None
    validation_categories: list[str] = Field(default_factory=list, max_length=20)
    reviewer_role: str = Field(min_length=1, max_length=120)
    reviewer_id: str | None = Field(default=None, max_length=120)
    timestamp: str = Field(min_length=1, max_length=40)

    @model_validator(mode="after")
    def consistent_result(self) -> "SpecialistReviewActionResult":
        if self.result_status == SpecialistReviewActionResultStatus.APPLIED:
            if self.rejection_reason is not None or self.validated_after is None:
                raise ValueError("applied review results require validated after state")
        elif self.rejection_reason is None or self.validated_after is not None:
            raise ValueError("rejected review results require a reason and no after state")
        return self


class ExternalAcmgAssessment(FrozenSpecialistModel):
    external_assessment_id: str = Field(min_length=1, max_length=100, pattern=LOCAL_ID_PATTERN)
    finding_id: str = Field(min_length=1, max_length=100, pattern=LOCAL_ID_PATTERN)
    external_acmg_assessment_recorded: Literal[True] = True
    external_source: str = Field(min_length=1, max_length=240)
    external_assessment_date: str | None = Field(default=None, max_length=40)
    external_criteria_as_reported: list[str] = Field(default_factory=list, max_length=100)
    external_classification_as_reported: str | None = Field(default=None, max_length=240)
    verification_status: SpecialistReviewStatus = SpecialistReviewStatus.UNREVIEWED
    source_document_id: str | None = Field(default=None, max_length=120)
    reviewer_notes: str | None = Field(default=None, max_length=2000)
    required_wording: Literal[
        "External ACMG assessment recorded; not assigned by InSilicoPop."
    ] = "External ACMG assessment recorded; not assigned by InSilicoPop."


class SpecialistAgentWorkspaceRequest(FrozenSpecialistModel):
    schema_version: Literal["0.33"] = SPECIALIST_AGENT_SCHEMA_VERSION
    spawn_requests: list[AgentSpawnRequest] = Field(default_factory=list, max_length=500)
    candidate_requests: list[CandidateCriterionRequest] = Field(default_factory=list, max_length=500)
    review_actions: list[SpecialistHumanReviewAction] = Field(default_factory=list, max_length=2000)
    external_acmg_assessments: list[ExternalAcmgAssessment] = Field(default_factory=list, max_length=500)
    human_review_required: Literal[True] = True

    @model_validator(mode="after")
    def unique_identifiers(self) -> "SpecialistAgentWorkspaceRequest":
        groups = {
            "spawn request": [item.spawn_request_id for item in self.spawn_requests],
            "candidate request": [item.candidate_request_id for item in self.candidate_requests],
            "review action": [item.action_id for item in self.review_actions],
            "external ACMG assessment": [
                item.external_assessment_id for item in self.external_acmg_assessments
            ],
        }
        for label, identifiers in groups.items():
            if len(identifiers) != len(set(identifiers)):
                raise ValueError(f"{label} identifiers must be unique")
        spawn_ids = set(groups["spawn request"])
        if any(
            item.spawn_request_id not in spawn_ids
            for item in self.candidate_requests
        ):
            raise ValueError("candidate requests must reference an existing spawn request")
        return self


class AgentTaskEnvelope(FrozenSpecialistModel):
    agent_task_id: str
    case_id: str
    agent_id: str
    agent_version: str
    task_type: AgentTaskType
    structured_case_snapshot: dict[str, Any]
    allowed_fact_ids: list[str]
    allowed_finding_ids: list[str]
    allowed_strategy_option_ids: list[str]
    allowed_ledger_entry_ids: list[str]
    allowed_conflict_group_ids: list[str]
    input_hash: str
    budget: BudgetProfile
    tool_policy: ToolPolicy
    provider_policy: ProviderPolicy
    safety_policy: SafetyPolicy
    requested_at: str


class AgentStructuredObservation(FrozenSpecialistModel):
    observation_id: str
    observation_type: str
    statement: str
    source_fact_ids: list[str] = Field(default_factory=list)
    source_finding_ids: list[str] = Field(default_factory=list)
    source_strategy_option_ids: list[str] = Field(default_factory=list)
    source_ledger_entry_ids: list[str] = Field(default_factory=list)
    source_conflict_group_ids: list[str] = Field(default_factory=list)
    position: str | None = None


class AgentSafetyReview(FrozenSpecialistModel):
    passed: bool
    review_status: Literal["review_ready", "blocked_by_policy", "invalid_output"]
    unsupported_source_references: list[str] = Field(default_factory=list)
    forbidden_language_matches: list[str] = Field(default_factory=list)
    policy_rule_ids: list[str] = Field(default_factory=list)
    provider_disclosure_valid: bool = True
    tool_disclosure_valid: bool = True
    budget_compliant: bool = True
    validator_version: Literal[
        "insilicopop-agent-output-validator-0.33.0"
    ] = AGENT_OUTPUT_VALIDATOR_VERSION


class AgentBudgetRemaining(FrozenSpecialistModel):
    calls: int
    tokens: int
    cost: float
    steps: int
    runtime_seconds: float


class SpecialistAgentOutput(FrozenSpecialistModel):
    agent_output_id: str
    agent_task_id: str
    agent_id: str
    agent_version: str
    status: AgentExecutionStatus
    proposal_status: Literal["proposed_not_approved"] = "proposed_not_approved"
    summary: str = Field(min_length=1, max_length=4000)
    structured_observations: list[AgentStructuredObservation] = Field(default_factory=list)
    source_fact_ids: list[str] = Field(default_factory=list)
    source_finding_ids: list[str] = Field(default_factory=list)
    source_strategy_option_ids: list[str] = Field(default_factory=list)
    source_ledger_entry_ids: list[str] = Field(default_factory=list)
    source_conflict_group_ids: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    human_review_required: Literal[True] = True
    external_llm_called: bool = False
    external_tools_executed: bool = False
    provider: str = "mock"
    model: str = "deterministic-specialist-fixture"
    token_usage: int = 0
    cost: float = 0.0
    runtime_seconds: float = 0.0
    call_count: int = 0
    step_count: int = 0
    budget_remaining: AgentBudgetRemaining
    started_at: str | None = None
    completed_at: str | None = None
    output_hash: str
    validator_version: Literal[
        "insilicopop-agent-output-validator-0.33.0"
    ] = AGENT_OUTPUT_VALIDATOR_VERSION
    safety_review: AgentSafetyReview
    human_review_status: SpecialistReviewStatus = SpecialistReviewStatus.PENDING
    human_reviewed_summary: str | None = Field(default=None, max_length=4000)
    reviewer_notes: str | None = Field(default=None, max_length=2000)
    suggested_follow_up_agent_id: str | None = Field(
        default=None, max_length=100, pattern=LOCAL_ID_PATTERN
    )
    suggested_reason: str | None = Field(default=None, max_length=1000)


class CandidateCriterionRecord(FrozenSpecialistModel):
    candidate_criterion_id: str = Field(min_length=1, max_length=120, pattern=LOCAL_ID_PATTERN)
    case_id: str = Field(min_length=1, max_length=100, pattern=LOCAL_ID_PATTERN)
    finding_id: str = Field(min_length=1, max_length=100, pattern=LOCAL_ID_PATTERN)
    criterion_code: CandidateCriterionCode
    criterion_family: str = Field(min_length=1, max_length=80)
    candidate_status: CandidateStatus
    proposed_strength: str | None = Field(default=None, max_length=80)
    source_ledger_entry_ids: list[str] = Field(max_length=500)
    supporting_observations: list[str] = Field(max_length=100)
    contradicting_ledger_entry_ids: list[str] = Field(max_length=500)
    missing_prerequisites: list[str] = Field(max_length=100)
    applicability_notes: list[str] = Field(max_length=100)
    gene_disease_context: str | None = Field(default=None, max_length=1000)
    mechanism_context: str | None = Field(default=None, max_length=1000)
    inheritance_context: str | None = Field(default=None, max_length=1000)
    phenotype_context: str | None = Field(default=None, max_length=1000)
    technical_limitations: list[str] = Field(max_length=100)
    candidate_rule_id: str = Field(min_length=1, max_length=120, pattern=LOCAL_ID_PATTERN)
    candidate_rule_version: str = Field(min_length=1, max_length=120)
    agent_output_id: str = Field(min_length=1, max_length=120, pattern=LOCAL_ID_PATTERN)
    human_review_status: SpecialistReviewStatus = SpecialistReviewStatus.PENDING
    reviewer_notes: str | None = Field(default=None, max_length=2000)
    created_at: str | None = Field(default=None, max_length=40)
    updated_at: str | None = Field(default=None, max_length=40)
    proposal_status: Literal["proposed_not_approved"] = "proposed_not_approved"
    human_review_required: Literal[True] = True


class DisagreementGroup(FrozenSpecialistModel):
    disagreement_group_id: str
    case_id: str
    finding_id: str | None = None
    agent_output_ids: list[str]
    conflicting_statements: list[str]
    supporting_source_ids: list[str]
    source_conflict_group_ids: list[str]
    resolution_status: Literal["requires_human_review"] = "requires_human_review"
    majority_vote_used: Literal[False] = False
    winning_agent_selected: Literal[False] = False


class SpawnDecision(FrozenSpecialistModel):
    spawn_request_id: str
    agent_task_id: str | None = None
    status: AgentExecutionStatus
    rule_ids: list[str] = Field(default_factory=list)
    message: str
    review_ready: bool = False


class SpecialistExecutionTraceEvent(FrozenSpecialistModel):
    event: Literal[
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
    ]
    spawn_request_id: str | None = None
    agent_task_id: str | None = None
    agent_output_id: str | None = None
    status: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class SpecialistReproducibility(FrozenSpecialistModel):
    agent_registry_version: str
    agent_versions: dict[str, str]
    agent_task_ids: list[str]
    agent_input_hashes: dict[str, str]
    allowed_ledger_entry_ids: list[str]
    provider: str
    model: str
    external_llm_called: bool
    external_tools_executed: bool
    token_usage: int
    cost: float
    step_count: int
    budget_profiles: list[dict[str, Any]]
    output_hashes: dict[str, str]
    candidate_rule_versions: list[str]
    candidate_criterion_ids: list[str]
    human_review_actions: list[dict[str, Any]]
    applied_human_review_actions: list[dict[str, Any]]
    human_review_action_results: list[dict[str, Any]]
    safety_policy_version: str


class SpecialistAgentWorkspaceResult(FrozenSpecialistModel):
    schema_version: Literal["0.33"] = SPECIALIST_AGENT_SCHEMA_VERSION
    controller_version: Literal[
        "insilicopop-bounded-agent-controller-0.33.0"
    ] = AGENT_CONTROLLER_VERSION
    registry_version: Literal[
        "insilicopop-specialist-agent-registry-0.33.0"
    ] = AGENT_REGISTRY_VERSION
    safety_policy_version: Literal[
        "insilicopop-specialist-agent-safety-0.33.0"
    ] = AGENT_SAFETY_POLICY_VERSION
    candidate_ruleset_version: Literal[
        "insilicopop-candidate-acmg-organizer-0.33.0"
    ] = CANDIDATE_RULESET_VERSION
    candidate_vocabulary_version: Literal[
        "insilicopop-acmg-amp-code-vocabulary-0.33.0"
    ] = CANDIDATE_VOCABULARY_VERSION
    pseudonymous_case_id: str
    approved_registry: list[SpecialistAgentDefinition]
    spawn_requests: list[AgentSpawnRequest]
    spawn_decisions: list[SpawnDecision]
    task_envelopes: list[AgentTaskEnvelope]
    agent_outputs: list[SpecialistAgentOutput]
    review_ready_output_ids: list[str]
    candidate_criteria: list[CandidateCriterionRecord]
    disagreement_groups: list[DisagreementGroup]
    review_actions: list[SpecialistHumanReviewAction]
    requested_review_actions: list[SpecialistHumanReviewAction]
    applied_review_actions: list[SpecialistHumanReviewAction]
    review_action_results: list[SpecialistReviewActionResult]
    external_acmg_assessments: list[ExternalAcmgAssessment]
    execution_trace: list[SpecialistExecutionTraceEvent]
    reproducibility: SpecialistReproducibility
    human_review_required: Literal[True] = True
    research_use_only: Literal[True] = True
    external_llm_called: bool = False
    external_tools_executed: bool = False
    provider: str = "mock"
    model: str = "deterministic-specialist-fixture"
    recursive_spawning_used: Literal[False] = False
    dynamic_roles_created: Literal[False] = False
    majority_vote_used: Literal[False] = False
    automatic_criterion_combination_used: Literal[False] = False
    pathogenicity_score_calculated: Literal[False] = False
    causality_claim_made: Literal[False] = False
    diagnosis_made: Literal[False] = False
    treatment_recommendation_made: Literal[False] = False
    test_order_placed: Literal[False] = False
    clinical_sign_out_made: Literal[False] = False
