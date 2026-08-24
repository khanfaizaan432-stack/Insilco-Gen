from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator


INTEGRATED_ANALYSIS_SCHEMA_VERSION = "0.38"
INTEGRATED_ANALYSIS_ALGORITHM_VERSION = "insilicopop-integrated-analysis-0.38.0"
INTEGRATED_ANALYSIS_RULE_VERSION = "insilicopop-integrated-analysis-rules-0.38.0"
INTEGRATED_ANALYSIS_RETRIEVAL_VERSION = "insilicopop-controlled-retrieval-0.38.0"
INTEGRATED_ANALYSIS_TOOL_VERSION = "insilicopop-controlled-tool-execution-0.38.0"
SHA256_PATTERN = r"^[a-fA-F0-9]{64}$"
SAFE_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"
SAFE_PATH_PATTERN = r"^[A-Za-z0-9_./\\-]+$"


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_hex(value: Any) -> str:
    payload = value if isinstance(value, (bytes, bytearray)) else canonical_json(value).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class IntegratedFrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        revalidate_instances="always",
    )


class SourceClassification(str, Enum):
    SUPPLIED = "supplied"
    NORMALIZED = "normalized"
    DETERMINISTIC = "deterministic"
    RETRIEVED = "retrieved"
    CANDIDATE_INTERPRETATION = "candidate_interpretation"
    EXTERNAL_ASSESSMENT = "external_assessment"
    HUMAN_DECISION = "human_decision"


class IntegratedWorkspaceStatus(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    BLOCKED = "blocked"
    STALE = "stale"
    TAMPERED = "tampered"


class EvidenceLifecycleState(str, Enum):
    ELIGIBLE = "eligible"
    CONTEXT_ONLY = "context_only"
    QUARANTINED = "quarantined"
    EXCLUDED = "excluded"


class EvidenceRole(str, Enum):
    SUPPORTING = "supporting"
    CONTRADICTING = "contradicting"
    UNRESOLVED = "unresolved"
    CONTEXT_ONLY = "context_only"


class FreshnessState(str, Enum):
    FRESH = "fresh"
    STALE = "stale"
    UNKNOWN = "unknown"


class CorrectionRetractionState(str, Enum):
    NONE = "none"
    CORRECTED = "corrected"
    RETRACTED = "retracted"
    EXPRESSION_OF_CONCERN = "expression_of_concern"
    UNKNOWN = "unknown"


class RetrievalCacheStatus(str, Enum):
    HIT = "hit"
    MISS = "miss"
    EXPIRED = "expired"
    REPLAY = "replay"
    NOT_CACHED = "not_cached"


class SourceAvailability(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    MANAGED_ACCESS = "managed_access"
    FIXTURE_ONLY = "fixture_only"
    MANUAL_VERIFIED_ONLY = "manual_verified_only"
    AUTH_REQUIRED = "auth_required"


class MosaicismMeasurementState(str, Enum):
    NOT_ASSESSED = "not_assessed"
    NOT_REPORTED = "not_reported"
    MEASUREMENT_AVAILABLE = "measurement_available"
    CONFIRMATION_PENDING = "confirmation_pending"
    EXTERNALLY_SUPPLIED_CONFIRMATION = "externally_supplied_confirmation"


class ReviewState(str, Enum):
    UNREVIEWED = "unreviewed"
    PENDING = "pending"
    IN_REVIEW = "in_review"
    REVIEWED = "reviewed"
    VERIFIED = "verified"


class ConfirmationState(str, Enum):
    NOT_ASSESSED = "not_assessed"
    NOT_CONFIRMED = "not_confirmed"
    PENDING = "pending"
    CONFIRMED = "confirmed"
    SUPPLIED = "supplied"


class ExternalToolExecutionStatus(str, Enum):
    COMPLETED = "completed"
    UNAVAILABLE = "unavailable"
    BLOCKED = "blocked"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    NOT_REQUESTED = "not_requested"


class RetrievalFailureState(str, Enum):
    NONE = "none"
    BLOCKED = "blocked"
    UNAVAILABLE = "unavailable"
    QUARANTINED = "quarantined"
    FAILED = "failed"


def _check_sha(value: str | None) -> str | None:
    if value is not None and not re.fullmatch(SHA256_PATTERN, value):
        raise ValueError("identity must be a 64-character SHA-256 hexadecimal digest")
    return value


def _finite_unit(value: float | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("value must be a finite numeric value, not a boolean")
    if not 0 <= float(value) <= 1:
        raise ValueError("value must be within [0, 1]")
    return float(value)


def _safe_relative_path(value: str) -> str:
    if value.startswith(("/", "\\")) or value in {".", ".."} or "/../" in f"/{value.replace('\\', '/')}/" or "\\..\\" in f"\\{value}\\":
        raise ValueError("path must be relative and cannot contain parent-directory traversal")
    return value


class SourceBinding(IntegratedFrozenModel):
    source_report_id: str = Field(min_length=1, max_length=160, pattern=SAFE_ID_PATTERN)
    source_manifest_entry_path: str = Field(min_length=1, max_length=240, pattern=SAFE_PATH_PATTERN)
    source_manifest_entry_sha256: str = Field(pattern=SHA256_PATTERN)
    source_package_identity_sha256: str = Field(pattern=SHA256_PATTERN)
    source_manifest_identity_sha256: str = Field(pattern=SHA256_PATTERN)
    source_report_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)

    _safe_path = field_validator("source_manifest_entry_path")(_safe_relative_path)


class CandidateBinding(IntegratedFrozenModel):
    candidate_id: str | None = Field(default=None, max_length=160, pattern=SAFE_ID_PATTERN)
    source_record_id: str | None = Field(default=None, max_length=160, pattern=SAFE_ID_PATTERN)
    gene: str | None = Field(default=None, max_length=80)
    variant: str | None = Field(default=None, max_length=240)
    finding_id: str | None = Field(default=None, max_length=160, pattern=SAFE_ID_PATTERN)


class StrictCountModel(IntegratedFrozenModel):
    @field_validator("alternate_read_count", "total_read_count", "depth", mode="before", check_fields=False)
    @classmethod
    def _counts_are_strict(cls, value: Any) -> Any:
        if value is None:
            return value
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("read counts and depth must be integers and cannot be booleans")
        if value < 0:
            raise ValueError("read counts and depth cannot be negative")
        return value


class SuppliedCNVFinding(IntegratedFrozenModel):
    finding_id: str = Field(min_length=1, max_length=160, pattern=SAFE_ID_PATTERN)
    source_binding: SourceBinding
    genome_build: str = Field(min_length=1, max_length=40)
    chromosome: str = Field(min_length=1, max_length=24)
    start: int = Field(strict=True, ge=1)
    end: int = Field(strict=True, ge=1)
    event_type: Literal["deletion", "duplication"]
    supplied_copy_number: float | None = Field(default=None, strict=True, ge=0, le=16)
    supplied_copy_number_state: str | None = Field(default=None, max_length=120)
    affected_interval: str | None = Field(default=None, max_length=240)
    gene_exon_overlap: tuple[str, ...] = Field(default_factory=tuple, max_length=100)
    dosage_evidence_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=100)
    population_frequency: float | None = Field(default=None, strict=True)
    phenotype_relevance: str | None = Field(default=None, max_length=600)
    supplied_inheritance: str | None = Field(default=None, max_length=160)
    assay: str = Field(min_length=1, max_length=240)
    resolution_bp: int | None = Field(default=None, strict=True, ge=1)
    confirmation_state: ConfirmationState = ConfirmationState.NOT_ASSESSED
    supplied_external_classification: str | None = Field(default=None, max_length=240)
    limitations: tuple[str, ...] = Field(default_factory=tuple, max_length=40)
    provenance: tuple[str, ...] = Field(default_factory=tuple, max_length=40)
    source_classification: SourceClassification = SourceClassification.SUPPLIED
    human_review_state: ReviewState = ReviewState.PENDING
    human_review_required: Literal[True] = True

    @field_validator("population_frequency")
    @classmethod
    def _frequency(cls, value: float | None) -> float | None:
        return _finite_unit(value)

    @model_validator(mode="after")
    def _coordinates(self) -> "SuppliedCNVFinding":
        if self.end < self.start:
            raise ValueError("CNV end coordinate cannot precede start coordinate")
        return self


class SuppliedMitochondrialFinding(StrictCountModel):
    finding_id: str = Field(min_length=1, max_length=160, pattern=SAFE_ID_PATTERN)
    source_binding: SourceBinding
    reference_sequence: str = Field(min_length=1, max_length=120)
    coordinate: int = Field(strict=True, ge=1)
    ref: str = Field(min_length=1, max_length=20)
    alt: str = Field(min_length=1, max_length=20)
    heteroplasmy: float | None = Field(default=None, strict=True)
    alternate_read_count: int | None = Field(default=None, strict=True, ge=0)
    total_read_count: int | None = Field(default=None, strict=True, ge=0)
    depth: int | None = Field(default=None, strict=True, ge=0)
    tissue: str = Field(min_length=1, max_length=160)
    assay: str = Field(min_length=1, max_length=240)
    detection_threshold: float | None = Field(default=None, strict=True)
    maternal_family_context_supplied: str | None = Field(default=None, max_length=600)
    mitochondrial_population_frequency: float | None = Field(default=None, strict=True)
    supplied_external_classification: str | None = Field(default=None, max_length=240)
    confirmation_state: ConfirmationState = ConfirmationState.NOT_ASSESSED
    limitations: tuple[str, ...] = Field(default_factory=tuple, max_length=40)
    provenance: tuple[str, ...] = Field(default_factory=tuple, max_length=40)
    source_classification: SourceClassification = SourceClassification.SUPPLIED
    human_review_state: ReviewState = ReviewState.PENDING
    human_review_required: Literal[True] = True

    @field_validator("heteroplasmy", "detection_threshold", "mitochondrial_population_frequency")
    @classmethod
    def _unit_fields(cls, value: float | None) -> float | None:
        return _finite_unit(value)

    @model_validator(mode="after")
    def _counts_and_reference(self) -> "SuppliedMitochondrialFinding":
        if self.alternate_read_count is not None and self.total_read_count is not None:
            if self.alternate_read_count > self.total_read_count:
                raise ValueError("alternate mitochondrial reads cannot exceed total reads")
            if self.total_read_count == 0 and self.heteroplasmy not in (None, 0.0):
                raise ValueError("non-zero heteroplasmy requires non-zero total reads")
            if self.total_read_count and self.heteroplasmy is not None:
                observed = self.alternate_read_count / self.total_read_count
                if abs(observed - self.heteroplasmy) > 0.05:
                    raise ValueError("heteroplasmy is inconsistent with supplied read counts")
        if self.depth is not None and self.total_read_count is not None and self.total_read_count > self.depth:
            raise ValueError("total mitochondrial reads cannot exceed supplied depth")
        return self


class MosaicismMeasurement(StrictCountModel):
    measurement_id: str = Field(min_length=1, max_length=160, pattern=SAFE_ID_PATTERN)
    source_binding: SourceBinding
    finding_id: str | None = Field(default=None, max_length=160, pattern=SAFE_ID_PATTERN)
    variant: str | None = Field(default=None, max_length=240)
    variant_allele_fraction: float | None = Field(default=None, strict=True)
    alternate_read_count: int | None = Field(default=None, strict=True, ge=0)
    total_read_count: int | None = Field(default=None, strict=True, ge=0)
    depth: int | None = Field(default=None, strict=True, ge=0)
    tissue: str = Field(min_length=1, max_length=160)
    assay: str = Field(min_length=1, max_length=240)
    detection_threshold: float | None = Field(default=None, strict=True)
    technical_artifact_warning: str | None = Field(default=None, max_length=600)
    confirmation_state: ConfirmationState = ConfirmationState.NOT_ASSESSED
    other_tissue_tested: bool | None = None
    measurement_state: MosaicismMeasurementState = MosaicismMeasurementState.MEASUREMENT_AVAILABLE
    limitations: tuple[str, ...] = Field(default_factory=tuple, max_length=40)
    provenance: tuple[str, ...] = Field(default_factory=tuple, max_length=40)
    source_classification: SourceClassification = SourceClassification.SUPPLIED
    human_review_state: ReviewState = ReviewState.PENDING
    human_review_required: Literal[True] = True

    @field_validator("variant_allele_fraction", "detection_threshold")
    @classmethod
    def _fractions(cls, value: float | None) -> float | None:
        return _finite_unit(value)

    @model_validator(mode="after")
    def _counts_and_fraction(self) -> "MosaicismMeasurement":
        if self.alternate_read_count is not None and self.total_read_count is not None:
            if self.alternate_read_count > self.total_read_count:
                raise ValueError("alternate mosaic reads cannot exceed total reads")
            if self.total_read_count and self.variant_allele_fraction is not None:
                observed = self.alternate_read_count / self.total_read_count
                if abs(observed - self.variant_allele_fraction) > 0.05:
                    raise ValueError("variant allele fraction is inconsistent with supplied read counts")
        if self.depth is not None and self.total_read_count is not None and self.total_read_count > self.depth:
            raise ValueError("total mosaic reads cannot exceed supplied depth")
        return self


class TypedRetrievalQuery(IntegratedFrozenModel):
    source_id: str = Field(min_length=1, max_length=40, pattern=SAFE_ID_PATTERN)
    variant_identifier: str | None = Field(default=None, max_length=240)
    hgvs: str | None = Field(default=None, max_length=240)
    rsid: str | None = Field(default=None, max_length=40, pattern=r"^rs\d+$")
    gene: str | None = Field(default=None, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")
    condition_terms: tuple[str, ...] = Field(default_factory=tuple, max_length=20)
    phenotype_terms: tuple[str, ...] = Field(default_factory=tuple, max_length=20)
    inheritance_terms: tuple[str, ...] = Field(default_factory=tuple, max_length=20)
    assembly: str | None = Field(default=None, max_length=40)
    candidate_binding: CandidateBinding | None = None
    query_id: str = Field(default="query", min_length=1, max_length=80, pattern=SAFE_ID_PATTERN)

    @field_validator("variant_identifier", "hgvs", "gene", "assembly", "condition_terms", "phenotype_terms", "inheritance_terms")
    @classmethod
    def _reject_urls_and_shell(cls, value: Any) -> Any:
        values = value if isinstance(value, (list, tuple)) else (value,)
        for item in values:
            if item is None:
                continue
            text = str(item)
            if any(token in text for token in ("http://", "https://", "://", "#", "\\", "\x00", "--")):
                raise ValueError("retrieval query contains a URL, fragment, path or shell-like token")
        return value


class FrozenRetrievalFixture(IntegratedFrozenModel):
    fixture_id: str = Field(min_length=1, max_length=160, pattern=SAFE_ID_PATTERN)
    source_id: str = Field(min_length=1, max_length=40, pattern=SAFE_ID_PATTERN)
    request_signature: str = Field(min_length=1, max_length=2000)
    content_type: Literal["application/json", "application/xml", "text/xml"]
    response_body: str = Field(min_length=1, max_length=2_000_000)
    response_sha256: str = Field(pattern=SHA256_PATTERN)
    source_release: str = Field(min_length=1, max_length=120)
    recorded_at: str = Field(min_length=1, max_length=80)
    parser_version: str = Field(min_length=1, max_length=80)

    @model_validator(mode="after")
    def _response_digest(self) -> "FrozenRetrievalFixture":
        actual = sha256_hex(self.response_body.encode("utf-8"))
        if actual != self.response_sha256:
            raise ValueError("frozen retrieval fixture response digest does not match its body")
        return self


class PaperEvidenceRecord(IntegratedFrozenModel):
    evidence_id: str = Field(min_length=1, max_length=160, pattern=SAFE_ID_PATTERN)
    source_id: Literal["pubmed", "pmc"] = "pubmed"
    pmid: str = Field(min_length=1, max_length=20, pattern=r"^\d+$")
    doi: str | None = Field(default=None, max_length=240)
    title: str = Field(min_length=1, max_length=600)
    authors_summary: tuple[str, ...] = Field(default_factory=tuple, max_length=20)
    journal: str = Field(min_length=1, max_length=240)
    publication_year: int = Field(strict=True, ge=1800, le=2200)
    publication_type: tuple[str, ...] = Field(default_factory=tuple, max_length=20)
    official_pubmed_url: str = Field(min_length=1, max_length=300)
    official_pmc_url: str | None = Field(default=None, max_length=300)
    abstract_available: bool
    reusable_full_text_status: str = Field(min_length=1, max_length=80)
    correction_retraction_status: CorrectionRetractionState = CorrectionRetractionState.UNKNOWN
    retrieval_timestamp: str = Field(min_length=1, max_length=80)
    source_api_version: str = Field(min_length=1, max_length=120)
    adapter_version: str = Field(min_length=1, max_length=120)
    raw_response_sha256: str = Field(pattern=SHA256_PATTERN)
    normalized_identity_sha256: str = Field(pattern=SHA256_PATTERN)
    candidate_binding: CandidateBinding | None = None
    evidence_role: EvidenceRole = EvidenceRole.UNRESOLVED
    evidence_lifecycle_state: EvidenceLifecycleState = EvidenceLifecycleState.ELIGIBLE
    freshness: FreshnessState = FreshnessState.FRESH
    applicability_limitations: tuple[str, ...] = Field(default_factory=tuple, max_length=40)
    concise_paraphrase: str = Field(min_length=1, max_length=1000)
    evidence_location: str | None = Field(default=None, max_length=240)
    human_review_state: ReviewState = ReviewState.PENDING
    human_review_required: Literal[True] = True
    source_classification: SourceClassification = SourceClassification.RETRIEVED

    @model_validator(mode="after")
    def _identity_matches(self) -> "PaperEvidenceRecord":
        payload = self.model_dump(mode="json")
        payload.pop("normalized_identity_sha256", None)
        if sha256_hex(payload) != self.normalized_identity_sha256:
            raise ValueError("paper normalized identity does not match its canonical record")
        return self

    @field_validator("doi")
    @classmethod
    def _doi(cls, value: str | None) -> str | None:
        if value is not None and ("\n" in value or "\r" in value or " " in value):
            raise ValueError("DOI must be a compact identifier")
        return value


class DatabaseEvidenceRecord(IntegratedFrozenModel):
    evidence_id: str = Field(min_length=1, max_length=160, pattern=SAFE_ID_PATTERN)
    source_id: str = Field(min_length=1, max_length=40, pattern=SAFE_ID_PATTERN)
    record_id: str = Field(min_length=1, max_length=240)
    record_type: str = Field(min_length=1, max_length=120)
    source_release: str = Field(min_length=1, max_length=160)
    assembly: str | None = Field(default=None, max_length=40)
    classification: str | None = Field(default=None, max_length=240)
    record_fields: dict[str, Any] = Field(default_factory=dict, max_length=40)
    citations: tuple[str, ...] = Field(default_factory=tuple, max_length=100)
    collection_method: str = Field(min_length=1, max_length=160)
    raw_response_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    normalized_identity_sha256: str = Field(pattern=SHA256_PATTERN)
    candidate_binding: CandidateBinding | None = None
    evidence_role: EvidenceRole = EvidenceRole.UNRESOLVED
    evidence_lifecycle_state: EvidenceLifecycleState = EvidenceLifecycleState.ELIGIBLE
    freshness: FreshnessState = FreshnessState.FRESH
    conflict_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=100)
    limitations: tuple[str, ...] = Field(default_factory=tuple, max_length=40)
    human_review_state: ReviewState = ReviewState.PENDING
    human_review_required: Literal[True] = True
    source_classification: SourceClassification = SourceClassification.RETRIEVED

    @model_validator(mode="after")
    def _identity_matches(self) -> "DatabaseEvidenceRecord":
        payload = self.model_dump(mode="json")
        payload.pop("normalized_identity_sha256", None)
        if sha256_hex(payload) != self.normalized_identity_sha256:
            raise ValueError("database evidence normalized identity does not match its canonical record")
        return self


class RetrievalEvent(IntegratedFrozenModel):
    event_id: str = Field(min_length=1, max_length=160, pattern=SAFE_ID_PATTERN)
    typed_query: TypedRetrievalQuery
    source_id: str = Field(min_length=1, max_length=40, pattern=SAFE_ID_PATTERN)
    source_release: str = Field(min_length=1, max_length=160)
    retrieval_timestamp: str = Field(min_length=1, max_length=80)
    adapter_version: str = Field(min_length=1, max_length=120)
    raw_response_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    normalized_record_identity_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    cache_status: RetrievalCacheStatus
    freshness: FreshnessState
    correction_retraction_status: CorrectionRetractionState = CorrectionRetractionState.UNKNOWN
    failure_state: RetrievalFailureState = RetrievalFailureState.NONE
    failure_or_quarantine_reason: str | None = Field(default=None, max_length=600)
    evidence_lifecycle_state: EvidenceLifecycleState
    candidate_binding: CandidateBinding | None = None
    record_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=200)


class RetrievalSnapshot(IntegratedFrozenModel):
    snapshot_id: str = Field(min_length=1, max_length=160, pattern=SAFE_ID_PATTERN)
    retrieval_event_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=500)
    normalized_record_identity_sha256: str = Field(pattern=SHA256_PATTERN)
    source_releases: tuple[str, ...] = Field(default_factory=tuple, max_length=100)
    replay_mode: Literal["fixture", "live", "mixed"]
    created_at: str = Field(min_length=1, max_length=80)
    freshness: FreshnessState = FreshnessState.UNKNOWN


class EvidenceLifecycleSummary(IntegratedFrozenModel):
    eligible_count: int = Field(default=0, strict=True, ge=0)
    context_only_count: int = Field(default=0, strict=True, ge=0)
    quarantined_count: int = Field(default=0, strict=True, ge=0)
    excluded_count: int = Field(default=0, strict=True, ge=0)
    lifecycle_identity_sha256: str = Field(pattern=SHA256_PATTERN)


class FilterHistoryEntry(IntegratedFrozenModel):
    filter_event_id: str = Field(min_length=1, max_length=160, pattern=SAFE_ID_PATTERN)
    candidate_id: str | None = Field(default=None, max_length=160, pattern=SAFE_ID_PATTERN)
    source_record_id: str | None = Field(default=None, max_length=160, pattern=SAFE_ID_PATTERN)
    rule: str = Field(min_length=1, max_length=240)
    reason: str = Field(min_length=1, max_length=800)
    rule_version: str = Field(min_length=1, max_length=120)
    original_state: str = Field(min_length=1, max_length=80)
    resulting_state: str = Field(min_length=1, max_length=80)
    action: Literal["included", "excluded", "deprioritized", "ranked", "retained"]
    source_classification: SourceClassification = SourceClassification.DETERMINISTIC


class CandidateReference(IntegratedFrozenModel):
    candidate_id: str = Field(min_length=1, max_length=160, pattern=SAFE_ID_PATTERN)
    source_record_id: str = Field(min_length=1, max_length=160, pattern=SAFE_ID_PATTERN)
    gene: str | None = Field(default=None, max_length=80)
    variant: str | None = Field(default=None, max_length=240)
    deterministic_rank: int | None = Field(default=None, strict=True, ge=1)
    aggregate_score: float | None = Field(default=None, strict=True)
    candidate_state: str = Field(min_length=1, max_length=80)
    source_classification: SourceClassification = SourceClassification.CANDIDATE_INTERPRETATION
    v037_analysis_identity_sha256: str = Field(pattern=SHA256_PATTERN)


class ExternalToolExecutionRecord(IntegratedFrozenModel):
    execution_id: str = Field(min_length=1, max_length=160, pattern=SAFE_ID_PATTERN)
    tool_id: str = Field(min_length=1, max_length=80, pattern=SAFE_ID_PATTERN)
    tool_name: str = Field(min_length=1, max_length=80)
    adapter_version: str = Field(min_length=1, max_length=120)
    execution_status: ExternalToolExecutionStatus
    availability: SourceAvailability
    operation: str = Field(min_length=1, max_length=120)
    typed_invocation: dict[str, Any] = Field(default_factory=dict, max_length=30)
    executable_path: str | None = Field(default=None, max_length=500)
    tool_version: str | None = Field(default=None, max_length=160)
    binary_or_image_digest: str | None = Field(default=None, max_length=160)
    license: str | None = Field(default=None, max_length=160)
    execution_environment: str = Field(min_length=1, max_length=160)
    input_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    output_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    invocation_identity_sha256: str = Field(pattern=SHA256_PATTERN)
    parser_version: str = Field(min_length=1, max_length=120)
    schema_version: str = Field(min_length=1, max_length=80)
    network_disabled: Literal[True] = True
    shell_used: Literal[False] = False
    timeout_seconds: int = Field(default=30, strict=True, ge=1, le=3600)
    output_size_bytes: int | None = Field(default=None, strict=True, ge=0)
    error_code: str | None = Field(default=None, max_length=120)
    error_detail: str | None = Field(default=None, max_length=600)
    source_classification: SourceClassification = SourceClassification.DETERMINISTIC


CANONICAL_BCFTOOLS_OPERATIONS: tuple[str, ...] = (
    "version",
    "validate",
    "stats",
    "sample_names",
    "decompose_multiallelic",
)


class WslBcftoolsRuntimeBinding(IntegratedFrozenModel):
    """Pinned local runtime metadata; this is configuration, never a user API value."""

    runtime_id: str = Field(min_length=1, max_length=160, pattern=SAFE_ID_PATTERN)
    distribution: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    wsl_executable_path: str = Field(min_length=1, max_length=500)
    bcftools_wsl_path: str = Field(min_length=1, max_length=500)
    executable_sha256: str = Field(pattern=SHA256_PATTERN)
    executable_byte_size: int = Field(strict=True, gt=0)
    bcftools_version: str = Field(min_length=1, max_length=80)
    htslib_version: str = Field(min_length=1, max_length=80)
    micromamba_version: str = Field(min_length=1, max_length=80)
    environment_name: Literal["insilicopop-bcftools-1.24"]
    environment_lock_sha256: str = Field(pattern=SHA256_PATTERN)
    platform: Literal["linux-64"] = "linux-64"
    license: str = Field(min_length=1, max_length=240)
    max_input_bytes: int = Field(default=50_000_000, strict=True, ge=1, le=50_000_000)
    max_output_bytes: int = Field(default=50_000_000, strict=True, ge=1, le=50_000_000)
    max_timeout_seconds: int = Field(default=30, strict=True, ge=1, le=600)
    network_isolation_level: Literal["local_file_only_proxy_scrubbed_no_kernel_namespace"]
    local_file_only: Literal[True] = True
    shell_interpolation_allowed: Literal[False] = False

    @field_validator("wsl_executable_path")
    @classmethod
    def _wsl_executable_path(cls, value: str) -> str:
        normalized = value.replace("/", "\\")
        if not re.fullmatch(r"[A-Za-z]:\\(?:[^\\/:*?\"<>|\x00]+\\)*wsl\.exe", normalized, flags=re.IGNORECASE):
            raise ValueError("WSL executable path must be an absolute Windows path ending in wsl.exe")
        return normalized

    @field_validator("bcftools_wsl_path")
    @classmethod
    def _bcftools_wsl_path(cls, value: str) -> str:
        if (
            not re.fullmatch(r"/[A-Za-z0-9._/+\-]+", value)
            or "/../" in f"/{value.strip('/')}/"
            or not value.endswith("/bcftools")
        ):
            raise ValueError("bcftools WSL path must be a safe absolute Linux path ending in /bcftools")
        return value

    def identity_sha256(self) -> str:
        return sha256_hex(self.model_dump(mode="json"))


class BcftoolsExecutionAuthorization(IntegratedFrozenModel):
    """A typed, bounded local-maintenance approval without a credential or token."""

    authorization_id: str = Field(min_length=1, max_length=160, pattern=SAFE_ID_PATTERN)
    authorization_version: str = Field(min_length=1, max_length=120)
    approval_record: Literal["human_authorized_local_maintenance"]
    scope: Literal["canonical_synthetic_vcf_only"]
    runtime_binding_identity_sha256: str = Field(pattern=SHA256_PATTERN)
    authorized_input_relative_path: str = Field(min_length=1, max_length=240, pattern=SAFE_PATH_PATTERN)
    authorized_input_sha256: str = Field(pattern=SHA256_PATTERN)
    authorized_operations: tuple[
        Literal["version", "validate", "stats", "sample_names", "decompose_multiallelic"], ...
    ] = Field(min_length=5, max_length=5)
    issued_at_utc: str = Field(min_length=20, max_length=40)
    expires_at_utc: str = Field(min_length=20, max_length=40)
    reference_left_normalization_performed: Literal[False] = False

    _safe_authorized_path = field_validator("authorized_input_relative_path")(_safe_relative_path)

    @field_validator("issued_at_utc", "expires_at_utc")
    @classmethod
    def _utc_timestamp(cls, value: str) -> str:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("authorization timestamps must be ISO-8601 UTC values") from exc
        if parsed.tzinfo is None:
            raise ValueError("authorization timestamps must include a UTC offset")
        return value

    @model_validator(mode="after")
    def _bounded_scope(self) -> "BcftoolsExecutionAuthorization":
        if tuple(self.authorized_operations) != CANONICAL_BCFTOOLS_OPERATIONS:
            raise ValueError("authorization must retain the exact canonical bcftools operation set and order")
        if self._parse_time(self.expires_at_utc) <= self._parse_time(self.issued_at_utc):
            raise ValueError("authorization expiry must be after issuance")
        return self

    @staticmethod
    def _parse_time(value: str) -> datetime:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)

    def is_current(self, now: datetime | None = None) -> bool:
        reference = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        return self._parse_time(self.issued_at_utc) <= reference < self._parse_time(self.expires_at_utc)

    def identity_sha256(self) -> str:
        return sha256_hex(self.model_dump(mode="json"))


class BcftoolsInvocation(IntegratedFrozenModel):
    operation: Literal["version", "validate", "stats", "sample_names", "decompose_multiallelic"]
    input_relative_path: str | None = Field(default=None, max_length=240, pattern=SAFE_PATH_PATTERN)
    output_relative_path: str | None = Field(default=None, max_length=240, pattern=SAFE_PATH_PATTERN)
    reference_name: str | None = Field(default=None, max_length=160)
    reference_source: str | None = Field(default=None, max_length=300)
    reference_assembly: str | None = Field(default=None, max_length=40)
    reference_byte_size: int | None = Field(default=None, strict=True, ge=0)
    reference_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    timeout_seconds: int = Field(default=30, strict=True, ge=1, le=600)

    _safe_input_path = field_validator("input_relative_path", "output_relative_path")(
        lambda value: _safe_relative_path(value) if value is not None else value
    )

    @model_validator(mode="after")
    def _reference_identity(self) -> "BcftoolsInvocation":
        reference_values = (
            self.reference_name,
            self.reference_source,
            self.reference_assembly,
            self.reference_byte_size,
            self.reference_sha256,
        )
        if any(value is not None for value in reference_values) and not all(value is not None for value in reference_values):
            raise ValueError("reference-dependent execution requires a complete pinned reference identity")
        return self


class IndiaPopulationContext(IntegratedFrozenModel):
    source_id: Literal["indigenomes", "gnomad_south_asian"]
    availability: SourceAvailability
    genome_build: str | None = Field(default=None, max_length=40)
    release: str | None = Field(default=None, max_length=120)
    sample_count: int | None = Field(default=None, strict=True, ge=0)
    frequency: float | None = Field(default=None, strict=True)
    source_url: str | None = Field(default=None, max_length=400)
    snapshot_byte_size: int | None = Field(default=None, strict=True, ge=0)
    snapshot_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    licensing_label: str = Field(min_length=1, max_length=400)
    ancestry_inference_performed: Literal[False] = False
    absence_means_zero: Literal[False] = False
    limitations: tuple[str, ...] = Field(default_factory=tuple, max_length=40)

    @field_validator("frequency")
    @classmethod
    def _frequency(cls, value: float | None) -> float | None:
        return _finite_unit(value)


class NABLScopeVerification(IntegratedFrozenModel):
    laboratory_name: str = Field(min_length=1, max_length=240)
    laboratory_reference: str = Field(min_length=1, max_length=160)
    certificate_number: str | None = Field(default=None, max_length=160)
    iso_15189_wording: str | None = Field(default=None, max_length=240)
    issue_date: str | None = Field(default=None, max_length=40)
    expiry_date: str | None = Field(default=None, max_length=40)
    exact_accreditation_scope: str = Field(min_length=1, max_length=600)
    molecular_genetics_assay_coverage: str | None = Field(default=None, max_length=600)
    verification_date: str = Field(min_length=1, max_length=40)
    official_source_url: str | None = Field(default=None, max_length=400)
    state: Literal["supplied", "independently_verified", "scope_unverified"]
    snapshot_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    limitations: tuple[str, ...] = Field(default_factory=tuple, max_length=30)


class ManagedAccessContext(IntegratedFrozenModel):
    source_id: Literal["genomeindia_ibdc"]
    availability: SourceAvailability = SourceAvailability.MANAGED_ACCESS
    access_program: str = Field(min_length=1, max_length=240)
    official_source_url: str = Field(min_length=1, max_length=400)
    access_granted: Literal[False] = False
    data_retrieved: Literal[False] = False
    limitations: tuple[str, ...] = Field(default_factory=tuple, max_length=30)


class RareDiseaseReferralContext(IntegratedFrozenModel):
    source_id: Literal["mohfw_rare_disease_centres"]
    official_source_url: str = Field(min_length=1, max_length=400)
    version_or_access_date: str = Field(min_length=1, max_length=80)
    centres_of_excellence_reference: str = Field(min_length=1, max_length=600)
    automatic_selection_performed: Literal[False] = False
    treatment_recommendation_made: Literal[False] = False


class IndiaContext(IntegratedFrozenModel):
    population_context: tuple[IndiaPopulationContext, ...] = Field(default_factory=tuple, max_length=20)
    nabl_scope_verifications: tuple[NABLScopeVerification, ...] = Field(default_factory=tuple, max_length=20)
    managed_access_contexts: tuple[ManagedAccessContext, ...] = Field(default_factory=tuple, max_length=20)
    referral_contexts: tuple[RareDiseaseReferralContext, ...] = Field(default_factory=tuple, max_length=20)
    ancestry_inferred: Literal[False] = False
    caste_or_community_inferred: Literal[False] = False
    human_review_required: Literal[True] = True


class HumanReviewProposal(IntegratedFrozenModel):
    proposal_id: str = Field(min_length=1, max_length=160, pattern=SAFE_ID_PATTERN)
    proposal_type: str = Field(min_length=1, max_length=160)
    rationale: str = Field(min_length=1, max_length=1000)
    evidence_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=100)
    supporting_evidence: tuple[str, ...] = Field(default_factory=tuple, max_length=40)
    contradicting_evidence: tuple[str, ...] = Field(default_factory=tuple, max_length=40)
    unresolved_information: tuple[str, ...] = Field(default_factory=tuple, max_length=40)
    assay_or_evidence_limitations: tuple[str, ...] = Field(default_factory=tuple, max_length=40)
    review_priority: Literal["high", "medium", "low"]
    provenance: tuple[str, ...] = Field(default_factory=tuple, max_length=40)
    human_decision_required: Literal[True] = True
    test_ordered: Literal[False] = False
    treatment_recommended: Literal[False] = False


class InputIntegritySummary(IntegratedFrozenModel):
    source_package_identity_sha256: str = Field(pattern=SHA256_PATTERN)
    v036_manifest_identity_sha256: str = Field(pattern=SHA256_PATTERN)
    v036_result_gateway_identity_sha256: str = Field(pattern=SHA256_PATTERN)
    v037_analysis_identity_sha256: str = Field(pattern=SHA256_PATTERN)
    v037_ranking_input_identity_sha256: str = Field(pattern=SHA256_PATTERN)
    v037_ranking_output_identity_sha256: str = Field(pattern=SHA256_PATTERN)
    input_integrity_sha256: str = Field(pattern=SHA256_PATTERN)


class IdentityChain(IntegratedFrozenModel):
    supplied_package_identity_sha256: str = Field(pattern=SHA256_PATTERN)
    v036_manifest_identity_sha256: str = Field(pattern=SHA256_PATTERN)
    v036_result_gateway_identity_sha256: str = Field(pattern=SHA256_PATTERN)
    phenotype_identity_sha256: str = Field(pattern=SHA256_PATTERN)
    family_identity_sha256: str = Field(pattern=SHA256_PATTERN)
    v037_ranking_input_identity_sha256: str = Field(pattern=SHA256_PATTERN)
    v037_ranking_output_identity_sha256: str = Field(pattern=SHA256_PATTERN)
    candidate_analysis_identity_sha256: str = Field(pattern=SHA256_PATTERN)
    multimodal_findings_identity_sha256: str = Field(pattern=SHA256_PATTERN)
    external_tool_execution_identity_sha256: str = Field(pattern=SHA256_PATTERN)
    retrieval_event_identity_sha256: str = Field(pattern=SHA256_PATTERN)
    retrieval_snapshot_identity_sha256: str = Field(pattern=SHA256_PATTERN)
    evidence_lifecycle_identity_sha256: str = Field(pattern=SHA256_PATTERN)
    integrated_workspace_identity_sha256: str = Field(pattern=SHA256_PATTERN)
    final_integrity_sha256: str = Field(pattern=SHA256_PATTERN)


class IntegratedAnalysisRequest(IntegratedFrozenModel):
    schema_version: Literal["0.38"] = INTEGRATED_ANALYSIS_SCHEMA_VERSION
    source_package_identity_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    v036_manifest_identity_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    supplied_cnv_findings: tuple[SuppliedCNVFinding, ...] = Field(default_factory=tuple, max_length=100)
    supplied_mitochondrial_findings: tuple[SuppliedMitochondrialFinding, ...] = Field(default_factory=tuple, max_length=100)
    mosaicism_measurements: tuple[MosaicismMeasurement, ...] = Field(default_factory=tuple, max_length=100)
    retrieval_queries: tuple[TypedRetrievalQuery, ...] = Field(default_factory=tuple, max_length=100)
    frozen_retrieval_fixtures: tuple[FrozenRetrievalFixture, ...] = Field(
        default_factory=tuple,
        validation_alias=AliasChoices("frozen_retrieval_fixtures", "retrieval_fixtures"),
        max_length=100,
    )
    external_tool_request: BcftoolsInvocation | None = None
    filter_history: tuple[FilterHistoryEntry, ...] = Field(default_factory=tuple, max_length=1000)
    laboratory_assay_metadata: dict[str, Any] = Field(default_factory=dict, max_length=80)
    qc_summary: dict[str, Any] = Field(default_factory=dict, max_length=80)
    coverage_blind_spots: tuple[dict[str, Any], ...] = Field(default_factory=tuple, max_length=200)
    supplied_database_evidence: tuple[DatabaseEvidenceRecord, ...] = Field(
        default_factory=tuple,
        validation_alias=AliasChoices("supplied_database_evidence", "database_evidence"),
        max_length=500,
    )
    candidate_acmg_evidence_organization: tuple[dict[str, Any], ...] = Field(default_factory=tuple, max_length=1000)
    specialist_outputs: tuple[dict[str, Any], ...] = Field(default_factory=tuple, max_length=500)
    draft_report_inputs: tuple[dict[str, Any], ...] = Field(default_factory=tuple, max_length=500)
    india_context: IndiaContext | None = None
    human_review_proposals: tuple[HumanReviewProposal, ...] = Field(default_factory=tuple, max_length=200)
    workspace_created_at: str = Field(default="2026-08-23T00:00:00Z", max_length=80)
    live_retrieval_authorized: Literal[False] = False
    live_tool_authorized: Literal[False] = False


class IntegratedAnalysisWorkspace(IntegratedFrozenModel):
    schema_version: Literal["0.38"] = INTEGRATED_ANALYSIS_SCHEMA_VERSION
    algorithm_version: str = INTEGRATED_ANALYSIS_ALGORITHM_VERSION
    rule_version: str = INTEGRATED_ANALYSIS_RULE_VERSION
    workspace_id: str = Field(min_length=1, max_length=160, pattern=SAFE_ID_PATTERN)
    pseudonymous_case_id: str = Field(min_length=1, max_length=80, pattern=SAFE_ID_PATTERN)
    status: IntegratedWorkspaceStatus
    status_reasons: tuple[str, ...] = Field(default_factory=tuple, max_length=100)
    input_integrity: InputIntegritySummary
    laboratory_assay_metadata: dict[str, Any] = Field(default_factory=dict, max_length=80)
    qc_summary: dict[str, Any] = Field(default_factory=dict, max_length=80)
    coverage_blind_spots: tuple[dict[str, Any], ...] = Field(default_factory=tuple, max_length=200)
    normalized_snv_small_indel_summaries: tuple[dict[str, Any], ...] = Field(default_factory=tuple, max_length=1000)
    external_tool_executions: tuple[ExternalToolExecutionRecord, ...] = Field(default_factory=tuple, max_length=100)
    annotation_summaries: tuple[dict[str, Any], ...] = Field(default_factory=tuple, max_length=1000)
    filter_history: tuple[FilterHistoryEntry, ...] = Field(default_factory=tuple, max_length=2000)
    ranked_candidates: tuple[CandidateReference, ...] = Field(default_factory=tuple, max_length=1000)
    excluded_candidates: tuple[CandidateReference, ...] = Field(default_factory=tuple, max_length=1000)
    family_segregation_findings: tuple[dict[str, Any], ...] = Field(default_factory=tuple, max_length=500)
    supplied_cnv_findings: tuple[SuppliedCNVFinding, ...] = Field(default_factory=tuple, max_length=100)
    supplied_mitochondrial_findings: tuple[SuppliedMitochondrialFinding, ...] = Field(default_factory=tuple, max_length=100)
    mosaicism_measurements: tuple[MosaicismMeasurement, ...] = Field(default_factory=tuple, max_length=100)
    papers: tuple[PaperEvidenceRecord, ...] = Field(default_factory=tuple, max_length=1000)
    database_evidence: tuple[DatabaseEvidenceRecord, ...] = Field(default_factory=tuple, max_length=1000)
    retrieval_events: tuple[RetrievalEvent, ...] = Field(default_factory=tuple, max_length=1000)
    retrieval_snapshot: RetrievalSnapshot
    evidence_lifecycle_summary: EvidenceLifecycleSummary
    conflicts_and_limitations: tuple[str, ...] = Field(default_factory=tuple, max_length=500)
    candidate_acmg_evidence_organization: tuple[dict[str, Any], ...] = Field(default_factory=tuple, max_length=1000)
    specialist_outputs: tuple[dict[str, Any], ...] = Field(default_factory=tuple, max_length=500)
    human_review_proposals: tuple[HumanReviewProposal, ...] = Field(default_factory=tuple, max_length=500)
    draft_report_inputs: tuple[dict[str, Any], ...] = Field(default_factory=tuple, max_length=500)
    india_context: IndiaContext | None = None
    provenance: tuple[str, ...] = Field(default_factory=tuple, max_length=500)
    review_state: ReviewState = ReviewState.PENDING
    identity_chain: IdentityChain
    multimodal_findings_identity_sha256: str = Field(pattern=SHA256_PATTERN)
    integrated_workspace_identity_sha256: str = Field(pattern=SHA256_PATTERN)
    final_integrity_sha256: str = Field(pattern=SHA256_PATTERN)
    research_use_only: Literal[True] = True
    human_review_required: Literal[True] = True
    draft_not_clinically_approved: Literal[True] = True
    diagnosis_performed: Literal[False] = False
    treatment_recommended: Literal[False] = False
    test_ordered: Literal[False] = False
    final_acmg_classification_performed: Literal[False] = False
    clinical_signout_performed: Literal[False] = False
    raw_bytes_persisted: Literal[False] = False
    external_llm_called: Literal[False] = False
    patient_data_sent_externally: Literal[False] = False

    @model_validator(mode="after")
    def _identity_chain_matches(self) -> "IntegratedAnalysisWorkspace":
        if self.identity_chain.integrated_workspace_identity_sha256 != self.integrated_workspace_identity_sha256:
            raise ValueError("identity chain integrated workspace identity does not match workspace identity")
        if self.identity_chain.final_integrity_sha256 != self.final_integrity_sha256:
            raise ValueError("identity chain final integrity does not match workspace final integrity")
        return self

    def _workspace_payload(self) -> dict[str, Any]:
        payload = self.model_dump(mode="json", exclude={"integrated_workspace_identity_sha256", "final_integrity_sha256"})
        payload["identity_chain"]["integrated_workspace_identity_sha256"] = None
        payload["identity_chain"]["final_integrity_sha256"] = None
        return payload

    def _final_payload(self) -> dict[str, Any]:
        payload = self.model_dump(mode="json", exclude={"final_integrity_sha256"})
        payload["identity_chain"]["final_integrity_sha256"] = None
        return payload

    def verify_integrity(self, *, persisted_checksum: str | None = None) -> None:
        expected_workspace = sha256_hex(self._workspace_payload())
        if expected_workspace != self.integrated_workspace_identity_sha256:
            raise ValueError("integrated workspace identity does not match its canonical payload")
        expected_final = sha256_hex(self._final_payload())
        if expected_final != self.final_integrity_sha256:
            raise ValueError("integrated workspace final integrity does not match its canonical payload")
        if persisted_checksum is not None and persisted_checksum not in {self.final_integrity_sha256, self.integrated_workspace_identity_sha256}:
            raise ValueError("persisted integrated workspace checksum does not match the verified workspace")

    @classmethod
    def verified_load(cls, payload: dict[str, Any], *, persisted_checksum: str | None = None) -> "IntegratedAnalysisWorkspace":
        workspace = cls.model_validate(payload)
        workspace.verify_integrity(persisted_checksum=persisted_checksum)
        return workspace


def build_integrity_chain_payload(**values: str) -> dict[str, str]:
    return {key: values[key] for key in sorted(values)}


__all__ = [
    "INTEGRATED_ANALYSIS_SCHEMA_VERSION",
    "INTEGRATED_ANALYSIS_ALGORITHM_VERSION",
    "INTEGRATED_ANALYSIS_RULE_VERSION",
    "INTEGRATED_ANALYSIS_RETRIEVAL_VERSION",
    "INTEGRATED_ANALYSIS_TOOL_VERSION",
    "IntegratedFrozenModel",
    "SourceClassification",
    "IntegratedWorkspaceStatus",
    "EvidenceLifecycleState",
    "EvidenceRole",
    "FreshnessState",
    "CorrectionRetractionState",
    "RetrievalCacheStatus",
    "SourceAvailability",
    "MosaicismMeasurementState",
    "ReviewState",
    "ConfirmationState",
    "ExternalToolExecutionStatus",
    "RetrievalFailureState",
    "SourceBinding",
    "CandidateBinding",
    "SuppliedCNVFinding",
    "SuppliedMitochondrialFinding",
    "MosaicismMeasurement",
    "TypedRetrievalQuery",
    "FrozenRetrievalFixture",
    "PaperEvidenceRecord",
    "DatabaseEvidenceRecord",
    "RetrievalEvent",
    "RetrievalSnapshot",
    "EvidenceLifecycleSummary",
    "FilterHistoryEntry",
    "CandidateReference",
    "ExternalToolExecutionRecord",
    "CANONICAL_BCFTOOLS_OPERATIONS",
    "WslBcftoolsRuntimeBinding",
    "BcftoolsExecutionAuthorization",
    "BcftoolsInvocation",
    "IndiaPopulationContext",
    "NABLScopeVerification",
    "ManagedAccessContext",
    "RareDiseaseReferralContext",
    "IndiaContext",
    "HumanReviewProposal",
    "InputIntegritySummary",
    "IdentityChain",
    "IntegratedAnalysisRequest",
    "IntegratedAnalysisWorkspace",
    "canonical_json",
    "sha256_hex",
]
