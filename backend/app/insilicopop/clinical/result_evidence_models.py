from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


RESULT_EVIDENCE_SCHEMA_VERSION = "0.32"
RESULT_INTAKE_VERSION = "insilicopop-result-intake-0.32.0"
NORMALIZATION_VERSION = "insilicopop-result-normalization-0.32.0"
RETRIEVAL_VERSION = "insilicopop-controlled-evidence-retrieval-0.32.0"
LEDGER_VERSION = "insilicopop-evidence-ledger-0.32.0"
LOCAL_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"


class FrozenResultEvidenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)


class ResultCategory(str, Enum):
    SEQUENCE_VARIANT_RESULT = "sequence_variant_result"
    COPY_NUMBER_RESULT = "copy_number_result"
    STRUCTURAL_VARIANT_RESULT = "structural_variant_result"
    REPEAT_EXPANSION_RESULT = "repeat_expansion_result"
    MITOCHONDRIAL_RESULT = "mitochondrial_result"
    CYTOGENETIC_RESULT = "cytogenetic_result"
    BIOCHEMICAL_RESULT = "biochemical_result"
    NEGATIVE_OR_UNINFORMATIVE_RESULT = "negative_or_uninformative_result"
    EXTERNAL_REANALYSIS_RESULT = "external_reanalysis_result"
    OTHER_STRUCTURED_FINDING = "other_structured_finding"


class ExplicitInformationState(str, Enum):
    KNOWN = "known"
    UNKNOWN = "unknown"
    NOT_PROVIDED = "not_provided"
    NOT_APPLICABLE = "not_applicable"
    REQUIRES_REVIEW = "requires_review"


class SourceState(str, Enum):
    SOURCE_REPORTED = "source_reported"
    NORMALIZED = "normalized"
    SYSTEM_GENERATED = "system_generated"
    HUMAN_REVIEWED = "human_reviewed"
    EXTERNAL_DECISION = "external_decision"


class NormalizationOutcome(str, Enum):
    NORMALIZED = "normalized"
    PARTIALLY_NORMALIZED = "partially_normalized"
    UNCHANGED_SOURCE_ONLY = "unchanged_source_only"
    REQUIRES_RULE_REVIEW = "requires_rule_review"
    REJECTED_AS_INVALID = "rejected_as_invalid"


class ExternalClassificationValue(str, Enum):
    PATHOGENIC = "pathogenic"
    LIKELY_PATHOGENIC = "likely_pathogenic"
    UNCERTAIN_SIGNIFICANCE = "uncertain_significance"
    LIKELY_BENIGN = "likely_benign"
    BENIGN = "benign"
    RISK_ALLELE = "risk_allele"
    CARRIER_STATUS = "carrier_status"
    PHARMACOGENOMIC = "pharmacogenomic"
    NOT_PROVIDED = "not_provided"
    OTHER = "other"


class BreakpointPrecision(str, Enum):
    EXACT = "exact"
    INTERVAL = "interval"
    CYTOBAND_ONLY = "cytoband_only"
    APPROXIMATE = "approximate"
    UNKNOWN = "unknown"


class RetrievalState(str, Enum):
    NOT_ATTEMPTED = "not_attempted"
    READY_FOR_REVIEW = "ready_for_review"
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    NO_RECORDS_FOUND = "no_records_found"
    SOURCE_UNAVAILABLE = "source_unavailable"
    AUTHENTICATION_REQUIRED = "authentication_required"
    RATE_LIMITED = "rate_limited"
    INVALID_QUERY = "invalid_query"
    REQUIRES_RULE_REVIEW = "requires_rule_review"


class EvidenceSourceType(str, Enum):
    VARIANT_DATABASE_RECORD = "variant_database_record"
    GENE_DISEASE_VALIDITY_RECORD = "gene_disease_validity_record"
    POPULATION_FREQUENCY_RECORD = "population_frequency_record"
    PEER_REVIEWED_PUBLICATION = "peer_reviewed_publication"
    CLINICAL_GUIDELINE_OR_CONSENSUS = "clinical_guideline_or_consensus"
    FUNCTIONAL_EVIDENCE_RECORD = "functional_evidence_record"
    SEGREGATION_EVIDENCE_RECORD = "segregation_evidence_record"
    COMPUTATIONAL_EVIDENCE_RECORD = "computational_evidence_record"
    LABORATORY_OR_ASSAY_DOCUMENTATION = "laboratory_or_assay_documentation"


class EvidenceDomain(str, Enum):
    POPULATION_FREQUENCY = "population_frequency"
    CASE_OBSERVATION = "case_observation"
    SEGREGATION = "segregation"
    DE_NOVO_OBSERVATION = "de_novo_observation"
    FUNCTIONAL_ASSAY = "functional_assay"
    COMPUTATIONAL_PREDICTION = "computational_prediction"
    GENE_DISEASE_VALIDITY = "gene_disease_validity"
    MECHANISM = "mechanism"
    ALLELIC_DATA = "allelic_data"
    PHENOTYPE_ASSOCIATION = "phenotype_association"
    LABORATORY_METHOD = "laboratory_method"
    TECHNICAL_LIMITATION = "technical_limitation"
    GUIDELINE_STATEMENT = "guideline_statement"
    CONFLICTING_INTERPRETATION = "conflicting_interpretation"
    OTHER = "other"


class HumanReviewStatus(str, Enum):
    UNREVIEWED = "unreviewed"
    PENDING = "pending"
    ACCEPTED_INTO_WORKSPACE = "accepted_into_workspace"
    EDITED = "edited"
    REJECTED = "rejected"
    DEFERRED = "deferred"
    REQUIRES_REVIEW = "requires_review"


class ReviewActionType(str, Enum):
    ACCEPT_AS_TRANSCRIBED = "accept_as_transcribed"
    EDIT_TRANSCRIPTION = "edit_transcription"
    REJECT_TRANSCRIPTION = "reject_transcription"
    ACCEPT_NORMALIZATION = "accept_normalization"
    EDIT_NORMALIZATION = "edit_normalization"
    REJECT_NORMALIZATION = "reject_normalization"
    REQUEST_SOURCE_REPORT = "request_source_report"
    REQUEST_MORE_INFORMATION = "request_more_information"
    APPROVE_QUERY_FOR_RETRIEVAL = "approve_query_for_retrieval"
    EDIT_QUERY = "edit_query"
    REJECT_QUERY = "reject_query"
    ACCEPT_LEDGER_ENTRY = "accept_ledger_entry"
    ANNOTATE_LEDGER_ENTRY = "annotate_ledger_entry"
    MARK_NOT_APPLICABLE = "mark_not_applicable"
    MARK_DUPLICATE = "mark_duplicate"
    MARK_CONFLICT = "mark_conflict"
    DEFER_REVIEW = "defer_review"
    RECORD_EXTERNAL_INTERPRETATION = "record_external_interpretation"


class FactType(str, Enum):
    REFERRAL_FACT = "referral_fact"
    PHENOTYPE_FACT = "phenotype_fact"
    HPO_FACT = "hpo_fact"
    PEDIGREE_FACT = "pedigree_fact"
    RELATIONSHIP_FACT = "relationship_fact"
    PREVIOUS_INVESTIGATION_FACT = "previous_investigation_fact"
    TEST_STRATEGY_OPTION = "test_strategy_option"
    SAMPLE_FACT = "sample_fact"
    EXTERNAL_REPORT_FACT = "external_report_fact"


class FactRelationship(str, Enum):
    SUPPORTS_CONTEXT = "supports_context"
    CONFLICTS_WITH_CONTEXT = "conflicts_with_context"
    SUPERSEDES_EXTERNAL_RECORD = "supersedes_external_record"
    DUPLICATES_EXTERNAL_RECORD = "duplicates_external_record"
    RELATED_TO_PRIOR_TEST = "related_to_prior_test"
    RELATED_TO_STRATEGY_OPTION = "related_to_strategy_option"
    REQUIRES_CLINICIAN_CORRELATION = "requires_clinician_correlation"


class ResultSourceProvenance(FrozenResultEvidenceModel):
    source_type: str = Field(min_length=1, max_length=80)
    source_document_id: str | None = Field(default=None, max_length=120)
    source_document_hash: str | None = Field(default=None, pattern=r"^[a-fA-F0-9]{64}$")
    source_document_name: str | None = Field(default=None, max_length=240)
    source_document_date: str | None = Field(default=None, max_length=40)
    source_page_or_section: str | None = Field(default=None, max_length=120)
    reporting_laboratory: str | None = Field(default=None, max_length=240)
    laboratory_location: str | None = Field(default=None, max_length=240)
    laboratory_accreditation_status: ExplicitInformationState = ExplicitInformationState.NOT_PROVIDED
    accreditation_scope_verified: ExplicitInformationState = ExplicitInformationState.NOT_PROVIDED
    test_name_as_reported: str | None = Field(default=None, max_length=300)
    test_method_as_reported: str | None = Field(default=None, max_length=1000)
    test_scope_as_reported: str | None = Field(default=None, max_length=4000)
    specimen_type: str | None = Field(default=None, max_length=120)
    specimen_collection_date: str | None = Field(default=None, max_length=40)
    report_issue_date: str | None = Field(default=None, max_length=40)
    report_version: str | None = Field(default=None, max_length=80)
    report_status: str | None = Field(default=None, max_length=80)
    external_order_reference: str | None = Field(default=None, max_length=120)
    external_case_reference: str | None = Field(default=None, max_length=120)
    entered_by: str | None = Field(default=None, max_length=120)
    entered_at: str | None = Field(default=None, max_length=40)
    reviewed_by: str | None = Field(default=None, max_length=120)
    reviewed_at: str | None = Field(default=None, max_length=40)
    translation_status: ExplicitInformationState = ExplicitInformationState.NOT_APPLICABLE
    transcription_status: ExplicitInformationState = ExplicitInformationState.REQUIRES_REVIEW
    provenance_notes: str | None = Field(default=None, max_length=2000)


class ExternalLaboratoryClassification(FrozenResultEvidenceModel):
    value: ExternalClassificationValue
    value_as_reported: str = Field(min_length=1, max_length=240)
    label: Literal["external_laboratory_classification"] = "external_laboratory_classification"
    classification_system_as_reported: str | None = Field(default=None, max_length=240)
    classification_date: str | None = Field(default=None, max_length=40)
    classification_source: str = Field(min_length=1, max_length=240)
    classification_review_status: HumanReviewStatus = HumanReviewStatus.UNREVIEWED
    required_wording: Literal[
        "Classification reported by the external source; not assigned by InSilicoPop."
    ] = "Classification reported by the external source; not assigned by InSilicoPop."


class SequenceVariantFinding(FrozenResultEvidenceModel):
    gene_symbol_reported: str | None = Field(default=None, max_length=80)
    transcript_reported: str | None = Field(default=None, max_length=120)
    reference_assembly_reported: str | None = Field(default=None, max_length=80)
    chromosome: str | None = Field(default=None, max_length=40)
    genomic_position: int | None = Field(default=None, ge=0)
    reference_allele: str | None = Field(default=None, max_length=1000)
    alternate_allele: str | None = Field(default=None, max_length=1000)
    hgvs_g_reported: str | None = Field(default=None, max_length=1000)
    hgvs_c_reported: str | None = Field(default=None, max_length=1000)
    hgvs_p_reported: str | None = Field(default=None, max_length=1000)
    zygosity_reported: str | None = Field(default=None, max_length=120)
    phase_status: str | None = Field(default=None, max_length=120)
    allele_origin_reported: str | None = Field(default=None, max_length=120)
    mosaic_status_reported: str | None = Field(default=None, max_length=240)
    variant_type: str | None = Field(default=None, max_length=120)
    alternate_source_representations: list[str] = Field(default_factory=list, max_length=20)
    representations_equivalent: bool | None = None


class CopyNumberFinding(FrozenResultEvidenceModel):
    copy_number_type: str | None = Field(default=None, max_length=120)
    region_reported: str | None = Field(default=None, max_length=500)
    assembly: str | None = Field(default=None, max_length=80)
    chromosome: str | None = Field(default=None, max_length=40)
    start: int | None = Field(default=None, ge=0)
    end: int | None = Field(default=None, ge=0)
    copy_number_state: str | None = Field(default=None, max_length=120)
    size_bp: int | None = Field(default=None, ge=0)
    genes_listed_by_source: list[str] = Field(default_factory=list, max_length=1000)
    inheritance_reported: str | None = Field(default=None, max_length=240)
    mosaic_fraction_reported: str | None = Field(default=None, max_length=120)
    platform_resolution: str | None = Field(default=None, max_length=240)
    breakpoint_precision: BreakpointPrecision = BreakpointPrecision.UNKNOWN


class StructuralCytogeneticFinding(FrozenResultEvidenceModel):
    iscn_reported: str | None = Field(default=None, max_length=2000)
    structural_event_type: str | None = Field(default=None, max_length=120)
    chromosomes_involved: list[str] = Field(default_factory=list, max_length=100)
    balanced_status_reported: str | None = Field(default=None, max_length=120)
    breakpoints_reported: list[str] = Field(default_factory=list, max_length=100)
    mosaic_cell_counts: str | None = Field(default=None, max_length=240)
    culture_or_tissue: str | None = Field(default=None, max_length=240)


class RepeatExpansionFinding(FrozenResultEvidenceModel):
    repeat_locus: str | None = Field(default=None, max_length=120)
    repeat_unit: str | None = Field(default=None, max_length=120)
    allele_sizes_reported: list[str] = Field(default_factory=list, max_length=20)
    allele_category_reported: list[str] = Field(default_factory=list, max_length=20)
    measurement_method: str | None = Field(default=None, max_length=240)
    methylation_status_reported: str | None = Field(default=None, max_length=240)
    interruption_status_reported: str | None = Field(default=None, max_length=240)
    reportable_range: str | None = Field(default=None, max_length=240)


class MitochondrialFinding(FrozenResultEvidenceModel):
    mt_reference_sequence: str | None = Field(default=None, max_length=120)
    mt_hgvs_reported: str | None = Field(default=None, max_length=1000)
    heteroplasmy_reported: str | None = Field(default=None, max_length=240)
    heteroplasmy_value: float | None = Field(default=None, ge=0)
    heteroplasmy_unit: str | None = Field(default=None, max_length=40)
    specimen_type: str | None = Field(default=None, max_length=120)
    detection_limit: str | None = Field(default=None, max_length=120)
    mtdna_deletion_reported: str | None = Field(default=None, max_length=1000)
    mtdna_copy_number_or_depletion_reported: str | None = Field(default=None, max_length=1000)
    nuclear_gene_finding: str | None = Field(default=None, max_length=1000)


class BiochemicalFinding(FrozenResultEvidenceModel):
    analyte: str = Field(min_length=1, max_length=120)
    value: float
    unit_reported: str = Field(min_length=1, max_length=80)
    requested_normalized_unit: str | None = Field(default=None, max_length=80)
    reference_interval: str | None = Field(default=None, max_length=240)
    specimen: str | None = Field(default=None, max_length=120)
    collection_context: str | None = Field(default=None, max_length=500)
    fasting_status: str | None = Field(default=None, max_length=120)
    treatment_status: str | None = Field(default=None, max_length=240)
    abnormal_flag_as_reported: str | None = Field(default=None, max_length=120)
    laboratory_comment: str | None = Field(default=None, max_length=1000)


class NegativeResultScope(FrozenResultEvidenceModel):
    negative_scope: str = Field(min_length=1, max_length=2000)
    genes_or_regions_assessed: list[str] = Field(default_factory=list, max_length=5000)
    variant_classes_assessed: list[str] = Field(default_factory=list, max_length=100)
    coverage_or_resolution_as_reported: str | None = Field(default=None, max_length=2000)
    limitations_as_reported: list[str] = Field(default_factory=list, max_length=100)
    secondary_findings_policy: str | None = Field(default=None, max_length=1000)
    reanalysis_policy_as_reported: str | None = Field(default=None, max_length=1000)


class FactLink(FrozenResultEvidenceModel):
    link_id: str = Field(min_length=1, max_length=100, pattern=LOCAL_ID_PATTERN)
    fact_type: FactType
    fact_id: str = Field(min_length=1, max_length=120, pattern=LOCAL_ID_PATTERN)
    relationship: FactRelationship
    notes: str | None = Field(default=None, max_length=1000)


class ReportedFinding(FrozenResultEvidenceModel):
    finding_id: str = Field(min_length=1, max_length=100, pattern=LOCAL_ID_PATTERN)
    category: ResultCategory
    original_text: str = Field(min_length=1, max_length=10000)
    original_terminology: list[str] = Field(default_factory=list, max_length=100)
    original_variant_string: str | None = Field(default=None, max_length=2000)
    original_result_comments: str | None = Field(default=None, max_length=4000)
    original_report_limitations: list[str] = Field(default_factory=list, max_length=100)
    transcription_confidence: ExplicitInformationState = ExplicitInformationState.REQUIRES_REVIEW
    human_transcription_verified: bool = False
    sequence_variant: SequenceVariantFinding | None = None
    copy_number: CopyNumberFinding | None = None
    structural_or_cytogenetic: StructuralCytogeneticFinding | None = None
    repeat_expansion: RepeatExpansionFinding | None = None
    mitochondrial: MitochondrialFinding | None = None
    biochemical: BiochemicalFinding | None = None
    negative_or_uninformative: NegativeResultScope | None = None
    external_laboratory_classification: ExternalLaboratoryClassification | None = None
    fact_links: list[FactLink] = Field(default_factory=list, max_length=100)


class ResultIntakeRecord(FrozenResultEvidenceModel):
    result_id: str = Field(min_length=1, max_length=100, pattern=LOCAL_ID_PATTERN)
    case_id: str = Field(min_length=1, max_length=100, pattern=LOCAL_ID_PATTERN)
    category: ResultCategory
    provenance: ResultSourceProvenance
    findings: list[ReportedFinding] = Field(default_factory=list, max_length=500)
    blocking_missing_fields: list[str] = Field(default_factory=list, max_length=100)
    advisory_missing_fields: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def unique_findings_and_matching_category(self) -> "ResultIntakeRecord":
        finding_ids = [item.finding_id for item in self.findings]
        if len(finding_ids) != len(set(finding_ids)):
            raise ValueError("finding IDs must be unique within a result record")
        if any(item.category != self.category for item in self.findings):
            raise ValueError("finding category must match its result category")
        return self


class RetrievalQuery(FrozenResultEvidenceModel):
    query_id: str = Field(min_length=1, max_length=100, pattern=LOCAL_ID_PATTERN)
    finding_id: str = Field(min_length=1, max_length=100, pattern=LOCAL_ID_PATTERN)
    normalized_gene: str | None = Field(default=None, max_length=80)
    normalized_variant: str | None = Field(default=None, max_length=2000)
    transcript: str | None = Field(default=None, max_length=120)
    reference_assembly: str | None = Field(default=None, max_length=80)
    variant_type: str | None = Field(default=None, max_length=120)
    condition_term_reviewed: str | None = Field(default=None, max_length=240)
    inheritance_term_reviewed: str | None = Field(default=None, max_length=120)
    evidence_source_selection: list[str] = Field(default_factory=list, max_length=30)
    date_range: str | None = Field(default=None, max_length=80)
    language: str = Field(default="en", min_length=2, max_length=20)
    review_status: Literal["unreviewed", "human_reviewed", "rejected"] = "unreviewed"
    reviewed_by: str | None = Field(default=None, max_length=120)
    reviewed_at: str | None = Field(default=None, max_length=40)


class FixtureEvidenceRecord(FrozenResultEvidenceModel):
    fixture_record_id: str = Field(min_length=1, max_length=120, pattern=LOCAL_ID_PATTERN)
    query_id: str = Field(min_length=1, max_length=100, pattern=LOCAL_ID_PATTERN)
    source_identifier: str = Field(min_length=1, max_length=300)
    source_title: str = Field(min_length=1, max_length=500)
    source_version: str = Field(min_length=1, max_length=120)
    publication_date: str | None = Field(default=None, max_length=40)
    jurisdiction: str | None = Field(default=None, max_length=120)
    evidence_domain: EvidenceDomain
    source_statement: str = Field(min_length=1, max_length=10000)
    source_excerpt: str | None = Field(default=None, max_length=4000)
    source_location: str | None = Field(default=None, max_length=500)
    structured_observation: dict[str, Any] = Field(default_factory=dict)
    applicability_status: str = Field(default="unreviewed", max_length=80)
    interpretation_tag: str | None = Field(default=None, max_length=120)
    conflict_group_id: str | None = Field(default=None, max_length=120)
    withdrawn_or_updated: bool = False


class ControlledSourceAdapter(FrozenResultEvidenceModel):
    source_name: str = Field(min_length=1, max_length=160)
    source_type: EvidenceSourceType
    source_version: str = Field(min_length=1, max_length=120)
    source_url_or_identifier: str = Field(min_length=1, max_length=500)
    adapter_state: Literal[
        "available",
        "source_unavailable",
        "authentication_required",
        "rate_limited",
    ] = "available"
    retrieval_method: Literal["deterministic_fixture", "local_evidence_store"] = "deterministic_fixture"
    records: list[FixtureEvidenceRecord] = Field(default_factory=list, max_length=1000)
    warnings: list[str] = Field(default_factory=list, max_length=100)


class EvidenceSummaryRequest(FrozenResultEvidenceModel):
    summary_request_id: str = Field(min_length=1, max_length=100, pattern=LOCAL_ID_PATTERN)
    finding_id: str = Field(min_length=1, max_length=100, pattern=LOCAL_ID_PATTERN)
    requested_by: str = Field(min_length=1, max_length=120)
    requested_at: str = Field(min_length=1, max_length=40)
    summary_limitations: list[str] = Field(default_factory=list, max_length=100)


class HumanReviewAction(FrozenResultEvidenceModel):
    action_id: str = Field(min_length=1, max_length=100, pattern=LOCAL_ID_PATTERN)
    action: ReviewActionType
    target_type: Literal["result", "finding", "normalization", "query", "ledger_entry", "external_interpretation"]
    target_id: str = Field(min_length=1, max_length=120)
    reviewer_role: str = Field(min_length=1, max_length=120)
    reviewer_id: str | None = Field(default=None, max_length=120)
    timestamp: str = Field(min_length=1, max_length=40)
    before_value: Any = None
    after_value: Any = None
    notes: str | None = Field(default=None, max_length=2000)


class ExternalInterpretation(FrozenResultEvidenceModel):
    external_interpretation_id: str = Field(min_length=1, max_length=100, pattern=LOCAL_ID_PATTERN)
    finding_id: str = Field(min_length=1, max_length=100, pattern=LOCAL_ID_PATTERN)
    external_interpretation_recorded: Literal[True] = True
    external_interpretation_source: str = Field(min_length=1, max_length=240)
    external_interpretation_date: str | None = Field(default=None, max_length=40)
    external_interpretation_text: str = Field(min_length=1, max_length=4000)
    external_classification: ExternalClassificationValue | None = None
    verification_status: HumanReviewStatus = HumanReviewStatus.UNREVIEWED
    required_wording: Literal[
        "External interpretation recorded; not assigned by InSilicoPop."
    ] = "External interpretation recorded; not assigned by InSilicoPop."


class ResultEvidenceWorkspaceRequest(FrozenResultEvidenceModel):
    schema_version: Literal["0.32"] = RESULT_EVIDENCE_SCHEMA_VERSION
    results: list[ResultIntakeRecord] = Field(default_factory=list, max_length=200)
    retrieval_queries: list[RetrievalQuery] = Field(default_factory=list, max_length=500)
    source_adapters: list[ControlledSourceAdapter] = Field(default_factory=list, max_length=100)
    summary_requests: list[EvidenceSummaryRequest] = Field(default_factory=list, max_length=200)
    review_actions: list[HumanReviewAction] = Field(default_factory=list, max_length=2000)
    external_interpretations: list[ExternalInterpretation] = Field(default_factory=list, max_length=500)
    human_review_required: Literal[True] = True

    @model_validator(mode="after")
    def identifiers_are_unique(self) -> "ResultEvidenceWorkspaceRequest":
        groups = {
            "result": [item.result_id for item in self.results],
            "query": [item.query_id for item in self.retrieval_queries],
            "source adapter": [item.source_name for item in self.source_adapters],
            "summary request": [item.summary_request_id for item in self.summary_requests],
            "review action": [item.action_id for item in self.review_actions],
            "external interpretation": [
                item.external_interpretation_id for item in self.external_interpretations
            ],
        }
        all_findings = [finding.finding_id for result in self.results for finding in result.findings]
        groups["finding"] = all_findings
        for label, identifiers in groups.items():
            if len(identifiers) != len(set(identifiers)):
                raise ValueError(f"{label} identifiers must be unique")
        return self


class IntakeAssessment(FrozenResultEvidenceModel):
    result_id: str
    intake_status: NormalizationOutcome
    source_report_present: bool
    blocking_missing_fields: list[str]
    advisory_missing_fields: list[str]
    bounded_result_wording: str | None = None
    rule_ids: list[str] = Field(default_factory=list)


class NormalizedFinding(FrozenResultEvidenceModel):
    finding_id: str
    result_id: str
    category: ResultCategory
    reported_finding_snapshot: ReportedFinding
    reported_value: dict[str, Any]
    normalized_value: dict[str, Any]
    normalization_status: NormalizationOutcome
    normalization_method: str
    normalization_notes: list[str]
    normalization_rule_id: str
    normalization_version: Literal["insilicopop-result-normalization-0.32.0"] = NORMALIZATION_VERSION
    normalization_timestamp: str | None = None
    normalization_warnings: list[str] = Field(default_factory=list)
    human_review_status: HumanReviewStatus = HumanReviewStatus.PENDING
    source_state: Literal["normalized"] = "normalized"


class FactLinkAssessment(FrozenResultEvidenceModel):
    link_id: str
    finding_id: str
    fact_type: FactType
    fact_id: str
    relationship: FactRelationship
    linkage_status: Literal["linked", "requires_rule_review"]
    message: str


class RetrievalRecord(FrozenResultEvidenceModel):
    retrieval_id: str
    query_id: str
    finding_id: str
    query_terms: dict[str, Any]
    normalized_query: str
    source_name: str
    source_type: EvidenceSourceType | None = None
    source_version: str | None = None
    source_url_or_identifier: str | None = None
    retrieved_at: str | None = None
    retrieval_method: str | None = None
    provider: str
    external_llm_called: bool
    byok_used: bool
    result_count: int
    pagination_state: Literal["complete", "not_applicable"] = "not_applicable"
    raw_response_hash: str | None = None
    cache_status: Literal["fixture", "local", "not_applicable"] = "not_applicable"
    state: RetrievalState
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    returned_fixture_record_ids: list[str] = Field(default_factory=list)
    no_records_wording: str | None = None


class EvidenceLedgerEntry(FrozenResultEvidenceModel):
    ledger_entry_id: str
    case_id: str
    finding_id: str
    retrieval_id: str
    source_type: EvidenceSourceType
    source_identifier: str
    source_title: str
    source_version: str
    publication_date: str | None = None
    retrieval_date: str | None = None
    jurisdiction: str | None = None
    evidence_domain: EvidenceDomain
    source_statement: str
    source_excerpt: str | None = None
    source_location: str | None = None
    system_summary: str | None = None
    summary_status: Literal["not_requested", "proposed_not_approved"] = "not_requested"
    summary_based_on_source_ids: list[str] = Field(default_factory=list)
    summary_limitations: list[str] = Field(default_factory=list)
    structured_observation: dict[str, Any] = Field(default_factory=dict)
    applicability_status: str
    applicability_notes: str | None = None
    conflict_detected: bool = False
    conflict_group_id: str | None = None
    conflict_description: str | None = None
    duplicate_group_id: str | None = None
    duplicate_of: str | None = None
    newer_version_of: str | None = None
    supersedes_source_record: str | None = None
    withdrawn_or_updated: bool = False
    human_review_status: HumanReviewStatus = HumanReviewStatus.UNREVIEWED
    reviewer_notes: str | None = None
    superseded_by: str | None = None
    requires_human_review: Literal[True] = True
    created_at: str | None = None


class GeneratedEvidenceSummary(FrozenResultEvidenceModel):
    summary_id: str
    finding_id: str
    system_summary: str
    summary_status: Literal["proposed_not_approved"] = "proposed_not_approved"
    summary_based_on_source_ids: list[str]
    summary_limitations: list[str]
    human_review_status: HumanReviewStatus = HumanReviewStatus.PENDING
    source_state: Literal["system_generated"] = "system_generated"


class ResultEvidenceWorkspaceResult(FrozenResultEvidenceModel):
    schema_version: Literal["0.32"] = RESULT_EVIDENCE_SCHEMA_VERSION
    result_intake_version: Literal["insilicopop-result-intake-0.32.0"] = RESULT_INTAKE_VERSION
    normalization_version: Literal["insilicopop-result-normalization-0.32.0"] = NORMALIZATION_VERSION
    retrieval_version: Literal["insilicopop-controlled-evidence-retrieval-0.32.0"] = RETRIEVAL_VERSION
    ledger_version: Literal["insilicopop-evidence-ledger-0.32.0"] = LEDGER_VERSION
    pseudonymous_case_id: str
    source_results: list[ResultIntakeRecord]
    intake_assessments: list[IntakeAssessment]
    normalized_findings: list[NormalizedFinding]
    fact_link_assessments: list[FactLinkAssessment]
    retrieval_queries: list[RetrievalQuery]
    retrieval_records: list[RetrievalRecord]
    ledger_entries: list[EvidenceLedgerEntry]
    generated_summaries: list[GeneratedEvidenceSummary]
    review_actions: list[HumanReviewAction]
    external_interpretations: list[ExternalInterpretation]
    normalization_rules: list[str]
    source_document_hashes: list[str]
    retrieval_source_versions: dict[str, str]
    raw_response_hashes: list[str]
    audit_history: list[dict[str, Any]]
    stable_workspace_id: str
    external_llm_called: bool = False
    provider: str = "deterministic_fixture"
    byok_used: bool = False
    human_review_required: Literal[True] = True
    research_use_only: Literal[True] = True
    diagnosis_made: Literal[False] = False
    treatment_recommendation_made: Literal[False] = False
    final_acmg_classification_made: Literal[False] = False
    pathogenicity_interpretation_performed: Literal[False] = False
    clinical_sign_out_made: Literal[False] = False
    causality_claim_made: Literal[False] = False
    acmg_criteria_generated: Literal[False] = False
    test_order_placed: Literal[False] = False
