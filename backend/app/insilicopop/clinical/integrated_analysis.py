from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from app.insilicopop.clinical.integrated_analysis_models import (
    BcftoolsInvocation,
    BcftoolsExecutionAuthorization,
    CANONICAL_BCFTOOLS_OPERATIONS,
    CandidateBinding,
    CandidateReference,
    ConfirmationState,
    CorrectionRetractionState,
    DatabaseEvidenceRecord,
    EvidenceLifecycleState,
    EvidenceLifecycleSummary,
    EvidenceRole,
    ExternalToolExecutionRecord,
    ExternalToolExecutionStatus,
    FilterHistoryEntry,
    FreshnessState,
    HumanReviewProposal,
    IdentityChain,
    InputIntegritySummary,
    IntegratedAnalysisRequest,
    IntegratedAnalysisWorkspace,
    IntegratedWorkspaceStatus,
    RetrievalEvent,
    RetrievalFailureState,
    RetrievalSnapshot,
    ReviewState,
    SourceAvailability,
    SourceClassification,
    SuppliedCNVFinding,
    SuppliedMitochondrialFinding,
    canonical_json,
    sha256_hex,
)
from app.insilicopop.clinical.models import ClinicalCaseIntake
from app.insilicopop.clinical.retrieval_registry import ControlledRetrievalService
from app.insilicopop.clinical.service import build_clinical_case_v035_bundle
from app.insilicopop.clinical.tool_execution import BcftoolsAdapter, WslBcftoolsAdapter


def build_clinical_case_v038_workspace(
    payload: dict[str, Any],
    *,
    base_bundle: tuple[Any, ...] | None = None,
    request_text: str | None = None,
    retrieval_service: ControlledRetrievalService | None = None,
    tool_adapter: BcftoolsAdapter | WslBcftoolsAdapter | None = None,
    tool_execution_authorized: bool = False,
    tool_execution_authorization: BcftoolsExecutionAuthorization | None = None,
) -> IntegratedAnalysisWorkspace:
    del request_text, tool_execution_authorized
    intake = ClinicalCaseIntake.model_validate(payload)
    request = intake.integrated_analysis
    if request is None:
        raise ValueError("v0.38 integrated_analysis request is required")
    bundle = base_bundle or build_clinical_case_v035_bundle(payload)
    if len(bundle) != 10:
        raise ValueError("v0.35 clinical bundle width changed; v0.38 fails closed")
    intake_result = bundle[0]
    gateway = getattr(intake_result, "result_gateway", None)
    candidate_analysis = getattr(intake_result, "candidate_analysis", None)
    if gateway is None or candidate_analysis is None:
        raise ValueError("v0.38 requires valid v0.36 result-gateway and v0.37 candidate-analysis records")
    if request.source_package_identity_sha256 and request.source_package_identity_sha256 != gateway.package_identity_sha256:
        raise ValueError("v0.38 source package identity does not match the v0.36 gateway")
    if request.v036_manifest_identity_sha256 and request.v036_manifest_identity_sha256 != gateway.input_manifest_sha256:
        raise ValueError("v0.38 manifest identity does not match the v0.36 gateway")

    gateway_payload = gateway.model_dump(mode="json")
    gateway_identity = sha256_hex(gateway_payload)
    package_identity = gateway.package_identity_sha256
    manifest_identity = gateway.input_manifest_sha256
    candidate_identity = candidate_analysis.analysis_identity_sha256
    v037_input_identity = candidate_analysis.ranking_input_identity_sha256
    v037_output_identity = candidate_analysis.ranking_output_identity_sha256
    phenotype_identity = candidate_analysis.phenotype_snapshot_identity_sha256
    family_identity = candidate_analysis.family_snapshot_identity_sha256
    input_integrity = sha256_hex(
        {
            "package_identity_sha256": package_identity,
            "manifest_identity_sha256": manifest_identity,
            "gateway_identity_sha256": gateway_identity,
            "candidate_analysis_identity_sha256": candidate_identity,
            "ranking_input_identity_sha256": v037_input_identity,
            "ranking_output_identity_sha256": v037_output_identity,
        }
    )

    _validate_source_bindings(
        tuple(request.supplied_cnv_findings) + tuple(request.supplied_mitochondrial_findings) + tuple(request.mosaicism_measurements),
        gateway,
    )

    ranked_candidates = tuple(_ranked_candidate_reference(item, candidate_identity) for item in candidate_analysis.ranked_candidates)
    excluded_candidates = tuple(_excluded_candidate_reference(item, candidate_identity) for item in candidate_analysis.excluded_candidates)
    all_v037_candidate_ids = {
        *(_candidate_id(item) for item in candidate_analysis.ranked_candidates),
        *(_candidate_id(item) for item in candidate_analysis.excluded_candidates),
    }
    all_v038_candidate_ids = {item.candidate_id for item in ranked_candidates + excluded_candidates}
    if all_v037_candidate_ids != all_v038_candidate_ids:
        raise ValueError("v0.38 candidate references do not retain every v0.37 ranked or excluded candidate")

    filter_history = _filter_history(candidate_analysis, request.filter_history)
    normalized_snv = _normalized_snv_summaries(gateway)
    laboratory_metadata, qc_summary, coverage_blind_spots = _source_quality_summaries(gateway, request)

    external_tool_executions: tuple[ExternalToolExecutionRecord, ...] = ()
    if request.external_tool_request is not None:
        if tool_execution_authorization is None:
            # A caller-controlled boolean or adapter instance is never an execution grant.
            blocked_adapter = BcftoolsAdapter(
                bounded_root=_project_root(),
                authorization_granted=False,
            )
            external_tool_executions = (_execute_bcftools(blocked_adapter, request.external_tool_request),)
        else:
            if not isinstance(tool_adapter, WslBcftoolsAdapter):
                raise ValueError("typed WSL BCFtools authorization requires a bound WslBcftoolsAdapter")
            if tool_adapter.authorization is None or (
                tool_adapter.authorization.identity_sha256() != tool_execution_authorization.identity_sha256()
            ):
                raise ValueError("typed WSL BCFtools authorization does not match the bound adapter")
            external_tool_executions = _execute_authorized_wsl_bcftools_suite(
                tool_adapter,
                tool_execution_authorization,
                _deterministic_source_representations(gateway),
            )

    service = retrieval_service or ControlledRetrievalService()
    fixture_by_signature = {item.request_signature: item for item in request.frozen_retrieval_fixtures}
    retrieval_results = tuple(
        service.retrieve(query, frozen_fixture=fixture_by_signature.get(canonical_json(query.model_dump(mode="json"))))
        for query in request.retrieval_queries
    )
    papers = tuple(item for result in retrieval_results for item in result.papers)
    database_records = tuple(item for result in retrieval_results for item in result.database_records) + tuple(request.supplied_database_evidence)
    retrieval_events = tuple(result.event for result in retrieval_results)
    retrieval_snapshot = _retrieval_snapshot(retrieval_events, request.workspace_created_at)
    evidence_lifecycle = _evidence_lifecycle_summary(papers, database_records)
    human_review_proposals = request.human_review_proposals or _review_proposals(
        papers=papers,
        database_records=database_records,
        cnvs=request.supplied_cnv_findings,
        mitochondrial=request.supplied_mitochondrial_findings,
        mosaic=request.mosaicism_measurements,
        coverage_blind_spots=coverage_blind_spots,
        india_context=request.india_context,
    )

    multimodal_identity = sha256_hex(
        {
            "cnv": [item.model_dump(mode="json") for item in request.supplied_cnv_findings],
            "mitochondrial": [item.model_dump(mode="json") for item in request.supplied_mitochondrial_findings],
            "mosaic": [item.model_dump(mode="json") for item in request.mosaicism_measurements],
        }
    )
    tool_identity = sha256_hex([item.model_dump(mode="json") for item in external_tool_executions])
    retrieval_identity = sha256_hex([item.model_dump(mode="json") for item in retrieval_events])
    lifecycle_identity = evidence_lifecycle.lifecycle_identity_sha256
    workspace_id = "integrated-" + sha256_hex({"case": intake.pseudonymous_case_id, "package": package_identity, "candidate": candidate_identity})[:24]
    status, status_reasons = _workspace_status(external_tool_executions, retrieval_events, papers, database_records)
    provenance = (
        "supplied:v0.36-result-gateway",
        "candidate_interpretation:v0.37-candidate-analysis",
        "deterministic:insilicopop-integrated-analysis-0.38.0",
        "retrieved:controlled-adapter-registry",
        "human_decision:review-proposals",
    )
    identity_placeholder = sha256_hex({"workspace": workspace_id, "placeholder": True})
    chain = IdentityChain(
        supplied_package_identity_sha256=package_identity,
        v036_manifest_identity_sha256=manifest_identity,
        v036_result_gateway_identity_sha256=gateway_identity,
        phenotype_identity_sha256=phenotype_identity,
        family_identity_sha256=family_identity,
        v037_ranking_input_identity_sha256=v037_input_identity,
        v037_ranking_output_identity_sha256=v037_output_identity,
        candidate_analysis_identity_sha256=candidate_identity,
        multimodal_findings_identity_sha256=multimodal_identity,
        external_tool_execution_identity_sha256=tool_identity,
        retrieval_event_identity_sha256=retrieval_identity,
        retrieval_snapshot_identity_sha256=retrieval_snapshot.normalized_record_identity_sha256,
        evidence_lifecycle_identity_sha256=lifecycle_identity,
        integrated_workspace_identity_sha256=identity_placeholder,
        final_integrity_sha256=identity_placeholder,
    )
    workspace = IntegratedAnalysisWorkspace(
        workspace_id=workspace_id,
        pseudonymous_case_id=intake.pseudonymous_case_id,
        status=status,
        status_reasons=status_reasons,
        input_integrity=InputIntegritySummary(
            source_package_identity_sha256=package_identity,
            v036_manifest_identity_sha256=manifest_identity,
            v036_result_gateway_identity_sha256=gateway_identity,
            v037_analysis_identity_sha256=candidate_identity,
            v037_ranking_input_identity_sha256=v037_input_identity,
            v037_ranking_output_identity_sha256=v037_output_identity,
            input_integrity_sha256=input_integrity,
        ),
        laboratory_assay_metadata=laboratory_metadata,
        qc_summary=qc_summary,
        coverage_blind_spots=coverage_blind_spots,
        normalized_snv_small_indel_summaries=normalized_snv,
        external_tool_executions=external_tool_executions,
        annotation_summaries=tuple(request.candidate_acmg_evidence_organization),
        filter_history=filter_history,
        ranked_candidates=ranked_candidates,
        excluded_candidates=excluded_candidates,
        family_segregation_findings=_family_findings(candidate_analysis),
        supplied_cnv_findings=tuple(request.supplied_cnv_findings),
        supplied_mitochondrial_findings=tuple(request.supplied_mitochondrial_findings),
        mosaicism_measurements=tuple(request.mosaicism_measurements),
        papers=papers,
        database_evidence=database_records,
        retrieval_events=retrieval_events,
        retrieval_snapshot=retrieval_snapshot,
        evidence_lifecycle_summary=evidence_lifecycle,
        conflicts_and_limitations=_conflicts_and_limitations(papers, database_records, external_tool_executions, retrieval_events),
        candidate_acmg_evidence_organization=tuple(request.candidate_acmg_evidence_organization),
        specialist_outputs=tuple(request.specialist_outputs),
        human_review_proposals=tuple(human_review_proposals),
        draft_report_inputs=tuple(request.draft_report_inputs),
        india_context=request.india_context,
        provenance=provenance,
        review_state=ReviewState.PENDING,
        identity_chain=chain,
        multimodal_findings_identity_sha256=multimodal_identity,
        integrated_workspace_identity_sha256=identity_placeholder,
        final_integrity_sha256=identity_placeholder,
    )
    workspace_identity = sha256_hex(workspace._workspace_payload())
    workspace = workspace.model_copy(update={
        "integrated_workspace_identity_sha256": workspace_identity,
        "identity_chain": workspace.identity_chain.model_copy(update={"integrated_workspace_identity_sha256": workspace_identity}),
    })
    final_identity = sha256_hex(workspace._final_payload())
    workspace = workspace.model_copy(update={
        "final_integrity_sha256": final_identity,
        "identity_chain": workspace.identity_chain.model_copy(update={"final_integrity_sha256": final_identity}),
    })
    workspace.verify_integrity()
    return workspace


def _project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _validate_source_bindings(findings: Iterable[Any], gateway: Any) -> None:
    manifest = {item.safe_relative_path: item.sha256 for item in gateway.manifest_entries}
    for finding in findings:
        binding = finding.source_binding
        if binding.source_package_identity_sha256 != gateway.package_identity_sha256:
            raise ValueError(f"{finding.finding_id} source package binding is stale or forged")
        if binding.source_manifest_identity_sha256 != gateway.input_manifest_sha256:
            raise ValueError(f"{finding.finding_id} source manifest binding is stale or forged")
        actual_hash = manifest.get(binding.source_manifest_entry_path)
        if actual_hash is None or actual_hash != binding.source_manifest_entry_sha256:
            raise ValueError(f"{finding.finding_id} source manifest entry binding is stale or forged")


def _candidate_id(item: Any) -> str:
    identity = getattr(item, "candidate_identity", None)
    if identity is not None:
        return str(getattr(identity, "candidate_id", "candidate"))
    return str(getattr(item, "candidate_id", "candidate"))


def _source_record_id(item: Any) -> str:
    identity = getattr(item, "candidate_identity", None)
    source = getattr(identity, "source_record", None) if identity is not None else None
    return str(getattr(source, "source_record_id", getattr(item, "source_record_id", _candidate_id(item))))


def _ranked_candidate_reference(item: Any, analysis_identity: str) -> CandidateReference:
    identity = getattr(item, "candidate_identity", None)
    source = getattr(identity, "source_record", None) if identity is not None else None
    return CandidateReference(
        candidate_id=_candidate_id(item),
        source_record_id=_source_record_id(item),
        gene=getattr(source, "gene", None),
        variant=getattr(source, "submitted_representation", getattr(source, "variant", None)),
        deterministic_rank=getattr(item, "deterministic_rank", None),
        aggregate_score=getattr(item, "aggregate_score", None),
        candidate_state=str(getattr(getattr(item, "review_status", None), "value", getattr(item, "review_status", "ranked"))),
        v037_analysis_identity_sha256=analysis_identity,
    )


def _excluded_candidate_reference(item: Any, analysis_identity: str) -> CandidateReference:
    source_record_id = getattr(item, "source_record_id", None) or getattr(item, "candidate_id", "candidate")
    return CandidateReference(
        candidate_id=str(getattr(item, "candidate_id", "candidate")),
        source_record_id=str(source_record_id),
        gene=getattr(item, "gene", None),
        variant=getattr(item, "variant", None),
        candidate_state="excluded",
        v037_analysis_identity_sha256=analysis_identity,
    )


def _filter_history(candidate_analysis: Any, supplied: Iterable[FilterHistoryEntry]) -> tuple[FilterHistoryEntry, ...]:
    entries: list[FilterHistoryEntry] = list(supplied)
    existing_ids = {item.filter_event_id for item in entries}
    for index, trace in enumerate(candidate_analysis.exclusion_trace):
        payload = trace.model_dump(mode="json") if hasattr(trace, "model_dump") else dict(trace)
        event_id = f"v037-filter-{index + 1:04d}"
        if event_id in existing_ids:
            continue
        code = str(payload.get("code", "candidate_analysis_exclusion"))
        entries.append(FilterHistoryEntry(
            filter_event_id=event_id,
            candidate_id=payload.get("candidate_id"),
            source_record_id=payload.get("source_record_id"),
            rule=code,
            reason=str(payload.get("reason") or payload.get("message") or "Retained v0.37 exclusion trace."),
            rule_version=str(payload.get("rule_version") or candidate_analysis.ranking_rule.rule_version),
            original_state=str(payload.get("original_state") or "supplied"),
            resulting_state=str(payload.get("resulting_state") or "excluded"),
            action="excluded",
        ))
    for index, item in enumerate(candidate_analysis.ranked_candidates):
        event_id = f"v037-rank-{index + 1:04d}"
        if event_id in existing_ids:
            continue
        entries.append(FilterHistoryEntry(
            filter_event_id=event_id,
            candidate_id=_candidate_id(item),
            source_record_id=_source_record_id(item),
            rule="v037-deterministic-ranking",
            reason="Retained with the frozen v0.37 deterministic rank; v0.38 evidence retrieval does not change this rank.",
            rule_version=candidate_analysis.ranking_rule.rule_version,
            original_state="supplied",
            resulting_state="ranked",
            action="ranked",
        ))
    return tuple(sorted(entries, key=lambda item: item.filter_event_id))


def _normalized_snv_summaries(gateway: Any) -> tuple[dict[str, Any], ...]:
    vcf = gateway.vcf
    if vcf is None:
        return ()
    summaries: list[dict[str, Any]] = []
    for record in vcf.records:
        payload = record.model_dump(mode="json")
        payload.pop("raw_bytes", None)
        payload.pop("source_bytes", None)
        summaries.append({
            key: payload.get(key)
            for key in (
                "record_id",
                "source_record_id",
                "source_record_sha256",
                "chromosome",
                "position",
                "reference_allele",
                "alternate_allele",
                "variant_scope",
                "filter_status",
                "quality",
                "source_state",
                "normalized_state",
                "normalized_chromosome",
                "normalized_position",
                "normalized_reference_allele",
                "normalized_alternate_allele",
                "source_alt_index",
                "source_alt_count",
                "decomposition_performed",
                "reference_dependent_left_normalization_performed",
                "sample_calls",
                "review_status",
                "reason_if_out_of_scope",
            )
            if key in payload
        })
    return tuple(summaries)


def _source_quality_summaries(gateway: Any, request: IntegratedAnalysisRequest) -> tuple[dict[str, Any], dict[str, Any], tuple[dict[str, Any], ...]]:
    laboratory = gateway.laboratory_report.model_dump(mode="json") if gateway.laboratory_report else {}
    laboratory = {key: value for key, value in laboratory.items() if "raw" not in key.casefold() and "byte" not in key.casefold()}
    qc = gateway.qc.model_dump(mode="json") if gateway.qc else {}
    coverage = gateway.coverage.model_dump(mode="json") if gateway.coverage else {}
    blind_spots = tuple(request.coverage_blind_spots) + (({"coverage_summary": coverage} if coverage else {}),)
    return request.laboratory_assay_metadata or laboratory, request.qc_summary or qc, tuple(item for item in blind_spots if item)


def _family_findings(candidate_analysis: Any) -> tuple[dict[str, Any], ...]:
    family = candidate_analysis.family_segregation
    payload = family.model_dump(mode="json")
    return ({key: payload[key] for key in ("family_shape", "member_count", "tested_member_count", "missing_relative_ids") if key in payload},)


def _execute_bcftools(adapter: BcftoolsAdapter, invocation: BcftoolsInvocation) -> ExternalToolExecutionRecord:
    input_path = _project_root() / invocation.input_relative_path if invocation.input_relative_path else None
    output_path = None
    if invocation.operation == "decompose_multiallelic":
        output_path = adapter.bounded_root / "v038-decomposed.vcf"
    return adapter.execute(invocation, input_path=input_path, output_path=output_path).record


def _execute_authorized_wsl_bcftools_suite(
    adapter: WslBcftoolsAdapter,
    authorization: BcftoolsExecutionAuthorization,
    deterministic_source_representations: dict[str, tuple[str, ...]],
) -> tuple[ExternalToolExecutionRecord, ...]:
    """Run only the fixed authorized suite and retain parsed, bounded provenance."""

    staged_input: Path | None = None
    records: list[ExternalToolExecutionRecord] = []
    try:
        if adapter.availability.available:
            staged_input = adapter.stage_canonical_input(_project_root() / authorization.authorized_input_relative_path)
        for operation in CANONICAL_BCFTOOLS_OPERATIONS:
            invocation = BcftoolsInvocation(
                operation=operation,
                input_relative_path=(None if operation == "version" else authorization.authorized_input_relative_path),
                timeout_seconds=adapter.runtime_binding.max_timeout_seconds,
            )
            output_path = (
                adapter.bounded_root / "output" / "canonical-v038-decomposed.vcf"
                if operation == "decompose_multiallelic"
                else None
            )
            result = adapter.execute(
                invocation,
                input_path=(None if operation == "version" else staged_input),
                output_path=output_path,
            )
            record = result.record
            if operation == "decompose_multiallelic" and result.parsed_output is not None:
                record = _bind_decomposition_to_deterministic_source(record, deterministic_source_representations)
            records.append(record)
    finally:
        cleanup_outcome = adapter.cleanup()
    return tuple(adapter.with_cleanup_outcome(record, cleanup_outcome) for record in records)


def _deterministic_source_representations(gateway: Any) -> dict[str, tuple[str, ...]]:
    records = getattr(getattr(gateway, "vcf", None), "records", ())
    matches: dict[str, list[str]] = {}
    source_groups: dict[str, list[tuple[int, str, str, str, str]]] = {}
    for record in records:
        chromosome = getattr(record, "normalized_chromosome", None)
        position = getattr(record, "normalized_position", None)
        reference = getattr(record, "normalized_reference_allele", None)
        alternate = getattr(record, "normalized_alternate_allele", None)
        source_id = getattr(record, "source_record_id", None)
        if None in (chromosome, position, reference, alternate, source_id):
            continue
        representation = f"{chromosome}:{position}:{reference}>{alternate}"
        matches.setdefault(representation, []).append(str(source_id))
        source_groups.setdefault(str(source_id), []).append(
            (
                int(getattr(record, "source_alt_index", 1)),
                str(chromosome),
                str(position),
                str(reference),
                str(alternate),
            )
        )
    for source_id, entries in source_groups.items():
        ordered = sorted(entries)
        alt_list = ",".join(entry[4] for entry in ordered)
        source_representation = f"{ordered[0][1]}:{ordered[0][2]}:{ordered[0][3]}>{alt_list}"
        matches.setdefault(source_representation, []).append(source_id)
    return {representation: tuple(sorted(set(source_ids))) for representation, source_ids in matches.items()}


def _bind_decomposition_to_deterministic_source(
    record: ExternalToolExecutionRecord,
    deterministic_source_representations: dict[str, tuple[str, ...]],
) -> ExternalToolExecutionRecord:
    payload = dict(record.typed_invocation)
    summary = dict(payload.get("result_summary") or {})
    decomposed_records = tuple(summary.get("decomposed_records") or ())
    matched_source_ids: set[str] = set()
    for decomposed in decomposed_records:
        representation = str(decomposed.get("source_representation", ""))
        source_ids = deterministic_source_representations.get(representation)
        if not source_ids:
            raise ValueError("BCFtools decomposition representation does not match a deterministic source record")
        matched_source_ids.update(source_ids)
    if not decomposed_records:
        raise ValueError("BCFtools decomposition produced no records for the canonical synthetic VCF")
    summary["source_representation_matches_deterministic_record"] = True
    summary["matched_deterministic_source_record_ids"] = tuple(sorted(matched_source_ids))
    summary["representation_comparison_scope"] = "normalized chromosome-position-ref-alt only"
    payload["result_summary"] = summary
    return record.model_copy(update={"typed_invocation": payload})


def _retrieval_snapshot(events: tuple[RetrievalEvent, ...], created_at: str) -> RetrievalSnapshot:
    return RetrievalSnapshot(
        snapshot_id="retrieval-snapshot-" + sha256_hex([item.event_id for item in events])[:24],
        retrieval_event_ids=tuple(item.event_id for item in events),
        normalized_record_identity_sha256=sha256_hex([item.normalized_record_identity_sha256 for item in events]),
        source_releases=tuple(sorted({item.source_release for item in events})),
        replay_mode="fixture" if events and all(item.cache_status.value == "replay" for item in events) else ("live" if events and all(item.cache_status.value != "replay" for item in events) else "mixed"),
        created_at=created_at,
        freshness=FreshnessState.FRESH if events and all(item.freshness == FreshnessState.FRESH for item in events) else FreshnessState.UNKNOWN,
    )


def _evidence_lifecycle_summary(papers: tuple[Any, ...], records: tuple[Any, ...]) -> EvidenceLifecycleSummary:
    states = [item.evidence_lifecycle_state for item in papers + records]
    counts = {state: states.count(state) for state in EvidenceLifecycleState}
    identity = sha256_hex([item.model_dump(mode="json") for item in papers + records])
    return EvidenceLifecycleSummary(
        eligible_count=counts[EvidenceLifecycleState.ELIGIBLE],
        context_only_count=counts[EvidenceLifecycleState.CONTEXT_ONLY],
        quarantined_count=counts[EvidenceLifecycleState.QUARANTINED],
        excluded_count=counts[EvidenceLifecycleState.EXCLUDED],
        lifecycle_identity_sha256=identity,
    )


def _review_proposals(*, papers: tuple[Any, ...], database_records: tuple[Any, ...], cnvs: tuple[SuppliedCNVFinding, ...], mitochondrial: tuple[SuppliedMitochondrialFinding, ...], mosaic: tuple[Any, ...], coverage_blind_spots: tuple[dict[str, Any], ...], india_context: Any) -> tuple[HumanReviewProposal, ...]:
    proposals: list[HumanReviewProposal] = []

    def add(proposal_id: str, proposal_type: str, rationale: str, evidence_ids: tuple[str, ...], priority: str, unresolved: tuple[str, ...] = ()) -> None:
        proposals.append(HumanReviewProposal(
            proposal_id=proposal_id,
            proposal_type=proposal_type,
            rationale=rationale,
            evidence_ids=evidence_ids,
            supporting_evidence=evidence_ids,
            contradicting_evidence=(),
            unresolved_information=unresolved,
            assay_or_evidence_limitations=("Research-use-only review aid; no diagnosis, treatment or test order is produced.",),
            review_priority=priority,
            provenance=("deterministic:integrated-analysis-0.38",),
        ))

    if papers:
        add("review-paper-001", "review_specific_paper", "Review the source-grounded paper paraphrase and its applicability to the bound candidate.", tuple(item.evidence_id for item in papers[:3]), "high")
    clinvar = tuple(item for item in database_records if item.source_id == "clinvar")
    if clinvar:
        add("review-clinvar-001", "resolve_clinvar_conflict", "Review externally submitted ClinVar assertions and any conflicting submissions; do not promote them to a final classification.", tuple(item.evidence_id for item in clinvar), "high")
    add("review-segregation-001", "review_parental_phase_and_segregation", "Review whether parental phase and segregation evidence are available and correctly bound.", (), "medium", ("Parental phase and orthogonal confirmation were not inferred by InSilicoPop.",))
    if coverage_blind_spots:
        add("review-coverage-001", "inspect_poorly_covered_region", "Review coverage blind spots before treating an unresolved result as informative.", (), "high")
    if cnvs:
        add("review-cnv-001", "review_supplied_cnv_scope", "Review the supplied CNV report, assay resolution and dosage evidence; no raw CNV calling or final classification was performed.", tuple(item.finding_id for item in cnvs), "high")
    if mitochondrial:
        add("review-mito-001", "review_mitochondrial_scope", "Review supplied mitochondrial measurement, tissue and assay limitations; no raw mitochondrial calling or maternal inference was performed.", tuple(item.finding_id for item in mitochondrial), "high")
    if mosaic:
        add("review-mosaic-001", "review_mosaicism_confirmation", "Review low-fraction measurement, technical-artifact warning and orthogonal confirmation; no mosaic disease conclusion was made.", tuple(item.measurement_id for item in mosaic), "high")
    if india_context:
        add("review-india-001", "verify_indian_laboratory_access_and_referral_context", "Review NABL scope, access, affordability, turnaround, shipping and appropriate rare-disease referral context with a human reviewer.", (), "medium")
    return tuple(proposals)


def _conflicts_and_limitations(papers: tuple[Any, ...], records: tuple[Any, ...], tools: tuple[Any, ...], events: tuple[Any, ...]) -> tuple[str, ...]:
    limitations: list[str] = []
    if any(item.correction_retraction_status != CorrectionRetractionState.NONE for item in papers):
        limitations.append("A corrected, retracted or expression-of-concern paper remains visible but is not eligible as unqualified support.")
    if any(item.conflict_ids for item in records):
        limitations.append("Conflicting ClinVar submissions remain visible and require human review.")
    if any(item.execution_status != ExternalToolExecutionStatus.COMPLETED for item in tools):
        limitations.append("The requested external tool was unavailable or did not complete; no execution is fabricated.")
    if any(item.failure_state != RetrievalFailureState.NONE for item in events):
        limitations.append("One or more retrieval events were blocked, unavailable or quarantined.")
    limitations.append("External evidence does not alter the frozen v0.37 rank, and candidate ACMG evidence is organized without final classification.")
    return tuple(dict.fromkeys(limitations))


def _workspace_status(tools: tuple[Any, ...], events: tuple[Any, ...], papers: tuple[Any, ...], records: tuple[Any, ...]) -> tuple[IntegratedWorkspaceStatus, tuple[str, ...]]:
    reasons: list[str] = []
    if any(item.execution_status != ExternalToolExecutionStatus.COMPLETED for item in tools):
        if any(item.error_code == "TOOL_AUTHORIZATION_REQUIRED" for item in tools):
            reasons.append("bcftools execution requires explicit controlled approval")
        else:
            reasons.append("bcftools genuine execution is unavailable or incomplete in this environment")
    if any(item.failure_state != RetrievalFailureState.NONE for item in events):
        reasons.append("one or more controlled retrievals are blocked, unavailable or quarantined")
    if not papers:
        reasons.append("no paper evidence was available")
    if not records:
        reasons.append("no database evidence was available")
    return (IntegratedWorkspaceStatus.PARTIAL if reasons else IntegratedWorkspaceStatus.COMPLETE), tuple(reasons)


__all__ = ["build_clinical_case_v038_workspace"]
