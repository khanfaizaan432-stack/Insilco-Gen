from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


VARIANT_INTELLIGENCE_SCHEMA_VERSION = "0.30"
VARIANT_INTELLIGENCE_ALGORITHM_VERSION = "insilicopop-variant-intelligence-0.30.1"


class VariantFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)


class VariantRepresentationType(str, Enum):
    HGVS_GENOMIC = "hgvs_genomic"
    HGVS_CODING = "hgvs_coding"
    HGVS_NON_CODING = "hgvs_non_coding"
    HGVS_RNA = "hgvs_rna"
    HGVS_PROTEIN = "hgvs_protein"
    GENOMIC_COORDINATE = "genomic_coordinate"
    VCF_LIKE_FIELDS = "vcf_like_fields"
    SPDI = "spdi"
    VRS = "vrs"
    CAID = "caid"
    FREE_TEXT = "free_text"
    UNKNOWN = "unknown"


class CoordinateSystem(str, Enum):
    ONE_BASED_CLOSED = "one_based_closed"
    ZERO_BASED_HALF_OPEN = "zero_based_half_open"
    VCF_ONE_BASED = "vcf_one_based"
    UNKNOWN = "unknown"


class RequestedVariantOutput(str, Enum):
    VALIDATED_SUPPLIED_REPRESENTATION = "validated_supplied_representation"
    NORMALIZED_HGVS = "normalized_hgvs"
    SPDI = "spdi"
    VRS = "vrs"
    CAID = "caid"
    CANONICAL_INTERNAL_ALLELE = "canonical_internal_allele"


class VariantReviewState(str, Enum):
    UNREVIEWED = "unreviewed"
    PENDING = "pending"
    IN_REVIEW = "in_review"
    CONFIRMED = "confirmed"
    NEEDS_REVISION = "needs_revision"


class VariantValidationStatus(str, Enum):
    VALID = "valid"
    INVALID = "invalid"
    PARTIALLY_VALID = "partially_valid"
    CANNOT_VALIDATE = "cannot_validate"
    UNSUPPORTED = "unsupported"


class VariantNormalizationStatus(str, Enum):
    NORMALIZED = "normalized"
    PARTIALLY_NORMALIZED = "partially_normalized"
    NOT_NORMALIZED = "not_normalized"
    CANNOT_NORMALIZE = "cannot_normalize"
    UNSUPPORTED = "unsupported"


class VariantEquivalenceStatus(str, Enum):
    EXACT_EQUIVALENCE = "exact_equivalence"
    NORMALIZED_EQUIVALENCE = "normalized_equivalence"
    UNRESOLVED_EQUIVALENCE = "unresolved_equivalence"
    INCOMPATIBLE_REPRESENTATIONS = "incompatible_representations"
    UNSUPPORTED_REPRESENTATION = "unsupported_representation"


class DeclaredVariantClass(str, Enum):
    SNV = "snv"
    DELETION = "deletion"
    INSERTION = "insertion"
    DUPLICATION = "duplication"
    DELINS = "delins"
    MNV = "mnv"
    CNV = "cnv"
    STRUCTURAL_VARIANT = "structural_variant"
    INVERSION = "inversion"
    TRANSLOCATION = "translocation"
    REPEAT_EXPANSION = "repeat_expansion"
    MOBILE_ELEMENT_INSERTION = "mobile_element_insertion"
    BREAKEND = "breakend"
    GENE_FUSION = "gene_fusion"
    CHROMOSOMAL_ABNORMALITY = "chromosomal_abnormality"
    MOSAIC = "mosaic"
    SOMATIC = "somatic"
    MITOCHONDRIAL_COMPLEX = "mitochondrial_complex"
    COMPLEX_REARRANGEMENT = "complex_rearrangement"
    PHARMACOGENOMIC_HAPLOTYPE = "pharmacogenomic_haplotype"
    HLA_ALLELE = "hla_allele"
    STAR_ALLELE = "star_allele"
    POLYGENIC_SCORE = "polygenic_score"
    OTHER = "other"
    UNKNOWN = "unknown"


class StructuredAlleleInput(VariantFrozenModel):
    chromosome: str = Field(min_length=1, max_length=40)
    position: int = Field(ge=0)
    reference: str = Field(max_length=500)
    alternate: str = Field(max_length=500)
    coordinate_system: CoordinateSystem
    genome_build: str | None = Field(default=None, min_length=1, max_length=80)
    reference_accession: str | None = Field(default=None, max_length=120)
    reference_source_id: str | None = Field(default=None, max_length=120)
    reference_context_sequence: str | None = Field(default=None, max_length=2000)
    reference_context_start: int | None = Field(default=None, ge=0)
    reference_context_verified: bool = False

    @model_validator(mode="after")
    def reference_window_is_complete(self) -> "StructuredAlleleInput":
        supplied = self.reference_context_sequence is not None or self.reference_context_start is not None
        if supplied and (self.reference_context_sequence is None or self.reference_context_start is None):
            raise ValueError("reference context sequence and start must be supplied together")
        if self.reference_context_verified and not supplied:
            raise ValueError("verified reference context requires a bounded sequence and start")
        return self


class VariantNormalizationRequest(VariantFrozenModel):
    request_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    candidate_variant_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    supplied_representation: str = Field(min_length=1, max_length=1000)
    representation_type: VariantRepresentationType
    declared_variant_class: DeclaredVariantClass = DeclaredVariantClass.UNKNOWN
    supplied_genome_build: str | None = Field(default=None, max_length=80)
    supplied_reference_accession: str | None = Field(default=None, max_length=120)
    supplied_transcript_accession: str | None = Field(default=None, max_length=120)
    supplied_gene_id: str | None = Field(default=None, max_length=120)
    supplied_chromosome: str | None = Field(default=None, max_length=40)
    supplied_reference: str | None = Field(default=None, max_length=500)
    supplied_alternate: str | None = Field(default=None, max_length=500)
    supplied_spdi: str | None = Field(default=None, max_length=1000)
    supplied_vrs: str | dict[str, Any] | None = None
    supplied_caid: str | None = Field(default=None, max_length=120)
    supplied_protein_consequence: str | None = Field(default=None, max_length=500)
    structured_allele: StructuredAlleleInput | None = None
    requested_outputs: list[RequestedVariantOutput] = Field(default_factory=list, max_length=10)
    provenance_source_ids: list[str] = Field(default_factory=list, max_length=30)
    review_state: VariantReviewState = VariantReviewState.PENDING


class VariantIntelligenceRequest(VariantFrozenModel):
    schema_version: Literal["0.30"] = VARIANT_INTELLIGENCE_SCHEMA_VERSION
    normalization_requests: list[VariantNormalizationRequest] = Field(default_factory=list, max_length=500)
    reviewer_status: VariantReviewState = VariantReviewState.PENDING
    human_review_required: Literal[True] = True

    @model_validator(mode="after")
    def unique_request_ids(self) -> "VariantIntelligenceRequest":
        request_ids = [item.request_id for item in self.normalization_requests]
        if len(request_ids) != len(set(request_ids)):
            raise ValueError("variant normalization request IDs must be unique")
        return self


class VariantIssue(VariantFrozenModel):
    issue_id: str
    code: str
    message: str
    field: str | None = None
    severity: Literal["error", "warning", "missing", "unsupported", "conflict", "review"]
    provenance_source_ids: list[str] = Field(default_factory=list)
    human_review_required: Literal[True] = True


class VariantReferenceContext(VariantFrozenModel):
    genome_build: str | None = None
    chromosome: str | None = None
    reference_accession: str | None = None
    reference_source_id: str | None = None
    accession: str | None = None
    accession_version: str | None = None
    coordinate_system: str | None = None
    reference_window_coordinate_system: str | None = None
    position_supplied: int | None = None
    start_zero_based: int | None = None
    window_start_zero_based: int | None = None
    window_end_zero_based: int | None = None
    sequence_sha256: str | None = None
    registry_version: str | None = None
    provenance_source_id: str | None = None
    fixture_only: bool = False
    reference_context_verified: bool = False


class VariantTranscriptContext(VariantFrozenModel):
    supplied_transcript_accession: str | None = None
    version_explicit: bool = False
    transcript_selected: Literal[False] = False


class VariantNormalizationOperation(VariantFrozenModel):
    operation_id: str
    operation_name: str
    algorithm_version: Literal["insilicopop-variant-intelligence-0.30.1"] = VARIANT_INTELLIGENCE_ALGORITHM_VERSION
    status: Literal["succeeded", "refused", "not_applicable"]
    input_hash: str
    output_hash: str | None = None
    reference_context: VariantReferenceContext
    warnings: list[str] = Field(default_factory=list)


class VariantNormalizedOutput(VariantFrozenModel):
    output_id: str
    output_type: RequestedVariantOutput
    status: Literal["generated", "preserved", "unsupported", "not_generated"]
    value: str | dict[str, Any] | None = None
    reason_code: str | None = None
    human_review_required: Literal[True] = True


class VariantNormalizationResult(VariantFrozenModel):
    schema_version: Literal["0.30"] = VARIANT_INTELLIGENCE_SCHEMA_VERSION
    algorithm_version: Literal["insilicopop-variant-intelligence-0.30.1"] = VARIANT_INTELLIGENCE_ALGORITHM_VERSION
    request_id: str
    candidate_variant_id: str
    supplied_request_snapshot: VariantNormalizationRequest
    variant_class: str
    validation_status: VariantValidationStatus
    normalization_status: VariantNormalizationStatus
    equivalence_status: VariantEquivalenceStatus
    normalized_outputs: list[VariantNormalizedOutput]
    reference_context_used: VariantReferenceContext
    transcript_context_used: VariantTranscriptContext
    normalization_operations: list[VariantNormalizationOperation]
    validation_errors: list[VariantIssue]
    warnings: list[VariantIssue]
    missing_information: list[VariantIssue]
    unsupported_reasons: list[VariantIssue]
    conflicts: list[VariantIssue]
    review_actions: list[VariantIssue]
    provenance_source_ids: list[str]
    stable_result_id: str
    research_use_only: Literal[True] = True
    human_review_required: Literal[True] = True
    diagnosis_provided: Literal[False] = False
    treatment_recommended: Literal[False] = False
    final_acmg_classification: Literal[False] = False
    pathogenicity_interpretation_performed: Literal[False] = False
    transcript_selection_performed: Literal[False] = False
    external_llm_called: Literal[False] = False
    external_tools_executed: Literal[False] = False
    raw_genomic_files_parsed: Literal[False] = False


class VariantIntelligenceResult(VariantFrozenModel):
    schema_version: Literal["0.30"] = VARIANT_INTELLIGENCE_SCHEMA_VERSION
    algorithm_version: Literal["insilicopop-variant-intelligence-0.30.1"] = VARIANT_INTELLIGENCE_ALGORITHM_VERSION
    pseudonymous_case_id: str
    normalization_results: list[VariantNormalizationResult]
    validation_status_counts: dict[str, int]
    normalization_status_counts: dict[str, int]
    equivalence_status_counts: dict[str, int]
    reviewer_status: str
    stable_result_id: str
    variant_validation_performed: Literal[True] = True
    variant_normalization_performed: bool
    variant_pathogenicity_interpretation_performed: Literal[False] = False
    transcript_selection_performed: Literal[False] = False
    research_use_only: Literal[True] = True
    human_review_required: Literal[True] = True
    diagnosis_provided: Literal[False] = False
    treatment_recommended: Literal[False] = False
    final_acmg_classification: Literal[False] = False
    external_llm_called: Literal[False] = False
    external_tools_executed: Literal[False] = False
    raw_genomic_files_parsed: Literal[False] = False
