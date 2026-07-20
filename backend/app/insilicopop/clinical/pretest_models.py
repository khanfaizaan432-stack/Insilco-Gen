from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


PRETEST_SCHEMA_VERSION = "0.31.2"
PRETEST_ALGORITHM_VERSION = "insilicopop-referral-pretest-assessment-0.31.2"
LOCAL_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"


class FrozenPreTestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)


class ReferralSource(str, Enum):
    GP = "gp"
    SPECIALIST = "specialist"
    CLINICAL_GENETICS = "clinical_genetics"
    OTHER = "other"
    UNKNOWN = "unknown"


class ReferralUrgencyContext(str, Enum):
    ROUTINE = "routine"
    EXPEDITED = "expedited"
    URGENT = "urgent"
    UNKNOWN = "unknown"
    NOT_ASSESSED = "not_assessed"


class DiseaseCourse(str, Enum):
    STATIC = "static"
    PROGRESSIVE = "progressive"
    EPISODIC = "episodic"
    IMPROVING = "improving"
    RESOLVED = "resolved"
    VARIABLE = "variable"
    UNKNOWN = "unknown"
    NOT_ASSESSED = "not_assessed"


class InformationStatus(str, Enum):
    SUPPLIED = "supplied"
    NONE_REPORTED = "none_reported"
    UNKNOWN = "unknown"
    NOT_ASSESSED = "not_assessed"


class RecordAvailability(str, Enum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    REQUESTED = "requested"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"
    NOT_ASSESSED = "not_assessed"


class InvestigationCategory(str, Enum):
    CLINICAL = "clinical"
    IMAGING = "imaging"
    BIOCHEMICAL = "biochemical"
    METABOLIC = "metabolic"
    PATHOLOGY = "pathology"
    CYTOGENETIC = "cytogenetic"
    MOLECULAR_GENETIC = "molecular_genetic"
    OTHER = "other"


class SampleAvailabilityReview(str, Enum):
    AVAILABLE = "available"
    POTENTIALLY_AVAILABLE = "potentially_available"
    NONE_AVAILABLE = "none_available"
    UNKNOWN = "unknown"
    NOT_ASSESSED = "not_assessed"


class AccessReviewStatus(str, Enum):
    REVIEWED_NO_CONSTRAINTS_REPORTED = "reviewed_no_constraints_reported"
    CONSTRAINTS_SUPPLIED = "constraints_supplied"
    UNKNOWN = "unknown"
    NOT_ASSESSED = "not_assessed"


class PreTestWorkflowOutcome(str, Enum):
    MORE_INFORMATION_REQUIRED = "more_information_required"
    NO_TEST_YET = "no_test_yet"
    READY_FOR_TEST_STRATEGY_REVIEW = "ready_for_test_strategy_review"
    AWAITING_HUMAN_REVIEW = "awaiting_human_review"


class CheckpointType(str, Enum):
    REFERRAL_REVIEW = "referral_review"
    HISTORY_REVIEW = "history_review"
    PHENOTYPE_REVIEW = "phenotype_review"
    PEDIGREE_REVIEW = "pedigree_review"
    PREVIOUS_INVESTIGATIONS_REVIEW = "previous_investigations_review"
    SAMPLE_AND_ACCESS_REVIEW = "sample_and_access_review"
    PRE_TEST_ASSESSMENT_REVIEW = "pre_test_assessment_review"


class CheckpointStatus(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    NEEDS_REVISION = "needs_revision"
    DEFERRED = "deferred"


class MissingInformationCategory(str, Enum):
    REFERRAL = "referral"
    CLINICAL_HISTORY = "clinical_history"
    PHENOTYPE = "phenotype"
    PEDIGREE = "pedigree"
    PREVIOUS_INVESTIGATION = "previous_investigation"
    FAMILY_REPORT = "family_report"
    SAMPLE_AVAILABILITY = "sample_availability"
    ACCESS_AND_AFFORDABILITY = "access_and_affordability"
    HUMAN_REVIEW = "human_review"
    OTHER = "other"


class MissingInformationStatus(str, Enum):
    OPEN = "open"
    RESOLVED = "resolved"
    DEFERRED = "deferred"


class ReferralPacket(FrozenPreTestModel):
    referral_id: str = Field(min_length=1, max_length=80, pattern=LOCAL_ID_PATTERN)
    source: ReferralSource = ReferralSource.UNKNOWN
    referring_specialty_exact: str | None = Field(default=None, max_length=160)
    reason_exact: str | None = Field(default=None, max_length=600)
    urgency_context: ReferralUrgencyContext = ReferralUrgencyContext.NOT_ASSESSED
    supplied_urgency_wording_exact: str | None = Field(default=None, max_length=160)
    provenance_source_ids: list[str] = Field(default_factory=list, max_length=20)


class ClinicalGeneticsHistory(FrozenPreTestModel):
    history_id: str = Field(min_length=1, max_length=80, pattern=LOCAL_ID_PATTERN)
    summary_exact: str | None = Field(default=None, max_length=1200)
    phenotype_observation_ids: list[str] = Field(default_factory=list, max_length=500)
    pedigree_member_ids: list[str] = Field(default_factory=list, max_length=500)
    onset_exact: str | None = Field(default=None, max_length=240)
    disease_course: DiseaseCourse = DiseaseCourse.NOT_ASSESSED
    birth_history_status: InformationStatus = InformationStatus.NOT_ASSESSED
    birth_history_exact: str | None = Field(default=None, max_length=600)
    development_history_status: InformationStatus = InformationStatus.NOT_ASSESSED
    development_history_exact: str | None = Field(default=None, max_length=600)
    review_status: CheckpointStatus = CheckpointStatus.PENDING
    provenance_source_ids: list[str] = Field(default_factory=list, max_length=20)


class PreviousInvestigationRecord(FrozenPreTestModel):
    investigation_id: str = Field(min_length=1, max_length=80, pattern=LOCAL_ID_PATTERN)
    timeline_order: int | None = Field(default=None, ge=0, le=10000)
    category: InvestigationCategory
    test_or_assessment_exact: str = Field(min_length=1, max_length=240)
    occurred_on_or_period_exact: str | None = Field(default=None, max_length=120)
    result_summary_exact: str | None = Field(default=None, max_length=600)
    report_availability: RecordAvailability = RecordAvailability.UNKNOWN
    provenance_source_ids: list[str] = Field(default_factory=list, max_length=20)


class KnownFamilyReportRecord(FrozenPreTestModel):
    family_report_id: str = Field(min_length=1, max_length=80, pattern=LOCAL_ID_PATTERN)
    family_member_id: str = Field(min_length=1, max_length=80, pattern=LOCAL_ID_PATTERN)
    report_type_exact: str = Field(min_length=1, max_length=240)
    report_availability: RecordAvailability = RecordAvailability.UNKNOWN
    supplied_summary_exact: str | None = Field(default=None, max_length=600)
    provenance_source_ids: list[str] = Field(default_factory=list, max_length=20)


class PreTestContextReview(FrozenPreTestModel):
    sample_availability: SampleAvailabilityReview = SampleAvailabilityReview.NOT_ASSESSED
    sample_context_exact: str | None = Field(default=None, max_length=400)
    access_review_status: AccessReviewStatus = AccessReviewStatus.NOT_ASSESSED
    access_constraints_exact: list[str] = Field(default_factory=list, max_length=20)
    affordability_context_exact: str | None = Field(default=None, max_length=400)


class SuppliedMissingInformationRequest(FrozenPreTestModel):
    request_id: str = Field(min_length=1, max_length=80, pattern=LOCAL_ID_PATTERN)
    category: MissingInformationCategory
    information_needed_exact: str = Field(min_length=1, max_length=500)
    why_needed_exact: str | None = Field(default=None, max_length=500)
    linked_record_ids: list[str] = Field(default_factory=list, max_length=50)
    status: MissingInformationStatus = MissingInformationStatus.OPEN


class ClinicianCheckpoint(FrozenPreTestModel):
    checkpoint_id: str = Field(min_length=1, max_length=80, pattern=LOCAL_ID_PATTERN)
    checkpoint_type: CheckpointType
    status: CheckpointStatus = CheckpointStatus.PENDING
    reviewer_role_exact: str | None = Field(default=None, max_length=120)
    note_exact: str | None = Field(default=None, max_length=400)
    provenance_source_ids: list[str] = Field(default_factory=list, max_length=20)


class PreTestAssessmentRequest(FrozenPreTestModel):
    schema_version: Literal["0.31.2"] = PRETEST_SCHEMA_VERSION
    referral_packet: ReferralPacket | None = None
    clinical_history: ClinicalGeneticsHistory | None = None
    previous_investigations_review_status: InformationStatus = InformationStatus.NOT_ASSESSED
    previous_investigations: list[PreviousInvestigationRecord] = Field(default_factory=list, max_length=100)
    known_family_reports_review_status: InformationStatus = InformationStatus.NOT_ASSESSED
    known_family_reports: list[KnownFamilyReportRecord] = Field(default_factory=list, max_length=100)
    context_review: PreTestContextReview = Field(default_factory=PreTestContextReview)
    supplied_missing_information_requests: list[SuppliedMissingInformationRequest] = Field(default_factory=list, max_length=100)
    testing_status: PreTestWorkflowOutcome = PreTestWorkflowOutcome.AWAITING_HUMAN_REVIEW
    clinician_checkpoints: list[ClinicianCheckpoint] = Field(default_factory=list, max_length=50)
    human_review_required: Literal[True] = True


class PreTestLinkageIssue(FrozenPreTestModel):
    issue_id: str
    code: str
    field: str
    record_id: str | None = None
    linked_record_id: str | None = None
    message: str


class MissingInformationPlanItem(FrozenPreTestModel):
    request_id: str
    category: MissingInformationCategory
    code: str
    information_needed: str
    why_needed: str
    source: Literal["system_identified", "user_supplied"]
    linked_record_ids: list[str] = Field(default_factory=list)
    status: MissingInformationStatus = MissingInformationStatus.OPEN
    human_review_required: Literal[True] = True


class PreTestAssessmentResult(FrozenPreTestModel):
    schema_version: Literal["0.31.2"] = PRETEST_SCHEMA_VERSION
    algorithm_version: Literal["insilicopop-referral-pretest-assessment-0.31.2"] = PRETEST_ALGORITHM_VERSION
    research_use_only: Literal[True] = True
    pseudonymous_case_id: str
    referral_packet: ReferralPacket | None = None
    clinical_history: ClinicalGeneticsHistory | None = None
    previous_investigation_timeline: list[PreviousInvestigationRecord] = Field(default_factory=list)
    known_family_reports: list[KnownFamilyReportRecord] = Field(default_factory=list)
    context_review: PreTestContextReview
    testing_status_as_supplied: PreTestWorkflowOutcome
    assessment_outcome: PreTestWorkflowOutcome
    outcome_rationale_codes: list[str] = Field(default_factory=list)
    linkage_issues: list[PreTestLinkageIssue] = Field(default_factory=list)
    missing_information_plan: list[MissingInformationPlanItem] = Field(default_factory=list)
    open_missing_information_count: int = 0
    clinician_checkpoint_status_counts: dict[str, int] = Field(default_factory=dict)
    ready_for_test_strategy_review: bool = False
    human_review_required: Literal[True] = True
    test_strategy_generated: Literal[False] = False
    test_recommendation_made: Literal[False] = False
    test_order_placed: Literal[False] = False
    automatic_wes_or_wgs_recommendation_made: Literal[False] = False
    diagnosis_made: Literal[False] = False
    treatment_recommendation_made: Literal[False] = False
    final_acmg_classification_made: Literal[False] = False
    clinical_sign_out_made: Literal[False] = False
    external_api_call_made: Literal[False] = False
    external_llm_called: Literal[False] = False
    external_tools_executed: Literal[False] = False
    raw_genomic_files_parsed: Literal[False] = False
