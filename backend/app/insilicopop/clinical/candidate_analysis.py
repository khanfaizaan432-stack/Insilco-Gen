from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

from app.insilicopop.clinical.candidate_analysis_models import (
    CANDIDATE_ANALYSIS_ALGORITHM_VERSION,
    CANDIDATE_FIXED_COMPONENT_WEIGHTS,
    CANDIDATE_FIXED_FAMILY_GQ_THRESHOLD,
    CANDIDATE_FIXED_SUPPORT_THRESHOLD,
    CANDIDATE_FIXED_TIE_EPSILON,
    CANDIDATE_RANKING_RULE_VERSION,
    CANDIDATE_RANKING_WEIGHT_VERSION,
    CANDIDATE_REQUIRED_UNRESOLVED_WORDING,
    CandidateAnalysisRecord,
    CandidateAnalysisRequest,
    CandidateAnalysisResult,
    CandidateAnalysisState,
    CandidateContextInput,
    CandidateEvidence,
    CandidateEvidenceInput,
    CandidateIdentity,
    CandidateSourceAlleleKey,
    CandidateRankingComponent,
    CandidateRankingRule,
    CandidateReviewStatus,
    CandidateSourceRecordIdentity,
    CandidateVariantScope,
    ComponentWeight,
    ComponentState,
    ConsequenceContext,
    DeNovoState,
    EvidenceRole,
    EvidenceState,
    ExcludedCandidate,
    ExclusionCode,
    ExclusionOutcome,
    ExclusionTrace,
    FilteringRule,
    FamilySegregationObservation,
    FamilySegregationSummary,
    FamilyShape,
    FamilySampleBindingInput,
    FamilyObservationStatus,
    FrequencyContext,
    GeneTranscriptContext,
    InheritanceCompatibilitySummary,
    InheritanceStatementState,
    MissingInformation,
    NegativeUnresolvedResult,
    PhaseEvaluation,
    PhenotypeMatchSummary,
    ProvenanceReference,
    QualityCoverageAssayContext,
    RelationshipObservationState,
    RuntimeMetadata,
    UnresolvedUncertainty,
    VariantGenotypeContext,
    canonical_json,
    canonical_candidate_id,
    calculate_candidate_component,
    safe_candidate_id,
    sha256_hex,
    stable_candidate_id,
)
from app.insilicopop.clinical.models import ClinicalCaseIntake
from app.insilicopop.clinical.pedigree_models import (
    InheritanceAuditStatus,
    PhaseState,
    VariantPresenceState,
)


COMPONENT_WEIGHTS = dict(CANDIDATE_FIXED_COMPONENT_WEIGHTS)

COMPONENT_RATIONALES = {
    "phenotype_match": "Supplied HPO identifiers are compared exactly; related terms are used only when a pinned supplied relation is present.",
    "phenotype_specificity": "Only a supplied specificity value is used; specificity is not inferred from an unpinned ontology.",
    "onset_compatibility": "Only the supplied onset compatibility state is used.",
    "inheritance_compatibility": "Uses supplied inheritance statements and the bounded v0.29 consistency audit; it is review evidence, not a diagnosis.",
    "segregation": "Uses supplied family observations and deterministic genotype/sample bindings where all prerequisites are present.",
    "frequency": "Uses a supplied population-frequency value as prioritization context; absence from a dataset is never negative evidence.",
    "consequence": "Uses supplied consequence text only and does not predict pathogenicity.",
    "transcript_relevance": "Uses supplied transcript relevance only; transcript selection is not performed.",
    "gene_disease_validity": "Uses supplied validity context only; no external evidence retrieval is performed.",
    "variant_quality": "Uses supplied VCF quality/filter fields only.",
    "qc": "Uses supplied QC fields only; missing or warning-only QC is not converted into disease absence.",
    "coverage_assay_scope": "Coverage and reportable-scope limits change confidence and review status, never disease absence.",
    "supporting_evidence": "Counts supplied candidate evidence with visible source references.",
    "contradicting_evidence": "Counts supplied contradictory evidence and retains it visibly.",
    "missing_information": "Missing inputs are retained as missing and contribute no false positive or false negative evidence.",
    "unresolved_uncertainty": "Unresolved inputs remain explicit and contribute no score.",
}


def build_candidate_analysis(
    case: ClinicalCaseIntake,
    *,
    result_gateway: Any = None,
    phenotype_curation: Any = None,
    pedigree_audit: Any = None,
    request: CandidateAnalysisRequest | None = None,
) -> CandidateAnalysisResult:
    """Build a deterministic, source-bound v0.37 candidate analysis.

    The builder consumes only typed records already present in the repository.
    It never performs annotation retrieval, raw variant calling, or external
    execution.  A candidate is retained or excluded with a trace entry; no
    filtering step silently drops a supplied record.
    """

    request = request or getattr(case, "candidate_analysis", None) or CandidateAnalysisRequest()
    gateway = result_gateway
    package_identity = getattr(gateway, "package_identity_sha256", None)
    manifest_identity = getattr(gateway, "input_manifest_sha256", None)
    package_id = getattr(gateway, "package_id", None)
    package_version = getattr(gateway, "package_version", "not_available")
    vcf = getattr(gateway, "vcf", None)
    records = list(getattr(vcf, "records", ()) or ())
    out_of_scope_records = list(getattr(vcf, "retained_out_of_scope", ()) or ())

    phenotype_snapshot = _phenotype_snapshot(case, phenotype_curation)
    family_snapshot = _family_snapshot(case, pedigree_audit)
    assay_snapshot = _assay_snapshot(gateway)
    evidence_snapshot = _evidence_snapshot(request)
    phenotype_identity = sha256_hex(phenotype_snapshot)
    family_identity = sha256_hex(family_snapshot)
    assay_identity = sha256_hex(assay_snapshot)
    evidence_identity = sha256_hex(evidence_snapshot)
    input_payload = {
        "case_id": case.pseudonymous_case_id,
        "request": request.model_dump(mode="json"),
        "source_record_ids": sorted(str(getattr(item, "record_id", "")) for item in records),
        "out_of_scope_record_ids": sorted(str(getattr(item, "record_id", "")) for item in out_of_scope_records),
        "package_identity": package_identity,
        "manifest_identity": manifest_identity,
        "phenotype_identity": phenotype_identity,
        "family_identity": family_identity,
        "assay_identity": assay_identity,
        "evidence_identity": evidence_identity,
    }
    input_identity = sha256_hex(input_payload)

    stale_codes = _stale_codes(
        request=request,
        gateway=gateway,
        phenotype_identity=phenotype_identity,
        family_identity=family_identity,
        assay_identity=assay_identity,
    )
    source_provenance = _gateway_provenance(gateway)
    context_by_record = _context_by_record(request, case, records)
    context_by_candidate = {item.candidate_id: item for item in request.candidate_contexts}
    record_by_candidate = {
        canonical_candidate_id(_source_identity(item, gateway)): item
        for item in records
    }
    case_candidates = {item.candidate_id: item for item in case.candidate_variants}
    audit_by_candidate = _audit_by_candidate(pedigree_audit)
    evidence_by_candidate = _evidence_by_candidate(request.evidence, source_provenance)
    exclusion_trace: list[ExclusionTrace] = []
    excluded: list[ExcludedCandidate] = []
    ranked: list[CandidateAnalysisRecord] = []
    all_missing: list[MissingInformation] = []
    all_unresolved: list[UnresolvedUncertainty] = []

    if stale_codes:
        for code in stale_codes:
            all_unresolved.append(
                _uncertainty(
                    "case",
                    f"stale-{code}",
                    "stale_input",
                    f"The v0.37 analysis input is stale for {code}; replay is required before ranking is used.",
                    f"Expected and current snapshot identities differ for {code}.",
                    source_provenance,
                )
            )

    if gateway is None or not records:
        for context in request.candidate_contexts:
            trace = _trace(
                context.candidate_id,
                "source_record_not_present",
                ExclusionCode.SOURCE_RECORD_NOT_FOUND,
                "A supported v0.36 result-gateway record is required before a candidate can be ranked.",
                source_provenance,
                outcome=ExclusionOutcome.EXCLUDED,
                input_state="no_v036_source_record",
            )
            exclusion_trace.append(trace)
            excluded.append(
                ExcludedCandidate(
                    candidate_id=context.candidate_id,
                    candidate_identity=None,
                    exclusion_history=(trace,),
                    missing_information=(
                        _missing(
                            context.candidate_id,
                            "source_result",
                            "A supported SNV/small-indel source record from the v0.36 gateway is missing.",
                            source_provenance,
                        ),
                    ),
                )
            )
        all_missing.append(
            _missing(
                None,
                "source_result",
                "A v0.36 result-gateway package with supported SNV/small-indel records was not supplied.",
                source_provenance,
            )
        )
    else:
        for record in records:
            source_identity = _source_identity(record, gateway)
            expected_candidate_id = canonical_candidate_id(source_identity)
            matching_contexts = context_by_record.get(str(record.record_id), [])
            if not matching_contexts:
                matching_contexts = _coordinate_contexts(case, request, record)
            if not matching_contexts:
                matching_contexts = [
                    CandidateContextInput(
                        candidate_id=expected_candidate_id,
                        source_record_id=str(record.record_id),
                        provenance=tuple(source_provenance),
                    )
                ]
            for context in matching_contexts:
                supplied_candidate_id = context.candidate_id
                candidate_id = expected_candidate_id
                candidate_identity = CandidateIdentity(
                    candidate_id=candidate_id,
                    stable_candidate_id=stable_candidate_id(source_identity),
                    source_record=source_identity,
                    supplied_candidate_id=(supplied_candidate_id if supplied_candidate_id != candidate_id else None),
                    supplied_representation=(case_candidates.get(supplied_candidate_id).submitted_representation if supplied_candidate_id in case_candidates else None),
                )
                record_provenance = tuple(_merge_provenance(source_provenance, context.provenance))
                binding_error = _source_binding_error(context, record, source_identity, expected_candidate_id)
                if binding_error:
                    trace = _trace(
                        supplied_candidate_id,
                        "invalid-source-binding",
                        ExclusionCode.INVALID_SOURCE_BINDING,
                        binding_error,
                        record_provenance,
                        outcome=ExclusionOutcome.EXCLUDED,
                        input_state="source_binding_validation_failed",
                    )
                    exclusion_trace.append(trace)
                    excluded.append(
                        ExcludedCandidate(
                            candidate_id=supplied_candidate_id,
                            candidate_identity=candidate_identity,
                            exclusion_history=(trace,),
                            unresolved_uncertainties=(
                                _uncertainty(
                                    supplied_candidate_id,
                                    "invalid-source-binding",
                                    "source_binding",
                                    "The supplied candidate representation did not bind to the canonical v0.36 source record.",
                                    binding_error,
                                    record_provenance,
                                ),
                            ),
                        )
                    )
                    continue
                if stale_codes:
                    trace = _trace(
                        candidate_id,
                        "stale_input",
                        ExclusionCode.STALE_RESULT_PACKAGE if "result_package" in stale_codes else ExclusionCode.STALE_RANKING_RULE,
                        "A stale input prevents ranking this candidate until the v0.37 analysis is replayed.",
                        record_provenance,
                        outcome=ExclusionOutcome.EXCLUDED,
                        input_state="stale",
                    )
                    exclusion_trace.append(trace)
                    excluded.append(ExcludedCandidate(candidate_id=candidate_id, candidate_identity=candidate_identity, exclusion_history=(trace,)))
                    continue
                record_scope = _variant_scope(record)
                if record_scope not in {CandidateVariantScope.SNV, CandidateVariantScope.SMALL_INDEL}:
                    trace = _trace(
                        candidate_id,
                        "unsupported_variant_scope",
                        ExclusionCode.UNSUPPORTED_VARIANT_SCOPE,
                        f"The v0.36 record is retained out of supported v0.37 scope as {record_scope.value}; it is not interpreted.",
                        record_provenance,
                        outcome=ExclusionOutcome.EXCLUDED,
                        input_state=record_scope.value,
                    )
                    exclusion_trace.append(trace)
                    excluded.append(ExcludedCandidate(candidate_id=candidate_id, candidate_identity=candidate_identity, exclusion_history=(trace,)))
                    continue
                if context.exclusion_rule_id:
                    trace = _trace(
                        candidate_id,
                        "versioned_rule_exclusion",
                        ExclusionCode.VERSIONED_RULE_EXCLUSION,
                        context.exclusion_rule_reason or "The supplied versioned v0.37 rule excludes this candidate from ranking while retaining its trace.",
                        record_provenance,
                        outcome=ExclusionOutcome.EXCLUDED,
                        input_state="supported_source_record",
                        rule_id=context.exclusion_rule_id,
                        rule_version=context.exclusion_rule_version or CANDIDATE_RANKING_RULE_VERSION,
                    )
                    exclusion_trace.append(trace)
                    excluded.append(ExcludedCandidate(candidate_id=candidate_id, candidate_identity=candidate_identity, exclusion_history=(trace,)))
                    continue
                if _outside_reportable_range(context, record, gateway):
                    trace = _trace(
                        candidate_id,
                        "outside_reportable_range",
                        ExclusionCode.OUTSIDE_REPORTABLE_RANGE,
                        "The supplied assay reportable range does not include this candidate; this is an assay-scope limitation, not evidence of disease absence.",
                        record_provenance,
                        outcome=ExclusionOutcome.EXCLUDED,
                        input_state="supported_source_record",
                    )
                    exclusion_trace.append(trace)
                    excluded.append(
                        ExcludedCandidate(
                            candidate_id=candidate_id,
                            candidate_identity=candidate_identity,
                            exclusion_history=(trace,),
                            unresolved_uncertainties=(
                                _uncertainty(
                                    candidate_id,
                                    "outside-reportable-range",
                                    "assay_scope",
                                    "This record was outside the supplied reportable range.",
                                    "The assay scope cannot be used to infer absence outside its assessed range.",
                                    record_provenance,
                                ),
                            ),
                        )
                    )
                    continue
                candidate_record, record_missing, record_unresolved, retained_trace = _build_record(
                    case=case,
                    candidate_id=candidate_id,
                    context=context,
                    record=record,
                    gateway=gateway,
                    phenotype_curation=phenotype_curation,
                    pedigree_audit=pedigree_audit,
                    audit_by_candidate=audit_by_candidate,
                    evidence_by_candidate=evidence_by_candidate,
                    source_provenance=record_provenance,
                    request=request,
                    context_by_candidate=context_by_candidate,
                    record_by_candidate=record_by_candidate,
                )
                ranked.append(candidate_record)
                all_missing.extend(record_missing)
                all_unresolved.extend(record_unresolved)
                if retained_trace is not None:
                    exclusion_trace.append(retained_trace)

        bound_ids = {item.candidate_identity.candidate_id for item in ranked} | {
            item.candidate_id for item in excluded
        }
        for context in request.candidate_contexts:
            if context.candidate_id in bound_ids:
                continue
            trace = _trace(
                context.candidate_id,
                "context_without_source_record",
                ExclusionCode.SOURCE_RECORD_NOT_FOUND,
                "The supplied candidate context did not bind to a v0.36 record; it is retained as an exclusion rather than silently dropped.",
                tuple(_merge_provenance(source_provenance, context.provenance)),
                outcome=ExclusionOutcome.EXCLUDED,
                input_state="unbound_candidate_context",
            )
            exclusion_trace.append(trace)
            excluded.append(ExcludedCandidate(candidate_id=context.candidate_id, candidate_identity=None, exclusion_history=(trace,)))

        ranked_or_excluded_source_ids = {
            str(item.candidate_identity.source_record.source_record_id)
            for item in ranked
            if item.candidate_identity is not None
        } | {
            str(item.candidate_identity.source_record.source_record_id)
            for item in excluded
            if item.candidate_identity is not None
        }
        for record in out_of_scope_records:
            if str(record.record_id) in ranked_or_excluded_source_ids:
                continue
            context = _out_of_scope_context(request, record)
            candidate_id = context.candidate_id if context else f"CAND-OUT-{record.record_id}"
            candidate_identity = _out_of_scope_identity(record, gateway, candidate_id)
            trace = _trace(
                candidate_id,
                "retained_out_of_scope_record",
                ExclusionCode.UNSUPPORTED_VARIANT_SCOPE,
                f"The supplied v0.36 out-of-scope reason is retained unchanged: {getattr(record, 'reason', 'not supplied')}.",
                source_provenance,
                outcome=ExclusionOutcome.EXCLUDED,
                input_state=str(getattr(record, "variant_scope", "out_of_scope")),
            )
            exclusion_trace.append(trace)
            excluded.append(ExcludedCandidate(candidate_id=candidate_id, candidate_identity=candidate_identity, exclusion_history=(trace,)))

    ranked = _assign_ranks(ranked, request)
    exclusion_trace = sorted(exclusion_trace, key=lambda item: (item.candidate_id, item.code.value, item.exclusion_id))
    excluded = sorted(excluded, key=lambda item: item.candidate_id)
    all_missing = _dedupe_missing(all_missing)
    all_unresolved = _dedupe_uncertainties(all_unresolved)
    family_summary = _family_summary(case, request, gateway, ranked, excluded)
    unavailable_adapters = _unavailable_adapters(gateway)
    unsupported_types = sorted({
        str(getattr(getattr(item, "variant_scope", None), "value", getattr(item, "variant_scope", "unsupported")))
        for item in out_of_scope_records
    })
    weak_ids = tuple(
        item.candidate_identity.candidate_id
        for item in ranked
        if item.review_status in {CandidateReviewStatus.RETAINED_WEAK_FOR_REVIEW, CandidateReviewStatus.RETAINED_NOT_ASSESSED_FOR_REVIEW}
    )
    contradictory_ids = tuple(
        item.candidate_identity.candidate_id
        for item in ranked
        if item.contradicting_evidence or item.inheritance_compatibility.state == ComponentState.NEGATIVE
    )
    supported_ids = tuple(
        item.candidate_identity.candidate_id
        for item in ranked
        if item.aggregate_score is not None and item.aggregate_score >= _support_threshold(request)
    )
    negative = NegativeUnresolvedResult(
        analysis_scope=_analysis_scope(gateway),
        assessed_regions=_assessed_regions(gateway),
        unassessed_regions=_unassessed_regions(gateway),
        coverage_gaps=_coverage_gaps(gateway),
        assay_blind_spots=_assay_blind_spots(gateway),
        unsupported_result_types=tuple(unsupported_types),
        unavailable_adapters=tuple(unavailable_adapters),
        retained_candidate_ids=tuple(item.candidate_identity.candidate_id for item in ranked),
        excluded_candidate_ids=tuple(item.candidate_id for item in excluded),
        excluded_candidate_reasons=tuple(
            f"{item.candidate_id}: {trace.code.value} - {trace.reason}"
            for item in excluded
            for trace in item.exclusion_history
        ),
        weak_candidate_ids=weak_ids,
        contradictory_candidate_ids=contradictory_ids,
        missing_information=tuple(all_missing),
        unresolved_questions=tuple(all_unresolved),
        human_review_questions=_human_review_questions(
            ranked=ranked,
            excluded=excluded,
            stale_codes=stale_codes,
            unavailable_adapters=unavailable_adapters,
        ),
        no_sufficiently_supported_candidate=not supported_ids,
        summary=CANDIDATE_REQUIRED_UNRESOLVED_WORDING,
    )
    rule = _ranking_rule(request)
    analysis_status = _analysis_status(
        gateway=gateway,
        records=records,
        ranked=ranked,
        excluded=excluded,
        stale_codes=stale_codes,
        supported_ids=supported_ids,
    )
    output_payload = {
        "ranked_candidates": [item.model_dump(mode="json") for item in ranked],
        "excluded_candidates": [item.model_dump(mode="json") for item in excluded],
        "exclusion_trace": [item.model_dump(mode="json") for item in exclusion_trace],
        "negative_unresolved_result": negative.model_dump(mode="json"),
        "rule": rule.model_dump(mode="json"),
    }
    output_identity = sha256_hex(output_payload)
    base = CandidateAnalysisResult.model_construct(
        pseudonymous_case_id=case.pseudonymous_case_id,
        analysis_status=analysis_status,
        ranking_rule=rule,
        ranked_candidates=tuple(ranked),
        excluded_candidates=tuple(excluded),
        exclusion_trace=tuple(exclusion_trace),
        family_segregation=family_summary,
        negative_unresolved_result=negative,
        source_record_ids=tuple(sorted({
            *[str(getattr(item, "record_id", "")) for item in records],
            *[str(getattr(item, "record_id", "")) for item in out_of_scope_records],
        })),
        v036_package_id=package_id,
        v036_package_identity_sha256=package_identity,
        v036_manifest_identity_sha256=manifest_identity,
        v036_invocation_ids=tuple(sorted(_invocation_identities(gateway))),
        phenotype_snapshot_identity_sha256=phenotype_identity,
        family_snapshot_identity_sha256=family_identity,
        assay_coverage_identity_sha256=assay_identity,
        evidence_input_identity_sha256=evidence_identity,
        ranking_input_canonical_json=canonical_json(input_payload),
        ranking_input_identity_sha256=input_identity,
        ranking_output_identity_sha256=output_identity,
        analysis_identity_sha256="0" * 64,
        result_integrity_sha256="0" * 64,
        stale_input_codes=tuple(stale_codes),
        missing_information=tuple(all_missing),
        unresolved_uncertainties=tuple(all_unresolved),
        runtime_metadata=RuntimeMetadata(),
    )
    analysis_identity = sha256_hex(
        base.model_dump(
            mode="json",
            exclude={"analysis_identity_sha256", "result_integrity_sha256", "runtime_metadata"},
        )
    )
    finalized = base.model_copy(update={"analysis_identity_sha256": analysis_identity})
    integrity = sha256_hex(
        finalized.model_dump(
            mode="json",
            exclude={"result_integrity_sha256", "runtime_metadata"},
        )
    )
    finalized = finalized.model_copy(update={"result_integrity_sha256": integrity})
    finalized.verify_integrity()
    return finalized


def _build_record(
    *,
    case: ClinicalCaseIntake,
    candidate_id: str,
    context: CandidateContextInput,
    record: Any,
    gateway: Any,
    phenotype_curation: Any,
    pedigree_audit: Any,
    audit_by_candidate: dict[str, list[Any]],
    evidence_by_candidate: dict[str, tuple[CandidateEvidence, ...]],
    source_provenance: tuple[ProvenanceReference, ...],
    request: CandidateAnalysisRequest,
    context_by_candidate: dict[str, CandidateContextInput],
    record_by_candidate: dict[str, Any],
) -> tuple[CandidateAnalysisRecord, list[MissingInformation], list[UnresolvedUncertainty], ExclusionTrace | None]:
    missing: list[MissingInformation] = []
    unresolved: list[UnresolvedUncertainty] = []
    source_record_id = str(record.record_id)
    case_candidate = next((item for item in case.candidate_variants if item.candidate_id == candidate_id), None)
    source_identity = _source_identity(record, gateway)
    gene = source_identity.gene
    transcript = source_identity.transcript
    source_provenance = tuple(_merge_provenance(source_provenance, context.provenance))
    phenotype = _phenotype_match(case, context, request, phenotype_curation, source_provenance)
    inheritance, family_observations, family_missing, family_unresolved = _inheritance_summary(
        case=case,
        candidate_id=candidate_id,
        context=context,
        record=record,
        gateway=gateway,
        pedigree_audit=pedigree_audit,
        audit_records=audit_by_candidate.get(candidate_id, []),
        request=request,
        provenance=source_provenance,
        context_by_candidate=context_by_candidate,
        record_by_candidate=record_by_candidate,
    )
    missing.extend(family_missing)
    unresolved.extend(family_unresolved)
    if gene is None:
        missing.append(_missing(candidate_id, "gene_context", "Gene context was not supplied for this source record.", source_provenance))
    if transcript is None:
        missing.append(_missing(candidate_id, "transcript_context", "Transcript context was not supplied; no transcript selection is performed.", source_provenance))
    frequency = _frequency_context(context, source_provenance)
    if context.population_frequency is None:
        missing.append(_missing(candidate_id, "population_frequency", "Population frequency was not supplied; absence from a population dataset is not treated as negative evidence.", source_provenance))
    consequence = ConsequenceContext(
        consequence_supplied=context.consequence,
        transcript_relevance=_state_from_literal(context.transcript_relevance),
        explanation=(
            "Supplied consequence context is retained as review evidence only."
            if context.consequence
            else "Consequence context was not supplied; no external annotation was retrieved."
        ),
        provenance=source_provenance,
    )
    quality, coverage, retained_trace, quality_missing, quality_unresolved = _quality_coverage_assay(
        candidate_id=candidate_id,
        context=context,
        record=record,
        gateway=gateway,
        gene=gene,
        provenance=source_provenance,
    )
    missing.extend(quality_missing)
    unresolved.extend(quality_unresolved)
    supporting = evidence_by_candidate.get(candidate_id, ())
    contradicting = tuple(item for item in supporting if item.role == EvidenceRole.CONTRADICTING)
    supporting = tuple(item for item in supporting if item.role == EvidenceRole.SUPPORTING)
    missing_evidence = tuple(item for item in evidence_by_candidate.get(candidate_id, ()) if item.role == EvidenceRole.MISSING)
    unresolved_evidence = tuple(item for item in evidence_by_candidate.get(candidate_id, ()) if item.role == EvidenceRole.UNRESOLVED)
    if not supporting and not contradicting and not missing_evidence and not unresolved_evidence:
        missing.append(_missing(candidate_id, "candidate_evidence", "No supplied supporting or contradicting evidence was linked to this candidate.", source_provenance))
    missing.extend(
        _missing(candidate_id, "evidence", item.statement, (item.source,))
        for item in missing_evidence
    )
    unresolved.extend(
        _uncertainty(candidate_id, item.evidence_id, "evidence", item.statement, "The supplied evidence is unresolved and requires human review.", (item.source,))
        for item in unresolved_evidence
    )
    components = _ranking_components(
        phenotype=phenotype,
        inheritance=inheritance,
        frequency=frequency,
        consequence=consequence,
        context=context,
        record=record,
        quality=quality,
        coverage=coverage,
        supporting_count=len(supporting),
        contradicting_count=len(contradicting),
        missing_count=len(missing),
        unresolved_count=len(unresolved),
        provenance=source_provenance,
    )
    score = round(sum(item.numerical_contribution or 0.0 for item in components), 6)
    status = (
        CandidateReviewStatus.RETAINED_NOT_ASSESSED_FOR_REVIEW
        if any(item.state in {ComponentState.MISSING, ComponentState.NOT_ASSESSED} for item in components)
        and not any(item.state == ComponentState.POSITIVE for item in components)
        else CandidateReviewStatus.RETAINED_WEAK_FOR_REVIEW
    )
    record_model = CandidateAnalysisRecord(
        candidate_identity=CandidateIdentity(
            candidate_id=candidate_id,
            stable_candidate_id=stable_candidate_id(source_identity),
            source_record=source_identity,
            supplied_candidate_id=(candidate_id if case_candidate else None),
            supplied_representation=(case_candidate.submitted_representation if case_candidate else None),
        ),
        gene_transcript_context=GeneTranscriptContext(
            gene=gene,
            transcript=transcript,
            supplied_gene=context.gene,
            supplied_transcript=context.transcript,
            consequence=context.consequence,
            transcript_relevance=_state_from_literal(context.transcript_relevance),
            gene_disease_validity=_validity_state(context.gene_disease_validity),
            validity_label_supplied=context.gene_disease_validity,
            provenance=source_provenance,
        ),
        variant_genotype_context=_variant_context(record, context),
        phenotype_match=phenotype,
        inheritance_compatibility=inheritance,
        frequency_context=frequency,
        consequence_context=consequence,
        quality_coverage_assay=quality_coverage_assay_model(quality, coverage),
        supporting_evidence=tuple(supporting),
        contradicting_evidence=tuple(contradicting),
        missing_information=tuple(_dedupe_missing(missing)),
        unresolved_uncertainties=tuple(_dedupe_uncertainties(unresolved)),
        family_segregation_observations=tuple(family_observations),
        ranking_components=tuple(components),
        aggregate_score=score,
        deterministic_rank=None,
        tied=False,
        tie_break_explanation="Rank and tie status are assigned after all candidates are evaluated.",
        review_status=status,
        exclusion_history=((retained_trace,) if retained_trace else ()),
    )
    return record_model, _dedupe_missing(missing), _dedupe_uncertainties(unresolved), retained_trace


def quality_coverage_assay_model(quality: QualityCoverageAssayContext, coverage: QualityCoverageAssayContext) -> QualityCoverageAssayContext:
    """Merge quality and scope findings into one immutable public context."""

    return QualityCoverageAssayContext(
        variant_quality_state=quality.variant_quality_state,
        qc_state=quality.qc_state,
        coverage_state=coverage.coverage_state,
        assay_scope_state=coverage.assay_scope_state,
        poor_coverage_region_ids=coverage.poor_coverage_region_ids,
        outside_reportable_range=coverage.outside_reportable_range,
        assay_blind_spot_ids=coverage.assay_blind_spot_ids,
        warnings=tuple(sorted(set((*quality.warnings, *coverage.warnings)))),
        explanation=coverage.explanation if coverage.explanation != "not_assessed" else quality.explanation,
        provenance=tuple(_merge_provenance(quality.provenance, coverage.provenance)),
    )


def _ranking_components(
    *,
    phenotype: PhenotypeMatchSummary,
    inheritance: InheritanceCompatibilitySummary,
    frequency: FrequencyContext,
    consequence: ConsequenceContext,
    context: CandidateContextInput,
    record: Any,
    quality: QualityCoverageAssayContext,
    coverage: QualityCoverageAssayContext,
    supporting_count: int,
    contradicting_count: int,
    missing_count: int,
    unresolved_count: int,
    provenance: tuple[ProvenanceReference, ...],
) -> list[CandidateRankingComponent]:
    components: list[CandidateRankingComponent] = []
    phenotype_state = ComponentState.POSITIVE if phenotype.exact_hpo_ids else ComponentState.NEUTRAL if phenotype.related_hpo_ids else ComponentState.MISSING if phenotype.matched_term_count == 0 and not context.phenotype_hpo_ids else ComponentState.NEUTRAL
    phenotype_value = (1.0 if phenotype.exact_hpo_ids else 0.5 if phenotype.related_hpo_ids else -0.5 if phenotype.negated_hpo_ids else 0.0) if phenotype_state != ComponentState.MISSING else None
    components.append(_component("phenotype_match", phenotype_state, phenotype_value, f"exact={len(phenotype.exact_hpo_ids)};related={len(phenotype.related_hpo_ids)};negated={len(phenotype.negated_hpo_ids)}", "Exact HPO IDs score above pinned supplied relations; negated supplied HPO observations are visible contradictions, not disease absence.", provenance, "Supplied HPO match summary was evaluated deterministically."))
    specificity_state = phenotype.specificity_state
    specificity_value = phenotype.specificity_value_supplied if specificity_state == ComponentState.POSITIVE else 0.0 if specificity_state == ComponentState.NEUTRAL else None
    components.append(_component("phenotype_specificity", specificity_state, specificity_value, str(phenotype.specificity_value_supplied if phenotype.specificity_value_supplied is not None else "not_supplied"), "A supplied specificity score is used only when present; no ontology depth is inferred.", provenance, "Phenotype specificity is supplied or not assessed."))
    onset_state = phenotype.onset_state
    onset_value = 1.0 if onset_state == ComponentState.POSITIVE else -1.0 if onset_state == ComponentState.NEGATIVE else 0.0 if onset_state == ComponentState.NEUTRAL else None
    components.append(_component("onset_compatibility", onset_state, onset_value, context.onset_compatibility, "Use the supplied onset compatibility state only.", provenance, "Supplied age-of-onset context is preserved."))
    inheritance_value = 1.0 if inheritance.state == ComponentState.POSITIVE else -1.0 if inheritance.state == ComponentState.NEGATIVE else 0.0 if inheritance.state == ComponentState.NEUTRAL else None
    components.append(_component("inheritance_compatibility", inheritance.state, inheritance_value, inheritance.deterministic_compatibility, "Bounded supplied-record inheritance compatibility; no relationship inference.", inheritance.provenance or provenance, inheritance.explanation))
    segregation_state = inheritance.segregation_state
    segregation_value = 1.0 if segregation_state == ComponentState.POSITIVE else -1.0 if segregation_state == ComponentState.NEGATIVE else 0.0 if segregation_state == ComponentState.NEUTRAL else None
    components.append(_component("segregation", segregation_state, segregation_value, segregation_state.value, "Use supplied or deterministically supported segregation observations only.", inheritance.provenance or provenance, "Segregation is review evidence and is not assigned ACMG strength."))
    frequency_state, frequency_value = _frequency_score(frequency)
    components.append(_component("frequency", frequency_state, frequency_value, str(frequency.frequency_supplied if frequency.frequency_supplied is not None else "not_supplied"), "Rare/common context is a prioritization signal only; no population dataset absence is negative evidence.", frequency.provenance or provenance, frequency.explanation))
    consequence_state, consequence_value = _consequence_score(consequence.consequence_supplied)
    components.append(_component("consequence", consequence_state, consequence_value, consequence.consequence_supplied or "not_supplied", "Use supplied consequence text only; do not convert it to pathogenicity.", consequence.provenance or provenance, consequence.explanation))
    transcript_state = _state_from_literal(context.transcript_relevance)
    transcript_value = 1.0 if transcript_state == ComponentState.POSITIVE else -1.0 if transcript_state == ComponentState.NEGATIVE else 0.0 if transcript_state == ComponentState.NEUTRAL else None
    components.append(_component("transcript_relevance", transcript_state, transcript_value, context.transcript_relevance, "Use supplied transcript relevance only; no transcript selection is performed.", provenance, "Transcript relevance remains supplied or not assessed."))
    validity_state = _validity_state(context.gene_disease_validity)
    validity_value = 1.0 if context.gene_disease_validity == "established" else 0.3 if context.gene_disease_validity == "limited" else -1.0 if context.gene_disease_validity == "conflicting" else None
    components.append(_component("gene_disease_validity", validity_state, validity_value, context.gene_disease_validity, "Use supplied gene-disease validity context only; no external retrieval.", provenance, "Gene-disease validity is context for review, not a final conclusion."))
    quality_state = quality.variant_quality_state
    quality_value = 1.0 if quality_state == ComponentState.POSITIVE else -1.0 if quality_state == ComponentState.NEGATIVE else 0.0 if quality_state == ComponentState.NEUTRAL else None
    components.append(_component("variant_quality", quality_state, quality_value, str(getattr(record, "filter_status", None) or getattr(record, "quality", None) or "not_supplied"), "Use supplied VCF quality/filter fields only.", quality.provenance or provenance, quality.explanation))
    qc_state = quality.qc_state
    qc_value = 1.0 if qc_state == ComponentState.POSITIVE else -1.0 if qc_state == ComponentState.NEGATIVE else 0.0 if qc_state == ComponentState.NEUTRAL else None
    components.append(_component("qc", qc_state, qc_value, qc_state.value, "QC warnings reduce certainty but never prove disease absence.", quality.provenance or provenance, quality.explanation))
    coverage_state = coverage.coverage_state if not coverage.outside_reportable_range else ComponentState.NOT_ASSESSED
    coverage_value = 1.0 if coverage_state == ComponentState.POSITIVE else -1.0 if coverage_state == ComponentState.NEGATIVE else 0.0 if coverage_state == ComponentState.NEUTRAL else None
    components.append(_component("coverage_assay_scope", coverage_state, coverage_value, f"coverage={coverage.coverage_state.value};assay={coverage.assay_scope_state.value}", "Poor coverage and assay scope limitations are not false negative evidence.", coverage.provenance or provenance, coverage.explanation))
    support_state = ComponentState.POSITIVE if supporting_count else ComponentState.MISSING
    support_value = min(1.0, supporting_count / 2.0) if supporting_count else None
    components.append(_component("supporting_evidence", support_state, support_value, f"supplied_count={supporting_count}", "Count linked supplied supporting evidence with visible provenance.", provenance, "Supporting evidence remains candidate-only and requires human review."))
    contradiction_state = ComponentState.NEGATIVE if contradicting_count else ComponentState.NEUTRAL
    contradiction_value = -min(1.0, contradicting_count / 2.0) if contradicting_count else 0.0
    components.append(_component("contradicting_evidence", contradiction_state, contradiction_value, f"supplied_count={contradicting_count}", "Retain linked contradictory evidence visibly and subtract only its bounded ranking contribution.", provenance, "Contradictions remain visible for reviewer comparison."))
    components.append(_component("missing_information", ComponentState.MISSING if missing_count else ComponentState.NEUTRAL, None if missing_count else 0.0, f"missing_count={missing_count}", "Missing information has no numerical contribution.", provenance, "Missing information is displayed rather than converted into absence."))
    components.append(_component("unresolved_uncertainty", ComponentState.NOT_ASSESSED if unresolved_count else ComponentState.NEUTRAL, None if unresolved_count else 0.0, f"unresolved_count={unresolved_count}", "Unresolved uncertainty has no numerical contribution.", provenance, "Unresolved questions remain explicit for human review."))
    return components


def _component(component_id: str, state: ComponentState, value: float | None, supplied: str, rule: str, provenance: Iterable[ProvenanceReference], explanation: str) -> CandidateRankingComponent:
    calculation = calculate_candidate_component(
        component_version=CANDIDATE_RANKING_RULE_VERSION,
        component_id=component_id,
        state=state,
        normalized_value=value,
    )
    return CandidateRankingComponent(
        component_id=component_id,
        component_version=CANDIDATE_RANKING_RULE_VERSION,
        display_name=component_id.replace("_", " "),
        supplied_input=supplied[:4000],
        normalized_input=(supplied[:4000] if supplied else None),
        deterministic_rule=rule[:2000],
        state=state,
        normalized_value=value,
        raw_contribution=calculation.raw_contribution,
        numerical_contribution=calculation.weighted_contribution,
        weight=COMPONENT_WEIGHTS[component_id],
        source=tuple(provenance),
        explanation=explanation[:3000],
    )


def _ranking_rule(request: CandidateAnalysisRequest) -> CandidateRankingRule:
    weights = tuple(
        ComponentWeight(
            component_id=component_id,
            component_version=CANDIDATE_RANKING_RULE_VERSION,
            weight=weight,
            priority=index,
            rationale=COMPONENT_RATIONALES[component_id],
        )
        for index, (component_id, weight) in enumerate(COMPONENT_WEIGHTS.items(), start=1)
    )
    filtering = (
        FilteringRule(
            rule_id="supported_variant_scope",
            rule_version=CANDIDATE_RANKING_RULE_VERSION,
            rule="variant_scope in {snv, small_indel}",
            outcome="exclude",
            explanation="Retain out-of-scope records and their v0.36 reasons without interpreting them.",
        ),
        FilteringRule(
            rule_id="assay_reportable_scope",
            rule_version=CANDIDATE_RANKING_RULE_VERSION,
            rule="supplied gene is in supplied reportable_genes when reportable_genes is non-empty",
            outcome="exclude",
            explanation="Outside-reportable-range records are excluded from ranking but are not disease-negative evidence.",
        ),
        FilteringRule(
            rule_id="candidate_context_exclusion",
            rule_version=CANDIDATE_RANKING_RULE_VERSION,
            rule="explicit candidate context exclusion_rule_id and exclusion_rule_version are required",
            outcome="exclude",
            explanation="An explicit versioned review rule can exclude a candidate while retaining its complete trace.",
        ),
    )
    return CandidateRankingRule(
        support_threshold=CANDIDATE_FIXED_SUPPORT_THRESHOLD,
        tie_epsilon=CANDIDATE_FIXED_TIE_EPSILON,
        component_weights=weights,
        filtering_rules=filtering,
    )


def _assign_ranks(records: list[CandidateAnalysisRecord], request: CandidateAnalysisRequest) -> list[CandidateAnalysisRecord]:
    ordered = sorted(
        records,
        key=lambda item: (
            -(item.aggregate_score if item.aggregate_score is not None else float("-inf")),
            item.candidate_identity.candidate_id,
            item.candidate_identity.source_record.source_record_id,
        ),
    )
    epsilon = CANDIDATE_FIXED_TIE_EPSILON
    result: list[CandidateAnalysisRecord] = []
    index = 0
    while index < len(ordered):
        anchor_score = ordered[index].aggregate_score
        end = index + 1
        while end < len(ordered) and anchor_score is not None and ordered[end].aggregate_score is not None and abs(anchor_score - ordered[end].aggregate_score) <= epsilon:
            end += 1
        group = ordered[index:end]
        rank = index + 1
        tie_group_id = (
            safe_candidate_id(
                "tie-group",
                CANDIDATE_RANKING_RULE_VERSION,
                round(anchor_score or 0.0, 6),
                tuple(item.candidate_identity.candidate_id for item in group),
            )
            if len(group) > 1
            else None
        )
        for item in group:
            score = item.aggregate_score
            tied = len(group) > 1
            status = item.review_status
            if score is not None and score >= CANDIDATE_FIXED_SUPPORT_THRESHOLD:
                status = CandidateReviewStatus.RANKED_FOR_REVIEW
            tie_explanation = (
                "This candidate belongs to a deterministic tie group; all members share the competition rank, and candidate ID order is used only for stable presentation."
                if tied
                else "No deterministic score tie was detected for this candidate."
            )
            result.append(item.model_copy(update={"deterministic_rank": rank, "tied": tied, "tie_group_id": tie_group_id, "tie_break_explanation": tie_explanation, "review_status": status}))
        index = end
    return result


def _source_identity(record: Any, gateway: Any) -> CandidateSourceRecordIdentity:
    gene, transcript = _source_gene_transcript(record)
    gateway_record_id = str(record.record_id)
    source_record_key = str(getattr(record, "source_record_id", record.record_id))
    return CandidateSourceRecordIdentity(
        gateway_record_id=gateway_record_id,
        source_record_id=gateway_record_id,
        source_record_key=source_record_key,
        package_id=str(getattr(gateway, "package_id", "missing-v036-package")),
        package_version=str(getattr(gateway, "package_version", "not_available")),
        package_identity_sha256=str(getattr(gateway, "package_identity_sha256", sha256_hex("missing-package"))),
        manifest_identity_sha256=str(getattr(gateway, "input_manifest_sha256", sha256_hex("missing-manifest"))),
        invocation_identity_sha256=_invocation_identity_for_record(record, gateway),
        source_record_sha256=str(record.source_record_sha256),
        source_file=str(record.source_file),
        chromosome=str(record.chromosome),
        position=int(record.position),
        reference_allele=str(record.reference_allele),
        alternate_allele=str(record.alternate_allele),
        variant_scope=_variant_scope(record),
        source_alt_index=int(getattr(record, "source_alt_index", 1)),
        gene=gene,
        transcript=transcript,
    )


def _out_of_scope_identity(record: Any, gateway: Any, candidate_id: str) -> CandidateIdentity:
    source_identity = _source_identity(record, gateway)
    canonical_id = canonical_candidate_id(source_identity)
    return CandidateIdentity(
        candidate_id=canonical_id,
        stable_candidate_id=stable_candidate_id(source_identity),
        source_record=source_identity,
        supplied_candidate_id=(candidate_id if candidate_id != canonical_id else None),
    )


def _invocation_identity_for_record(record: Any, gateway: Any) -> str:
    record_id = str(getattr(record, "record_id", ""))
    matching = sorted(
        str(item.invocation_sha256)
        for item in getattr(gateway, "tool_provenance", ()) or ()
        if record_id in {str(value) for value in getattr(item, "selected_record_ids", ()) or ()}
        and getattr(item, "invocation_sha256", None)
    )
    if matching:
        return sha256_hex({"record_id": record_id, "invocation_sha256": matching})
    return sha256_hex({"record_id": record_id, "invocation_sha256": "not_supplied"})


def _source_gene_transcript(record: Any) -> tuple[str | None, str | None]:
    values = {
        str(getattr(item, "key", "")).casefold(): str(getattr(item, "value", ""))
        for item in getattr(record, "supplied_annotations", ()) or ()
    }
    gene = values.get("gene") or values.get("gene_symbol") or values.get("gene_id")
    transcript = values.get("transcript") or values.get("transcript_id") or values.get("tx")
    csq = values.get("csq")
    if csq and (gene is None or transcript is None):
        first = csq.split(",", 1)[0]
        parts = [item.strip() for item in first.split("|")]
        if len(parts) >= 2:
            gene = gene or parts[0] or None
            transcript = transcript or parts[1] or None
    return gene, transcript


def _source_binding_error(
    context: CandidateContextInput,
    record: Any,
    source_identity: CandidateSourceRecordIdentity,
    expected_candidate_id: str,
) -> str | None:
    mismatches: list[str] = []
    if context.source_record_id != source_identity.gateway_record_id:
        mismatches.append("source record ID does not match the v0.36 gateway record")
    if context.candidate_id != expected_candidate_id:
        mismatches.append("candidate ID is not the domain-separated canonical ID for this source binding")
    assertions = (
        ("source_record_sha256", context.source_record_sha256, source_identity.source_record_sha256),
        ("chromosome", context.chromosome, source_identity.chromosome),
        ("position", context.position, source_identity.position),
        ("reference allele", context.reference_allele, source_identity.reference_allele),
        ("alternate allele", context.alternate_allele, source_identity.alternate_allele),
        ("source ALT index", context.source_alt_index, source_identity.source_alt_index),
    )
    for label, supplied, expected in assertions:
        if supplied is not None and supplied != expected:
            mismatches.append(f"{label} does not match the v0.36 source record")
    if context.gene is not None and context.gene != source_identity.gene:
        mismatches.append("candidate gene does not match the source annotation")
    if context.transcript is not None and context.transcript != source_identity.transcript:
        mismatches.append("candidate transcript does not match the source annotation")
    if source_identity.gene is None and context.gene is not None:
        mismatches.append("the source record has no gene annotation from which a caller-supplied gene can be accepted")
    if source_identity.transcript is None and context.transcript is not None:
        mismatches.append("the source record has no transcript annotation from which a caller-supplied transcript can be accepted")
    return "; ".join(dict.fromkeys(mismatches)) or None


def _variant_scope(record: Any) -> CandidateVariantScope:
    value = getattr(getattr(record, "variant_scope", None), "value", getattr(record, "variant_scope", "unknown"))
    try:
        return CandidateVariantScope(str(value))
    except ValueError:
        return CandidateVariantScope.UNKNOWN


def _variant_context(record: Any, context: CandidateContextInput) -> VariantGenotypeContext:
    sample_names = tuple(str(item.sample_name) for item in getattr(record, "sample_calls", ()) or ())
    zygosity = context.zygosity
    phase_state = "unknown"
    if not zygosity:
        for call in getattr(record, "sample_calls", ()) or ():
            genotype = getattr(call, "genotype", None)
            if genotype is None:
                continue
            allele_indices = [item for item in genotype.allele_indices if item is not None]
            alt_index = int(getattr(record, "source_alt_index", 1))
            alt_count = allele_indices.count(alt_index)
            if genotype.ploidy == 1 and alt_count:
                zygosity = "hemizygous"
            elif alt_count == genotype.ploidy and alt_count:
                zygosity = "homozygous"
            elif alt_count:
                zygosity = "heterozygous"
            else:
                zygosity = "absent_or_unknown"
            phase_state = getattr(getattr(genotype, "phase_state", None), "value", "unknown")
            break
    return VariantGenotypeContext(
        chromosome=str(record.chromosome),
        position=int(record.position),
        reference_allele=str(record.reference_allele),
        alternate_allele=str(record.alternate_allele),
        variant_scope=_variant_scope(record),
        sample_names=sample_names,
        zygosity=zygosity,
        phase_state=phase_state,
        quality=getattr(record, "quality", None),
        filter_status=getattr(record, "filter_status", None),
        source_state="supplied",
    )


def _phenotype_match(case: ClinicalCaseIntake, context: CandidateContextInput, request: CandidateAnalysisRequest, phenotype_curation: Any, provenance: tuple[ProvenanceReference, ...]) -> PhenotypeMatchSummary:
    present = {str(item.hpo_id) for item in case.phenotypes if item.hpo_id and str(item.state.value if hasattr(item.state, "value") else item.state) in {"present", "resolved"}}
    absent = {str(item.hpo_id) for item in case.phenotypes if item.hpo_id and str(item.state.value if hasattr(item.state, "value") else item.state) == "absent"}
    if phenotype_curation is not None:
        present.update(str(item.hpo_id) for item in getattr(phenotype_curation, "promoted_observations", ()) or () if getattr(item, "hpo_id", None))
    candidate_hpos = set(context.phenotype_hpo_ids)
    exact = sorted(present & candidate_hpos)
    negated = sorted(absent & candidate_hpos)
    related: set[str] = set()
    relation_provenance: list[ProvenanceReference] = list(provenance)
    for relation in request.phenotype_relations:
        if (relation.source_hpo_id in present and relation.target_hpo_id in candidate_hpos) or (relation.target_hpo_id in present and relation.source_hpo_id in candidate_hpos):
            related.add(relation.target_hpo_id if relation.target_hpo_id in candidate_hpos else relation.source_hpo_id)
            relation_provenance.append(
                ProvenanceReference(source_id=relation.source_id, source_type=relation.source_type, source_version=relation.ontology_version)
            )
    specificity_state = ComponentState.POSITIVE if context.phenotype_specificity_score is not None and context.phenotype_specificity_score > 0 else ComponentState.MISSING
    onset_state = _state_from_literal(context.onset_compatibility)
    if not present:
        explanation = "No curated or supplied HPO terms were available for matching."
    elif not candidate_hpos:
        explanation = "Candidate phenotype context was not supplied; no phenotype match is inferred."
    elif exact:
        explanation = f"Exact supplied HPO identifiers matched: {', '.join(exact)}."
    elif related:
        explanation = f"Related supplied HPO identifiers matched only through pinned ontology relation records: {', '.join(sorted(related))}."
    elif negated:
        explanation = f"Supplied absent HPO identifiers overlap candidate context: {', '.join(negated)}; this is a review contradiction, not proof of disease absence."
    else:
        explanation = "No exact or pinned-related HPO identifier matched the supplied candidate phenotype context."
    return PhenotypeMatchSummary(
        exact_hpo_ids=tuple(exact),
        related_hpo_ids=tuple(sorted(related)),
        negated_hpo_ids=tuple(negated),
        specificity_state=specificity_state,
        specificity_value_supplied=context.phenotype_specificity_score,
        onset_state=onset_state,
        matched_term_count=len(exact) + len(related),
        explanation=explanation,
        provenance=tuple(_merge_provenance(provenance, relation_provenance)),
    )


def _inheritance_summary(*, case: ClinicalCaseIntake, candidate_id: str, context: CandidateContextInput, record: Any, gateway: Any, pedigree_audit: Any, audit_records: list[Any], request: CandidateAnalysisRequest, provenance: tuple[ProvenanceReference, ...], context_by_candidate: dict[str, CandidateContextInput], record_by_candidate: dict[str, Any]) -> tuple[InheritanceCompatibilitySummary, list[FamilySegregationObservation], list[MissingInformation], list[UnresolvedUncertainty]]:
    observations: list[FamilySegregationObservation] = []
    missing: list[MissingInformation] = []
    unresolved: list[UnresolvedUncertainty] = []
    audit_status: str | None = None
    audit_supporting: list[str] = []
    for audit in audit_records:
        audit_status = getattr(getattr(audit, "status", None), "value", getattr(audit, "status", None))
        audit_supporting.extend(str(item) for item in getattr(audit, "supporting_record_ids", ()) or ())
    audit_status = audit_status or _audit_status_for_case_candidate(pedigree_audit, candidate_id)
    inheritance_state = {
        InheritanceAuditStatus.CONSISTENT.value: ComponentState.POSITIVE,
        InheritanceAuditStatus.PARTIALLY_CONSISTENT.value: ComponentState.NEUTRAL,
        InheritanceAuditStatus.INCONSISTENT.value: ComponentState.NEGATIVE,
        InheritanceAuditStatus.MISSING_EVIDENCE.value: ComponentState.MISSING,
        InheritanceAuditStatus.CANNOT_EVALUATE.value: ComponentState.NOT_ASSESSED,
    }.get(str(audit_status), ComponentState.NOT_ASSESSED)
    supplied_statements = (
        ()
        if context.inheritance_context_state == "missing"
        else tuple(context.supplied_inheritance) or _supplied_inheritance_statements(case)
    )
    statement_state = InheritanceStatementState.SUPPLIED_INHERITANCE if supplied_statements else InheritanceStatementState.NOT_SUPPLIED
    supplied_phase = context.supplied_phase
    phase = _phase_for_candidate(pedigree_audit, candidate_id)
    if phase == PhaseEvaluation.NOT_ASSESSED:
        phase = supplied_phase
        if phase == PhaseEvaluation.CONFIRMED_TRANS:
            phase = PhaseEvaluation.SUPPLIED_TRANS
    de_novo = DeNovoState.SUPPLIED_DE_NOVO if context.supplied_de_novo is True else DeNovoState.NOT_ASSESSED
    if context.supplied_de_novo is False:
        de_novo = DeNovoState.INSUFFICIENT_INFORMATION
    observations = _family_observations(case, candidate_id, record, gateway, request, phase, de_novo, provenance)
    observations = [
        item.model_copy(update={"supplied_inheritance_state": statement_state})
        for item in observations
    ]
    deterministic_de_novo = _deterministic_de_novo(case, candidate_id, record, observations, request, gateway)
    if deterministic_de_novo:
        de_novo = DeNovoState.DETERMINISTICALLY_SUPPORTED_DE_NOVO
        observations = [
            item.model_copy(update={"supplied_de_novo_state": de_novo})
            for item in observations
        ]
    elif supplied_statements and any("de_novo" in item.casefold() for item in supplied_statements) and not deterministic_de_novo:
        de_novo = DeNovoState.INSUFFICIENT_INFORMATION
        unresolved.append(_uncertainty(candidate_id, "de-novo-prerequisites", "family_segregation", "Supplied de novo language is retained, but deterministic prerequisites are incomplete.", "Required parent genotypes, bindings, and quality states were not all available.", provenance))
    if phase == PhaseEvaluation.PHASE_UNKNOWN:
        unresolved.append(_uncertainty(candidate_id, "phase-unknown", "phase", "Phase is unknown for this candidate.", "The supplied records do not establish cis/trans phase.", provenance))
    missing_relatives = _missing_relative_ids(case, request)
    low_quality = tuple(sorted({item.family_member_id for item in observations if item.genotype_quality_state in {ComponentState.NEGATIVE, ComponentState.MISSING, ComponentState.NOT_ASSESSED} and item.sample_name}))
    x_linked_state = _state_from_literal(context.x_linked_compatibility)
    segregation_state = _segregation_state(observations)
    if not observations and len(case.pedigree) <= 1:
        missing.append(_missing(candidate_id, "family_segregation", "Singleton or no family observations were supplied; segregation was not assessed.", provenance))
    if missing_relatives:
        missing.append(_missing(candidate_id, "missing_family_samples", f"Missing relative/sample records remain unknown: {', '.join(missing_relatives)}.", provenance))
    if context.inheritance_context_state == "missing":
        missing.append(_missing(candidate_id, "inheritance_statement", "A candidate-specific inheritance statement was not supplied.", provenance))
    if low_quality:
        unresolved.append(_uncertainty(candidate_id, "low-quality-family-genotypes", "family_segregation", f"Family genotype quality is inadequate or unavailable for: {', '.join(low_quality)}.", "Low-quality family genotypes are not treated as incompatible.", provenance))
    expected_package_id = getattr(gateway, "package_id", None)
    mismatched_bindings = tuple(sorted(
        item.family_member_id
        for item in request.family_sample_bindings
        if expected_package_id is not None and item.package_id != expected_package_id
    ))
    if mismatched_bindings:
        unresolved.append(_uncertainty(candidate_id, "family-sample-binding-package", "family_sample_binding", f"Family sample bindings do not all point to the supplied result package: {', '.join(mismatched_bindings)}.", "Deterministic de novo support requires package-aligned sample bindings.", provenance))
    contradiction_codes = tuple(sorted({"inheritance_audit_inconsistent" for item in audit_records if str(getattr(getattr(item, "status", None), "value", getattr(item, "status", ""))) == InheritanceAuditStatus.INCONSISTENT.value}))
    compound_state, compound_partner, compound_pair_identity, compound_error = _validated_compound_pair(
        candidate_id=candidate_id,
        context=context,
        record=record,
        gateway=gateway,
        context_by_candidate=context_by_candidate,
        record_by_candidate=record_by_candidate,
        pedigree_audit=pedigree_audit,
        supplied_statements=supplied_statements,
        missing_relative_ids=missing_relatives,
        low_quality_member_ids=low_quality,
    )
    if compound_error:
        unresolved.append(
            _uncertainty(
                candidate_id,
                "invalid-compound-pair",
                "compound_heterozygosity",
                "The supplied compound-heterozygous pairing was not accepted as deterministic evidence.",
                compound_error,
                provenance,
            )
        )
    explanation = _inheritance_explanation(
        inheritance_state,
        statement_state,
        de_novo,
        phase,
        segregation_state,
        missing_relatives,
        low_quality,
        x_linked_state,
        compound_state,
        compound_partner,
    )
    summary = InheritanceCompatibilitySummary(
        state=inheritance_state,
        x_linked_state=x_linked_state,
        supplied_inheritance_statements=supplied_statements,
        deterministic_compatibility=str(audit_status or "not_assessed"),
        segregation_state=segregation_state,
        de_novo_state=de_novo,
        phase_state=phase,
        compound_heterozygosity_state=compound_state,
        compound_partner_candidate_id=compound_partner,
        missing_relative_ids=missing_relatives,
        low_quality_member_ids=low_quality,
        contradiction_codes=contradiction_codes,
        explanation=explanation,
        provenance=provenance,
        compound_pair_identity=compound_pair_identity,
    )
    return summary, observations, _dedupe_missing(missing), _dedupe_uncertainties(unresolved)


def _validated_compound_pair(
    *,
    candidate_id: str,
    context: CandidateContextInput,
    record: Any,
    gateway: Any,
    context_by_candidate: dict[str, CandidateContextInput],
    record_by_candidate: dict[str, Any],
    pedigree_audit: Any,
    supplied_statements: tuple[str, ...],
    missing_relative_ids: tuple[str, ...] = (),
    low_quality_member_ids: tuple[str, ...] = (),
) -> tuple[PhaseEvaluation, str | None, str | None, str | None]:
    partner_id = context.compound_heterozygosity_partner_candidate_id
    requested = bool(partner_id) or any("compound" in item.casefold() for item in supplied_statements)
    if not requested:
        return PhaseEvaluation.NOT_ASSESSED, None, None, None
    if not partner_id:
        return PhaseEvaluation.INSUFFICIENT_INFORMATION, None, None, "compound pairing requires an explicit partner candidate ID"
    if partner_id == candidate_id:
        return PhaseEvaluation.INSUFFICIENT_INFORMATION, partner_id, None, "a compound pair must contain two distinct canonical candidate IDs"
    partner_context = context_by_candidate.get(partner_id)
    partner_record = record_by_candidate.get(partner_id)
    if partner_context is None or partner_record is None:
        return PhaseEvaluation.INSUFFICIENT_INFORMATION, partner_id, None, "compound partner is not a valid source-bound candidate in the same analysis"
    current_key = _canonical_source_allele_key(record, gateway)
    partner_key = _canonical_source_allele_key(partner_record, gateway)
    if current_key == partner_key:
        return PhaseEvaluation.INSUFFICIENT_INFORMATION, partner_id, None, "compound pair members resolve to the same source allele"
    current_gene, _ = _source_gene_transcript(record)
    partner_gene, _ = _source_gene_transcript(partner_record)
    # A v0.36 record may lack an annotation while the v0.37 request still
    # supplies an explicit same-gene review context.  This context is used
    # only for the compound-pair compatibility check; it never rewrites the
    # canonical source identity or candidate ID.
    current_gene = current_gene or context.compound_gene_context
    partner_gene = partner_gene or partner_context.compound_gene_context
    if not current_gene or not partner_gene:
        return PhaseEvaluation.INSUFFICIENT_INFORMATION, partner_id, None, "compound pairing requires gene context on both source-bound candidates"
    if current_gene.casefold() != partner_gene.casefold():
        return PhaseEvaluation.INSUFFICIENT_INFORMATION, partner_id, None, "compound pair members do not have the same authoritative source gene"
    phase = context.supplied_phase
    audit_phase = _phase_for_candidate(pedigree_audit, candidate_id)
    if audit_phase in {PhaseEvaluation.CONFIRMED_TRANS, PhaseEvaluation.DETERMINISTICALLY_SUPPORTED_TRANS}:
        phase = audit_phase
    elif phase == PhaseEvaluation.CONFIRMED_TRANS:
        phase = PhaseEvaluation.SUPPLIED_TRANS
    if (
        (missing_relative_ids or low_quality_member_ids)
        and (
            phase in {PhaseEvaluation.CONFIRMED_TRANS, PhaseEvaluation.DETERMINISTICALLY_SUPPORTED_TRANS}
            or context.supplied_phase == PhaseEvaluation.CONFIRMED_TRANS
        )
    ):
        phase = PhaseEvaluation.INSUFFICIENT_INFORMATION
    if phase == PhaseEvaluation.NOT_ASSESSED:
        phase = PhaseEvaluation.INSUFFICIENT_INFORMATION
    pair_identity = safe_candidate_id(
        "compound-pair",
        CANDIDATE_RANKING_RULE_VERSION,
        tuple(sorted((candidate_id, partner_id))),
        tuple(sorted((current_key.model_dump(mode="json"), partner_key.model_dump(mode="json")), key=canonical_json)),
    )
    return phase, partner_id, pair_identity, None


def _canonical_source_allele_key(record: Any, gateway: Any) -> CandidateSourceAlleleKey:
    """Build the complete typed source-allele identity used for pair checks."""

    return CandidateSourceAlleleKey(
        package_id=str(getattr(gateway, "package_id", "missing-v036-package")),
        package_version=str(getattr(gateway, "package_version", "not_available")),
        package_identity_sha256=str(getattr(gateway, "package_identity_sha256", sha256_hex("missing-package"))),
        source_record_id=str(getattr(record, "record_id", "")),
        source_record_key=str(getattr(record, "source_record_id", getattr(record, "record_id", ""))),
        source_record_sha256=str(getattr(record, "source_record_sha256", sha256_hex("missing-source-record"))),
        chromosome=str(getattr(record, "chromosome", "")),
        position=int(getattr(record, "position", 0)),
        reference_allele=str(getattr(record, "reference_allele", "")),
        alternate_allele=str(getattr(record, "alternate_allele", "")),
        source_alt_index=int(getattr(record, "source_alt_index", 1)),
    )
def _family_observations(case: ClinicalCaseIntake, candidate_id: str, record: Any, gateway: Any, request: CandidateAnalysisRequest, phase: PhaseEvaluation, de_novo: DeNovoState, provenance: tuple[ProvenanceReference, ...]) -> list[FamilySegregationObservation]:
    audit_request = getattr(case, "pedigree_inheritance_audit", None)
    supplied = [item for item in (getattr(audit_request, "variant_observations", ()) or ()) if item.candidate_variant_id in {candidate_id, str(getattr(record, "record_id", ""))}]
    member_map = {item.family_member_id: item for item in case.pedigree}
    relationships = list(getattr(audit_request, "relationships", ()) or ())
    relationship_by_member: dict[str, list[Any]] = defaultdict(list)
    for item in relationships:
        relationship_by_member[item.child_member_id].append(item)
        relationship_by_member[item.parent_member_id].append(item)
    bindings = {item.family_member_id: item for item in request.family_sample_bindings}
    result: list[FamilySegregationObservation] = []
    for item in sorted(supplied, key=lambda value: value.observation_id):
        member = member_map.get(item.family_member_id)
        relationship_state = RelationshipObservationState.SUPPLIED_RELATIONSHIP if item.family_member_id in relationship_by_member or (member and member.relationship_to_proband.casefold() == "proband") else RelationshipObservationState.MISSING_RELATIONSHIP
        supplied_presence = getattr(getattr(item, "presence_state", None), "value", getattr(item, "presence_state", "unknown"))
        testing = getattr(getattr(item, "testing_state", None), "value", getattr(item, "testing_state", "unknown"))
        binding = bindings.get(item.family_member_id)
        actual = _actual_sample_observation(record, gateway, binding)
        presence = actual["presence"]
        quality_state = actual["quality_state"]
        observed_gq = actual["observed_gq"]
        selected_alt_index = actual["selected_alt_index"]
        sample_name = actual["sample_name"]
        deterministic = ComponentState.POSITIVE if presence in {"present", "absent"} and quality_state == ComponentState.POSITIVE else ComponentState.NOT_ASSESSED
        if actual["binding_error"]:
            status = FamilyObservationStatus.MISSING
        elif supplied_presence in {"present", "absent"} and presence in {"present", "absent"} and supplied_presence != presence:
            status = FamilyObservationStatus.CONTRADICTORY
        elif deterministic == ComponentState.POSITIVE:
            status = FamilyObservationStatus.COMPATIBLE
        else:
            status = FamilyObservationStatus.NOT_ASSESSED
        relationship_type = None
        if member and member.relationship_to_proband.casefold() != "proband":
            relationship_type = member.relationship_to_proband
        elif member:
            relationship_type = "proband"
        elif any(
            getattr(getattr(edge, "relationship_type", None), "value", "") == "biological_parent"
            for edge in relationship_by_member.get(item.family_member_id, ())
        ):
            relationship_type = "biological_parent"
        observation_provenance = tuple(provenance)
        if binding:
            observation_provenance = tuple(_merge_provenance(
                provenance,
                (
                    ProvenanceReference(
                        source_id=binding.source_id,
                        source_type="supplied_family_sample_binding",
                        source_path=binding.sample_name,
                        package_identity_sha256=(
                            getattr(gateway, "package_identity_sha256", None)
                            if binding.package_id == getattr(gateway, "package_id", None)
                            else None
                        ),
                    ),
                ),
            ))
        result.append(FamilySegregationObservation(
            observation_id=item.observation_id,
            candidate_id=candidate_id,
            source_record_id=str(record.record_id),
            family_member_id=item.family_member_id,
            sample_name=sample_name,
            selected_alt_index=selected_alt_index,
            observed_alt_presence_state=presence if presence in {"present", "absent", "unknown"} else "not_assessed",
            observed_genotype_quality=observed_gq,
            relationship_state=relationship_state,
            relationship_type=relationship_type,
            affected_status=getattr(getattr(member, "affected_status", None), "value", "unknown"),
            presence_state=presence,
            zygosity=getattr(getattr(item, "zygosity", None), "value", "unknown"),
            genotype_quality_state=quality_state,
            supplied_inheritance_state=(InheritanceStatementState.SUPPLIED_INHERITANCE if getattr(case, "hypotheses", None) else InheritanceStatementState.NOT_SUPPLIED),
            deterministic_compatibility=deterministic,
            supplied_de_novo_state=de_novo,
            phase_state=phase,
            compound_heterozygosity_state=phase,
            status=status,
            explanation=(
                "The v0.36 header, selected-ALT presence, and observed GQ meet the fixed family binding contract."
                if status == FamilyObservationStatus.COMPATIBLE
                else "The supplied family observation is retained, but the actual v0.36 sample call or fixed GQ evidence is missing, invalid, or contradictory; it is not converted into absence."
            ),
            provenance=observation_provenance,
        ))
    return result


def _actual_sample_observation(record: Any, gateway: Any, binding: FamilySampleBindingInput | None) -> dict[str, Any]:
    if binding is None:
        return {"binding_error": "family sample binding is missing", "sample_name": None, "presence": "unknown", "quality_state": ComponentState.NOT_ASSESSED, "observed_gq": None, "selected_alt_index": None}
    sample_name = str(binding.sample_name)
    header = getattr(getattr(gateway, "vcf", None), "header", None)
    header_names = {str(item) for item in getattr(header, "sample_names", ()) or ()}
    if sample_name not in header_names:
        return {"binding_error": "sample is absent from the v0.36 VCF header", "sample_name": sample_name, "presence": "unknown", "quality_state": ComponentState.MISSING, "observed_gq": None, "selected_alt_index": None}
    call = next((item for item in getattr(record, "sample_calls", ()) or () if str(item.sample_name) == sample_name), None)
    if call is None:
        return {"binding_error": "sample call is absent for the v0.36 source record", "sample_name": sample_name, "presence": "unknown", "quality_state": ComponentState.MISSING, "observed_gq": None, "selected_alt_index": None}
    alt_index = int(getattr(record, "source_alt_index", 1))
    presence_entry = next((item for item in getattr(record, "selected_alt_presence", ()) or () if str(item.sample_name) == sample_name and int(item.selected_alt_index) == alt_index), None)
    presence = getattr(getattr(presence_entry, "state", None), "value", getattr(presence_entry, "state", "unknown")) if presence_entry else "unknown"
    gq_value: float | None = None
    gq_missing = True
    for value in getattr(call, "format_values", ()) or ():
        if str(getattr(value, "key", "")).casefold() != "gq":
            continue
        token = str(getattr(value, "source_token", ""))
        if not getattr(value, "is_missing", False) and token not in {"", "."}:
            try:
                parsed = float(token)
                if parsed == parsed and parsed not in {float("inf"), float("-inf")}:
                    gq_value = parsed
                    gq_missing = False
            except (TypeError, ValueError):
                gq_missing = False
        break
    if gq_value is None:
        quality_state = ComponentState.MISSING if gq_missing else ComponentState.NOT_ASSESSED
    elif gq_value >= CANDIDATE_FIXED_FAMILY_GQ_THRESHOLD:
        quality_state = ComponentState.POSITIVE
    else:
        quality_state = ComponentState.NEGATIVE
    return {"binding_error": None, "sample_name": sample_name, "presence": presence, "quality_state": quality_state, "observed_gq": gq_value, "selected_alt_index": alt_index}


def _deterministic_de_novo(case: ClinicalCaseIntake, candidate_id: str, record: Any, observations: list[FamilySegregationObservation], request: CandidateAnalysisRequest, gateway: Any) -> bool:
    audit_request = getattr(case, "pedigree_inheritance_audit", None)
    if audit_request is None:
        return False
    proband_id = str(audit_request.proband_member_id)
    parents = [item.parent_member_id for item in getattr(audit_request, "relationships", ()) or () if getattr(getattr(item, "relationship_type", None), "value", getattr(item, "relationship_type", "")) == "biological_parent" and item.child_member_id == proband_id]
    if len(parents) != 2:
        return False
    by_member = {item.family_member_id: item for item in observations}
    bindings = {item.family_member_id: item for item in request.family_sample_bindings}
    required_ids = {*parents, proband_id}
    if not required_ids.issubset(bindings):
        return False
    package_id = getattr(gateway, "package_id", None)
    if package_id is not None and any(bindings[member_id].package_id != package_id for member_id in required_ids):
        return False
    bound_samples = [bindings[member_id].sample_name for member_id in required_ids]
    if len(bound_samples) != len(set(bound_samples)):
        return False
    header_names = {str(item) for item in getattr(getattr(getattr(gateway, "vcf", None), "header", None), "sample_names", ()) or ()}
    if any(sample not in header_names for sample in bound_samples):
        return False
    proband = by_member.get(proband_id)
    if proband is None or proband.source_record_id != str(record.record_id) or proband.observed_alt_presence_state != "present" or proband.genotype_quality_state != ComponentState.POSITIVE or proband.observed_genotype_quality is None:
        return False
    return all(
        by_member.get(parent)
        and by_member[parent].source_record_id == str(record.record_id)
        and by_member[parent].observed_alt_presence_state == "absent"
        and by_member[parent].genotype_quality_state == ComponentState.POSITIVE
        and by_member[parent].observed_genotype_quality is not None
        for parent in parents
    )


def _family_summary(case: ClinicalCaseIntake, request: CandidateAnalysisRequest, gateway: Any, ranked: list[CandidateAnalysisRecord], excluded: list[ExcludedCandidate]) -> FamilySegregationSummary:
    audit_request = getattr(case, "pedigree_inheritance_audit", None)
    relationships = list(getattr(audit_request, "relationships", ()) or ())
    biological = [item for item in relationships if getattr(getattr(item, "relationship_type", None), "value", getattr(item, "relationship_type", "")) == "biological_parent"]
    observations = tuple(
        sorted(
            (item for candidate in ranked for item in candidate.family_segregation_observations),
            key=lambda item: (item.candidate_id, item.observation_id),
        )
    )
    tested = len({item.family_member_id for item in observations if item.sample_name})
    affected = sum(1 for item in case.pedigree if getattr(getattr(item, "affected_status", None), "value", "unknown") == "affected")
    missing = sorted({
        *(_missing_relative_ids(case, request)),
        *(member_id for candidate in ranked for member_id in candidate.inheritance_compatibility.missing_relative_ids),
    })
    low_quality = sorted({member_id for candidate in ranked for member_id in candidate.inheritance_compatibility.low_quality_member_ids})
    count = len(case.pedigree)
    if count <= 1:
        shape = FamilyShape.SINGLETON
    elif count == 2:
        shape = FamilyShape.DUO
    elif count == 3 and len(biological) >= 2:
        shape = FamilyShape.TRIO
    elif count > 3:
        shape = FamilyShape.EXTENDED_FAMILY
    else:
        shape = FamilyShape.DUO
    supplied_statements = _supplied_inheritance_statements(case)
    return FamilySegregationSummary(
        family_shape=shape,
        member_count=count,
        biological_parent_relationship_count=len(biological),
        tested_member_count=tested,
        affected_member_count=affected,
        missing_relative_ids=tuple(missing),
        low_quality_member_ids=tuple(low_quality),
        supplied_relationship_count=len(relationships),
        supplied_inheritance_statement_count=len(supplied_statements),
        observations=observations,
    )


def _quality_coverage_assay(*, candidate_id: str, context: CandidateContextInput, record: Any, gateway: Any, gene: str | None, provenance: tuple[ProvenanceReference, ...]) -> tuple[QualityCoverageAssayContext, QualityCoverageAssayContext, ExclusionTrace | None, list[MissingInformation], list[UnresolvedUncertainty]]:
    missing: list[MissingInformation] = []
    unresolved: list[UnresolvedUncertainty] = []
    filter_status = str(getattr(record, "filter_status", "") or "").casefold()
    if context.quality_state != "not_assessed":
        variant_quality_state = _state_from_literal(context.quality_state)
    elif not getattr(record, "filter_status", None) and not getattr(record, "quality", None):
        variant_quality_state = ComponentState.NOT_ASSESSED
    elif filter_status in {"pass", "."}:
        variant_quality_state = ComponentState.POSITIVE
    elif filter_status:
        variant_quality_state = ComponentState.NEGATIVE
    else:
        variant_quality_state = ComponentState.NEUTRAL
    qc = getattr(gateway, "qc", None)
    qc_state = _state_from_literal(context.qc_state) if context.qc_state != "not_assessed" else ComponentState.POSITIVE if qc is not None and not getattr(qc, "warnings", ()) else ComponentState.NOT_ASSESSED if qc is not None else ComponentState.MISSING
    coverage_summary = getattr(gateway, "coverage", None)
    poor = []
    for region in getattr(coverage_summary, "poor_regions", ()) or ():
        region_gene = str(getattr(region, "gene_or_region", "") or "")
        if (getattr(region, "chromosome", None) == getattr(record, "chromosome", None) and getattr(region, "start", None) is not None and getattr(region, "end", None) is not None and int(region.start) <= int(record.position) <= int(region.end)) or (gene and gene.casefold() in region_gene.casefold()):
            poor.append(str(region.region_id))
    coverage_state = ComponentState.NOT_ASSESSED if poor else ComponentState.POSITIVE if coverage_summary is not None else ComponentState.MISSING
    assay = getattr(gateway, "assay_scope", None)
    reportable_genes = {str(item).casefold() for item in getattr(assay, "reportable_genes", ()) or ()}
    outside = bool(gene and reportable_genes and gene.casefold() not in reportable_genes)
    assay_state = ComponentState.NOT_ASSESSED if outside else ComponentState.POSITIVE if assay is not None else ComponentState.MISSING
    blind_spots = tuple(f"BLIND-SPOT-{index + 1}" for index, _ in enumerate(getattr(assay, "blind_spots", ()) or ()))
    warnings = tuple(getattr(qc, "warnings", ()) or ()) + tuple(getattr(coverage_summary, "warnings", ()) or ())
    quality = QualityCoverageAssayContext(
        variant_quality_state=variant_quality_state,
        qc_state=qc_state,
        coverage_state=coverage_state,
        assay_scope_state=assay_state,
        poor_coverage_region_ids=tuple(sorted(poor)),
        outside_reportable_range=outside,
        assay_blind_spot_ids=blind_spots,
        warnings=tuple(sorted(set(str(item) for item in warnings))),
        explanation="Supplied variant quality and QC values were retained for review.",
        provenance=provenance,
    )
    coverage = quality.model_copy(update={
        "explanation": (
            "The candidate overlaps a supplied poor-coverage region; it is retained without false negative evidence."
            if poor
            else "The candidate is within the supplied assay scope and no matching poor-coverage region was supplied."
            if assay is not None
            else "Coverage and assay scope were not supplied."
        )
    })
    retained_trace = None
    if poor:
        retained_trace = _trace(
            candidate_id,
            "inadequate_coverage",
            ExclusionCode.INADEQUATE_COVERAGE,
            "poor coverage retains the candidate for review with not_assessed coverage contribution",
            provenance,
            outcome=ExclusionOutcome.RETAINED,
            input_state="poor_coverage",
        )
        unresolved.append(_uncertainty(candidate_id, "poor-coverage", "coverage", "The candidate overlaps a supplied poor-coverage region.", "The assay coverage is inadequate for a confident review decision.", provenance))
    if coverage_summary is None:
        missing.append(_missing(candidate_id, "coverage", "Coverage metadata was not supplied.", provenance))
    if assay is None:
        missing.append(_missing(candidate_id, "assay_scope", "Assay reportable scope was not supplied.", provenance))
    return quality, coverage, retained_trace, missing, unresolved


def _frequency_context(context: CandidateContextInput, provenance: tuple[ProvenanceReference, ...]) -> FrequencyContext:
    if context.population_frequency is None:
        explanation = "Population frequency was not supplied; no frequency absence inference is made."
    else:
        explanation = f"Supplied frequency {context.population_frequency:g} from {context.population_source_name or 'unspecified source'} is used as bounded prioritization context only."
    return FrequencyContext(
        frequency_supplied=context.population_frequency,
        source_name=context.population_source_name,
        source_version=context.population_source_version,
        source_scope=context.population_source_scope,
        indian_population_source=context.indian_population_source,
        explanation=explanation,
        provenance=provenance,
    )


def _frequency_score(context: FrequencyContext) -> tuple[ComponentState, float | None]:
    if context.frequency_supplied is None:
        return ComponentState.MISSING, None
    if context.frequency_supplied <= 0.01:
        return ComponentState.POSITIVE, 1.0
    return ComponentState.NEGATIVE, -1.0


def _consequence_score(value: str | None) -> tuple[ComponentState, float | None]:
    if not value:
        return ComponentState.MISSING, None
    lowered = value.casefold()
    if any(marker in lowered for marker in ("loss_of_function", "lof", "nonsense", "frameshift", "splice", "stop_gained")):
        return ComponentState.POSITIVE, 1.0
    return ComponentState.NEUTRAL, 0.0


def _state_from_literal(value: str | ComponentState) -> ComponentState:
    raw = getattr(value, "value", value)
    return {
        "positive": ComponentState.POSITIVE,
        "negative": ComponentState.NEGATIVE,
        "neutral": ComponentState.NEUTRAL,
        "missing": ComponentState.MISSING,
        "not_assessed": ComponentState.NOT_ASSESSED,
        "relevant": ComponentState.POSITIVE,
        "not_relevant": ComponentState.NEGATIVE,
        "compatible": ComponentState.POSITIVE,
        "incompatible": ComponentState.NEGATIVE,
        "unknown": ComponentState.NOT_ASSESSED,
    }.get(str(raw), ComponentState.NOT_ASSESSED)


def _validity_state(value: str) -> ComponentState:
    return {"established": ComponentState.POSITIVE, "limited": ComponentState.NEUTRAL, "conflicting": ComponentState.NEGATIVE}.get(value, ComponentState.MISSING if value in {"not_supplied"} else ComponentState.NOT_ASSESSED)


def _supplied_inheritance_statements(case: ClinicalCaseIntake) -> tuple[str, ...]:
    return tuple(sorted({
        str(item.inheritance_candidate.value)
        for item in case.hypotheses
        if getattr(item, "inheritance_candidate", None) is not None
    }))


def _audit_by_candidate(pedigree_audit: Any) -> dict[str, list[Any]]:
    result: dict[str, list[Any]] = defaultdict(list)
    for item in getattr(pedigree_audit, "inheritance_audits", ()) or ():
        for candidate_id in getattr(item, "candidate_variant_ids", ()) or ():
            result[str(candidate_id)].append(item)
    return result


def _audit_status_for_case_candidate(pedigree_audit: Any, candidate_id: str) -> str | None:
    for item in getattr(pedigree_audit, "inheritance_audits", ()) or ():
        if candidate_id in {str(value) for value in getattr(item, "candidate_variant_ids", ()) or ()}:
            return str(getattr(getattr(item, "status", None), "value", getattr(item, "status", "")))
    return None


def _phase_for_candidate(pedigree_audit: Any, candidate_id: str) -> PhaseEvaluation:
    for item in getattr(pedigree_audit, "phase_assessments", ()) or ():
        if candidate_id in {str(value) for value in getattr(item, "involved_candidate_variant_ids", ()) or ()}:
            value = str(getattr(item, "assessment", "unknown"))
            return {
                "confirmed_in_trans": PhaseEvaluation.CONFIRMED_TRANS,
                "supported_in_trans_by_supplied_parental_observations": PhaseEvaluation.DETERMINISTICALLY_SUPPORTED_TRANS,
                "presumed_in_trans": PhaseEvaluation.SUPPLIED_TRANS,
                "confirmed_in_cis": PhaseEvaluation.CIS,
                "unknown": PhaseEvaluation.PHASE_UNKNOWN,
            }.get(value, PhaseEvaluation.NOT_ASSESSED)
    return PhaseEvaluation.NOT_ASSESSED


def _segregation_state(observations: list[FamilySegregationObservation]) -> ComponentState:
    if not observations:
        return ComponentState.NOT_ASSESSED
    if any(item.status == FamilyObservationStatus.CONTRADICTORY for item in observations):
        return ComponentState.NEGATIVE
    if all(item.status in {FamilyObservationStatus.COMPATIBLE, FamilyObservationStatus.SUPPLIED} for item in observations):
        return ComponentState.POSITIVE
    return ComponentState.NOT_ASSESSED


def _inheritance_explanation(state: ComponentState, statement_state: InheritanceStatementState, de_novo: DeNovoState, phase: PhaseEvaluation, segregation: ComponentState, missing: tuple[str, ...], low_quality: tuple[str, ...], x_linked: ComponentState, compound: PhaseEvaluation, compound_partner: str | None) -> str:
    parts = [f"deterministic compatibility={state.value}", f"supplied inheritance={statement_state.value}", f"de novo={de_novo.value}", f"phase={phase.value}", f"segregation={segregation.value}", f"x-linked={x_linked.value}", f"compound-heterozygosity={compound.value}"]
    if compound_partner:
        parts.append(f"compound partner={compound_partner}")
    if missing:
        parts.append(f"missing relatives={','.join(missing)}")
    if low_quality:
        parts.append(f"low-quality members={','.join(low_quality)}")
    parts.append("No family relationship, paternity, non-paternity, ancestry, caste, community, or ethnicity inference was performed.")
    return "; ".join(parts)


def _context_by_record(request: CandidateAnalysisRequest, case: ClinicalCaseIntake, records: list[Any]) -> dict[str, list[CandidateContextInput]]:
    result: dict[str, list[CandidateContextInput]] = defaultdict(list)
    for context in request.candidate_contexts:
        if context.source_record_id:
            result[context.source_record_id].append(context)
    return result


def _coordinate_contexts(case: ClinicalCaseIntake, request: CandidateAnalysisRequest, record: Any) -> list[CandidateContextInput]:
    contexts = [item for item in request.candidate_contexts if item.source_record_id == str(record.record_id)]
    if contexts:
        return contexts
    return []


def _coordinates_match(candidate: Any, record: Any) -> bool:
    return (
        str(getattr(candidate, "chromosome", "")) == str(getattr(record, "chromosome", ""))
        and getattr(candidate, "position", None) == getattr(record, "position", None)
        and str(getattr(candidate, "ref", "")) == str(getattr(record, "reference_allele", ""))
        and str(getattr(candidate, "alt", "")) == str(getattr(record, "alternate_allele", ""))
    )


def _out_of_scope_context(request: CandidateAnalysisRequest, record: Any) -> CandidateContextInput | None:
    for item in request.candidate_contexts:
        if item.source_record_id == str(record.record_id):
            return item
    return None


def _outside_reportable_range(context: CandidateContextInput, record: Any, gateway: Any) -> bool:
    assay = getattr(gateway, "assay_scope", None)
    genes = {str(item).casefold() for item in getattr(assay, "reportable_genes", ()) or ()}
    gene, _ = _source_gene_transcript(record)
    return bool(gene and genes and gene.casefold() not in genes)


def _evidence_by_candidate(items: tuple[CandidateEvidenceInput, ...], package_provenance: tuple[ProvenanceReference, ...]) -> dict[str, tuple[CandidateEvidence, ...]]:
    result: dict[str, list[CandidateEvidence]] = defaultdict(list)
    for item in items:
        source = ProvenanceReference(
            source_id=item.source_id,
            source_type=item.source_type,
            source_version=item.source_version,
            source_path=item.source_reference,
        )
        result[item.candidate_id].append(CandidateEvidence(
            evidence_id=item.evidence_id,
            candidate_id=item.candidate_id,
            role=item.role,
            state=EvidenceState.SUPPLIED,
            statement=item.statement,
            source=source,
        ))
    return {key: tuple(sorted(value, key=lambda item: item.evidence_id)) for key, value in result.items()}


def _case_provenance(case: ClinicalCaseIntake) -> list[ProvenanceReference]:
    return [ProvenanceReference(source_id=item.source_id, source_type=item.source_type, source_version=None, source_path=item.reference) for item in case.provenance]


def _gateway_provenance(gateway: Any) -> tuple[ProvenanceReference, ...]:
    if gateway is None:
        return ()
    package_id = str(getattr(gateway, "package_id", "missing-v036-package"))
    return (
        ProvenanceReference(
            source_id=f"RESULT-PACKAGE-{package_id}",
            source_type="v036_supplied_result_gateway",
            source_version=str(getattr(gateway, "schema_version", "0.36")),
            package_identity_sha256=getattr(gateway, "package_identity_sha256", None),
            manifest_identity_sha256=getattr(gateway, "input_manifest_sha256", None),
        ),
    )


def _merge_provenance(*groups: Iterable[ProvenanceReference]) -> list[ProvenanceReference]:
    unique: dict[tuple[str, str, str | None, str | None], ProvenanceReference] = {}
    for group in groups:
        for item in group:
            key = (item.source_id, item.source_type, item.source_path, item.source_identity_sha256)
            unique[key] = item
    return sorted(unique.values(), key=lambda item: (item.source_id, item.source_type, item.source_path or ""))


def _source_record_ids(gateway: Any) -> list[str]:
    vcf = getattr(gateway, "vcf", None)
    return [str(item.record_id) for item in getattr(vcf, "records", ()) or ()]


def _invocation_identities(gateway: Any) -> list[str]:
    return [str(item.invocation_sha256) for item in getattr(gateway, "tool_provenance", ()) or () if getattr(item, "invocation_sha256", None)]


def _unavailable_adapters(gateway: Any) -> list[str]:
    values = []
    for item in getattr(gateway, "adapter_results", ()) or ():
        status = str(getattr(getattr(item, "status", None), "value", getattr(item, "status", "")))
        if status == "unavailable":
            values.append(str(getattr(getattr(item, "adapter", None), "adapter_id", "unavailable_adapter")))
    return sorted(set(values))


def _stale_codes(*, request: CandidateAnalysisRequest, gateway: Any, phenotype_identity: str, family_identity: str, assay_identity: str) -> list[str]:
    result: list[str] = []
    if request.ranking_rule_version != CANDIDATE_RANKING_RULE_VERSION or request.ranking_weight_version != CANDIDATE_RANKING_WEIGHT_VERSION:
        result.append("ranking_rule")
    if gateway is None:
        if request.expected_result_package_identity_sha256:
            result.append("result_package")
    else:
        if request.expected_result_package_identity_sha256 and request.expected_result_package_identity_sha256 != getattr(gateway, "package_identity_sha256", None):
            result.append("result_package")
    if request.expected_phenotype_snapshot_sha256 and request.expected_phenotype_snapshot_sha256 != phenotype_identity:
        result.append("phenotype_snapshot")
    if request.expected_family_snapshot_sha256 and request.expected_family_snapshot_sha256 != family_identity:
        result.append("family_snapshot")
    if request.expected_assay_coverage_snapshot_sha256 and request.expected_assay_coverage_snapshot_sha256 != assay_identity:
        result.append("assay_coverage_snapshot")
    replay = str(getattr(getattr(gateway, "replay_status", None), "value", getattr(gateway, "replay_status", "")))
    if replay == "stale":
        result.append("result_package")
    return sorted(set(result))


def _analysis_status(*, gateway: Any, records: list[Any], ranked: list[CandidateAnalysisRecord], excluded: list[ExcludedCandidate], stale_codes: list[str], supported_ids: tuple[str, ...]) -> CandidateAnalysisState:
    if stale_codes:
        return CandidateAnalysisState.STALE
    package_status = str(getattr(getattr(gateway, "package_status", None), "value", getattr(gateway, "package_status", "")))
    if package_status in {"blocked", "rejected", "failed", "stale"} and not records:
        return CandidateAnalysisState.BLOCKED
    if gateway is None or not records:
        return CandidateAnalysisState.NOT_ASSESSED
    if excluded:
        return CandidateAnalysisState.PARTIAL if ranked else CandidateAnalysisState.UNRESOLVED
    return CandidateAnalysisState.COMPLETED if supported_ids else CandidateAnalysisState.UNRESOLVED


def _support_threshold(request: CandidateAnalysisRequest) -> float:
    return request.support_threshold if request.support_threshold is not None else 8.0


def _analysis_scope(gateway: Any) -> str:
    if gateway is None:
        return "No v0.36 supplied result package was available; no supported source records were assessed."
    return "Only supported SNV and small-indel records accepted by the frozen v0.36 result gateway were eligible for v0.37 prioritization."


def _assessed_regions(gateway: Any) -> tuple[str, ...]:
    assay = getattr(gateway, "assay_scope", None)
    return tuple(sorted({*(str(item) for item in getattr(assay, "reportable_genes", ()) or ()), *(str(item) for item in getattr(assay, "reportable_regions", ()) or ())}))


def _unassessed_regions(gateway: Any) -> tuple[str, ...]:
    assay = getattr(gateway, "assay_scope", None)
    return tuple(sorted(str(item) for item in getattr(assay, "blind_spots", ()) or ()))


def _coverage_gaps(gateway: Any) -> tuple[str, ...]:
    coverage = getattr(gateway, "coverage", None)
    return tuple(sorted(str(getattr(item, "region_id", "coverage-gap")) for item in getattr(coverage, "poor_regions", ()) or ()))


def _assay_blind_spots(gateway: Any) -> tuple[str, ...]:
    assay = getattr(gateway, "assay_scope", None)
    return tuple(sorted(str(item) for item in getattr(assay, "blind_spots", ()) or ()))


def _human_review_questions(*, ranked: list[CandidateAnalysisRecord], excluded: list[ExcludedCandidate], stale_codes: list[str], unavailable_adapters: list[str]) -> tuple[str, ...]:
    questions = [
        "Which candidate evidence and contradictions should a qualified reviewer examine first?",
        "Are the supplied phenotype terms, family relationships, sample bindings, and assay limitations complete for this review?",
    ]
    if any(item.inheritance_compatibility.phase_state == PhaseEvaluation.PHASE_UNKNOWN for item in ranked):
        questions.append("Can the supplied phase information be reviewed without inferring unobserved relationships?")
    if excluded:
        questions.append("Should the retained exclusion history be resolved by a human reviewer within the supplied assay scope?")
    if stale_codes:
        questions.append("Should the analysis be replayed against the current phenotype, family, result-package, assay, and rule identities?")
    if unavailable_adapters:
        questions.append("Does an unavailable adapter leave a review limitation that must remain open?")
    return tuple(questions)


def _missing(candidate_id: str | None, category: str, information_needed: str, provenance: Iterable[ProvenanceReference]) -> MissingInformation:
    return MissingInformation(
        missing_id=safe_candidate_id("missing", candidate_id or "case", category, information_needed),
        candidate_id=candidate_id,
        category=category,
        information_needed=information_needed,
        source=tuple(provenance),
    )


def _uncertainty(candidate_id: str | None, suffix: str, category: str, statement: str, reason: str, provenance: Iterable[ProvenanceReference]) -> UnresolvedUncertainty:
    return UnresolvedUncertainty(
        uncertainty_id=safe_candidate_id("uncertainty", candidate_id or "case", suffix),
        candidate_id=candidate_id,
        category=category,
        statement=statement,
        reason=reason,
        source=tuple(provenance),
    )


def _trace(candidate_id: str, suffix: str, code: ExclusionCode, reason: str, provenance: Iterable[ProvenanceReference], *, outcome: ExclusionOutcome, input_state: str, rule_id: str = "candidate_filter", rule_version: str = CANDIDATE_RANKING_RULE_VERSION) -> ExclusionTrace:
    return ExclusionTrace(
        exclusion_id=safe_candidate_id("exclusion", candidate_id, suffix, code.value),
        candidate_id=candidate_id,
        input_state=input_state,
        rule_id=rule_id,
        rule_version=rule_version,
        rule_or_threshold=(f"{rule_id}@{rule_version}"),
        result=outcome,
        code=code,
        reason=reason,
        provenance=tuple(provenance),
    )


def _dedupe_missing(items: Iterable[MissingInformation]) -> list[MissingInformation]:
    return sorted({item.missing_id: item for item in items}.values(), key=lambda item: item.missing_id)


def _dedupe_uncertainties(items: Iterable[UnresolvedUncertainty]) -> list[UnresolvedUncertainty]:
    return sorted({item.uncertainty_id: item for item in items}.values(), key=lambda item: item.uncertainty_id)


def _family_snapshot(case: ClinicalCaseIntake, pedigree_audit: Any) -> object:
    return _canonicalize_snapshot(
        {
            "pedigree": [item.model_dump(mode="json") for item in case.pedigree],
            "audit_request": getattr(case.pedigree_inheritance_audit, "model_dump", lambda **_: None)(mode="json"),
            "audit_result": getattr(pedigree_audit, "model_dump", lambda **_: None)(mode="json"),
        }
    )


def _phenotype_snapshot(case: ClinicalCaseIntake, phenotype_curation: Any) -> object:
    return _canonicalize_snapshot(
        {
            "phenotypes": [item.model_dump(mode="json") for item in case.phenotypes],
            "curation": getattr(phenotype_curation, "model_dump", lambda **_: None)(mode="json"),
        }
    )


def _assay_snapshot(gateway: Any) -> object:
    return {"qc": getattr(getattr(gateway, "qc", None), "model_dump", lambda **_: None)(mode="json"), "coverage": getattr(getattr(gateway, "coverage", None), "model_dump", lambda **_: None)(mode="json"), "assay_scope": getattr(getattr(gateway, "assay_scope", None), "model_dump", lambda **_: None)(mode="json")}


def _evidence_snapshot(request: CandidateAnalysisRequest) -> object:
    return {
        "evidence": [item.model_dump(mode="json") for item in request.evidence],
        "contexts": [item.model_dump(mode="json") for item in request.candidate_contexts],
    }


_UNORDERED_SNAPSHOT_KEYS = {
    "phenotypes",
    "candidate_variants",
    "pedigree",
    "relationships",
    "variant_observations",
    "audit_targets",
    "phase_declarations",
    "inheritance_audits",
    "phase_assessments",
    "missing_information",
    "unresolved_questions",
    "family_sample_bindings",
    "evidence",
    "contexts",
    "provenance",
    "supporting_evidence",
    "contradicting_evidence",
}


def _canonicalize_snapshot(value: Any, key: str | None = None) -> Any:
    if isinstance(value, dict):
        return {name: _canonicalize_snapshot(item, name) for name, item in value.items()}
    if isinstance(value, list):
        items = [_canonicalize_snapshot(item, key) for item in value]
        return sorted(items, key=canonical_json) if key in _UNORDERED_SNAPSHOT_KEYS else items
    return value


def _family_summary_provenance(case: ClinicalCaseIntake) -> tuple[ProvenanceReference, ...]:
    return tuple(_case_provenance(case))


def _missing_relative_ids(case: ClinicalCaseIntake, request: CandidateAnalysisRequest) -> tuple[str, ...]:
    audit_request = getattr(case, "pedigree_inheritance_audit", None)
    if audit_request is None:
        return ()
    proband = str(audit_request.proband_member_id)
    members = {item.family_member_id for item in case.pedigree}
    parent_ids = {
        item.parent_member_id
        for item in getattr(audit_request, "relationships", ()) or ()
        if item.child_member_id == proband
        and getattr(getattr(item, "relationship_type", None), "value", getattr(item, "relationship_type", "")) == "biological_parent"
    }
    bindings = {item.family_member_id for item in request.family_sample_bindings}
    observations = {
        item.family_member_id
        for item in getattr(audit_request, "variant_observations", ()) or ()
        if item.family_member_id in parent_ids
    }
    missing = {
        parent_id
        for parent_id in parent_ids
        if parent_id not in members or parent_id not in bindings or parent_id not in observations
    }
    return tuple(sorted(missing))


__all__ = ["build_candidate_analysis"]
