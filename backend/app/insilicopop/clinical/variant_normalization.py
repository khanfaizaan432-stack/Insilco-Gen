from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.insilicopop.clinical.models import CandidateVariantIntake
from app.insilicopop.clinical.variant_models import (
    CoordinateSystem,
    DeclaredVariantClass,
    RequestedVariantOutput,
    VariantEquivalenceStatus,
    VariantNormalizedOutput,
    VariantNormalizationOperation,
    VariantNormalizationRequest,
    VariantNormalizationResult,
    VariantNormalizationStatus,
    VariantReferenceContext,
    VariantTranscriptContext,
    VariantValidationStatus,
)
from app.insilicopop.clinical.variant_validation import (
    VariantValidationAssessment,
    canonical_json,
    canonical_request_snapshot,
    content_hash,
    stable_variant_identifier,
    validate_variant_request,
    variant_issue,
)


@dataclass(frozen=True)
class CanonicalAllele:
    chromosome: str
    genome_build: str
    reference_accession: str | None
    start_zero_based: int
    reference: str
    alternate: str
    variant_class: str
    minimal_changed: bool
    left_shift_count: int


def normalize_variant_request(
    request: VariantNormalizationRequest,
    candidate: CandidateVariantIntake | None,
) -> VariantNormalizationResult:
    snapshot = canonical_request_snapshot(request)
    assessment = validate_variant_request(request, candidate)
    reference_context = _reference_context(request)
    transcript_context = VariantTranscriptContext(
        supplied_transcript_accession=request.supplied_transcript_accession,
        version_explicit=bool(request.supplied_transcript_accession and "." in request.supplied_transcript_accession),
    )
    operations: list[VariantNormalizationOperation] = []
    outputs: list[VariantNormalizedOutput] = []
    canonical: CanonicalAllele | None = None

    operations.append(
        _operation(
            request,
            "bounded_schema_and_context_validation",
            "refused" if assessment.errors or assessment.unsupported else "succeeded",
            snapshot.model_dump(),
            None if assessment.errors or assessment.unsupported else {"request_id": request.request_id},
            reference_context,
            [item.code for item in [*assessment.warnings, *assessment.missing, *assessment.conflicts]],
        )
    )

    blocks_normalization = bool(assessment.errors or assessment.unsupported or assessment.conflicts)
    formatting_blocks = any(item.code in {"FORMATTING_ANOMALY_PRESERVED", "ALLELE_FORMATTING_ANOMALY_PRESERVED"} for item in assessment.warnings)
    if request.structured_allele is not None and not blocks_normalization and not assessment.missing and not formatting_blocks:
        canonical = _canonicalize_structured_allele(request, assessment, operations, reference_context)

    for output_type in sorted(set(request.requested_outputs), key=lambda item: item.value):
        outputs.append(_build_output(request, output_type, canonical, assessment))

    if not outputs and request.requested_outputs:
        outputs = []

    generated_normalizations = [
        item for item in outputs
        if item.status == "generated" and item.output_type != RequestedVariantOutput.VALIDATED_SUPPLIED_REPRESENTATION
    ]
    refused_outputs = [item for item in outputs if item.status in {"unsupported", "not_generated"}]
    validation_status = _validation_status(assessment)
    normalization_status = _normalization_status(
        request,
        validation_status,
        generated_normalizations=generated_normalizations,
        refused_outputs=refused_outputs,
    )
    equivalence_status = _equivalence_status(assessment, canonical)
    variant_class = canonical.variant_class if canonical else request.declared_variant_class.value

    if equivalence_status == VariantEquivalenceStatus.UNRESOLVED_EQUIVALENCE and not any(item.code == "HUMAN_VARIANT_REVIEW_REQUIRED" for item in assessment.review_actions):
        assessment.review_actions.append(
            variant_issue(
                request,
                "HUMAN_VARIANT_REVIEW_REQUIRED",
                "Insufficient or ambiguous representation context requires human review; no transcript, build, or missing allele was inferred.",
                "review",
            )
        )
    for collection in (assessment.errors, assessment.warnings, assessment.missing, assessment.unsupported, assessment.conflicts, assessment.review_actions):
        collection.sort(key=lambda item: (item.code, item.issue_id))
    operations.sort(key=lambda item: (item.operation_name, item.operation_id))
    outputs.sort(key=lambda item: (item.output_type.value, item.output_id))

    stable_payload = {
        "schema_version": "0.30",
        "algorithm_version": "insilicopop-variant-intelligence-0.30.0",
        "request": snapshot.model_dump(),
        "variant_class": variant_class,
        "validation_status": validation_status.value,
        "normalization_status": normalization_status.value,
        "equivalence_status": equivalence_status.value,
        "outputs": [item.model_dump() for item in outputs],
        "operations": [item.model_dump() for item in operations],
        "errors": [item.model_dump() for item in assessment.errors],
        "warnings": [item.model_dump() for item in assessment.warnings],
        "missing": [item.model_dump() for item in assessment.missing],
        "unsupported": [item.model_dump() for item in assessment.unsupported],
        "conflicts": [item.model_dump() for item in assessment.conflicts],
        "review": [item.model_dump() for item in assessment.review_actions],
    }
    return VariantNormalizationResult(
        request_id=request.request_id,
        candidate_variant_id=request.candidate_variant_id,
        supplied_request_snapshot=snapshot,
        variant_class=variant_class,
        validation_status=validation_status,
        normalization_status=normalization_status,
        equivalence_status=equivalence_status,
        normalized_outputs=outputs,
        reference_context_used=reference_context,
        transcript_context_used=transcript_context,
        normalization_operations=operations,
        validation_errors=assessment.errors,
        warnings=assessment.warnings,
        missing_information=assessment.missing,
        unsupported_reasons=assessment.unsupported,
        conflicts=assessment.conflicts,
        review_actions=assessment.review_actions,
        provenance_source_ids=sorted(set(request.provenance_source_ids)),
        stable_result_id=stable_variant_identifier("variant-result", stable_payload),
    )


def _reference_context(request: VariantNormalizationRequest) -> VariantReferenceContext:
    allele = request.structured_allele
    if allele is None:
        return VariantReferenceContext(
            genome_build=request.supplied_genome_build,
            chromosome=request.supplied_chromosome,
            reference_accession=request.supplied_reference_accession,
        )
    start = allele.position if allele.coordinate_system == CoordinateSystem.ZERO_BASED_HALF_OPEN else allele.position - 1
    return VariantReferenceContext(
        genome_build=allele.genome_build,
        chromosome=allele.chromosome,
        reference_accession=allele.reference_accession or request.supplied_reference_accession,
        coordinate_system=allele.coordinate_system.value,
        position_supplied=allele.position,
        start_zero_based=start,
        reference_context_verified=allele.reference_context_verified,
    )


def _canonicalize_structured_allele(
    request: VariantNormalizationRequest,
    assessment: VariantValidationAssessment,
    operations: list[VariantNormalizationOperation],
    reference_context: VariantReferenceContext,
) -> CanonicalAllele | None:
    allele = request.structured_allele
    assert allele is not None
    start = allele.position if allele.coordinate_system == CoordinateSystem.ZERO_BASED_HALF_OPEN else allele.position - 1
    operations.append(
        _operation(
            request,
            "explicit_coordinate_system_conversion",
            "succeeded",
            {"position": allele.position, "coordinate_system": allele.coordinate_system.value},
            {"start_zero_based": start},
            reference_context,
        )
    )
    if allele.reference_context_verified and allele.reference_context_sequence is not None and allele.reference:
        offset = start - int(allele.reference_context_start or 0)
        observed = allele.reference_context_sequence[offset:offset + len(allele.reference)] if offset >= 0 else ""
        if observed != allele.reference:
            assessment.conflicts.append(
                variant_issue(
                    request,
                    "REFERENCE_MISMATCH",
                    "The exact supplied reference allele does not match the verified bounded reference context; normalization was refused.",
                    "conflict",
                    field_name="structured_allele.reference",
                )
            )
            operations.append(_operation(request, "verified_reference_context_check", "refused", allele.reference, observed, reference_context, ["REFERENCE_MISMATCH"]))
            return None
        operations.append(_operation(request, "verified_reference_context_check", "succeeded", allele.reference, observed, reference_context))

    ref, alt = allele.reference, allele.alternate
    minimal_start, minimal_ref, minimal_alt = _minimal_representation(start, ref, alt)
    minimal_changed = (minimal_start, minimal_ref, minimal_alt) != (start, ref, alt)
    operations.append(
        _operation(
            request,
            "minimal_allele_representation",
            "succeeded",
            {"start_zero_based": start, "reference": ref, "alternate": alt},
            {"start_zero_based": minimal_start, "reference": minimal_ref, "alternate": minimal_alt},
            reference_context,
        )
    )
    left_shift_count = 0
    if allele.reference_context_verified and allele.reference_context_sequence is not None:
        shifted_start, shifted_ref, shifted_alt = _left_normalize(
            minimal_start,
            minimal_ref,
            minimal_alt,
            allele.reference_context_sequence,
            int(allele.reference_context_start or 0),
        )
        left_shift_count = minimal_start - shifted_start
        operations.append(
            _operation(
                request,
                "left_normalize_with_verified_bounded_reference",
                "succeeded",
                {"start_zero_based": minimal_start, "reference": minimal_ref, "alternate": minimal_alt},
                {"start_zero_based": shifted_start, "reference": shifted_ref, "alternate": shifted_alt},
                reference_context,
            )
        )
        minimal_start, minimal_ref, minimal_alt = shifted_start, shifted_ref, shifted_alt

    variant_class = _classify(minimal_ref, minimal_alt, request.declared_variant_class)
    return CanonicalAllele(
        chromosome=allele.chromosome,
        genome_build=allele.genome_build,
        reference_accession=allele.reference_accession or request.supplied_reference_accession,
        start_zero_based=minimal_start,
        reference=minimal_ref,
        alternate=minimal_alt,
        variant_class=variant_class,
        minimal_changed=minimal_changed,
        left_shift_count=left_shift_count,
    )


def _minimal_representation(start: int, reference: str, alternate: str) -> tuple[int, str, str]:
    ref, alt = reference, alternate
    while ref and alt and ref[-1] == alt[-1]:
        ref, alt = ref[:-1], alt[:-1]
    while ref and alt and ref[0] == alt[0]:
        ref, alt, start = ref[1:], alt[1:], start + 1
    return start, ref, alt


def _left_normalize(start: int, reference: str, alternate: str, context: str, context_start: int) -> tuple[int, str, str]:
    ref, alt = reference, alternate
    if bool(ref) == bool(alt):
        return start, ref, alt
    sequence = ref or alt
    while start > context_start:
        previous_index = start - context_start - 1
        if previous_index < 0 or previous_index >= len(context) or not sequence or context[previous_index] != sequence[-1]:
            break
        sequence = context[previous_index] + sequence[:-1]
        start -= 1
    return (start, sequence, "") if ref else (start, "", sequence)


def _classify(reference: str, alternate: str, declared: DeclaredVariantClass) -> str:
    if declared == DeclaredVariantClass.DUPLICATION:
        return "duplication"
    if len(reference) == 1 and len(alternate) == 1:
        return "snv"
    if reference and not alternate:
        return "deletion"
    if alternate and not reference:
        return "insertion"
    if len(reference) == len(alternate) and len(reference) > 1:
        return "mnv"
    if reference and alternate:
        return "delins"
    return declared.value


def _build_output(
    request: VariantNormalizationRequest,
    output_type: RequestedVariantOutput,
    canonical: CanonicalAllele | None,
    assessment: VariantValidationAssessment,
) -> VariantNormalizedOutput:
    if output_type == RequestedVariantOutput.VALIDATED_SUPPLIED_REPRESENTATION:
        status = "preserved"
        value: str | dict[str, Any] | None = request.supplied_representation
        reason = None if not assessment.errors else "SUPPLIED_REPRESENTATION_INVALID"
        return _output(request, output_type, status, value, reason)
    if output_type == RequestedVariantOutput.CAID:
        if request.supplied_caid and request.supplied_caid.startswith("CA") and request.supplied_caid[2:].isdigit():
            return _output(request, output_type, "preserved", request.supplied_caid, None)
        return _output(request, output_type, "unsupported", None, "CAID_LOOKUP_UNAVAILABLE")
    if output_type == RequestedVariantOutput.VRS:
        return _output(request, output_type, "unsupported", None, "NORMALIZATION_LIBRARY_UNAVAILABLE")
    if canonical is None:
        return _output(request, output_type, "not_generated", None, _primary_refusal_code(assessment))
    if output_type == RequestedVariantOutput.CANONICAL_INTERNAL_ALLELE:
        value = {
            "scope": "insilicopop_internal_research_representation",
            "genome_build": canonical.genome_build,
            "chromosome": canonical.chromosome,
            "start_zero_based": canonical.start_zero_based,
            "reference": canonical.reference,
            "alternate": canonical.alternate,
            "variant_class": canonical.variant_class,
        }
        return _output(request, output_type, "generated", value, None)
    if output_type == RequestedVariantOutput.SPDI:
        if not canonical.reference_accession:
            return _output(request, output_type, "not_generated", None, "REFERENCE_ACCESSION_REQUIRED")
        return _output(request, output_type, "generated", f"{canonical.reference_accession}:{canonical.start_zero_based}:{canonical.reference}:{canonical.alternate}", None)
    if output_type == RequestedVariantOutput.NORMALIZED_HGVS:
        if not canonical.reference_accession or "." not in canonical.reference_accession:
            return _output(request, output_type, "not_generated", None, "REFERENCE_VERSION_REQUIRED")
        return _output(request, output_type, "generated", _hgvs(canonical), None)
    return _output(request, output_type, "unsupported", None, "UNSUPPORTED_REQUESTED_OUTPUT")


def _hgvs(allele: CanonicalAllele) -> str:
    start = allele.start_zero_based + 1
    end = allele.start_zero_based + len(allele.reference)
    prefix = f"{allele.reference_accession}:g."
    if allele.variant_class == "snv":
        return f"{prefix}{start}{allele.reference}>{allele.alternate}"
    if allele.variant_class == "deletion":
        location = str(start) if start == end else f"{start}_{end}"
        return f"{prefix}{location}del"
    if allele.variant_class == "insertion":
        return f"{prefix}{allele.start_zero_based}_{allele.start_zero_based + 1}ins{allele.alternate}"
    if allele.variant_class == "duplication":
        location = str(start) if start == end else f"{start}_{end}"
        return f"{prefix}{location}dup"
    location = str(start) if start == end else f"{start}_{end}"
    return f"{prefix}{location}delins{allele.alternate}"


def _output(request: VariantNormalizationRequest, output_type: RequestedVariantOutput, status: str, value: str | dict[str, Any] | None, reason: str | None) -> VariantNormalizedOutput:
    return VariantNormalizedOutput(
        output_id=stable_variant_identifier("variant-output", request.request_id, output_type.value, status, value, reason),
        output_type=output_type,
        status=status,
        value=value,
        reason_code=reason,
    )


def _operation(
    request: VariantNormalizationRequest,
    name: str,
    status: str,
    input_value: Any,
    output_value: Any,
    context: VariantReferenceContext,
    warnings: list[str] | None = None,
) -> VariantNormalizationOperation:
    input_digest = content_hash(input_value)
    output_digest = content_hash(output_value) if output_value is not None else None
    return VariantNormalizationOperation(
        operation_id=stable_variant_identifier("variant-operation", request.request_id, name, status, input_digest, output_digest, context.model_dump()),
        operation_name=name,
        status=status,
        input_hash=input_digest,
        output_hash=output_digest,
        reference_context=context,
        warnings=sorted(set(warnings or [])),
    )


def _validation_status(assessment: VariantValidationAssessment) -> VariantValidationStatus:
    if assessment.unsupported:
        return VariantValidationStatus.UNSUPPORTED
    if assessment.errors:
        return VariantValidationStatus.INVALID
    if assessment.conflicts or assessment.warnings:
        return VariantValidationStatus.PARTIALLY_VALID
    if assessment.missing:
        return VariantValidationStatus.CANNOT_VALIDATE
    return VariantValidationStatus.VALID


def _normalization_status(
    request: VariantNormalizationRequest,
    validation_status: VariantValidationStatus,
    *,
    generated_normalizations: list[VariantNormalizedOutput],
    refused_outputs: list[VariantNormalizedOutput],
) -> VariantNormalizationStatus:
    if validation_status == VariantValidationStatus.UNSUPPORTED:
        return VariantNormalizationStatus.UNSUPPORTED
    if validation_status == VariantValidationStatus.INVALID:
        return VariantNormalizationStatus.CANNOT_NORMALIZE
    if not request.requested_outputs or not generated_normalizations:
        return VariantNormalizationStatus.CANNOT_NORMALIZE if refused_outputs else VariantNormalizationStatus.NOT_NORMALIZED
    if refused_outputs:
        return VariantNormalizationStatus.PARTIALLY_NORMALIZED
    return VariantNormalizationStatus.NORMALIZED


def _equivalence_status(assessment: VariantValidationAssessment, canonical: CanonicalAllele | None) -> VariantEquivalenceStatus:
    if assessment.unsupported:
        return VariantEquivalenceStatus.UNSUPPORTED_REPRESENTATION
    if assessment.conflicts or assessment.errors:
        return VariantEquivalenceStatus.INCOMPATIBLE_REPRESENTATIONS if assessment.conflicts else VariantEquivalenceStatus.UNRESOLVED_EQUIVALENCE
    if canonical is None:
        return VariantEquivalenceStatus.UNRESOLVED_EQUIVALENCE
    if canonical.minimal_changed or canonical.left_shift_count:
        return VariantEquivalenceStatus.NORMALIZED_EQUIVALENCE
    return VariantEquivalenceStatus.EXACT_EQUIVALENCE


def _primary_refusal_code(assessment: VariantValidationAssessment) -> str:
    for collection in (assessment.errors, assessment.conflicts, assessment.missing, assessment.unsupported, assessment.warnings):
        if collection:
            return collection[0].code
    return "REFERENCE_DATA_UNAVAILABLE"
