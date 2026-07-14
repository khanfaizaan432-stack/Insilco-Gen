from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


PEDIGREE_AUDIT_SCHEMA_VERSION = "0.29"
PEDIGREE_AUDIT_ALGORITHM_VERSION = "insilicopop-pedigree-inheritance-audit-0.29.0"
BoundedIdentifier = Annotated[
    str,
    Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"),
]


class AuditFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class AuditReviewState(str, Enum):
    UNREVIEWED = "unreviewed"
    PENDING = "pending"
    IN_REVIEW = "in_review"
    CONFIRMED = "confirmed"
    NEEDS_REVISION = "needs_revision"


class RelationshipType(str, Enum):
    BIOLOGICAL_PARENT = "biological_parent"
    OTHER_SUPPLIED = "other_supplied"


class VariantPresenceState(str, Enum):
    PRESENT = "present"
    ABSENT = "absent"
    UNKNOWN = "unknown"
    NOT_TESTED = "not_tested"


class SuppliedZygosity(str, Enum):
    HETEROZYGOUS = "heterozygous"
    HOMOZYGOUS = "homozygous"
    HEMIZYGOUS = "hemizygous"
    HETEROPLASMIC = "heteroplasmic"
    HOMOPLASMIC = "homoplasmic"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class ObservationTestingState(str, Enum):
    TESTED = "tested"
    NOT_TESTED = "not_tested"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class ConfirmationState(str, Enum):
    CONFIRMED = "confirmed"
    UNCONFIRMED = "unconfirmed"
    PENDING = "pending"
    UNKNOWN = "unknown"


class PhaseState(str, Enum):
    CONFIRMED_IN_TRANS = "confirmed_in_trans"
    PRESUMED_IN_TRANS = "presumed_in_trans"
    UNKNOWN = "unknown"
    CONFIRMED_IN_CIS = "confirmed_in_cis"
    CANNOT_EVALUATE = "cannot_evaluate"


class PhaseEvidenceBasis(str, Enum):
    DIRECTLY_SUPPLIED = "directly_supplied"
    PARENTAL_TRANSMISSION_SUPPORTED = "parental_transmission_supported"
    SUPPLIED_PRESUMED = "supplied_presumed"
    NOT_SUPPLIED = "not_supplied"


class InheritanceAuditStatus(str, Enum):
    CONSISTENT = "consistent"
    PARTIALLY_CONSISTENT = "partially_consistent"
    INCONSISTENT = "inconsistent"
    CANNOT_EVALUATE = "cannot_evaluate"
    MISSING_EVIDENCE = "missing_evidence"


class XLinkedLocusContext(str, Enum):
    NON_PSEUDOAUTOSOMAL_X = "non_pseudoautosomal_x"
    PSEUDOAUTOSOMAL_X = "pseudoautosomal_x"
    NON_X = "non_x"
    UNKNOWN = "unknown"


class XLinkedSexChromosomeContext(str, Enum):
    SUFFICIENT_FOR_BOUNDED_RULE = "sufficient_for_bounded_rule"
    OTHER_OR_COMPLEX = "other_or_complex"
    UNKNOWN = "unknown"


class XLinkedMosaicContext(str, Enum):
    NOT_INDICATED_IN_SUPPLIED_RECORDS = "not_indicated_in_supplied_records"
    INDICATED_OR_POSSIBLE = "indicated_or_possible"
    UNKNOWN = "unknown"


class XLinkedAuditContext(AuditFrozenModel):
    locus_context: XLinkedLocusContext
    sex_chromosome_context: XLinkedSexChromosomeContext
    mosaic_context: XLinkedMosaicContext
    provenance_source_ids: list[BoundedIdentifier] = Field(max_length=20)
    review_state: AuditReviewState


class PedigreeRelationshipInput(AuditFrozenModel):
    relationship_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    relationship_type: RelationshipType
    parent_member_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    child_member_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    provenance_source_ids: list[BoundedIdentifier] = Field(default_factory=list, max_length=20)
    review_state: AuditReviewState = AuditReviewState.UNREVIEWED


class FamilyVariantObservation(AuditFrozenModel):
    observation_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    family_member_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    candidate_variant_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    presence_state: VariantPresenceState
    zygosity: SuppliedZygosity = SuppliedZygosity.UNKNOWN
    testing_state: ObservationTestingState = ObservationTestingState.UNKNOWN
    confirmation_state: ConfirmationState = ConfirmationState.UNKNOWN
    provenance_source_ids: list[BoundedIdentifier] = Field(default_factory=list, max_length=20)
    review_state: AuditReviewState = AuditReviewState.UNREVIEWED


class InheritanceAuditTarget(AuditFrozenModel):
    audit_target_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    hypothesis_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    candidate_variant_ids: list[BoundedIdentifier] = Field(default_factory=list, max_length=10)
    phase_declaration_id: str | None = Field(default=None, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    x_linked_context: XLinkedAuditContext | None = None


class PhaseDeclaration(AuditFrozenModel):
    phase_declaration_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    candidate_variant_ids: list[BoundedIdentifier] = Field(min_length=2, max_length=2)
    state: PhaseState
    evidence_basis: PhaseEvidenceBasis
    provenance_source_ids: list[BoundedIdentifier] = Field(default_factory=list, max_length=20)
    review_state: AuditReviewState = AuditReviewState.UNREVIEWED

    @model_validator(mode="after")
    def distinct_candidates(self) -> "PhaseDeclaration":
        if len(set(self.candidate_variant_ids)) != 2:
            raise ValueError("phase candidate variant IDs must be distinct")
        return self


class PedigreeInheritanceAuditRequest(AuditFrozenModel):
    schema_version: Literal["0.29"] = PEDIGREE_AUDIT_SCHEMA_VERSION
    proband_member_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    relationships: list[PedigreeRelationshipInput] = Field(default_factory=list, max_length=1000)
    variant_observations: list[FamilyVariantObservation] = Field(default_factory=list, max_length=5000)
    audit_targets: list[InheritanceAuditTarget] = Field(default_factory=list, max_length=100)
    phase_declarations: list[PhaseDeclaration] = Field(default_factory=list, max_length=100)
    reviewer_status: AuditReviewState = AuditReviewState.PENDING
    human_review_required: Literal[True] = True


class PedigreeAuditIssue(AuditFrozenModel):
    issue_id: str
    code: str
    involved_member_ids: list[str] = Field(default_factory=list)
    involved_candidate_variant_ids: list[str] = Field(default_factory=list)
    involved_record_ids: list[str] = Field(default_factory=list)
    supplied_facts: dict[str, Any] = Field(default_factory=dict)
    explanation: str
    severity: Literal["error", "warning", "requirement", "conflict", "review"]
    provenance_source_ids: list[str] = Field(default_factory=list)
    human_review_required: Literal[True] = True


class PedigreeAuditPolicyBlock(AuditFrozenModel):
    issue_id: str
    code: str
    category: str
    explanation: str
    human_review_required: Literal[True] = True


class PhaseAssessment(AuditFrozenModel):
    assessment_id: str
    audit_target_id: str
    phase_declaration_id: str | None = None
    supplied_state: str
    assessment: Literal[
        "confirmed_in_trans",
        "supported_in_trans_by_supplied_parental_observations",
        "presumed_in_trans",
        "unknown",
        "confirmed_in_cis",
        "cannot_evaluate",
    ]
    involved_candidate_variant_ids: list[str]
    supporting_observation_ids: list[str] = Field(default_factory=list)
    human_review_required: Literal[True] = True


class ParentChildTransmissionRecord(AuditFrozenModel):
    transmission_id: str
    relationship_id: str
    parent_member_id: str
    child_member_id: str
    candidate_variant_id: str
    evaluable: bool
    parent_presence_state: str | None = None
    child_presence_state: str | None = None
    non_evaluable_reason_code: str | None = None
    human_review_required: Literal[True] = True


class AvailableParentChildTransmissionSummary(AuditFrozenModel):
    supplied_biological_parent_relationship_count: int
    candidate_parent_child_transmission_count: int
    evaluable_transmission_count: int
    non_evaluable_transmission_count: int
    non_evaluable_reason_counts: dict[str, int]
    human_review_required: Literal[True] = True


class InheritanceAuditRecord(AuditFrozenModel):
    audit_id: str
    audit_target_id: str
    hypothesis_id: str
    hypothesis_type: str
    candidate_variant_ids: list[str]
    status: InheritanceAuditStatus
    bounded_explanation: str
    supporting_record_ids: list[str] = Field(default_factory=list)
    relationship_issue_ids: list[str] = Field(default_factory=list)
    mendelian_inconsistency_ids: list[str] = Field(default_factory=list)
    missing_information_ids: list[str] = Field(default_factory=list)
    phase_assessment_id: str | None = None
    human_review_required: Literal[True] = True


class AuditReviewAction(AuditFrozenModel):
    action_id: str
    code: str
    audit_target_id: str | None = None
    involved_member_ids: list[str] = Field(default_factory=list)
    involved_candidate_variant_ids: list[str] = Field(default_factory=list)
    explanation: str
    status: Literal["required"] = "required"
    human_review_required: Literal[True] = True


class PedigreeInheritanceAuditResult(AuditFrozenModel):
    schema_version: Literal["0.29"] = PEDIGREE_AUDIT_SCHEMA_VERSION
    algorithm_version: Literal["insilicopop-pedigree-inheritance-audit-0.29.0"] = PEDIGREE_AUDIT_ALGORITHM_VERSION
    research_use_only: Literal[True] = True
    pseudonymous_case_id: str
    proband_member_id: str
    member_count: int
    biological_parent_relationship_count: int
    affected_status_summary: dict[str, int]
    testing_availability_summary: dict[str, int]
    supplied_hypothesis_types: list[str]
    variant_observation_count: int
    validation_errors: list[PedigreeAuditIssue]
    validation_warnings: list[PedigreeAuditIssue]
    missing_information: list[PedigreeAuditIssue]
    policy_blocks: list[PedigreeAuditPolicyBlock]
    relationship_issues: list[PedigreeAuditIssue]
    mendelian_inconsistencies: list[PedigreeAuditIssue]
    inheritance_audits: list[InheritanceAuditRecord]
    phase_assessments: list[PhaseAssessment]
    phase_requirements: list[PedigreeAuditIssue]
    missing_relative_requirements: list[PedigreeAuditIssue]
    review_actions: list[AuditReviewAction]
    available_parent_child_transmission_summary: AvailableParentChildTransmissionSummary
    parent_child_transmission_records: list[ParentChildTransmissionRecord]
    reviewer_status: str
    inheritance_consistency_audit_performed: Literal[True] = True
    human_review_required: Literal[True] = True
    diagnosis_made: Literal[False] = False
    treatment_recommendation_made: Literal[False] = False
    final_acmg_classification_made: Literal[False] = False
    clinical_sign_out_made: Literal[False] = False
    patient_facing_return_made: Literal[False] = False
    secondary_findings_return_made: Literal[False] = False
    pathogenicity_conclusion_made: Literal[False] = False
    inheritance_clinically_established: Literal[False] = False
    external_api_call_made: Literal[False] = False
    external_llm_called: Literal[False] = False
    external_tools_executed: Literal[False] = False
    raw_genomic_files_parsed: Literal[False] = False
