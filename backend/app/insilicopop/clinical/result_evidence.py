from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from typing import Any

from app.insilicopop.clinical.models import ClinicalCaseIntake
from app.insilicopop.clinical.pretest_models import PreTestAssessmentResult
from app.insilicopop.clinical.result_evidence_models import (
    NORMALIZATION_VERSION,
    BiochemicalFinding,
    ControlledSourceAdapter,
    EvidenceLedgerEntry,
    EvidenceSummaryRequest,
    FactLinkAssessment,
    FactType,
    FixtureEvidenceRecord,
    GeneratedEvidenceSummary,
    HumanReviewStatus,
    IntakeAssessment,
    NormalizationOutcome,
    NormalizedFinding,
    ReportedFinding,
    ResultCategory,
    ResultEvidenceWorkspaceResult,
    RetrievalQuery,
    RetrievalRecord,
    RetrievalState,
)
from app.insilicopop.clinical.test_strategy_models import TestStrategyWorkspaceResult


_NEGATIVE_WORDING = (
    "No reportable finding was identified within the externally reported scope and limitations."
)
_NO_RECORDS_TEMPLATE = (
    "No records were returned by the selected source {source_name} for this query."
)
_CONFLICT_WORDING = (
    "Sources provide differing observations or interpretations. "
    "InSilicoPop has not resolved the conflict."
)


def build_result_evidence_workspace(
    case: ClinicalCaseIntake,
    *,
    pretest_assessment: PreTestAssessmentResult | None = None,
    test_strategy_workspace: TestStrategyWorkspaceResult | None = None,
) -> ResultEvidenceWorkspaceResult | None:
    request = case.result_evidence_workspace
    if request is None:
        return None

    source_results = sorted(request.results, key=lambda item: item.result_id)
    intake_assessments = [_assess_intake(case, result) for result in source_results]
    normalized_findings = [
        _normalize_finding(result, finding)
        for result in source_results
        for finding in sorted(result.findings, key=lambda item: item.finding_id)
    ]
    finding_by_id = {item.finding_id: item for item in normalized_findings}
    fact_link_assessments = _assess_fact_links(
        case,
        source_results,
        pretest_assessment=pretest_assessment,
        test_strategy_workspace=test_strategy_workspace,
    )
    adapters = {item.source_name: item for item in request.source_adapters}
    retrieval_records = [
        record
        for query in sorted(request.retrieval_queries, key=lambda item: item.query_id)
        for record in _retrieve_query(query, finding_by_id.get(query.finding_id), adapters)
    ]
    ledger_entries, fixture_records = _build_ledger(
        case.pseudonymous_case_id,
        retrieval_records,
        adapters,
    )
    ledger_entries = _annotate_duplicates_updates_and_conflicts(ledger_entries, fixture_records)
    generated_summaries = _build_summaries(request.summary_requests, ledger_entries)
    audit_history = _audit_history(
        source_results,
        normalized_findings,
        retrieval_records,
        ledger_entries,
        request.review_actions,
    )
    source_hashes = sorted(
        {
            result.provenance.source_document_hash.lower()
            for result in source_results
            if result.provenance.source_document_hash
        }
    )
    source_versions = {
        item.source_name: item.source_version for item in sorted(request.source_adapters, key=lambda item: item.source_name)
    }
    raw_hashes = sorted({item.raw_response_hash for item in retrieval_records if item.raw_response_hash})
    rules = sorted({item.normalization_rule_id for item in normalized_findings})
    stable_payload = {
        "schema_version": "0.32",
        "case_id": case.pseudonymous_case_id,
        "source_results": [item.model_dump(mode="json") for item in source_results],
        "normalized_findings": [item.model_dump(mode="json") for item in normalized_findings],
        "retrieval_records": [item.model_dump(mode="json") for item in retrieval_records],
        "ledger_entries": [item.model_dump(mode="json") for item in ledger_entries],
        "review_actions": [item.model_dump(mode="json") for item in request.review_actions],
    }
    return ResultEvidenceWorkspaceResult(
        pseudonymous_case_id=case.pseudonymous_case_id,
        source_results=source_results,
        intake_assessments=intake_assessments,
        normalized_findings=normalized_findings,
        fact_link_assessments=fact_link_assessments,
        retrieval_queries=sorted(request.retrieval_queries, key=lambda item: item.query_id),
        retrieval_records=retrieval_records,
        ledger_entries=ledger_entries,
        generated_summaries=generated_summaries,
        review_actions=sorted(request.review_actions, key=lambda item: (item.timestamp, item.action_id)),
        external_interpretations=sorted(
            request.external_interpretations,
            key=lambda item: item.external_interpretation_id,
        ),
        normalization_rules=rules,
        source_document_hashes=source_hashes,
        retrieval_source_versions=source_versions,
        raw_response_hashes=raw_hashes,
        audit_history=audit_history,
        stable_workspace_id=_stable_id("result-evidence-workspace", stable_payload),
    )


def _assess_intake(case: ClinicalCaseIntake, result) -> IntakeAssessment:
    blocking = set(result.blocking_missing_fields)
    advisory = set(result.advisory_missing_fields)
    provenance = result.provenance
    if not provenance.source_document_id:
        blocking.add("source_document_id")
    if not provenance.source_document_hash:
        blocking.add("source_document_hash")
    for field in (
        "source_document_name",
        "source_document_date",
        "source_page_or_section",
        "reporting_laboratory",
        "test_name_as_reported",
        "test_method_as_reported",
        "test_scope_as_reported",
        "specimen_type",
        "report_issue_date",
        "report_version",
    ):
        if not getattr(provenance, field):
            advisory.add(field)
    rules = ["RESINT-001"] if blocking else []
    if any(item.external_laboratory_classification for item in result.findings):
        rules.append("RESINT-002")
    bounded_wording = None
    if result.category == ResultCategory.NEGATIVE_OR_UNINFORMATIVE_RESULT:
        rules.append("RESINT-003")
        bounded_wording = _NEGATIVE_WORDING
        if not any(item.negative_or_uninformative for item in result.findings):
            blocking.add("negative_scope")
    if result.case_id != case.pseudonymous_case_id:
        blocking.add("case_id")
    return IntakeAssessment(
        result_id=result.result_id,
        intake_status=(
            NormalizationOutcome.REQUIRES_RULE_REVIEW
            if blocking
            else NormalizationOutcome.UNCHANGED_SOURCE_ONLY
        ),
        source_report_present=bool(
            provenance.source_document_id and provenance.source_document_hash
        ),
        blocking_missing_fields=sorted(blocking),
        advisory_missing_fields=sorted(advisory - blocking),
        bounded_result_wording=bounded_wording,
        rule_ids=sorted(rules),
    )


def _normalize_finding(result, finding: ReportedFinding) -> NormalizedFinding:
    reported_value = _reported_payload(finding)
    normalized_value: dict[str, Any] = {}
    notes: list[str] = []
    warnings: list[str] = []
    status = NormalizationOutcome.UNCHANGED_SOURCE_ONLY
    method = "source_preservation_only"
    rule_id = "NORM-SOURCE-ONLY"

    if finding.category == ResultCategory.SEQUENCE_VARIANT_RESULT and finding.sequence_variant:
        status, normalized_value, notes, warnings, method, rule_id = _normalize_sequence(
            finding.sequence_variant
        )
    elif finding.category == ResultCategory.COPY_NUMBER_RESULT and finding.copy_number:
        status, normalized_value, notes, warnings, method, rule_id = _normalize_cnv(
            finding.copy_number
        )
    elif finding.category in {
        ResultCategory.STRUCTURAL_VARIANT_RESULT,
        ResultCategory.CYTOGENETIC_RESULT,
    } and finding.structural_or_cytogenetic:
        normalized_value = finding.structural_or_cytogenetic.model_dump(mode="json")
        notes = [
            "Original ISCN and reported breakpoints were preserved; no exact molecular event was inferred."
        ]
        rule_id = "NORM-CYTOGENETIC-SOURCE-PRESERVE"
    elif finding.category == ResultCategory.REPEAT_EXPANSION_RESULT and finding.repeat_expansion:
        normalized_value = finding.repeat_expansion.model_dump(mode="json")
        notes = [
            "Categorical allele language was preserved; no numeric repeat count was inferred."
        ]
        rule_id = "NORM-REPEAT-SOURCE-PRESERVE"
    elif finding.category == ResultCategory.MITOCHONDRIAL_RESULT and finding.mitochondrial:
        status, normalized_value, notes, warnings, method, rule_id = _normalize_mitochondrial(
            finding.mitochondrial
        )
    elif finding.category == ResultCategory.BIOCHEMICAL_RESULT and finding.biochemical:
        status, normalized_value, notes, warnings, method, rule_id = _normalize_biochemical(
            finding.biochemical
        )
    elif (
        finding.category == ResultCategory.NEGATIVE_OR_UNINFORMATIVE_RESULT
        and finding.negative_or_uninformative
    ):
        normalized_value = finding.negative_or_uninformative.model_dump(mode="json")
        notes = [_NEGATIVE_WORDING]
        rule_id = "RESINT-003"
    else:
        normalized_value = reported_value.copy()
        notes = ["Unsupported or other structured content remains source-only for human review."]

    if result.provenance.source_document_id is None or result.provenance.source_document_hash is None:
        warnings.append(
            "The finding cannot be fully verified against its original source report."
        )
        if status != NormalizationOutcome.REJECTED_AS_INVALID:
            status = NormalizationOutcome.REQUIRES_RULE_REVIEW
            rule_id = "RESINT-001"
    return NormalizedFinding(
        finding_id=finding.finding_id,
        result_id=result.result_id,
        category=finding.category,
        reported_finding_snapshot=finding,
        reported_value=reported_value,
        normalized_value=normalized_value,
        normalization_status=status,
        normalization_method=method,
        normalization_notes=notes,
        normalization_rule_id=rule_id,
        normalization_timestamp=result.provenance.reviewed_at or result.provenance.entered_at,
        normalization_warnings=warnings,
        human_review_status=(
            HumanReviewStatus.ACCEPTED_INTO_WORKSPACE
            if finding.human_transcription_verified
            else HumanReviewStatus.PENDING
        ),
    )


def _normalize_sequence(sequence):
    reported = sequence.model_dump(mode="json")
    if sequence.alternate_source_representations and sequence.representations_equivalent is not True:
        return (
            NormalizationOutcome.REQUIRES_RULE_REVIEW,
            reported,
            ["Every supplied representation was preserved; equivalence was not assumed."],
            ["Multiple source representations are not confirmed as equivalent."],
            "deterministic_reference_aware_sequence_review",
            "NORM-003",
        )
    if sequence.genomic_position == 0:
        return (
            NormalizationOutcome.REJECTED_AS_INVALID,
            {},
            ["The invalid normalization was rejected without deleting the reported source record."],
            ["A one-based genomic position cannot be zero."],
            "deterministic_reference_aware_sequence_review",
            "NORM-INVALID-POSITION",
        )
    assembly = _assembly(sequence.reference_assembly_reported)
    transcript = _clean(sequence.transcript_reported)
    normalized = {
        "gene_symbol_reported": sequence.gene_symbol_reported,
        "gene_symbol_normalized": (
            sequence.gene_symbol_reported.strip().upper()
            if sequence.gene_symbol_reported
            else None
        ),
        "transcript_reported": sequence.transcript_reported,
        "transcript_normalized": transcript,
        "transcript_version": transcript.rsplit(".", 1)[1] if transcript and re.search(r"\.\d+$", transcript) else None,
        "reference_assembly_reported": sequence.reference_assembly_reported,
        "reference_assembly_normalized": assembly,
        "chromosome": _clean(sequence.chromosome),
        "genomic_position": sequence.genomic_position,
        "reference_allele": sequence.reference_allele.upper() if sequence.reference_allele else None,
        "alternate_allele": sequence.alternate_allele.upper() if sequence.alternate_allele else None,
        "hgvs_g_reported": sequence.hgvs_g_reported,
        "hgvs_g_normalized": _clean(sequence.hgvs_g_reported),
        "hgvs_c_reported": sequence.hgvs_c_reported,
        "hgvs_c_normalized": _clean(sequence.hgvs_c_reported),
        "hgvs_p_reported": sequence.hgvs_p_reported,
        "hgvs_p_normalized": None,
        "zygosity_reported": sequence.zygosity_reported,
        "zygosity_normalized": _clean_lower(sequence.zygosity_reported),
        "phase_status": sequence.phase_status,
        "allele_origin_reported": sequence.allele_origin_reported,
        "mosaic_status_reported": sequence.mosaic_status_reported,
        "variant_type": _clean_lower(sequence.variant_type),
    }
    transcript_complete = bool(transcript and re.search(r"\.\d+$", transcript))
    coordinate_complete = bool(
        (sequence.hgvs_c_reported or (sequence.chromosome and sequence.genomic_position))
        and sequence.reference_allele
        and sequence.alternate_allele
    )
    if assembly and transcript_complete and coordinate_complete:
        return (
            NormalizationOutcome.NORMALIZED,
            normalized,
            ["Deterministic whitespace, gene-symbol case, assembly alias, and allele case normalization applied."],
            [],
            "deterministic_reference_aware_sequence_normalization",
            "NORM-001",
        )
    missing = []
    if not assembly:
        missing.append("reference assembly")
    if not transcript_complete:
        missing.append("transcript with explicit version")
    if not coordinate_complete:
        missing.append("HGVS/coordinate and reference-alternate representation")
    return (
        NormalizationOutcome.PARTIALLY_NORMALIZED,
        normalized,
        ["No transcript, transcript version, assembly, protein consequence, phase, origin, or mosaic fraction was invented."],
        [f"Missing or incomplete: {item}." for item in missing],
        "deterministic_source_bounded_sequence_normalization",
        "NORM-002",
    )


def _normalize_cnv(cnv):
    normalized = cnv.model_dump(mode="json")
    if cnv.start is not None and cnv.end is not None and cnv.end < cnv.start:
        return (
            NormalizationOutcome.REJECTED_AS_INVALID,
            normalized,
            ["The source region was retained while the coordinate normalization was rejected."],
            ["CNV end coordinate precedes start coordinate."],
            "deterministic_cnv_review",
            "NORM-CNV-INVALID-RANGE",
        )
    exact = cnv.start is not None and cnv.end is not None
    if not exact:
        if cnv.breakpoint_precision.value not in {"cytoband_only", "interval"}:
            normalized["breakpoint_precision"] = "approximate"
        normalized["start"] = cnv.start
        normalized["end"] = cnv.end
        return (
            NormalizationOutcome.PARTIALLY_NORMALIZED,
            normalized,
            ["Exact coordinates were not inferred from approximate or cytoband language."],
            ["Exact breakpoints were not supplied."],
            "deterministic_cnv_source_preservation",
            "NORM-004",
        )
    return (
        NormalizationOutcome.NORMALIZED,
        normalized,
        ["Supplied coordinates and breakpoint precision were preserved."],
        [],
        "deterministic_cnv_coordinate_validation",
        "NORM-CNV-EXACT",
    )


def _normalize_mitochondrial(mt):
    normalized = mt.model_dump(mode="json")
    normalized["mt_hgvs_normalized"] = _clean(mt.mt_hgvs_reported)
    normalized["heteroplasmy_binding"] = {
        "specimen_type": mt.specimen_type,
        "detection_limit": mt.detection_limit,
        "assay_scope": "reported_assay_only",
        "propagated_to_other_tissues_or_relatives": False,
    }
    warnings = []
    status = NormalizationOutcome.PARTIALLY_NORMALIZED
    if mt.heteroplasmy_value is not None and not mt.specimen_type:
        warnings.append("A heteroplasmy value requires the tested specimen for safe interpretation.")
        status = NormalizationOutcome.REQUIRES_RULE_REVIEW
    return (
        status,
        normalized,
        ["Heteroplasmy remains bound to the reported specimen, assay, and detection limit."],
        warnings,
        "deterministic_mitochondrial_source_binding",
        "NORM-005",
    )


def _normalize_biochemical(item: BiochemicalFinding):
    normalized = item.model_dump(mode="json")
    normalized["unit_normalized"] = None
    normalized["value_normalized"] = None
    target = _clean_lower(item.requested_normalized_unit)
    if item.analyte.strip().lower() == "glucose" and item.unit_reported.strip().lower() == "mg/dl" and target == "mmol/l":
        converted = round(item.value / 18.0182, 4)
        normalized["unit_normalized"] = "mmol/L"
        normalized["value_normalized"] = converted
        normalized["conversion_rule"] = "BIOCHEM-GLUCOSE-MGDL-MMOLL-001"
        return (
            NormalizationOutcome.NORMALIZED,
            normalized,
            [
                "Validated glucose conversion applied using mmol/L = mg/dL / 18.0182; the original value and unit remain stored.",
                "The conversion is reversible using mg/dL = mmol/L × 18.0182.",
            ],
            [],
            "validated_reversible_unit_conversion",
            "BIOCHEM-GLUCOSE-MGDL-MMOLL-001",
        )
    if item.requested_normalized_unit and target != item.unit_reported.strip().lower():
        return (
            NormalizationOutcome.REQUIRES_RULE_REVIEW,
            normalized,
            ["No unvalidated unit conversion was performed."],
            ["The requested biochemical conversion has no validated deterministic rule."],
            "source_unit_preservation",
            "NORM-BIOCHEM-UNSUPPORTED-CONVERSION",
        )
    normalized["unit_normalized"] = item.unit_reported
    normalized["value_normalized"] = item.value
    return (
        NormalizationOutcome.UNCHANGED_SOURCE_ONLY,
        normalized,
        ["Original biochemical value and unit were preserved without diagnostic interpretation."],
        [],
        "source_unit_preservation",
        "NORM-BIOCHEM-SOURCE-PRESERVE",
    )


def _assess_fact_links(
    case,
    source_results,
    *,
    pretest_assessment,
    test_strategy_workspace,
):
    known: dict[FactType, set[str]] = {
        FactType.REFERRAL_FACT: {case.pseudonymous_case_id},
        FactType.PHENOTYPE_FACT: {item.observation_id for item in case.phenotypes},
        FactType.HPO_FACT: {item.observation_id for item in case.phenotypes},
        FactType.PEDIGREE_FACT: {item.family_member_id for item in case.pedigree},
        FactType.RELATIONSHIP_FACT: {item.family_member_id for item in case.pedigree},
        FactType.PREVIOUS_INVESTIGATION_FACT: set(),
        FactType.TEST_STRATEGY_OPTION: set(),
        FactType.SAMPLE_FACT: {item.family_member_id for item in case.pedigree},
        FactType.EXTERNAL_REPORT_FACT: {item.result_id for item in source_results},
    }
    if case.pre_test_assessment:
        known[FactType.PREVIOUS_INVESTIGATION_FACT].update(
            item.investigation_id for item in case.pre_test_assessment.previous_investigations
        )
    if test_strategy_workspace:
        known[FactType.TEST_STRATEGY_OPTION].update(
            item.option_id for item in test_strategy_workspace.options
        )
    assessments = []
    for result in source_results:
        for finding in result.findings:
            for link in finding.fact_links:
                linked = link.fact_id in known.get(link.fact_type, set())
                assessments.append(
                    FactLinkAssessment(
                        link_id=link.link_id,
                        finding_id=finding.finding_id,
                        fact_type=link.fact_type,
                        fact_id=link.fact_id,
                        relationship=link.relationship,
                        linkage_status="linked" if linked else "requires_rule_review",
                        message=(
                            "Descriptive stable fact link preserved; no causality, diagnosis, pathogenicity, or family relationship was inferred."
                            if linked
                            else "The supplied fact identifier is not present in the bounded case record and requires rule review."
                        ),
                    )
                )
    return sorted(assessments, key=lambda item: item.link_id)


def _retrieve_query(
    query: RetrievalQuery,
    finding: NormalizedFinding | None,
    adapters: dict[str, ControlledSourceAdapter],
) -> list[RetrievalRecord]:
    terms = {
        key: value
        for key, value in query.model_dump(mode="json").items()
        if key
        in {
            "normalized_gene",
            "normalized_variant",
            "transcript",
            "reference_assembly",
            "variant_type",
            "condition_term_reviewed",
            "inheritance_term_reviewed",
            "date_range",
            "language",
        }
        and value not in {None, ""}
    }
    normalized_query = json.dumps(terms, sort_keys=True, separators=(",", ":"))
    if query.review_status != "human_reviewed":
        return [
            _retrieval_record(
                query,
                normalized_query,
                source_name="not_selected",
                state=RetrievalState.READY_FOR_REVIEW,
                errors=["Retrieval terms require explicit human review before execution."],
            )
        ]
    if finding is None:
        return [
            _retrieval_record(
                query,
                normalized_query,
                source_name="not_selected",
                state=RetrievalState.INVALID_QUERY,
                errors=["The query finding identifier was not found."],
            )
        ]
    if finding.normalization_status in {
        NormalizationOutcome.PARTIALLY_NORMALIZED,
        NormalizationOutcome.REQUIRES_RULE_REVIEW,
        NormalizationOutcome.REJECTED_AS_INVALID,
        NormalizationOutcome.UNCHANGED_SOURCE_ONLY,
    }:
        return [
            _retrieval_record(
                query,
                normalized_query,
                source_name="not_selected",
                state=RetrievalState.REQUIRES_RULE_REVIEW,
                errors=["Retrieval deferred because the finding does not have a reviewable normalized representation."],
            )
        ]
    if not query.evidence_source_selection:
        return [
            _retrieval_record(
                query,
                normalized_query,
                source_name="not_selected",
                state=RetrievalState.REQUIRES_RULE_REVIEW,
                errors=["Evidence source selection must be explicit."],
            )
        ]
    records = []
    for source_name in sorted(query.evidence_source_selection):
        adapter = adapters.get(source_name)
        if adapter is None:
            records.append(
                _retrieval_record(
                    query,
                    normalized_query,
                    source_name=source_name,
                    state=RetrievalState.SOURCE_UNAVAILABLE,
                    errors=["The selected bounded source adapter is not configured."],
                )
            )
            continue
        state_map = {
            "source_unavailable": RetrievalState.SOURCE_UNAVAILABLE,
            "authentication_required": RetrievalState.AUTHENTICATION_REQUIRED,
            "rate_limited": RetrievalState.RATE_LIMITED,
        }
        if adapter.adapter_state != "available":
            records.append(
                _retrieval_record(
                    query,
                    normalized_query,
                    source_name=source_name,
                    state=state_map[adapter.adapter_state],
                    adapter=adapter,
                    errors=[f"Selected source state: {adapter.adapter_state}."],
                )
            )
            continue
        matches = sorted(
            [item for item in adapter.records if item.query_id == query.query_id],
            key=lambda item: item.fixture_record_id,
        )
        raw_hash = _hash_payload([item.model_dump(mode="json") for item in matches])
        state = RetrievalState.COMPLETED if matches and not adapter.warnings else (
            RetrievalState.COMPLETED_WITH_WARNINGS if matches else RetrievalState.NO_RECORDS_FOUND
        )
        records.append(
            _retrieval_record(
                query,
                normalized_query,
                source_name=source_name,
                state=state,
                adapter=adapter,
                result_count=len(matches),
                raw_response_hash=raw_hash,
                returned_ids=[item.fixture_record_id for item in matches],
                warnings=list(adapter.warnings),
                no_records_wording=(
                    _NO_RECORDS_TEMPLATE.format(source_name=source_name) if not matches else None
                ),
            )
        )
    return records


def _retrieval_record(
    query,
    normalized_query,
    *,
    source_name,
    state,
    adapter=None,
    result_count=0,
    raw_response_hash=None,
    returned_ids=None,
    errors=None,
    warnings=None,
    no_records_wording=None,
):
    return RetrievalRecord(
        retrieval_id=_stable_id("retrieval", {"query_id": query.query_id, "source_name": source_name}),
        query_id=query.query_id,
        finding_id=query.finding_id,
        query_terms=json.loads(normalized_query),
        normalized_query=normalized_query,
        source_name=source_name,
        source_type=adapter.source_type if adapter else None,
        source_version=adapter.source_version if adapter else None,
        source_url_or_identifier=adapter.source_url_or_identifier if adapter else None,
        retrieved_at=query.reviewed_at,
        retrieval_method=adapter.retrieval_method if adapter else None,
        provider="local_bounded_adapter" if adapter else "none",
        external_llm_called=False,
        byok_used=False,
        result_count=result_count,
        pagination_state="complete" if adapter else "not_applicable",
        raw_response_hash=raw_response_hash,
        cache_status="fixture" if adapter and adapter.retrieval_method == "deterministic_fixture" else (
            "local" if adapter else "not_applicable"
        ),
        state=state,
        errors=errors or [],
        warnings=warnings or [],
        returned_fixture_record_ids=returned_ids or [],
        no_records_wording=no_records_wording,
    )


def _build_ledger(case_id, retrieval_records, adapters):
    fixture_lookup: dict[str, tuple[FixtureEvidenceRecord, ControlledSourceAdapter]] = {}
    for adapter in adapters.values():
        for record in adapter.records:
            fixture_lookup[record.fixture_record_id] = (record, adapter)
    entries = []
    entry_fixture_map = {}
    for retrieval in retrieval_records:
        if retrieval.state not in {
            RetrievalState.COMPLETED,
            RetrievalState.COMPLETED_WITH_WARNINGS,
        }:
            continue
        for fixture_id in retrieval.returned_fixture_record_ids:
            fixture, adapter = fixture_lookup[fixture_id]
            ledger_id = _stable_id(
                "ledger",
                {
                    "retrieval_id": retrieval.retrieval_id,
                    "fixture_record_id": fixture.fixture_record_id,
                    "source_version": fixture.source_version,
                    "source_statement": fixture.source_statement,
                },
            )
            entry = EvidenceLedgerEntry(
                ledger_entry_id=ledger_id,
                case_id=case_id,
                finding_id=retrieval.finding_id,
                retrieval_id=retrieval.retrieval_id,
                source_type=adapter.source_type,
                source_identifier=fixture.source_identifier,
                source_title=fixture.source_title,
                source_version=fixture.source_version,
                publication_date=fixture.publication_date,
                retrieval_date=retrieval.retrieved_at,
                jurisdiction=fixture.jurisdiction,
                evidence_domain=fixture.evidence_domain,
                source_statement=fixture.source_statement,
                source_excerpt=fixture.source_excerpt,
                source_location=fixture.source_location,
                structured_observation=fixture.structured_observation,
                applicability_status=fixture.applicability_status,
                conflict_group_id=fixture.conflict_group_id,
                withdrawn_or_updated=fixture.withdrawn_or_updated,
                created_at=retrieval.retrieved_at,
            )
            entries.append(entry)
            entry_fixture_map[ledger_id] = fixture
    return sorted(entries, key=lambda item: item.ledger_entry_id), entry_fixture_map


def _annotate_duplicates_updates_and_conflicts(entries, fixture_records):
    by_exact = defaultdict(list)
    by_source = defaultdict(list)
    by_conflict = defaultdict(list)
    for entry in entries:
        exact_key = (
            entry.source_identifier,
            entry.source_version,
            _hash_payload(entry.source_statement),
        )
        by_exact[exact_key].append(entry)
        by_source[(entry.finding_id, entry.source_identifier)].append(entry)
        fixture = fixture_records[entry.ledger_entry_id]
        conflict_key = fixture.conflict_group_id or (
            f"{entry.finding_id}:{entry.evidence_domain.value}"
            if fixture.interpretation_tag
            else None
        )
        if conflict_key:
            by_conflict[conflict_key].append(entry)

    updates: dict[str, dict[str, Any]] = defaultdict(dict)
    for group in by_exact.values():
        ordered = sorted(group, key=lambda item: item.ledger_entry_id)
        if len(ordered) > 1:
            duplicate_group_id = _stable_id("duplicate-group", [item.ledger_entry_id for item in ordered])
            first = ordered[0]
            for item in ordered:
                updates[item.ledger_entry_id]["duplicate_group_id"] = duplicate_group_id
                if item != first:
                    updates[item.ledger_entry_id]["duplicate_of"] = first.ledger_entry_id

    for group in by_source.values():
        ordered = sorted(group, key=lambda item: (item.publication_date or "", item.source_version, item.ledger_entry_id))
        previous = None
        for item in ordered:
            if previous and item.source_version != previous.source_version:
                updates[item.ledger_entry_id]["newer_version_of"] = previous.ledger_entry_id
                updates[item.ledger_entry_id]["supersedes_source_record"] = previous.ledger_entry_id
                updates[previous.ledger_entry_id]["superseded_by"] = item.ledger_entry_id
            previous = item

    for conflict_key, group in by_conflict.items():
        tags = {
            fixture_records[item.ledger_entry_id].interpretation_tag
            for item in group
            if fixture_records[item.ledger_entry_id].interpretation_tag
        }
        if len(tags) > 1 or any(
            fixture_records[item.ledger_entry_id].conflict_group_id for item in group
        ) and len(group) > 1:
            conflict_group_id = _stable_id("conflict-group", conflict_key)
            for item in group:
                updates[item.ledger_entry_id].update(
                    {
                        "conflict_detected": True,
                        "conflict_group_id": conflict_group_id,
                        "conflict_description": _CONFLICT_WORDING,
                    }
                )
    return [
        item.model_copy(update=updates.get(item.ledger_entry_id, {}))
        for item in entries
    ]


def _build_summaries(
    requests: list[EvidenceSummaryRequest],
    entries: list[EvidenceLedgerEntry],
) -> list[GeneratedEvidenceSummary]:
    summaries = []
    for request in sorted(requests, key=lambda item: item.summary_request_id):
        source_ids = sorted(
            item.ledger_entry_id for item in entries if item.finding_id == request.finding_id
        )
        if not source_ids:
            continue
        summaries.append(
            GeneratedEvidenceSummary(
                summary_id=_stable_id(
                    "summary",
                    {"request_id": request.summary_request_id, "source_ids": source_ids},
                ),
                finding_id=request.finding_id,
                system_summary=(
                    f"{len(source_ids)} source-linked ledger record(s) were assembled for human review. "
                    "This proposed summary does not resolve conflicts, assign evidence strength, apply ACMG criteria, "
                    "or determine pathogenicity, causality, or diagnosis."
                ),
                summary_based_on_source_ids=source_ids,
                summary_limitations=[
                    *request.summary_limitations,
                    "Source statements remain authoritative and separate from this system-generated summary.",
                ],
            )
        )
    return summaries


def _audit_history(source_results, normalized_findings, retrieval_records, ledger_entries, review_actions):
    events = []
    for result in source_results:
        events.append(
            {
                "event": "source_result_recorded",
                "result_id": result.result_id,
                "report_version": result.provenance.report_version,
                "source_document_hash": result.provenance.source_document_hash,
                "timestamp": result.provenance.entered_at,
                "source_state": "source_reported",
            }
        )
    for finding in normalized_findings:
        events.append(
            {
                "event": "normalization_evaluated",
                "finding_id": finding.finding_id,
                "rule_id": finding.normalization_rule_id,
                "rule_version": finding.normalization_version,
                "status": finding.normalization_status.value,
                "timestamp": finding.normalization_timestamp,
                "source_state": "normalized",
            }
        )
    for retrieval in retrieval_records:
        events.append(
            {
                "event": "bounded_retrieval_recorded",
                "retrieval_id": retrieval.retrieval_id,
                "query_id": retrieval.query_id,
                "source_name": retrieval.source_name,
                "source_version": retrieval.source_version,
                "status": retrieval.state.value,
                "timestamp": retrieval.retrieved_at,
            }
        )
    for entry in ledger_entries:
        events.append(
            {
                "event": "immutable_ledger_entry_created",
                "ledger_entry_id": entry.ledger_entry_id,
                "source_identifier": entry.source_identifier,
                "source_version": entry.source_version,
                "timestamp": entry.created_at,
            }
        )
    for action in review_actions:
        events.append(
            {
                "event": "human_review_action_recorded",
                **action.model_dump(mode="json"),
                "source_state": "human_reviewed",
            }
        )
    return sorted(
        events,
        key=lambda item: (
            str(item.get("timestamp") or ""),
            str(item.get("event") or ""),
            str(item.get("result_id") or item.get("finding_id") or item.get("retrieval_id") or item.get("ledger_entry_id") or item.get("action_id") or ""),
        ),
    )


def _reported_payload(finding: ReportedFinding) -> dict[str, Any]:
    for field in (
        "sequence_variant",
        "copy_number",
        "structural_or_cytogenetic",
        "repeat_expansion",
        "mitochondrial",
        "biochemical",
        "negative_or_uninformative",
    ):
        value = getattr(finding, field)
        if value is not None:
            return value.model_dump(mode="json")
    return {
        "original_text": finding.original_text,
        "original_terminology": finding.original_terminology,
        "original_variant_string": finding.original_variant_string,
    }


def _assembly(value: str | None) -> str | None:
    if not value:
        return None
    aliases = {
        "grch37": "GRCh37",
        "hg19": "GRCh37",
        "grch38": "GRCh38",
        "hg38": "GRCh38",
    }
    return aliases.get(value.strip().lower())


def _clean(value: str | None) -> str | None:
    return value.strip() if value and value.strip() else None


def _clean_lower(value: str | None) -> str | None:
    cleaned = _clean(value)
    return cleaned.lower() if cleaned else None


def _hash_payload(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _stable_id(prefix: str, payload: Any) -> str:
    return f"{prefix}-{_hash_payload(payload)[:20]}"
