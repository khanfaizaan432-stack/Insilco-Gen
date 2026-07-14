from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


HPO_CURATION_SCHEMA_VERSION = "0.28"
HPO_ALGORITHM_VERSION = "insilicopop-hpo-curation-0.28.0"


class HpoFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class HpoReviewStatus(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    MODIFIED = "modified"
    NEEDS_CLARIFICATION = "needs_clarification"


class HpoProvenance(HpoFrozenModel):
    source_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    source_type: str = Field(min_length=1, max_length=80)
    reference: str | None = Field(default=None, max_length=160)
    redacted: bool = True


class PhenotypeSnippet(HpoFrozenModel):
    snippet_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    redaction_declared: bool
    redacted_text: str = Field(min_length=1, max_length=1000)
    source_label: str | None = Field(default=None, max_length=80)
    supplied_onset: str | None = Field(default=None, max_length=80)
    supplied_temporal_context: str | None = Field(default=None, max_length=80)
    provenance: list[HpoProvenance] = Field(default_factory=list, max_length=10)
    reviewer_state: HpoReviewStatus = HpoReviewStatus.PENDING


class HpoReplacement(HpoFrozenModel):
    hpo_id: str = Field(pattern=r"^HP:\d{7}$")
    canonical_label: str | None = Field(default=None, max_length=160)
    state: Literal["present", "absent", "unknown", "not_assessed", "resolved"]
    onset_text: str | None = Field(default=None, max_length=160)
    temporal_context: str | None = Field(default=None, max_length=160)


class ReviewerActionInput(HpoFrozenModel):
    suggestion_id: str = Field(min_length=1, max_length=80)
    action: HpoReviewStatus
    replacement: HpoReplacement | None = None
    provenance: list[HpoProvenance] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def validate_replacement(self) -> "ReviewerActionInput":
        if self.action == HpoReviewStatus.MODIFIED and self.replacement is None:
            return self
        if self.action != HpoReviewStatus.MODIFIED and self.replacement is not None:
            raise ValueError("replacement is allowed only for a modified reviewer action")
        return self


class PhenotypeCurationRequest(HpoFrozenModel):
    snippets: list[PhenotypeSnippet] = Field(default_factory=list, max_length=50)
    reviewer_actions: list[ReviewerActionInput] = Field(default_factory=list, max_length=500)


class CurationIssue(HpoFrozenModel):
    code: str
    field: str | None = None
    record_id: str | None = None
    message: str


class CurationPolicyBlock(HpoFrozenModel):
    code: str
    category: str
    message: str


class SourceSnippetMetadata(HpoFrozenModel):
    snippet_id: str
    character_length: int
    text_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_label: str | None = None
    supplied_onset: str | None = None
    supplied_temporal_context: str | None = None
    provenance: list[HpoProvenance] = Field(default_factory=list)


class MatchContextRecord(HpoFrozenModel):
    detected_text: str
    start: int
    end: int
    source: Literal["explicit", "text_pattern"]


class NegationRecord(HpoFrozenModel):
    cue: str
    cue_start: int
    cue_end: int
    match_start: int
    match_end: int
    context_window_size: int
    result: Literal["clear", "ambiguous"]


class HpoSuggestion(HpoFrozenModel):
    suggestion_id: str
    source_snippet_id: str
    hpo_id: str = Field(pattern=r"^HP:\d{7}$")
    canonical_label: str
    match_start: int = Field(ge=0)
    match_end: int = Field(gt=0)
    matched_substring: str = Field(min_length=1, max_length=160)
    matching_method: Literal["canonical_exact", "synonym_exact"]
    proposed_state: Literal["present", "absent", "unknown", "not_assessed", "resolved"]
    negation: NegationRecord | None = None
    onset: MatchContextRecord | None = None
    temporal: MatchContextRecord | None = None
    match_quality: Literal["exact_canonical", "exact_synonym"]
    registry_version: str
    algorithm_version: str = HPO_ALGORITHM_VERSION
    provenance: list[HpoProvenance] = Field(default_factory=list)
    validation_warnings: list[str] = Field(default_factory=list)
    contradiction_references: list[str] = Field(default_factory=list)
    review_status: HpoReviewStatus = HpoReviewStatus.PENDING
    reviewer_action: ReviewerActionInput | None = None
    validated_modification: HpoReplacement | None = None
    human_review_required: Literal[True] = True


class ContradictionRecord(HpoFrozenModel):
    contradiction_id: str
    hpo_id: str
    involved_record_ids: list[str]
    contradiction_type: Literal[
        "proposed_present_and_absent",
        "existing_observation_conflict",
        "confirmed_resolved_without_temporal_context",
        "incompatible_source_states",
        "incompatible_reviewer_decisions",
        "modified_existing_observation_conflict",
    ]
    involved_states: list[str]
    source_references: list[str]
    resolution_status: Literal["requires_reviewer_resolution"] = "requires_reviewer_resolution"
    outcome: Literal["contradiction_detected"] = "contradiction_detected"
    deterministic_resolution: Literal["cannot_resolve_deterministically"] = "cannot_resolve_deterministically"
    human_review_required: Literal[True] = True


class PromotedObservation(HpoFrozenModel):
    observation_id: str
    suggestion_id: str
    supplied_term: str
    hpo_id: str
    state: str
    onset_text: str | None = None
    source_reference: str
    redacted_source_span: str
    review_state: Literal["confirmed"] = "confirmed"
    reviewer_provenance: list[HpoProvenance] = Field(default_factory=list)


class PhenotypeHpoCurationResult(HpoFrozenModel):
    schema_version: Literal["0.28"] = HPO_CURATION_SCHEMA_VERSION
    registry_version: str
    algorithm_version: str = HPO_ALGORITHM_VERSION
    research_use_only: Literal[True] = True
    pseudonymous_case_id: str
    source_snippets: list[SourceSnippetMetadata]
    validation_errors: list[CurationIssue]
    validation_warnings: list[CurationIssue]
    missing_information: list[CurationIssue]
    policy_blocks: list[CurationPolicyBlock]
    hpo_suggestions: list[HpoSuggestion]
    contradictions: list[ContradictionRecord]
    review_actions: list[ReviewerActionInput]
    promoted_observations: list[PromotedObservation]
    human_review_required: Literal[True] = True
    diagnosis_made: Literal[False] = False
    treatment_recommendation_made: Literal[False] = False
    final_acmg_classification_made: Literal[False] = False
    clinical_sign_out_made: Literal[False] = False
    patient_facing_return_made: Literal[False] = False
    secondary_findings_return_made: Literal[False] = False
    external_api_call_made: Literal[False] = False
    external_llm_called: Literal[False] = False
    external_tools_executed: Literal[False] = False
    raw_genomic_files_parsed: Literal[False] = False
