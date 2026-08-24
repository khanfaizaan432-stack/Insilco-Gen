from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.insilicopop.agent.loop import AgentLoop
from app.insilicopop.audit_service import InSilicoPopAuditService
from app.insilicopop.benchmarks.agent_trace import AgentMemoryBenchmarkRunner
from app.insilicopop.benchmarks.runner import MemoryBenchmarkRunner
from app.insilicopop.clinical import (
    build_clinical_case_v035_bundle,
    build_clinical_case_v038_workspace,
    run_canonical_handoff_journey,
)
from app.insilicopop.clinical.integrated_analysis_models import TypedRetrievalQuery
from app.insilicopop.clinical.retrieval_registry import ControlledRetrievalService
from app.insilicopop.clinical.tool_execution import WslBcftoolsAdapter, load_registered_wsl_runtime


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.insilicopop.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    benchmark = subparsers.add_parser("benchmark-memory")
    benchmark.add_argument("--scenario", default="all")
    benchmark.add_argument("--token-budget", type=int, default=1000)

    history = subparsers.add_parser("benchmark-history")
    history.add_argument("--last", type=int, default=10)

    agent_memory = subparsers.add_parser("benchmark-agent-memory")
    agent_memory.add_argument("--scenario", default="all")
    agent_memory.add_argument("--budget-chars", type=int, default=1500)
    agent_memory.add_argument("--memory-mode", default="compact")

    v035_demo = subparsers.add_parser(
        "v035-demo",
        help="Run the deterministic v0.35 structured handoff demonstration.",
    )
    v035_demo.add_argument(
        "--fixture",
        default=str(
            Path(__file__).resolve().parents[3]
            / "examples"
            / "insilicopop_demo"
            / "canonical_v035_case.json"
        ),
    )

    v036_demo = subparsers.add_parser(
        "v036-demo",
        help="Run the deterministic v0.36 controlled result-gateway demonstration.",
    )
    v036_demo.add_argument(
        "--fixture",
        default=str(
            Path(__file__).resolve().parents[3]
            / "examples"
            / "insilicopop_demo"
            / "canonical_v036_result_package.json"
        ),
    )

    v037_demo = subparsers.add_parser(
        "v037-demo",
        help="Run the deterministic v0.37 explainable candidate-analysis demonstration.",
    )
    v037_demo.add_argument(
        "--fixture",
        default=str(
            Path(__file__).resolve().parents[3]
            / "examples"
            / "insilicopop_demo"
            / "canonical_v037_candidate_analysis.json"
        ),
    )

    v038_demo = subparsers.add_parser(
        "v038-demo",
        help="Run the deterministic v0.38 integrated multimodal evidence workspace demonstration.",
    )
    v038_demo.add_argument(
        "--fixture",
        default=str(
            Path(__file__).resolve().parents[3]
            / "examples"
            / "insilicopop_demo"
            / "canonical_v038_integrated_analysis.json"
        ),
    )
    v038_demo.add_argument(
        "--authorize-tool",
        action="store_true",
        help="Run only the registered typed WSL BCFtools authorization for the canonical synthetic VCF.",
    )

    v038_live = subparsers.add_parser(
        "v038-live-smoke",
        help="Run bounded read-only PubMed, ClinVar and Ensembl smoke queries for a public synthetic identifier.",
    )
    v038_live.add_argument("--authorize-live", action="store_true")
    v038_live.add_argument("--rsid", default="rs113993960")

    audit = subparsers.add_parser("audit")
    audit.add_argument("--metadata")
    audit.add_argument("--pca")
    audit.add_argument("--admixture")
    audit.add_argument("--fst")
    audit.add_argument("--roh")
    audit.add_argument("--plink-qc")
    audit.add_argument("--selection")
    audit.add_argument("--query")

    agent_run = subparsers.add_parser("agent-run")
    agent_run.add_argument("--metadata")
    agent_run.add_argument("--pca")
    agent_run.add_argument("--admixture")
    agent_run.add_argument("--fst")
    agent_run.add_argument("--roh")
    agent_run.add_argument("--plink-qc")
    agent_run.add_argument("--selection")
    agent_run.add_argument("--vcf")
    agent_run.add_argument("--plink-bed")
    agent_run.add_argument("--plink-bim")
    agent_run.add_argument("--plink-fam")
    agent_run.add_argument("--ped")
    agent_run.add_argument("--map")
    agent_run.add_argument("--pgen")
    agent_run.add_argument("--pvar")
    agent_run.add_argument("--psam")
    agent_run.add_argument("--bam")
    agent_run.add_argument("--cram")
    agent_run.add_argument("--query")
    agent_run.add_argument("--goal")
    agent_run.add_argument("--memory-budget-chars", type=int, default=1500)
    agent_run.add_argument("--memory-mode", default="compact", choices=["compact", "ultra_compact"])
    agent_run.add_argument("--max-steps", type=int, default=8)
    agent_run.add_argument("--llm-provider", default="mock", choices=["mock", "openai_compatible"])
    agent_run.add_argument("--clinical-case-intake")

    args = parser.parse_args(argv)
    if args.command == "benchmark-memory":
        result = MemoryBenchmarkRunner().run(args.scenario, args.token_budget)
        print(f"InSilicoPop memory benchmark run_id={result['run_id']}")
        print(f"winner={result['winner']}")
        print(result["summary"])
        print(json.dumps({"generated_files": result["generated_files"]}, indent=2))
        return 0
    if args.command == "audit":
        result = InSilicoPopAuditService().run(args.query, _audit_uploads(args)).model_dump()
        print(f"InSilicoPop audit run_id={result['run_id']}")
        print(f"reliability_score={result['reliability_score']}")
        print(f"risk_flags={len(result['risk_flags'])}")
        print(json.dumps({"generated_files": result["generated_files"]}, indent=2))
        return 0
    if args.command == "benchmark-history":
        _print_history(args.last)
        return 0
    if args.command == "agent-run":
        result = AgentLoop().run(
            query=args.query or args.goal,
            uploads=_audit_uploads(args),
            max_steps=args.max_steps,
            memory_budget_chars=args.memory_budget_chars,
            memory_mode=args.memory_mode,
            llm_provider=args.llm_provider,
            clinical_case_intake=_json_object_file(args.clinical_case_intake) if args.clinical_case_intake else None,
        )
        top_failure = result["failure_reasons"][0]["message"] if result["failure_reasons"] else "none"
        memory_size = result["carried_memory"].get("size_chars", 0)
        report_path = result["generated_files"]["final_report"]["absolute_path"]
        reliability = result["final_state"].get("reliability_score")
        current_step = result["final_state"].get("current_step")
        print(f"InSilicoPop agent run_id={result['run_id']}")
        print(f"reliability_score={reliability}")
        print(f"final_state_current_step={current_step}")
        print(f"planned_actions={len(result['planned_actions'])}")
        print(f"completed_actions={len(result['completed_actions'])}")
        print(f"blocked_actions={len(result['blocked_actions'])}")
        print(f"failure_reasons={len(result['failure_reasons'])}")
        print(f"command_previews={len(result['command_previews'])}")
        print(f"agent_trace_events={len(result['agent_trace'])}")
        print(f"carried_memory_non_empty={bool(result['carried_memory'])}")
        print(f"top_failure_reason={top_failure}")
        print(f"memory_size_chars={memory_size}")
        print(f"generated_report={report_path}")
        print("external_llm_called=false")
        print("external_tools_executed=false")
        specialist = result["final_state"].get("specialist_agent_workspace") or {}
        print(f"specialist_agent_outputs={len(specialist.get('agent_outputs', []))}")
        print(f"candidate_acmg_evidence_items={len(specialist.get('candidate_criteria', []))}")
        print(
            "specialist_review_actions_applied="
            f"{len(specialist.get('applied_review_actions', []))}"
        )
        print(
            "specialist_review_actions_rejected="
            f"{sum(1 for item in specialist.get('review_action_results', []) if item.get('result_status') == 'rejected')}"
        )
        jarvis = (
            result["final_state"].get("jarvis_synthesis_report_workspace") or {}
        )
        print(
            f"jarvis_synthesis_claims={len(jarvis.get('synthesis_claims', []))}"
        )
        print(
            f"jarvis_eligibility_decisions={len(jarvis.get('eligibility_decisions', []))}"
        )
        print(f"jarvis_critic_findings={len(jarvis.get('critic_findings', []))}")
        print(f"draft_report_sections={len(jarvis.get('report_sections', []))}")
        print(
            "report_status="
            f"{jarvis.get('report_status', 'not_generated')}"
        )
        return 0
    if args.command == "benchmark-agent-memory":
        result = AgentMemoryBenchmarkRunner().run(args.scenario, args.budget_chars, args.memory_mode)
        print(f"InSilicoPop agent-memory benchmark run_id={result['run_id']}")
        print(f"winner={result['winner']}")
        print("scenario | method | critical_recall | dependency_recall | blocked_recall | next_step_recall | budget_violations | final_score")
        for method, method_result in result["results"].items():
            aggregate = method_result["aggregate"]
            print(
                f"{result['scenario']} | {method} | {aggregate['final_critical_fact_recall']} | "
                f"{aggregate['downstream_dependency_recall']} | {aggregate['blocked_interpretation_recall']} | "
                f"{aggregate['next_step_dependency_recall']} | {aggregate['budget_violation_count']} | {aggregate['final_score']}"
            )
        return 0
    if args.command == "v035-demo":
        payload = _json_object_file(args.fixture)
        bundle = build_clinical_case_v035_bundle(payload)
        handoff = bundle[9]
        if handoff is None:
            raise ValueError("v0.35 fixture did not produce a valid handoff workspace")
        handoff = run_canonical_handoff_journey(handoff)
        ready_audit_index = next(
            index
            for index, item in enumerate(handoff.audit_history)
            if item.event_type.value == "ready_for_external_handoff"
        )
        external_audit_index = next(
            index
            for index, item in enumerate(handoff.audit_history)
            if item.event_type.value == "handoff_sent"
        )
        external_event = handoff.external_handoff_events[-1]
        summary = {
            "bundle_width": len(bundle),
            "legacy_bundle_widths": [5, 6, 7, 8, 9],
            "case_id": handoff.pseudonymous_case_id,
            "schema_version": handoff.schema_version,
            "handoff_state": handoff.status.value,
            "state": handoff.status.value,
            "journey_states": [
                "assembled",
                "under_human_review",
                "ready_for_external_handoff",
                "externally_handed_off",
            ],
            "ready_for_external_handoff_before_external_event": ready_audit_index < external_audit_index,
            "stage_count": len(handoff.case_stages),
            "artifact_count": len(handoff.artifact_manifest),
            "available_artifact_count": sum(
                item.available for item in handoff.artifact_manifest
            ),
            "blocker_count": sum(
                item.resolution_status == "open" for item in handoff.blockers
            ),
            "unacknowledged_uncertainty_count": (
                handoff.review_readiness.unacknowledged_uncertainty_count
            ),
            "pending_human_decision_count": (
                handoff.review_readiness.pending_human_decision_count
            ),
            "ready_for_external_handoff": (
                handoff.review_readiness.ready_for_external_handoff
            ),
            "report_status": handoff.report_status,
            "human_review_required": handoff.human_review_required,
            "research_use_only": handoff.research_use_only,
            "clinical_approval_granted": handoff.clinical_approval_granted,
            "external_llm_called": handoff.external_llm_called,
            "external_tools_executed": handoff.external_tools_executed,
            "external_handoff_event_id": external_event.event_id,
            "receipt_id": handoff.handoff_receipt.receipt_id,
            "receipt_status": handoff.handoff_receipt.receipt_status.value,
            "packet_sha256": handoff.handoff_packet.packet_sha256,
            "receipt_sha256": handoff.handoff_receipt.receipt_sha256,
            "artifact_file_byte_sha256": {
                item.artifact_id: item.sha256
                for item in handoff.artifact_manifest
                if item.sha256 is not None
            },
            "artifact_canonical_payload_sha256": {
                item.artifact_id: item.canonical_payload_sha256
                for item in handoff.artifact_manifest
            },
            "canonical_action_count": len(handoff.applied_review_actions),
            "snapshot_hash": handoff.snapshot_hash,
        }
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0
    if args.command == "v036-demo":
        payload = _json_object_file(args.fixture)
        bundle = build_clinical_case_v035_bundle(payload)
        gateway = bundle[0].result_gateway
        if gateway is None:
            raise ValueError("v0.36 fixture did not produce a controlled result-gateway result")
        summary = {
            "bundle_width": len(bundle),
            "case_id": gateway.pseudonymous_case_id,
            "schema_version": gateway.schema_version,
            "gateway_version": gateway.gateway_version,
            "package_id": gateway.package_id,
            "package_status": gateway.package_status.value,
            "manifest_verified": gateway.manifest_verified,
            "input_manifest_sha256": gateway.input_manifest_sha256,
            "package_identity_sha256": gateway.package_identity_sha256,
            "file_hashes": {item.safe_relative_path: item.sha256 for item in gateway.input_file_hashes},
            "canonical_file_hashes": {item.safe_relative_path: item.sha256 for item in gateway.canonical_file_hashes},
            "vcf_record_count": gateway.vcf.record_count if gateway.vcf else 0,
            "accepted_record_count": len(gateway.accepted_record_ids),
            "retained_out_of_scope_record_count": len(gateway.retained_out_of_scope_record_ids),
            "multiallelic_source_record_count": gateway.vcf.multiallelic_source_record_count if gateway.vcf else 0,
            "adapter_statuses": [item.status.value for item in gateway.adapter_results],
            "adapter_provenance_count": len(gateway.tool_provenance),
            "reference_dependent_left_normalization_performed": False,
            "draft_not_clinically_approved": gateway.draft_not_clinically_approved,
            "human_review_required": gateway.human_review_required,
            "external_tools_executed": gateway.external_tools_executed,
            "external_api_call_made": gateway.external_api_call_made,
            "diagnosis_made": gateway.diagnosis_made,
            "treatment_recommendation_made": gateway.treatment_recommendation_made,
            "final_acmg_classification_made": gateway.final_acmg_classification_made,
            "error_codes": [item.code for item in gateway.errors],
            "warning_codes": [item.code for item in gateway.warnings],
        }
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0
    if args.command == "v037-demo":
        payload = _load_v037_fixture(args.fixture)
        bundle = build_clinical_case_v035_bundle(payload)
        analysis = bundle[0].candidate_analysis
        if analysis is None:
            raise ValueError("v0.37 fixture did not produce a candidate-analysis result")
        negative = analysis.negative_unresolved_result
        summary = {
            "bundle_width": len(bundle),
            "case_id": analysis.pseudonymous_case_id,
            "schema_version": analysis.schema_version,
            "algorithm_version": analysis.algorithm_version,
            "analysis_status": analysis.analysis_status.value,
            "ranking_rule_version": analysis.ranking_rule.rule_version,
            "ranking_weight_version": analysis.ranking_rule.weight_version,
            "support_threshold": analysis.ranking_rule.support_threshold,
            "tie_epsilon": analysis.ranking_rule.tie_epsilon,
            "ranked_candidates": [
                {
                    "candidate_id": item.candidate_identity.candidate_id,
                    "source_record_id": item.candidate_identity.source_record.source_record_id,
                    "rank": item.deterministic_rank,
                    "score": item.aggregate_score,
                    "tied": item.tied,
                    "review_status": item.review_status.value,
                    "supporting_evidence_count": len(item.supporting_evidence),
                    "contradicting_evidence_count": len(item.contradicting_evidence),
                }
                for item in analysis.ranked_candidates
            ],
            "excluded_candidates": [
                {
                    "candidate_id": item.candidate_id,
                    "codes": sorted({trace.code.value for trace in item.exclusion_history}),
                }
                for item in analysis.excluded_candidates
            ],
            "exclusion_trace_count": len(analysis.exclusion_trace),
            "family": {
                "shape": analysis.family_segregation.family_shape.value,
                "member_count": analysis.family_segregation.member_count,
                "tested_member_count": analysis.family_segregation.tested_member_count,
                "missing_relative_ids": list(analysis.family_segregation.missing_relative_ids),
            },
            "negative_unresolved_result": {
                "no_sufficiently_supported_candidate": negative.no_sufficiently_supported_candidate,
                "summary": negative.summary,
                "retained_candidate_ids": list(negative.retained_candidate_ids),
                "excluded_candidate_ids": list(negative.excluded_candidate_ids),
                "unsupported_result_types": list(negative.unsupported_result_types),
                "unavailable_adapters": list(negative.unavailable_adapters),
            },
            "source_record_ids": list(analysis.source_record_ids),
            "identities": {
                "v036_package_identity_sha256": analysis.v036_package_identity_sha256,
                "v036_manifest_identity_sha256": analysis.v036_manifest_identity_sha256,
                "phenotype_snapshot_identity_sha256": analysis.phenotype_snapshot_identity_sha256,
                "family_snapshot_identity_sha256": analysis.family_snapshot_identity_sha256,
                "assay_coverage_identity_sha256": analysis.assay_coverage_identity_sha256,
                "evidence_input_identity_sha256": analysis.evidence_input_identity_sha256,
                "ranking_input_identity_sha256": analysis.ranking_input_identity_sha256,
                "ranking_output_identity_sha256": analysis.ranking_output_identity_sha256,
                "analysis_identity_sha256": analysis.analysis_identity_sha256,
            },
            "safety": {
                "research_use_only": analysis.research_use_only,
                "human_review_required": analysis.human_review_required,
                "draft_not_clinically_approved": analysis.draft_not_clinically_approved,
                "diagnosis_made": analysis.diagnosis_made,
                "final_acmg_classification_made": analysis.final_acmg_classification_made,
                "external_api_call_made": analysis.external_api_call_made,
                "external_llm_called": analysis.external_llm_called,
                "external_tools_executed": analysis.external_tools_executed,
            },
        }
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0
    if args.command == "v038-demo":
        payload = _load_v038_fixture(args.fixture)
        tool_adapter = None
        tool_execution_authorization = None
        if args.authorize_tool:
            runtime_binding, tool_execution_authorization = load_registered_wsl_runtime()
            tool_adapter = WslBcftoolsAdapter(
                runtime_binding=runtime_binding,
                authorization=tool_execution_authorization,
            )
        workspace = build_clinical_case_v038_workspace(
            payload,
            tool_adapter=tool_adapter,
            tool_execution_authorization=tool_execution_authorization,
        )
        summary = {
            "case_id": workspace.pseudonymous_case_id,
            "schema_version": workspace.schema_version,
            "algorithm_version": workspace.algorithm_version,
            "rule_version": workspace.rule_version,
            "workspace_id": workspace.workspace_id,
            "workspace_status": workspace.status.value,
            "status_reasons": list(workspace.status_reasons),
            "bundle_width": 10,
            "navigator_stage_count": 18,
            "ranked_candidates": [
                {
                    "candidate_id": item.candidate_id,
                    "source_record_id": item.source_record_id,
                    "rank": item.deterministic_rank,
                    "score": item.aggregate_score,
                    "state": item.candidate_state,
                }
                for item in workspace.ranked_candidates
            ],
            "excluded_candidates": [
                {"candidate_id": item.candidate_id, "source_record_id": item.source_record_id, "state": item.candidate_state}
                for item in workspace.excluded_candidates
            ],
            "filter_history_count": len(workspace.filter_history),
            "paper_count": len(workspace.papers),
            "paper_pmids": [item.pmid for item in workspace.papers],
            "paper_dois": [item.doi for item in workspace.papers if item.doi],
            "database_evidence_count": len(workspace.database_evidence),
            "database_record_ids": [item.record_id for item in workspace.database_evidence],
            "retrieval_event_count": len(workspace.retrieval_events),
            "retrieval_sources": sorted({item.source_id for item in workspace.retrieval_events}),
            "retrieval_cache_statuses": [item.cache_status.value for item in workspace.retrieval_events],
            "evidence_lifecycle": workspace.evidence_lifecycle_summary.model_dump(mode="json"),
            "external_tool_executions": [_v038_tool_execution_summary(item) for item in workspace.external_tool_executions],
            "cnv_count": len(workspace.supplied_cnv_findings),
            "mitochondrial_count": len(workspace.supplied_mitochondrial_findings),
            "mosaicism_count": len(workspace.mosaicism_measurements),
            "human_review_proposal_count": len(workspace.human_review_proposals),
            "identities": {
                "input_integrity_sha256": workspace.input_integrity.input_integrity_sha256,
                "v036_manifest_identity_sha256": workspace.identity_chain.v036_manifest_identity_sha256,
                "v036_result_gateway_identity_sha256": workspace.identity_chain.v036_result_gateway_identity_sha256,
                "v037_ranking_input_identity_sha256": workspace.identity_chain.v037_ranking_input_identity_sha256,
                "v037_ranking_output_identity_sha256": workspace.identity_chain.v037_ranking_output_identity_sha256,
                "candidate_analysis_identity_sha256": workspace.identity_chain.candidate_analysis_identity_sha256,
                "multimodal_findings_identity_sha256": workspace.multimodal_findings_identity_sha256,
                "external_tool_execution_identity_sha256": workspace.identity_chain.external_tool_execution_identity_sha256,
                "retrieval_event_identity_sha256": workspace.identity_chain.retrieval_event_identity_sha256,
                "retrieval_snapshot_identity_sha256": workspace.identity_chain.retrieval_snapshot_identity_sha256,
                "evidence_lifecycle_identity_sha256": workspace.identity_chain.evidence_lifecycle_identity_sha256,
                "integrated_workspace_identity_sha256": workspace.integrated_workspace_identity_sha256,
                "final_integrity_sha256": workspace.final_integrity_sha256,
            },
            "safety": {
                "research_use_only": workspace.research_use_only,
                "human_review_required": workspace.human_review_required,
                "draft_not_clinically_approved": workspace.draft_not_clinically_approved,
                "diagnosis_performed": workspace.diagnosis_performed,
                "treatment_recommended": workspace.treatment_recommended,
                "test_ordered": workspace.test_ordered,
                "final_acmg_classification_performed": workspace.final_acmg_classification_performed,
                "clinical_signout_performed": workspace.clinical_signout_performed,
                "raw_bytes_persisted": workspace.raw_bytes_persisted,
                "external_llm_called": workspace.external_llm_called,
            },
        }
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0
    if args.command == "v038-live-smoke":
        if not args.authorize_live:
            print(json.dumps({"status": "blocked", "reason": "pass --authorize-live to record the explicit human authorization checkpoint"}, indent=2, sort_keys=True))
            return 2
        rsid = args.rsid
        queries = (
            TypedRetrievalQuery(source_id="pubmed", rsid=rsid, gene="CFTR", condition_terms=("cystic fibrosis",), query_id="pubmed-smoke"),
            TypedRetrievalQuery(source_id="clinvar", rsid=rsid, query_id="clinvar-smoke"),
            TypedRetrievalQuery(source_id="ensembl", rsid=rsid, assembly="GRCh38", query_id="ensembl-smoke"),
        )
        service = ControlledRetrievalService(allow_live=True, human_authorized=True)
        results = service.retrieve_many(queries)
        output = {
            "status": "complete" if all(item.event.failure_state.value == "none" for item in results) else "partial",
            "authorization_checkpoint": "human_authorized_for_public_synthetic_identifier_only",
            "queries": [item.typed_query.model_dump(mode="json") for item in (result.event for result in results)],
            "results": [
                {
                    "source_id": result.source_id,
                    "failure_state": result.event.failure_state.value,
                    "failure_reason": result.event.failure_or_quarantine_reason,
                    "cache_status": result.event.cache_status.value,
                    "record_ids": list(result.event.record_ids),
                    "paper_pmids": [item.pmid for item in result.papers],
                    "database_record_ids": [item.record_id for item in result.database_records],
                    "normalized_identity_sha256": result.event.normalized_record_identity_sha256,
                    "raw_response_sha256": result.event.raw_response_sha256,
                }
                for result in results
            ],
        }
        print(json.dumps(output, indent=2, sort_keys=True))
        return 0 if output["status"] == "complete" else 1
    return 2


def _v038_tool_execution_summary(item: Any) -> dict[str, Any]:
    """Expose only parsed, bounded execution provenance in the CLI artifact."""

    summary: dict[str, Any] = {
        "tool": item.tool_name,
        "operation": item.operation,
        "status": item.execution_status.value,
        "availability": item.availability.value,
        "activation": (
            "executed"
            if item.execution_status.value == "completed"
            else (
                "blocked_without_approval"
                if item.error_code in {"TOOL_AUTHORIZATION_REQUIRED", "TOOL_AUTHORIZATION_RECORD_REQUIRED"}
                else "not_completed"
            )
        ),
        "version": item.tool_version,
        "input_sha256": item.input_sha256,
        "output_sha256": item.output_sha256,
        "invocation_identity_sha256": item.invocation_identity_sha256,
    }
    contract = item.typed_invocation.get("execution_contract") if isinstance(item.typed_invocation, dict) else None
    result_summary = item.typed_invocation.get("result_summary") if isinstance(item.typed_invocation, dict) else None
    if isinstance(contract, dict):
        summary["execution_contract"] = contract
    if isinstance(result_summary, dict):
        summary["result_summary"] = result_summary
    return summary


def _audit_uploads(args: argparse.Namespace) -> dict[str, dict[str, bytes | str] | None]:
    mapping = {
        "metadata": args.metadata,
        "pca": args.pca,
        "admixture": args.admixture,
        "fst": args.fst,
        "roh": args.roh,
        "plink_qc": args.plink_qc,
        "selection_scan": args.selection,
        "vcf": getattr(args, "vcf", None),
        "plink_bed": getattr(args, "plink_bed", None),
        "plink_bim": getattr(args, "plink_bim", None),
        "plink_fam": getattr(args, "plink_fam", None),
        "ped": getattr(args, "ped", None),
        "map": getattr(args, "map", None),
        "pgen": getattr(args, "pgen", None),
        "pvar": getattr(args, "pvar", None),
        "psam": getattr(args, "psam", None),
        "bam": getattr(args, "bam", None),
        "cram": getattr(args, "cram", None),
    }
    uploads: dict[str, dict[str, bytes | str] | None] = {}
    for name, path_value in mapping.items():
        if not path_value:
            uploads[name] = None
            continue
        path = Path(path_value)
        uploads[name] = {"content": path.read_bytes(), "filename": path.name}
    return uploads


def _print_history(last: int) -> None:
    history_path = Path(__file__).resolve().parents[1] / "generated" / "benchmarks" / "benchmark_history.jsonl"
    if not history_path.exists():
        print("run_id | scenario | method | critical_recall | compression_ratio | final_score")
        return
    rows = [json.loads(line) for line in history_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    print("run_id | scenario | method | critical_recall | compression_ratio | final_score")
    for row in rows[-last:]:
        critical = row.get("critical_fact_recall", row.get("final_critical_fact_recall", ""))
        ratio = row.get("compression_ratio", "")
        score = row.get("final_score", "")
        print(
            f"{row['run_id']} | {row['scenario']} | {row['method']} | "
            f"{critical} | {ratio} | {score}"
        )


def _json_object_file(path_value: str) -> dict[str, Any]:
    value = json.loads(Path(path_value).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("clinical case intake file must contain a JSON object")
    return value


def _load_v037_fixture(path_value: str) -> dict[str, Any]:
    """Load a standalone v0.37 overlay without changing the v0.36 package fixture."""

    overlay = _json_object_file(path_value)
    base_name = overlay.pop("base_fixture", None)
    if not base_name:
        return overlay
    base_path = Path(path_value).resolve().parent / str(base_name)
    base = _json_object_file(str(base_path))
    base.update(overlay)
    return base


def _load_v038_fixture(path_value: str) -> dict[str, Any]:
    overlay = _json_object_file(path_value)
    base_name = overlay.pop("base_fixture", None)
    if not base_name:
        return overlay
    base_path = Path(path_value).resolve().parent / str(base_name)
    base = _load_v037_fixture(str(base_path))
    base.update(overlay)
    return base


if __name__ == "__main__":
    raise SystemExit(main())
