from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    field_serializer,
    field_validator,
    model_validator,
)


RESULT_GATEWAY_SCHEMA_VERSION = "0.36"
RESULT_GATEWAY_VERSION = "insilicopop-controlled-result-gateway-0.36.0"
ADAPTER_REGISTRY_VERSION = "insilicopop-result-adapter-registry-0.36.0"
PARSER_VERSION = "insilicopop-result-package-parser-0.36.0"
LOCAL_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"
SHA256_PATTERN = r"^[a-fA-F0-9]{64}$"


class ResultLogicalRole(str, Enum):
    VCF = "vcf"
    STRUCTURED_LABORATORY_REPORT = "structured_laboratory_report"
    QC = "qc"
    COVERAGE = "coverage"
    ASSAY_METADATA = "assay_metadata"


CANONICAL_RESULT_LOGICAL_ROLES = tuple(role.value for role in ResultLogicalRole)
RecordSelectorId = Annotated[StrictStr, Field(min_length=1, max_length=160, pattern=LOCAL_ID_PATTERN)]


class FrozenResultGatewayModel(BaseModel):
    """Frozen gateway base; persisted collections are tuples or frozen child models."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=False,
        revalidate_instances="always",
    )


class StrictFrozenParameterModel(FrozenResultGatewayModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=False,
        revalidate_instances="always",
    )


class GatewayPackageStatus(str, Enum):
    RECEIVED = "received"
    VALIDATED = "validated"
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    PARTIAL = "partial"
    BLOCKED = "blocked"
    REJECTED = "rejected"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"
    TIMED_OUT = "timed_out"
    STALE = "stale"
    DUPLICATE = "duplicate"


class GatewayIssueSeverity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class VerificationState(str, Enum):
    SUPPLIED_BUT_UNVERIFIED = "supplied_but_unverified"
    INDEPENDENTLY_VERIFIED = "independently_verified"
    NOT_SUPPLIED = "not_supplied"
    NOT_APPLICABLE = "not_applicable"
    REQUIRES_REVIEW = "requires_review"


class ResultSourceState(str, Enum):
    SUPPLIED = "supplied"
    VERIFIED = "verified"
    NORMALIZED = "normalized"
    DETERMINISTIC = "deterministic"
    HUMAN_REVIEWED = "human_reviewed"
    OUT_OF_SCOPE = "out_of_scope"


class VariantScope(str, Enum):
    SNV = "snv"
    SMALL_INDEL = "small_indel"
    SYMBOLIC_OUT_OF_SCOPE = "symbolic_out_of_scope"
    STRUCTURAL_VARIANT_OUT_OF_SCOPE = "structural_variant_out_of_scope"
    COPY_NUMBER_OUT_OF_SCOPE = "copy_number_out_of_scope"
    MITOCHONDRIAL_OUT_OF_SCOPE = "mitochondrial_out_of_scope"
    LARGE_INDEL_OUT_OF_SCOPE = "large_indel_out_of_scope"
    REPEAT_OUT_OF_SCOPE = "repeat_out_of_scope"
    MOSAIC_OUT_OF_SCOPE = "mosaic_out_of_scope"
    MALFORMED = "malformed"


class OutOfScopeReasonCode(str, Enum):
    SYMBOLIC_ALLELE = "symbolic_allele"
    STRUCTURAL_VARIANT = "structural_variant"
    COPY_NUMBER_VARIANT = "copy_number_variant"
    MITOCHONDRIAL_VARIANT = "mitochondrial_variant"
    LARGE_INDEL = "large_indel"
    EXPLICIT_REPEAT = "explicit_repeat"
    EXPLICIT_MOSAIC = "explicit_mosaic"


class VariantNormalizationState(str, Enum):
    UNCHANGED_SOURCE = "unchanged_source"
    DECOMPOSED = "decomposed"
    REFERENCE_DEPENDENT_LEFT_NORMALIZATION_NOT_APPLIED = (
        "reference_dependent_left_normalization_not_applied"
    )
    OUT_OF_SCOPE_RETAINED = "out_of_scope_retained"
    NOT_NORMALIZED = "not_normalized"


class VCFPhaseState(str, Enum):
    PHASED = "phased"
    UNPHASED = "unphased"
    UNKNOWN = "unknown"


class AltPresenceState(str, Enum):
    PRESENT = "present"
    ABSENT = "absent"
    UNKNOWN = "unknown"


class AdapterAvailability(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class AdapterExecutionStatus(str, Enum):
    COMPLETED = "completed"
    PARTIAL = "partial"
    BLOCKED = "blocked"
    REJECTED = "rejected"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"
    TIMED_OUT = "timed_out"


class ReplayStatus(str, Enum):
    NOT_REQUESTED = "not_requested"
    NEW_INPUT = "new_input"
    REPLAYED = "replayed"
    STALE = "stale"
    DUPLICATE = "duplicate"


class NetworkPolicy(str, Enum):
    DISABLED = "disabled"
    LOCAL_ONLY = "local_only"


class GatewayLimits(FrozenResultGatewayModel):
    max_files: int = Field(default=100, ge=1, le=1000)
    max_file_bytes: int = Field(default=20_000_000, ge=1, le=100_000_000)
    max_total_bytes: int = Field(default=50_000_000, ge=1, le=200_000_000)
    max_records: int = Field(default=10_000, ge=1, le=1_000_000)
    max_output_bytes: int = Field(default=1_000_000, ge=1, le=20_000_000)
    timeout_seconds: int = Field(default=30, ge=1, le=600)


class GatewayIssue(FrozenResultGatewayModel):
    code: str = Field(min_length=1, max_length=120, pattern=LOCAL_ID_PATTERN)
    severity: GatewayIssueSeverity
    message: str = Field(min_length=1, max_length=1000)
    path: str | None = Field(default=None, max_length=300)
    record_id: str | None = Field(default=None, max_length=160, pattern=LOCAL_ID_PATTERN)


class StringValueEntry(FrozenResultGatewayModel):
    key: str = Field(min_length=1, max_length=300)
    value: str = Field(max_length=4000)


class ScalarValueEntry(FrozenResultGatewayModel):
    key: str = Field(min_length=1, max_length=300)
    value: str | int | float | bool | None


class FileHashEntry(FrozenResultGatewayModel):
    safe_relative_path: str = Field(min_length=1, max_length=300)
    sha256: str = Field(pattern=SHA256_PATTERN)


def _string_entries(value: Any) -> tuple[StringValueEntry, ...]:
    if value is None:
        return ()
    if isinstance(value, dict):
        values = tuple(StringValueEntry(key=str(key), value=str(item)) for key, item in value.items())
    else:
        values = tuple(value)
    keys = [item.key if isinstance(item, StringValueEntry) else str(item.get("key")) for item in values]
    if len(keys) != len(set(keys)):
        raise ValueError("mapping entry keys must be unique")
    return tuple(sorted(values, key=lambda item: item.key if isinstance(item, StringValueEntry) else str(item.get("key"))))


def _scalar_entries(value: Any) -> tuple[ScalarValueEntry, ...]:
    if value is None:
        return ()
    if isinstance(value, dict):
        values = tuple(ScalarValueEntry(key=str(key), value=item) for key, item in value.items())
    else:
        values = tuple(value)
    keys = [item.key if isinstance(item, ScalarValueEntry) else str(item.get("key")) for item in values]
    if len(keys) != len(set(keys)):
        raise ValueError("mapping entry keys must be unique")
    return tuple(sorted(values, key=lambda item: item.key if isinstance(item, ScalarValueEntry) else str(item.get("key"))))


def _file_hash_entries(value: Any) -> tuple[FileHashEntry, ...]:
    if value is None:
        return ()
    if isinstance(value, dict):
        values = tuple(FileHashEntry(safe_relative_path=str(key), sha256=str(item).lower()) for key, item in value.items())
    else:
        values = tuple(value)
    paths = [item.safe_relative_path if isinstance(item, FileHashEntry) else str(item.get("safe_relative_path")) for item in values]
    if len(paths) != len(set(paths)):
        raise ValueError("file hash paths must be unique")
    return tuple(sorted(values, key=lambda item: item.safe_relative_path if isinstance(item, FileHashEntry) else str(item.get("safe_relative_path"))))


class ResultManifestEntry(FrozenResultGatewayModel):
    logical_role: StrictStr = Field(min_length=1, max_length=100)
    safe_relative_path: str = Field(min_length=1, max_length=300)
    media_type: str = Field(min_length=1, max_length=160)
    sha256: str = Field(pattern=SHA256_PATTERN)
    canonical_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    byte_size: int = Field(ge=0, le=200_000_000)
    parser_version: str | None = Field(default=PARSER_VERSION, max_length=120)
    schema_version: str | None = Field(default=RESULT_GATEWAY_SCHEMA_VERSION, max_length=80)


class SuppliedResultFile(FrozenResultGatewayModel):
    safe_relative_path: str = Field(min_length=1, max_length=300)
    logical_role: StrictStr = Field(min_length=1, max_length=100)
    media_type: str = Field(default="application/octet-stream", max_length=160)
    content_base64: str | None = Field(default=None, max_length=80_000_000)
    content_text: str | None = Field(default=None, max_length=80_000_000)
    content: str | None = Field(default=None, max_length=80_000_000)
    content_encoding: Literal["utf8", "base64"] = "utf8"
    is_symlink: bool = False
    symlink_target: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def one_content_representation(self) -> "SuppliedResultFile":
        supplied = [value is not None for value in (self.content_base64, self.content_text, self.content)]
        if sum(supplied) != 1:
            raise ValueError("exactly one of content_base64, content_text, or content is required")
        if self.is_symlink and not self.symlink_target:
            raise ValueError("symlink_target is required when is_symlink is true")
        if not self.is_symlink and self.symlink_target:
            raise ValueError("symlink_target is only allowed for a declared symlink")
        return self


class VCFInfoDefinition(FrozenResultGatewayModel):
    info_id: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z_][A-Za-z0-9_.:-]*$")
    number: str = Field(min_length=1, max_length=80)
    value_type: Literal["Integer", "Float", "Flag", "Character", "String"]
    description: str | None = Field(default=None, max_length=4000)
    source_token: str = Field(min_length=1, max_length=8000)


class VCFHeaderMetadata(FrozenResultGatewayModel):
    source_file: str
    fileformat: str
    reference_build: str | None = None
    reference_declarations: tuple[str, ...] = Field(default_factory=tuple, max_length=100)
    contig_names: tuple[str, ...] = Field(default_factory=tuple, max_length=10_000)
    sample_names: tuple[str, ...] = Field(default_factory=tuple, max_length=10_000)
    info_definitions: tuple[VCFInfoDefinition, ...] = Field(default_factory=tuple, max_length=10_000)
    header_sha256: str = Field(pattern=SHA256_PATTERN)
    parser_version: str = PARSER_VERSION
    build_validation: Literal["matched", "mismatch", "not_declared", "not_assessed"] = "not_assessed"


class SuppliedAnnotation(FrozenResultGatewayModel):
    key: str = Field(min_length=1, max_length=120)
    value: str = Field(max_length=20_000_000)
    source_token: str | None = Field(default=None, max_length=20_000_000)
    declared_type: str | None = Field(default=None, max_length=80)
    declared_in_header: bool = False
    is_flag: bool = False
    source_field: Literal["vcf_info", "vcf_format", "lab_report", "qc", "coverage", "assay_metadata"]
    source_file: str
    source_record_id: str | None = None
    provenance_hash: str = Field(pattern=SHA256_PATTERN)


class VCFFormatValue(FrozenResultGatewayModel):
    key: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z_][A-Za-z0-9_.:-]*$")
    source_token: str = Field(max_length=20_000_000)
    is_missing: bool
    provenance_hash: str = Field(pattern=SHA256_PATTERN)
    source_state: Literal["supplied"] = "supplied"


class VCFGenotypeCall(FrozenResultGatewayModel):
    source_token: str = Field(min_length=1, max_length=4000)
    allele_indices: tuple[int | None, ...] = Field(min_length=1, max_length=100)
    separators: tuple[Literal["/", "|"], ...] = Field(default_factory=tuple, max_length=99)
    ploidy: int = Field(ge=1, le=100)
    phase_state: VCFPhaseState
    complete_missing: bool
    partial_missing: bool


class VCFSampleCall(FrozenResultGatewayModel):
    sample_index: int = Field(ge=0)
    sample_name: str = Field(min_length=1, max_length=500)
    source_token: str = Field(max_length=20_000_000)
    format_values: tuple[VCFFormatValue, ...] = Field(default_factory=tuple, max_length=1000)
    genotype: VCFGenotypeCall | None = None
    phase_set_source_token: str | None = Field(default=None, max_length=4000)


class VCFSampleAltPresence(FrozenResultGatewayModel):
    sample_index: int = Field(ge=0)
    sample_name: str = Field(min_length=1, max_length=500)
    selected_alt_index: int = Field(ge=1)
    state: AltPresenceState
    reason: Literal[
        "selected_alt_index_present_in_source_gt",
        "selected_alt_index_absent_from_complete_source_gt",
        "source_gt_missing_or_partial",
        "source_gt_not_supplied",
    ]


class VCFVariantRecord(FrozenResultGatewayModel):
    record_id: str = Field(min_length=1, max_length=160, pattern=LOCAL_ID_PATTERN)
    source_record_id: str = Field(min_length=1, max_length=160, pattern=LOCAL_ID_PATTERN)
    source_file: str
    source_record_sha256: str = Field(pattern=SHA256_PATTERN)
    chromosome: str = Field(min_length=1, max_length=80)
    position: int = Field(ge=1)
    source_id: str | None = Field(default=None, max_length=240)
    reference_allele: str = Field(min_length=1, max_length=1_000_000)
    alternate_allele: str = Field(min_length=1, max_length=1_000_000)
    quality: str | None = Field(default=None, max_length=120)
    filter_status: str | None = Field(default=None, max_length=120)
    source_info_token: str = Field(default=".", max_length=20_000_000)
    source_format_token: str | None = Field(default=None, max_length=20_000_000)
    format_keys: tuple[str, ...] = Field(default_factory=tuple, max_length=1000)
    sample_calls: tuple[VCFSampleCall, ...] = Field(default_factory=tuple, max_length=10_000)
    selected_alt_presence: tuple[VCFSampleAltPresence, ...] = Field(default_factory=tuple, max_length=10_000)
    variant_scope: VariantScope
    source_state: ResultSourceState = ResultSourceState.SUPPLIED
    normalized_state: VariantNormalizationState
    normalized_chromosome: str | None = None
    normalized_position: int | None = Field(default=None, ge=1)
    normalized_reference_allele: str | None = None
    normalized_alternate_allele: str | None = None
    source_alt_index: int = Field(ge=1)
    source_alt_count: int = Field(ge=1)
    decomposition_performed: bool = False
    reference_dependent_left_normalization_performed: Literal[False] = False
    supplied_annotations: tuple[SuppliedAnnotation, ...] = Field(default_factory=tuple, max_length=5000)
    out_of_scope_reason_code: OutOfScopeReasonCode | None = None
    reason_if_out_of_scope: str | None = Field(default=None, max_length=500)
    review_status: Literal["accepted_for_review", "retained_out_of_scope", "requires_review"] = "accepted_for_review"


class RetainedOutOfScopeRecord(FrozenResultGatewayModel):
    record_id: str = Field(min_length=1, max_length=160, pattern=LOCAL_ID_PATTERN)
    source_file: str
    source_record_sha256: str = Field(pattern=SHA256_PATTERN)
    variant_scope: VariantScope
    reason_code: OutOfScopeReasonCode
    reason: str = Field(min_length=1, max_length=500)
    source_state: Literal["supplied", "out_of_scope"] = "out_of_scope"
    human_review_required: Literal[True] = True


class VCFParseResult(FrozenResultGatewayModel):
    source_file: str
    header: VCFHeaderMetadata | None = None
    records: tuple[VCFVariantRecord, ...] = Field(default_factory=tuple, max_length=1_000_000)
    retained_out_of_scope: tuple[RetainedOutOfScopeRecord, ...] = Field(default_factory=tuple, max_length=1_000_000)
    supplied_annotations: tuple[SuppliedAnnotation, ...] = Field(default_factory=tuple, max_length=1_000_000)
    issues: tuple[GatewayIssue, ...] = Field(default_factory=tuple, max_length=10_000)
    record_count: int = Field(ge=0)
    in_scope_record_count: int = Field(ge=0)
    out_of_scope_record_count: int = Field(ge=0)
    multiallelic_source_record_count: int = Field(ge=0)
    decomposition_performed: bool = False
    reference_dependent_left_normalization_performed: Literal[False] = False
    parser_version: str = PARSER_VERSION


class LaboratoryReportFinding(FrozenResultGatewayModel):
    finding_id: str = Field(min_length=1, max_length=160, pattern=LOCAL_ID_PATTERN)
    value_as_reported: str = Field(min_length=1, max_length=4000)
    source_state: Literal["supplied"] = "supplied"
    source_hash: str = Field(pattern=SHA256_PATTERN)
    classification_as_reported: str | None = Field(default=None, max_length=240)
    classification_assigned_by_gateway: Literal[False] = False
    human_review_required: Literal[True] = True


class SuppliedAccreditationClaim(FrozenResultGatewayModel):
    claim_kind: Literal["NABL", "ISO_15189", "other"]
    accreditation_body_or_standard: str | None = Field(default=None, max_length=300)
    certificate_or_reference_identifier: str | None = Field(default=None, max_length=300)
    supplied_scope: str | None = Field(default=None, max_length=1000)
    supplied_status_text: str | None = Field(default=None, max_length=300)
    verification_state: Literal[
        VerificationState.SUPPLIED_BUT_UNVERIFIED,
        VerificationState.NOT_SUPPLIED,
        VerificationState.NOT_APPLICABLE,
    ] = VerificationState.SUPPLIED_BUT_UNVERIFIED
    source_hash: str = Field(pattern=SHA256_PATTERN)


class AccreditationEvidence(FrozenResultGatewayModel):
    accreditation_body_or_standard: Literal["NABL", "ISO 15189"]
    certificate_or_reference_identifier: str = Field(min_length=1, max_length=300)
    supplied_scope: str | None = Field(default=None, max_length=1000)
    evidence_digest: str = Field(pattern=SHA256_PATTERN)
    evidence_type: str = Field(min_length=1, max_length=160)
    verifier_provenance: str = Field(min_length=1, max_length=500)
    verification_timestamp: str = Field(min_length=1, max_length=100)
    reviewer_action_identifier: str = Field(min_length=1, max_length=160, pattern=LOCAL_ID_PATTERN)
    verification_status: Literal["independently_verified", "rejected", "inconclusive"]
    verification_reason: str = Field(min_length=1, max_length=1000)
    trusted_channel: Literal["trusted_human_review_action", "trusted_evidence_channel"]


class StructuredLaboratoryReport(FrozenResultGatewayModel):
    source_file: str
    report_id: str | None = Field(default=None, max_length=160)
    laboratory_name: str | None = Field(default=None, max_length=300)
    laboratory_reference: str | None = Field(default=None, max_length=300)
    accreditation_status: VerificationState = VerificationState.SUPPLIED_BUT_UNVERIFIED
    accreditation_scope: str | None = Field(default=None, max_length=1000)
    accreditation_scope_verification: VerificationState = VerificationState.SUPPLIED_BUT_UNVERIFIED
    accreditation_claims: tuple[SuppliedAccreditationClaim, ...] = Field(default_factory=tuple, max_length=20)
    trusted_accreditation_evidence: tuple[AccreditationEvidence, ...] = Field(default_factory=tuple, max_length=20)
    assay_or_test_type: str | None = Field(default=None, max_length=400)
    platform: str | None = Field(default=None, max_length=240)
    genome_build: str | None = Field(default=None, max_length=100)
    transcript_version: str | None = Field(default=None, max_length=160)
    database_versions: tuple[StringValueEntry, ...] = Field(default_factory=tuple, max_length=100)
    confirmation_method: str | None = Field(default=None, max_length=500)
    report_date: str | None = Field(default=None, max_length=80)
    turnaround_time: str | None = Field(default=None, max_length=160)
    shipping_or_transport: str | None = Field(default=None, max_length=500)
    access_or_affordability_notes: str | None = Field(default=None, max_length=1000)
    findings: tuple[LaboratoryReportFinding, ...] = Field(default_factory=tuple, max_length=10_000)
    warnings: tuple[str, ...] = Field(default_factory=tuple, max_length=200)
    parser_version: str = PARSER_VERSION
    source_state: Literal["supplied"] = "supplied"
    human_review_required: Literal[True] = True

    _freeze_database_versions = field_validator("database_versions", mode="before")(_string_entries)

    @field_serializer("database_versions")
    def serialize_database_versions(self, value: tuple[StringValueEntry, ...]) -> dict[str, str]:
        return {item.key: item.value for item in value}


class QualityControlSummary(FrozenResultGatewayModel):
    source_file: str
    sample_id_as_reported: str | None = None
    metrics: tuple[ScalarValueEntry, ...] = Field(default_factory=tuple, max_length=500)
    warnings: tuple[str, ...] = Field(default_factory=tuple, max_length=500)
    parser_version: str = PARSER_VERSION
    provenance: tuple[SuppliedAnnotation, ...] = Field(default_factory=tuple, max_length=5000)
    source_state: Literal["supplied"] = "supplied"
    human_review_required: Literal[True] = True

    _freeze_metrics = field_validator("metrics", mode="before")(_scalar_entries)

    @field_serializer("metrics")
    def serialize_metrics(self, value: tuple[ScalarValueEntry, ...]) -> dict[str, str | int | float | bool | None]:
        return {item.key: item.value for item in value}


class PoorCoverageRegion(FrozenResultGatewayModel):
    region_id: str = Field(min_length=1, max_length=160, pattern=LOCAL_ID_PATTERN)
    chromosome: str | None = None
    start: int | None = Field(default=None, ge=1)
    end: int | None = Field(default=None, ge=1)
    gene_or_region: str | None = Field(default=None, max_length=300)
    supplied_coverage: str | float | int | None = None
    reason: str | None = Field(default=None, max_length=500)
    source_hash: str = Field(pattern=SHA256_PATTERN)


class CoverageSummary(FrozenResultGatewayModel):
    source_file: str
    sample_id_as_reported: str | None = None
    minimum_coverage_declared: str | float | int | None = None
    mean_coverage_declared: str | float | int | None = None
    poor_regions: tuple[PoorCoverageRegion, ...] = Field(default_factory=tuple, max_length=100_000)
    metrics: tuple[ScalarValueEntry, ...] = Field(default_factory=tuple, max_length=500)
    warnings: tuple[str, ...] = Field(default_factory=tuple, max_length=500)
    parser_version: str = PARSER_VERSION
    source_state: Literal["supplied"] = "supplied"
    human_review_required: Literal[True] = True

    _freeze_metrics = field_validator("metrics", mode="before")(_scalar_entries)

    @field_serializer("metrics")
    def serialize_metrics(self, value: tuple[ScalarValueEntry, ...]) -> dict[str, str | int | float | bool | None]:
        return {item.key: item.value for item in value}


class AssayScopeSummary(FrozenResultGatewayModel):
    source_file: str
    reportable_genes: tuple[str, ...] = Field(default_factory=tuple, max_length=20_000)
    reportable_transcripts: tuple[str, ...] = Field(default_factory=tuple, max_length=20_000)
    reportable_regions: tuple[str, ...] = Field(default_factory=tuple, max_length=20_000)
    blind_spots: tuple[str, ...] = Field(default_factory=tuple, max_length=5000)
    minimum_coverage_requirement: str | float | int | None = None
    poor_region_policy_as_supplied: str | None = Field(default=None, max_length=1000)
    cnv_scope: str | None = Field(default=None, max_length=500)
    mitochondrial_scope: str | None = Field(default=None, max_length=500)
    repeat_scope: str | None = Field(default=None, max_length=500)
    mosaic_scope: str | None = Field(default=None, max_length=500)
    mosaic_threshold_as_supplied: str | float | int | None = None
    confirmation_methods: tuple[str, ...] = Field(default_factory=tuple, max_length=500)
    source_state: Literal["supplied"] = "supplied"
    human_review_required: Literal[True] = True


class SummaryAdapterParameters(StrictFrozenParameterModel):
    parameter_schema_id: Literal["insilicopop.summary.parameters"] = "insilicopop.summary.parameters"
    parameter_schema_version: Literal["1.0"] = "1.0"
    mode: Literal["summary_only"] = "summary_only"


class LeftNormalizationParameters(StrictFrozenParameterModel):
    parameter_schema_id: Literal["insilicopop.bcftools-left-normalization.parameters"] = "insilicopop.bcftools-left-normalization.parameters"
    parameter_schema_version: Literal["1.0"] = "1.0"
    mode: Literal["reference_dependent_left_normalization"] = "reference_dependent_left_normalization"


class VepReconciliationParameters(StrictFrozenParameterModel):
    parameter_schema_id: Literal["insilicopop.vep-reconciliation.parameters"] = "insilicopop.vep-reconciliation.parameters"
    parameter_schema_version: Literal["1.0"] = "1.0"
    mode: Literal["supplied_annotation_reconciliation"] = "supplied_annotation_reconciliation"


AdapterParameters = Annotated[
    SummaryAdapterParameters | LeftNormalizationParameters | VepReconciliationParameters,
    Field(discriminator="parameter_schema_id"),
]


_ADAPTER_PARAMETER_BINDINGS: dict[str, tuple[type[StrictFrozenParameterModel], str, str]] = {
    "deterministic_supplied_result_summary": (SummaryAdapterParameters, "insilicopop.summary.parameters", "1.0"),
    "bcftools_left_normalization": (LeftNormalizationParameters, "insilicopop.bcftools-left-normalization.parameters", "1.0"),
    "vep_supplied_annotation_reconciliation": (VepReconciliationParameters, "insilicopop.vep-reconciliation.parameters", "1.0"),
}


def _bind_adapter_parameters(data: Any, *, allow_missing_adapter: bool) -> Any:
    if not isinstance(data, dict):
        return data
    copied = dict(data)
    adapter_id = copied.get("adapter_id")
    parameters = copied.get("parameters")
    if adapter_id is None:
        if parameters not in (None, {}):
            raise ValueError("adapter parameters require an adapter_id")
        copied["parameters"] = None
        return copied
    binding = _ADAPTER_PARAMETER_BINDINGS.get(str(adapter_id))
    if binding is None:
        raise ValueError("adapter_id is not present in the immutable v0.36 allowlist")
    model_type, schema_id, schema_version = binding
    if parameters is None:
        parameters = {}
    if isinstance(parameters, StrictFrozenParameterModel):
        if not isinstance(parameters, model_type):
            raise ValueError("adapter parameter model does not match adapter_id")
        copied["parameters"] = parameters
        return copied
    if not isinstance(parameters, dict):
        raise ValueError("adapter parameters must be an object matching the registered schema")
    parameter_copy = dict(parameters)
    parameter_copy.setdefault("parameter_schema_id", schema_id)
    parameter_copy.setdefault("parameter_schema_version", schema_version)
    copied["parameters"] = model_type.model_validate(parameter_copy)
    return copied


class ToolAnalysisIntent(FrozenResultGatewayModel):
    intent_id: str = Field(min_length=1, max_length=160, pattern=LOCAL_ID_PATTERN)
    analysis_kind: str = Field(min_length=1, max_length=160, pattern=LOCAL_ID_PATTERN)
    target_record_ids: tuple[RecordSelectorId, ...] | None = Field(default=None, max_length=10_000)
    adapter_id: str | None = Field(default=None, max_length=160, pattern=LOCAL_ID_PATTERN)
    parameters: AdapterParameters | None = None
    timeout_seconds: int = Field(default=30, ge=1, le=600)
    max_output_bytes: int = Field(default=1_000_000, ge=1, le=20_000_000)
    max_records: int = Field(default=10_000, ge=1, le=1_000_000)
    network_policy: NetworkPolicy = NetworkPolicy.DISABLED
    human_review_approved: StrictBool = False
    human_review_required: Literal[True] = True

    @model_validator(mode="before")
    @classmethod
    def bind_parameters(cls, data: Any) -> Any:
        return _bind_adapter_parameters(data, allow_missing_adapter=True)

    @model_validator(mode="after")
    def validate_policy_and_selectors(self) -> "ToolAnalysisIntent":
        if self.network_policy != NetworkPolicy.DISABLED:
            raise ValueError("v0.36 analysis intent requires network_policy=disabled")
        if self.target_record_ids is not None and len(self.target_record_ids) != len(set(self.target_record_ids)):
            raise ValueError("target_record_ids cannot contain duplicates")
        return self


class AdapterDefinition(FrozenResultGatewayModel):
    adapter_id: str = Field(min_length=1, max_length=160, pattern=LOCAL_ID_PATTERN)
    version: str = Field(min_length=1, max_length=80)
    registry_version: str = ADAPTER_REGISTRY_VERSION
    immutable_definition: Literal[True] = True
    parameter_schema_id: str = Field(min_length=1, max_length=200, pattern=LOCAL_ID_PATTERN)
    parameter_schema_version: str = Field(min_length=1, max_length=80)
    input_contract: str = Field(min_length=1, max_length=300)
    output_contract: str = Field(min_length=1, max_length=300)
    executable_identity: str = Field(min_length=1, max_length=300)
    executable_digest: str = Field(pattern=SHA256_PATTERN)
    container_identity: str | None = Field(default=None, max_length=300)
    container_digest: str | None = Field(default=None, pattern=SHA256_PATTERN)
    parser_version: str = PARSER_VERSION
    reference_version: str | None = Field(default=None, max_length=160)
    transcript_version: str | None = Field(default=None, max_length=160)
    database_versions: tuple[StringValueEntry, ...] = Field(default_factory=tuple, max_length=100)
    default_parameters: AdapterParameters
    timeout_seconds: int = Field(default=30, ge=1, le=600)
    max_output_bytes: int = Field(default=1_000_000, ge=1, le=20_000_000)
    workdir_policy: Literal["bounded_temp_only", "none"] = "bounded_temp_only"
    network_policy: NetworkPolicy = NetworkPolicy.DISABLED
    expected_exit_codes: tuple[int, ...] = (0,)
    availability: AdapterAvailability
    synthetic_fixture: bool = False
    approval_required: Literal[True] = True
    unavailable_reason: str | None = Field(default=None, max_length=500)

    _freeze_database_versions = field_validator("database_versions", mode="before")(_string_entries)

    @field_serializer("database_versions")
    def serialize_database_versions(self, value: tuple[StringValueEntry, ...]) -> dict[str, str]:
        return {item.key: item.value for item in value}

    @model_validator(mode="after")
    def definition_is_consistent(self) -> "AdapterDefinition":
        binding = _ADAPTER_PARAMETER_BINDINGS.get(self.adapter_id)
        if binding is None or not isinstance(self.default_parameters, binding[0]):
            raise ValueError("adapter definition parameter model does not match adapter_id")
        if self.parameter_schema_id != binding[1] or self.parameter_schema_version != binding[2]:
            raise ValueError("adapter definition parameter schema declaration is inconsistent")
        if self.availability == AdapterAvailability.UNAVAILABLE and not self.unavailable_reason:
            raise ValueError("unavailable adapters require unavailable_reason")
        if self.availability == AdapterAvailability.AVAILABLE and self.unavailable_reason:
            raise ValueError("available adapters cannot declare unavailable_reason")
        return self


class AdapterInvocationRequest(FrozenResultGatewayModel):
    invocation_id: str = Field(min_length=1, max_length=160, pattern=LOCAL_ID_PATTERN)
    adapter_id: str = Field(min_length=1, max_length=160, pattern=LOCAL_ID_PATTERN)
    adapter_version: str | None = Field(default=None, max_length=80)
    input_file_hashes: tuple[str, ...] = Field(default_factory=tuple, max_length=1000)
    input_record_ids: tuple[RecordSelectorId, ...] | None = Field(default=None, max_length=10_000)
    parameters: AdapterParameters
    timeout_seconds: int = Field(default=30, ge=1, le=600)
    max_records: int = Field(default=10_000, ge=1, le=1_000_000)
    max_output_bytes: int = Field(default=1_000_000, ge=1, le=20_000_000)
    network_policy: NetworkPolicy = NetworkPolicy.DISABLED
    working_directory_policy: Literal["bounded_temp_only", "none"] = "bounded_temp_only"
    replay_key: str | None = Field(default=None, max_length=160, pattern=LOCAL_ID_PATTERN)
    human_review_approved: StrictBool = False

    @model_validator(mode="before")
    @classmethod
    def bind_parameters(cls, data: Any) -> Any:
        return _bind_adapter_parameters(data, allow_missing_adapter=False)

    @model_validator(mode="after")
    def validate_shape_and_policy(self) -> "AdapterInvocationRequest":
        if self.network_policy != NetworkPolicy.DISABLED:
            raise ValueError("v0.36 adapter invocations require network_policy=disabled")
        for digest in self.input_file_hashes:
            if not isinstance(digest, str) or __import__("re").fullmatch(SHA256_PATTERN, digest) is None:
                raise ValueError("input_file_hashes must contain SHA-256 values")
        return self


class SelectorValidationIssue(FrozenResultGatewayModel):
    code: Literal["duplicate_input_record_id", "unknown_input_record_id", "out_of_scope_input_record_id"]
    record_id: RecordSelectorId
    message: str = Field(min_length=1, max_length=500)


class NormalizedAdapterInvocation(FrozenResultGatewayModel):
    invocation_id: str
    adapter_id: str
    adapter_version: str
    parameter_schema_id: str
    parameter_schema_version: str
    parameters: AdapterParameters
    package_identity_sha256: str = Field(pattern=SHA256_PATTERN)
    input_manifest_sha256: str = Field(pattern=SHA256_PATTERN)
    input_file_hashes: tuple[str, ...]
    requested_input_record_ids: tuple[RecordSelectorId, ...] | None = None
    selected_input_record_ids: tuple[RecordSelectorId, ...] = Field(default_factory=tuple)
    input_record_ids: tuple[str, ...]
    selector_validation_issues: tuple[SelectorValidationIssue, ...] = Field(default_factory=tuple)
    selector_mode: Literal["all_eligible", "explicit"]
    timeout_seconds: int
    max_records: int
    max_output_bytes: int
    network_policy: NetworkPolicy = NetworkPolicy.DISABLED
    working_directory_policy: Literal["bounded_temp_only", "none"]
    human_review_approved: bool
    invocation_sha256: str = Field(pattern=SHA256_PATTERN)
    replay_key: str | None = None


class ToolProvenance(FrozenResultGatewayModel):
    adapter_id: str
    adapter_version: str
    registry_version: str = ADAPTER_REGISTRY_VERSION
    parameter_schema_id: str
    parameter_schema_version: str
    executable_identity: str
    executable_digest: str = Field(pattern=SHA256_PATTERN)
    container_identity: str | None = None
    container_digest: str | None = Field(default=None, pattern=SHA256_PATTERN)
    parser_version: str
    reference_version: str | None = None
    transcript_version: str | None = None
    database_versions: tuple[StringValueEntry, ...] = Field(default_factory=tuple)
    normalized_parameters: AdapterParameters
    input_manifest_sha256: str = Field(pattern=SHA256_PATTERN)
    package_identity_sha256: str = Field(pattern=SHA256_PATTERN)
    input_file_hashes: tuple[str, ...] = Field(default_factory=tuple)
    requested_input_record_ids: tuple[RecordSelectorId, ...] | None = None
    selected_input_record_ids: tuple[RecordSelectorId, ...] = Field(default_factory=tuple)
    selected_record_ids: tuple[str, ...] = Field(default_factory=tuple)
    selector_validation_issues: tuple[SelectorValidationIssue, ...] = Field(default_factory=tuple)
    invocation_sha256: str = Field(pattern=SHA256_PATTERN)
    output_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    network_policy: NetworkPolicy = NetworkPolicy.DISABLED
    network_call_made: Literal[False] = False
    external_tools_executed: Literal[False] = False
    raw_command_execution: Literal[False] = False

    _freeze_database_versions = field_validator("database_versions", mode="before")(_string_entries)

    @field_serializer("database_versions")
    def serialize_database_versions(self, value: tuple[StringValueEntry, ...]) -> dict[str, str]:
        return {item.key: item.value for item in value}


class VariantScopeCount(FrozenResultGatewayModel):
    variant_scope: VariantScope
    count: StrictInt = Field(ge=0)


def _variant_scope_count_entries(value: Any) -> tuple[VariantScopeCount, ...]:
    if value is None:
        return ()
    if isinstance(value, dict):
        entries = []
        valid_scopes = {scope.value for scope in VariantScope}
        for scope, count in value.items():
            if not isinstance(scope, str) or scope not in valid_scopes:
                raise ValueError("variant_scope_counts contains an unknown scope")
            entries.append(VariantScopeCount(variant_scope=scope, count=count))
    else:
        try:
            entries = [
                item if isinstance(item, VariantScopeCount) else VariantScopeCount.model_validate(item)
                for item in value
            ]
        except TypeError as exc:
            raise ValueError("variant_scope_counts must be a mapping or immutable entry collection") from exc
    scopes = [item.variant_scope for item in entries]
    if len(scopes) != len(set(scopes)):
        raise ValueError("variant_scope_counts cannot contain duplicate scopes")
    return tuple(sorted(entries, key=lambda item: item.variant_scope.value))


class AdapterOutputSummary(FrozenResultGatewayModel):
    summary_kind: Literal["supplied_result_summary"] = "supplied_result_summary"
    record_count: int = Field(ge=0)
    record_ids: tuple[str, ...] = Field(default_factory=tuple)
    selected_record_ids: tuple[str, ...] = Field(default_factory=tuple)
    variant_scope_counts: tuple[VariantScopeCount, ...] = Field(default_factory=tuple)
    decomposition_only: bool = False
    reference_dependent_left_normalization_performed: Literal[False] = False
    external_annotation_or_classification: Literal[False] = False
    partial_output: bool = False

    _freeze_scope_counts = field_validator("variant_scope_counts", mode="before")(_variant_scope_count_entries)

    @field_serializer("variant_scope_counts")
    def serialize_scope_counts(self, value: tuple[VariantScopeCount, ...]) -> dict[str, int]:
        return {item.variant_scope.value: item.count for item in value}


class AdapterExecutionResult(FrozenResultGatewayModel):
    invocation: NormalizedAdapterInvocation
    adapter: AdapterDefinition
    status: AdapterExecutionStatus
    output_summary: AdapterOutputSummary | None = None
    output_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    output_byte_size: int = Field(default=0, ge=0)
    stdout_excerpt: str = Field(default="", max_length=4000)
    stderr_excerpt: str = Field(default="", max_length=4000)
    errors: tuple[str, ...] = Field(default_factory=tuple, max_length=100)
    warnings: tuple[str, ...] = Field(default_factory=tuple, max_length=100)
    provenance: ToolProvenance
    external_tools_executed: Literal[False] = False
    network_call_made: Literal[False] = False
    raw_command_execution: Literal[False] = False
    human_review_required: Literal[True] = True

    @field_serializer("output_summary")
    def serialize_output_summary(self, value: AdapterOutputSummary | None) -> dict[str, Any] | None:
        return None if value is None else value.model_dump(mode="json")


class ResultGatewayRequest(FrozenResultGatewayModel):
    schema_version: Literal["0.36"] = RESULT_GATEWAY_SCHEMA_VERSION
    package_id: str = Field(min_length=1, max_length=160, pattern=LOCAL_ID_PATTERN)
    package_version: str = Field(min_length=1, max_length=80)
    manifest: tuple[ResultManifestEntry, ...] = Field(default_factory=tuple, max_length=1000)
    files: tuple[SuppliedResultFile, ...] = Field(default_factory=tuple, max_length=1000)
    declared_case_id: str | None = Field(default=None, max_length=120, pattern=LOCAL_ID_PATTERN)
    expected_sample_id: str | None = Field(default=None, max_length=160, pattern=LOCAL_ID_PATTERN)
    declared_reference_build: str | None = Field(default=None, max_length=100)
    tool_analysis_intent: ToolAnalysisIntent | None = None
    adapter_invocations: tuple[AdapterInvocationRequest, ...] = Field(default_factory=tuple, max_length=100)
    limits: GatewayLimits = Field(default_factory=GatewayLimits)
    expected_input_manifest_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    previous_input_manifest_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    duplicate_of_input_manifest_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    expected_package_identity_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    previous_package_identity_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    duplicate_of_package_identity_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    replay_key: str | None = Field(default=None, max_length=160, pattern=LOCAL_ID_PATTERN)
    human_review_required: Literal[True] = True
    draft_not_clinically_approved: Literal[True] = True

    @model_validator(mode="after")
    def unique_invocation_ids(self) -> "ResultGatewayRequest":
        invocation_ids = [item.invocation_id for item in self.adapter_invocations]
        if len(invocation_ids) != len(set(invocation_ids)):
            raise ValueError("adapter invocation IDs must be unique")
        return self


class ResultGatewayResult(FrozenResultGatewayModel):
    schema_version: Literal["0.36"] = RESULT_GATEWAY_SCHEMA_VERSION
    gateway_version: Literal["insilicopop-controlled-result-gateway-0.36.0"] = RESULT_GATEWAY_VERSION
    pseudonymous_case_id: str | None = None
    package_id: str
    package_version: str
    package_status: GatewayPackageStatus
    replay_status: ReplayStatus = ReplayStatus.NOT_REQUESTED
    input_manifest_sha256: str = Field(pattern=SHA256_PATTERN)
    package_identity_sha256: str = Field(pattern=SHA256_PATTERN)
    input_file_hashes: tuple[FileHashEntry, ...] = Field(default_factory=tuple)
    manifest_entries: tuple[ResultManifestEntry, ...] = Field(default_factory=tuple)
    manifest_verified: bool = False
    canonical_file_hashes: tuple[FileHashEntry, ...] = Field(default_factory=tuple)
    vcf: VCFParseResult | None = None
    laboratory_report: StructuredLaboratoryReport | None = None
    qc: QualityControlSummary | None = None
    coverage: CoverageSummary | None = None
    assay_scope: AssayScopeSummary | None = None
    tool_analysis_intent: ToolAnalysisIntent | None = None
    adapter_registry_version: str = ADAPTER_REGISTRY_VERSION
    adapter_definitions: tuple[AdapterDefinition, ...] = Field(default_factory=tuple)
    adapter_results: tuple[AdapterExecutionResult, ...] = Field(default_factory=tuple)
    tool_provenance: tuple[ToolProvenance, ...] = Field(default_factory=tuple)
    warnings: tuple[GatewayIssue, ...] = Field(default_factory=tuple, max_length=10_000)
    errors: tuple[GatewayIssue, ...] = Field(default_factory=tuple, max_length=10_000)
    partial_output: bool = False
    stale_or_replay_message: str | None = None
    limits: GatewayLimits = Field(default_factory=GatewayLimits)
    accepted_record_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=1_000_000)
    retained_out_of_scope_record_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=1_000_000)
    source_vs_normalized_separation: Literal[True] = True
    reference_build_mismatch_blocked: bool = False
    sample_identity_inference_performed: Literal[False] = False
    raw_reads_ingested: Literal[False] = False
    raw_reads_called: Literal[False] = False
    raw_cnv_called: Literal[False] = False
    raw_mitochondrial_called: Literal[False] = False
    raw_repeat_called: Literal[False] = False
    raw_mosaic_called: Literal[False] = False
    diagnosis_made: Literal[False] = False
    treatment_recommendation_made: Literal[False] = False
    final_acmg_classification_made: Literal[False] = False
    clinical_sign_out_made: Literal[False] = False
    test_order_placed: Literal[False] = False
    external_api_call_made: Literal[False] = False
    external_llm_called: Literal[False] = False
    external_tools_executed: Literal[False] = False
    human_review_required: Literal[True] = True
    research_use_only: Literal[True] = True
    draft_not_clinically_approved: Literal[True] = True

    _freeze_input_hashes = field_validator("input_file_hashes", mode="before")(_file_hash_entries)
    _freeze_canonical_hashes = field_validator("canonical_file_hashes", mode="before")(_file_hash_entries)

    @field_serializer("input_file_hashes", "canonical_file_hashes")
    def serialize_file_hashes(self, value: tuple[FileHashEntry, ...]) -> dict[str, str]:
        return {item.safe_relative_path: item.sha256 for item in value}
