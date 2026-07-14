from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

from app.insilicopop.clinical.models import CandidateVariantIntake
from app.insilicopop.clinical.variant_models import (
    CoordinateSystem,
    DeclaredVariantClass,
    VariantIssue,
    VariantNormalizationRequest,
    VariantRepresentationType,
)


_ACCESSION_WITH_VERSION = re.compile(r"^[A-Za-z]{1,8}_[A-Za-z0-9]+\.\d+$")
_HGVS_SYNTAX = re.compile(r"^[^:\s]+:[gcnrpm]\.\S+$")
_CAID = re.compile(r"^CA\d+$")
_DNA = re.compile(r"^[ACGTN]*$")
_RAW_GENOMIC_PATH = re.compile(r"(?i)(?:^|[\\/])[^\\/]+\.(?:vcf(?:\.gz)?|bcf|bam|cram|fastq(?:\.gz)?|fq(?:\.gz)?|fasta|fa)$")


UNSUPPORTED_CLASS_REASON = {
    DeclaredVariantClass.CNV: "UNSUPPORTED_STRUCTURAL_VARIANT",
    DeclaredVariantClass.STRUCTURAL_VARIANT: "UNSUPPORTED_STRUCTURAL_VARIANT",
    DeclaredVariantClass.INVERSION: "UNSUPPORTED_STRUCTURAL_VARIANT",
    DeclaredVariantClass.TRANSLOCATION: "UNSUPPORTED_STRUCTURAL_VARIANT",
    DeclaredVariantClass.REPEAT_EXPANSION: "UNSUPPORTED_REPEAT_EXPANSION",
    DeclaredVariantClass.MOBILE_ELEMENT_INSERTION: "UNSUPPORTED_STRUCTURAL_VARIANT",
    DeclaredVariantClass.BREAKEND: "UNSUPPORTED_STRUCTURAL_VARIANT",
    DeclaredVariantClass.GENE_FUSION: "UNSUPPORTED_STRUCTURAL_VARIANT",
    DeclaredVariantClass.CHROMOSOMAL_ABNORMALITY: "UNSUPPORTED_STRUCTURAL_VARIANT",
    DeclaredVariantClass.MOSAIC: "UNSUPPORTED_MOSAIC_REPRESENTATION",
    DeclaredVariantClass.SOMATIC: "UNSUPPORTED_VARIANT_CLASS",
    DeclaredVariantClass.MITOCHONDRIAL_COMPLEX: "UNSUPPORTED_VARIANT_CLASS",
    DeclaredVariantClass.COMPLEX_REARRANGEMENT: "UNSUPPORTED_STRUCTURAL_VARIANT",
    DeclaredVariantClass.PHARMACOGENOMIC_HAPLOTYPE: "UNSUPPORTED_VARIANT_CLASS",
    DeclaredVariantClass.HLA_ALLELE: "UNSUPPORTED_VARIANT_CLASS",
    DeclaredVariantClass.STAR_ALLELE: "UNSUPPORTED_VARIANT_CLASS",
    DeclaredVariantClass.POLYGENIC_SCORE: "UNSUPPORTED_VARIANT_CLASS",
}


@dataclass
class VariantValidationAssessment:
    errors: list[VariantIssue] = field(default_factory=list)
    warnings: list[VariantIssue] = field(default_factory=list)
    missing: list[VariantIssue] = field(default_factory=list)
    unsupported: list[VariantIssue] = field(default_factory=list)
    conflicts: list[VariantIssue] = field(default_factory=list)
    review_actions: list[VariantIssue] = field(default_factory=list)


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def content_hash(value: Any) -> str:
    encoded = value if isinstance(value, str) else canonical_json(value)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def stable_variant_identifier(prefix: str, *parts: Any) -> str:
    digest = content_hash([prefix, *parts])[:20]
    return f"{prefix}-{digest}"


def variant_issue(
    request: VariantNormalizationRequest,
    code: str,
    message: str,
    severity: str,
    *,
    field_name: str | None = None,
) -> VariantIssue:
    provenance = sorted(set(request.provenance_source_ids))
    return VariantIssue(
        issue_id=stable_variant_identifier(
            "variant-issue",
            request.request_id,
            request.candidate_variant_id,
            code,
            field_name,
            provenance,
        ),
        code=code,
        message=message,
        field=field_name,
        severity=severity,
        provenance_source_ids=provenance,
    )


def canonical_request_snapshot(request: VariantNormalizationRequest) -> VariantNormalizationRequest:
    return request.model_copy(
        update={
            "requested_outputs": sorted(set(request.requested_outputs), key=lambda item: item.value),
            "provenance_source_ids": sorted(set(request.provenance_source_ids)),
        }
    )


def validate_variant_request(
    request: VariantNormalizationRequest,
    candidate: CandidateVariantIntake | None,
) -> VariantValidationAssessment:
    result = VariantValidationAssessment()
    representation = request.supplied_representation

    if candidate is None:
        result.errors.append(
            variant_issue(
                request,
                "CANDIDATE_VARIANT_REFERENCE_REQUIRED",
                "The normalization request must reference an exact supplied candidate variant ID.",
                "error",
                field_name="candidate_variant_id",
            )
        )

    if representation != representation.strip():
        result.warnings.append(
            variant_issue(
                request,
                "FORMATTING_ANOMALY_PRESERVED",
                "Surrounding characters in the supplied representation were preserved exactly and prevent silent exact matching.",
                "warning",
                field_name="supplied_representation",
            )
        )
        result.review_actions.append(
            variant_issue(
                request,
                "REVIEW_EXACT_SUPPLIED_FORMATTING",
                "Review the exact supplied representation before using any separate normalized candidate output.",
                "review",
                field_name="supplied_representation",
            )
        )

    if _RAW_GENOMIC_PATH.search(representation):
        result.unsupported.append(
            variant_issue(
                request,
                "RAW_GENOMIC_INPUT_NOT_SUPPORTED",
                "Raw genomic file paths or uploads are outside the v0.30 structured variant-intelligence scope.",
                "unsupported",
                field_name="supplied_representation",
            )
        )

    unsupported_code = UNSUPPORTED_CLASS_REASON.get(request.declared_variant_class)
    if unsupported_code:
        result.unsupported.append(
            variant_issue(
                request,
                unsupported_code,
                "The declared variant class is preserved but is outside bounded v0.30 normalization.",
                "unsupported",
                field_name="declared_variant_class",
            )
        )

    lowered = representation.casefold()
    inferred_unsupported = _unsupported_text_reason(lowered)
    if inferred_unsupported and not any(item.code == inferred_unsupported for item in result.unsupported):
        result.unsupported.append(
            variant_issue(
                request,
                inferred_unsupported,
                "The supplied representation indicates a variant class outside bounded v0.30 normalization.",
                "unsupported",
                field_name="supplied_representation",
            )
        )

    if request.representation_type in {VariantRepresentationType.FREE_TEXT, VariantRepresentationType.UNKNOWN}:
        result.unsupported.append(
            variant_issue(
                request,
                "UNSUPPORTED_FREE_TEXT_REPRESENTATION",
                "Free-text or unknown representations are preserved but cannot be normalized automatically.",
                "unsupported",
                field_name="representation_type",
            )
        )

    if request.representation_type in {
        VariantRepresentationType.HGVS_GENOMIC,
        VariantRepresentationType.HGVS_CODING,
        VariantRepresentationType.HGVS_NON_CODING,
        VariantRepresentationType.HGVS_RNA,
        VariantRepresentationType.HGVS_PROTEIN,
    }:
        if not _HGVS_SYNTAX.fullmatch(representation):
            result.errors.append(
                variant_issue(
                    request,
                    "MALFORMED_HGVS_SYNTAX",
                    "The supplied HGVS text does not satisfy the bounded syntax check; semantic validity was not inferred.",
                    "error",
                    field_name="supplied_representation",
                )
            )
        _validate_hgvs_context(request, result)

    if request.representation_type in {
        VariantRepresentationType.GENOMIC_COORDINATE,
        VariantRepresentationType.VCF_LIKE_FIELDS,
    }:
        _validate_structured_allele(request, result)

    if request.representation_type == VariantRepresentationType.SPDI:
        spdi = request.supplied_spdi or representation
        if len(spdi.split(":")) != 4:
            result.errors.append(
                variant_issue(request, "MALFORMED_SPDI", "A supplied SPDI representation must contain four explicit colon-delimited fields.", "error", field_name="supplied_spdi")
            )

    if request.supplied_caid is not None and not _CAID.fullmatch(request.supplied_caid):
        result.errors.append(
            variant_issue(request, "MALFORMED_CAID", "The supplied CAID was preserved but does not match the bounded CAID structure.", "error", field_name="supplied_caid")
        )

    if request.representation_type == VariantRepresentationType.VRS:
        result.unsupported.append(
            variant_issue(request, "NORMALIZATION_LIBRARY_UNAVAILABLE", "VRS generation or semantic validation is unavailable because no pinned local VRS library is installed.", "unsupported", field_name="representation_type")
        )

    if candidate is not None:
        _validate_candidate_context(request, candidate, result)

    for collection in (result.errors, result.warnings, result.missing, result.unsupported, result.conflicts, result.review_actions):
        collection.sort(key=lambda item: (item.code, item.issue_id))
    return result


def _validate_hgvs_context(request: VariantNormalizationRequest, result: VariantValidationAssessment) -> None:
    if request.representation_type == VariantRepresentationType.HGVS_GENOMIC:
        accession = request.supplied_reference_accession or request.supplied_representation.split(":", 1)[0]
        if not accession:
            result.missing.append(variant_issue(request, "REFERENCE_ACCESSION_REQUIRED", "A genomic HGVS request requires an explicit reference accession.", "missing", field_name="supplied_reference_accession"))
        elif not _ACCESSION_WITH_VERSION.fullmatch(accession):
            result.missing.append(variant_issue(request, "REFERENCE_VERSION_REQUIRED", "The supplied genomic reference accession must include an explicit version.", "missing", field_name="supplied_reference_accession"))
        if not request.supplied_genome_build:
            result.missing.append(variant_issue(request, "GENOME_BUILD_REQUIRED", "Genome build must be supplied explicitly for bounded genomic normalization.", "missing", field_name="supplied_genome_build"))
    if request.representation_type in {
        VariantRepresentationType.HGVS_CODING,
        VariantRepresentationType.HGVS_NON_CODING,
        VariantRepresentationType.HGVS_RNA,
    }:
        accession = request.supplied_transcript_accession or request.supplied_representation.split(":", 1)[0]
        if not accession or not _ACCESSION_WITH_VERSION.fullmatch(accession):
            result.missing.append(variant_issue(request, "TRANSCRIPT_VERSION_REQUIRED", "Transcript-level normalization requires an explicitly supplied transcript accession with version.", "missing", field_name="supplied_transcript_accession"))


def _validate_structured_allele(request: VariantNormalizationRequest, result: VariantValidationAssessment) -> None:
    allele = request.structured_allele
    if allele is None:
        result.missing.append(variant_issue(request, "STRUCTURED_ALLELE_REQUIRED", "Coordinate-based normalization requires explicit structured allele fields.", "missing", field_name="structured_allele"))
        return
    if allele.coordinate_system == CoordinateSystem.UNKNOWN:
        result.missing.append(variant_issue(request, "COORDINATE_SYSTEM_REQUIRED", "The coordinate system must be supplied explicitly and cannot be unknown.", "missing", field_name="structured_allele.coordinate_system"))
    if not allele.genome_build:
        result.missing.append(variant_issue(request, "GENOME_BUILD_REQUIRED", "Genome build must be supplied explicitly.", "missing", field_name="structured_allele.genome_build"))
    if allele.reference == "" and allele.alternate == "":
        result.errors.append(variant_issue(request, "REFERENCE_ALTERNATE_COMBINATION_INVALID", "Reference and alternate alleles cannot both be empty.", "error", field_name="structured_allele"))
    if allele.coordinate_system == CoordinateSystem.VCF_ONE_BASED and (not allele.reference or not allele.alternate):
        result.errors.append(variant_issue(request, "VCF_ALLELES_REQUIRED", "VCF-like fields require explicit non-empty reference and alternate alleles.", "error", field_name="structured_allele"))
    if allele.coordinate_system != CoordinateSystem.ZERO_BASED_HALF_OPEN and allele.position < 1:
        result.errors.append(variant_issue(request, "POSITION_OUT_OF_RANGE", "One-based coordinate systems require a position of at least one.", "error", field_name="structured_allele.position"))
    for name, value in (("reference", allele.reference), ("alternate", allele.alternate)):
        if value != value.strip() or not _DNA.fullmatch(value):
            result.warnings.append(variant_issue(request, "ALLELE_FORMATTING_ANOMALY_PRESERVED", f"The supplied {name} allele was preserved exactly and is not silently case- or whitespace-normalized.", "warning", field_name=f"structured_allele.{name}"))


def _validate_candidate_context(
    request: VariantNormalizationRequest,
    candidate: CandidateVariantIntake,
    result: VariantValidationAssessment,
) -> None:
    allele = request.structured_allele
    request_build = allele.genome_build if allele else request.supplied_genome_build
    request_chromosome = allele.chromosome if allele else request.supplied_chromosome
    request_reference = allele.reference if allele else request.supplied_reference
    request_alternate = allele.alternate if allele else request.supplied_alternate
    comparisons = [
        ("BUILD_CONFLICT", "genome_build", candidate.genome_build, request_build),
        ("CHROMOSOME_CONFLICT", "chromosome", candidate.chromosome, request_chromosome),
        ("REFERENCE_MISMATCH", "reference", candidate.ref, request_reference),
        ("ALTERNATE_MISMATCH", "alternate", candidate.alt, request_alternate),
        ("TRANSCRIPT_CONFLICT", "transcript", candidate.transcript, request.supplied_transcript_accession),
    ]
    for code, field_name, supplied_candidate, supplied_request in comparisons:
        if supplied_candidate is not None and supplied_request is not None and supplied_candidate != supplied_request:
            result.conflicts.append(
                variant_issue(
                    request,
                    code,
                    f"The exact supplied candidate {field_name} conflicts with the exact normalization-request value; neither value was changed.",
                    "conflict",
                    field_name=field_name,
                )
            )


def _unsupported_text_reason(text: str) -> str | None:
    checks = [
        ("UNSUPPORTED_MOSAIC_REPRESENTATION", ("mosaic", "vaf", "allele fraction", "%")),
        ("UNSUPPORTED_REPEAT_EXPANSION", ("repeat expansion", "triplet repeat", "[", "]")),
        ("UNSUPPORTED_STRUCTURAL_VARIANT", ("copy number", "cnv", "translocation", "inversion", "breakend", "fusion", "mobile element", "bnd")),
    ]
    for code, markers in checks:
        if any(marker in text for marker in markers):
            return code
    return None
