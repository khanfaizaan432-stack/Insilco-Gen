from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.insilicopop.clinical.hpo_models import PhenotypeCurationRequest
from app.insilicopop.clinical.pedigree_models import PedigreeInheritanceAuditRequest
from app.insilicopop.clinical.variant_models import VariantIntelligenceRequest
from app.insilicopop.clinical.global_intake_models import GlobalIntakeContext
from app.insilicopop.clinical.pretest_models import PreTestAssessmentRequest
from app.insilicopop.clinical.result_evidence_models import ResultEvidenceWorkspaceRequest
from app.insilicopop.clinical.test_strategy_models import TestStrategyWorkspaceRequest


SCHEMA_VERSION = "0.27"


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class PhenotypeState(str, Enum):
    PRESENT = "present"
    ABSENT = "absent"
    UNKNOWN = "unknown"
    NOT_ASSESSED = "not_assessed"
    RESOLVED = "resolved"


class ReviewState(str, Enum):
    UNREVIEWED = "unreviewed"
    PENDING = "pending"
    IN_REVIEW = "in_review"
    CONFIRMED = "confirmed"
    NEEDS_REVISION = "needs_revision"


class AffectedStatus(str, Enum):
    AFFECTED = "affected"
    UNAFFECTED = "unaffected"
    UNKNOWN = "unknown"
    NOT_ASSESSED = "not_assessed"


class SexForInheritance(str, Enum):
    FEMALE = "female"
    MALE = "male"
    OTHER = "other"
    UNKNOWN = "unknown"
    NOT_RECORDED = "not_recorded"


class TestingAvailability(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"
    NOT_TESTED = "not_tested"


class HypothesisType(str, Enum):
    DISEASE = "disease"
    GENE = "gene"
    INHERITANCE = "inheritance"


class InheritanceHypothesis(str, Enum):
    AUTOSOMAL_DOMINANT = "autosomal_dominant"
    AUTOSOMAL_RECESSIVE = "autosomal_recessive"
    X_LINKED = "x_linked"
    MITOCHONDRIAL = "mitochondrial"
    DE_NOVO = "de_novo"
    COMPOUND_HETEROZYGOUS = "compound_heterozygous"
    UNKNOWN = "unknown"
    OTHER = "other"


class ProvenanceRecord(FrozenModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    source_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    source_type: str = Field(min_length=1, max_length=80)
    reference: str | None = Field(default=None, max_length=240)
    redacted: bool = True


class PhenotypeObservation(FrozenModel):
    observation_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    supplied_term: str = Field(min_length=1, max_length=240)
    hpo_id: str | None = Field(default=None, pattern=r"^HP:\d{7}$")
    state: PhenotypeState
    onset_text: str | None = Field(default=None, max_length=160)
    source_reference: str | None = Field(default=None, max_length=160)
    redacted_source_span: str | None = Field(default=None, max_length=240)
    review_state: ReviewState = ReviewState.UNREVIEWED
    notes: str | None = Field(default=None, max_length=240)


class CandidateVariantIntake(FrozenModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    candidate_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    submitted_representation: str = Field(min_length=1, max_length=240)
    gene: str | None = Field(default=None, max_length=40)
    transcript: str | None = Field(default=None, max_length=80)
    genome_build: str | None = Field(default=None, max_length=40)
    chromosome: str | None = Field(default=None, max_length=20)
    position: int | None = Field(default=None, ge=1)
    ref: str | None = Field(default=None, max_length=200)
    alt: str | None = Field(default=None, max_length=200)
    submitted_hgvs: list[str] = Field(default_factory=list, max_length=10)
    zygosity: str | None = Field(default=None, max_length=80)
    provenance: list[ProvenanceRecord] = Field(default_factory=list, max_length=20)
    review_state: ReviewState = ReviewState.UNREVIEWED
    validation_warnings: list[str] = Field(default_factory=list, max_length=20)


class PedigreeMemberIntake(FrozenModel):
    family_member_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    relationship_to_proband: str = Field(min_length=1, max_length=80)
    affected_status: AffectedStatus = AffectedStatus.UNKNOWN
    phenotype_references: list[str] = Field(default_factory=list, max_length=50)
    sex_for_inheritance: SexForInheritance = SexForInheritance.NOT_RECORDED
    testing_availability: TestingAvailability = TestingAvailability.UNKNOWN
    supplied_variant_status: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=240)
    provenance: list[ProvenanceRecord] = Field(default_factory=list, max_length=20)
    review_state: ReviewState = ReviewState.UNREVIEWED


class ResearchHypothesis(FrozenModel):
    hypothesis_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    hypothesis_type: HypothesisType
    value: str = Field(min_length=1, max_length=160)
    inheritance_candidate: InheritanceHypothesis | None = None
    source: Literal["user_supplied", "agent_proposed"] = "user_supplied"
    review_state: ReviewState = ReviewState.UNREVIEWED


class ClinicalCaseIntake(FrozenModel):
    schema_version: Literal["0.27"] = SCHEMA_VERSION
    pseudonymous_case_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    intended_use: Literal["clinical_genetics_research_curation"]
    case_label: str | None = Field(default=None, max_length=120)
    redaction_declared: bool | None = None
    reviewer_status: ReviewState = ReviewState.PENDING
    human_review_required: Literal[True] = True
    genome_build: str | None = Field(default=None, max_length=40)
    provenance: list[ProvenanceRecord] = Field(default_factory=list, max_length=30)
    phenotypes: list[PhenotypeObservation] = Field(default_factory=list, max_length=500)
    candidate_variants: list[CandidateVariantIntake] = Field(default_factory=list, max_length=500)
    pedigree: list[PedigreeMemberIntake] = Field(default_factory=list, max_length=500)
    hypotheses: list[ResearchHypothesis] = Field(default_factory=list, max_length=100)
    requested_actions: list[str] = Field(default_factory=list, max_length=30)
    phenotype_curation: PhenotypeCurationRequest | None = None
    pedigree_inheritance_audit: PedigreeInheritanceAuditRequest | None = None
    variant_intelligence: VariantIntelligenceRequest | None = None
    global_intake_context: GlobalIntakeContext | None = None
    pre_test_assessment: PreTestAssessmentRequest | None = None
    test_strategy_workspace: TestStrategyWorkspaceRequest | None = None
    result_evidence_workspace: ResultEvidenceWorkspaceRequest | None = None


class ClinicalIntakeIssue(FrozenModel):
    code: str
    field: str | None = None
    record_id: str | None = None
    message: str


class ClinicalPolicyBlock(FrozenModel):
    code: str
    category: str
    message: str


class ClinicalHypothesisSummary(FrozenModel):
    hypothesis_id: str
    hypothesis_type: str
    inheritance_candidate: str | None = None
    source: str
    review_state: str


class ClinicalCaseIntakeResult(FrozenModel):
    schema_version: Literal["0.27"] = SCHEMA_VERSION
    research_use_only: Literal[True] = True
    pseudonymous_case_id: str
    intended_use: str
    redaction_declared: bool
    intake_completeness: Literal["complete", "incomplete", "blocked", "invalid"]
    phenotype_state_counts: dict[str, int]
    phenotype_observation_ids: list[str]
    candidate_variant_count: int
    candidate_variant_ids: list[str]
    supplied_candidate_variants: list[CandidateVariantIntake] = Field(default_factory=list)
    pedigree_record_count: int
    pedigree_member_ids: list[str]
    supplied_hypotheses: list[ClinicalHypothesisSummary]
    validation_errors: list[ClinicalIntakeIssue]
    validation_warnings: list[ClinicalIntakeIssue]
    missing_information: list[ClinicalIntakeIssue]
    policy_blocks: list[ClinicalPolicyBlock]
    reviewer_status: str
    human_review_required: Literal[True] = True
    diagnosis_made: Literal[False] = False
    treatment_recommendation_made: Literal[False] = False
    final_acmg_classification_made: Literal[False] = False
    clinical_sign_out_made: Literal[False] = False
    patient_facing_return_made: Literal[False] = False
    secondary_findings_return_made: Literal[False] = False
    inheritance_calculation_performed: Literal[False] = False
    variant_normalization_performed: Literal[False] = False
    external_api_call_made: Literal[False] = False
    external_llm_called: Literal[False] = False
    external_tools_executed: Literal[False] = False
    raw_genomic_files_parsed: Literal[False] = False
    global_intake_context: dict[str, Any] | None = Field(default=None, exclude_if=lambda value: value is None)
