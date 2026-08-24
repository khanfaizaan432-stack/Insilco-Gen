from __future__ import annotations

import json
import hashlib
import re
from pathlib import Path, PurePosixPath
from typing import Any

import yaml
from pydantic import BaseModel, Field

from app.insilicopop.clinical.handoff import apply_handoff_action
from app.insilicopop.clinical.candidate_analysis_models import CandidateAnalysisResult
from app.insilicopop.clinical.integrated_analysis_models import IntegratedAnalysisWorkspace
from app.insilicopop.clinical.handoff_models import (
    HandoffReviewAction,
    HandoffReviewActionResult,
    HandoffWorkspaceResult,
)


ALLOWED_ARTIFACTS = {
    "agent_state.json",
    "agent_trace.json",
    "action_proposals.json",
    "llm_action_proposals.json",
    "validated_actions.json",
    "command_previews.yaml",
    "blocked_actions.md",
    "failure_scope.md",
    "carried_memory.json",
    "workflow_selection.json",
    "final_report.md",
}

ALLOWED_REPRODUCIBILITY_ARTIFACTS = {
    "reproducibility/input_inventory.json",
    "reproducibility/workflow_selection.json",
    "reproducibility/command_previews.sh",
    "reproducibility/command_previews.yaml",
    "reproducibility/selected_recipe.json",
    "reproducibility/claim_audit.json",
    "reproducibility/data_governance_audit.json",
    "reproducibility/metadata_registry_audit.json",
    "reproducibility/evidence_retrieval.json",
    "reproducibility/orchestration_trace.json",
    "reproducibility/clinical_case_intake.json",
    "reproducibility/phenotype_hpo_curation.json",
    "reproducibility/pedigree_inheritance_audit.json",
    "reproducibility/candidate_analysis.json",
    "reproducibility/variant_intelligence.json",
    "reproducibility/pre_test_assessment.json",
    "reproducibility/test_strategy_workspace.json",
    "reproducibility/result_evidence_workspace.json",
    "reproducibility/result_gateway.json",
    "reproducibility/specialist_agent_workspace.json",
    "reproducibility/jarvis_synthesis_report_workspace.json",
    "reproducibility/handoff_workspace.json",
    "reproducibility/handoff_packet.json",
    "reproducibility/handoff_receipt.json",
    "reproducibility/results_audit.json",
    "reproducibility/guardrail_decisions.json",
    "reproducibility/provenance_index.json",
    "reproducibility/runtime_lock.json",
    "reproducibility/checksums.sha256",
    "reproducibility/integrated_analysis_workspace.json",
}

SECRET_KEY_NAMES = {
    "api_key",
    "access_token",
    "refresh_token",
    "id_token",
    "auth_token",
    "authorization",
    "authorization_header",
    "auth_header",
    "bearer",
    "password",
    "client_secret",
    "private_key",
    "credential",
    "credentials",
    "token",
    "secret",
}
SECRET_TEXT_PATTERN = re.compile(
    r"(?i)(?:\b(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|authorization|auth[_ -]?header|password|client[_ -]?secret|private[_ -]?key|credentials?)\b\s*[:=]|\bbearer\s+[A-Za-z0-9._~-]+)"
)
REDACTED = "[REDACTED]"


class AgentRunSummary(BaseModel):
    run_id: str
    created_at: str | None = None
    workflow_family: str | None = None
    llm_provider: str = "mock"
    external_llm_called: bool = False
    external_tools_executed: bool = False
    byok_provider: str | None = None
    byok_model: str | None = None
    byok_request_count: int = 0
    byok_estimated_cost_usd: float = 0.0
    current_step: str | None = None
    research_lane: str | None = None
    evidence_retrieval_mode: str | None = None
    evidence_snippet_count: int = 0
    evidence_local_only: bool = True
    orchestration_backend: str | None = None
    orchestration_fallback_used: bool = True
    orchestration_node_count: int = 0
    orchestration_blocked_nodes: list[str] = Field(default_factory=list)
    orchestration_safety_flags: dict[str, bool] = Field(default_factory=dict)
    clinical_intake_completeness: str | None = None
    clinical_policy_block_count: int = 0
    hpo_suggestion_count: int = 0
    hpo_contradiction_count: int = 0
    hpo_promoted_observation_count: int = 0
    hpo_curation_artifact_available: bool = False
    inheritance_audit_count: int = 0
    inheritance_audit_status_counts: dict[str, int] = Field(default_factory=dict)
    relationship_issue_count: int = 0
    mendelian_inconsistency_count: int = 0
    evaluable_parent_child_transmission_count: int = 0
    pedigree_inheritance_audit_artifact_available: bool = False
    candidate_analysis_status: str | None = None
    candidate_analysis_ranked_count: int = 0
    candidate_analysis_excluded_count: int = 0
    candidate_analysis_tied_count: int = 0
    candidate_analysis_no_sufficiently_supported_candidate: bool = False
    candidate_analysis_rule_version: str | None = None
    candidate_analysis_weight_version: str | None = None
    candidate_analysis_identity_sha256: str | None = None
    candidate_analysis_input_identity_sha256: str | None = None
    candidate_analysis_output_identity_sha256: str | None = None
    candidate_analysis_artifact_available: bool = False
    candidate_analysis_integrity_error: str | None = None
    integrated_analysis_status: str | None = None
    integrated_analysis_workspace_id: str | None = None
    integrated_analysis_identity_sha256: str | None = None
    integrated_analysis_final_integrity_sha256: str | None = None
    integrated_analysis_ranked_count: int = 0
    integrated_analysis_excluded_count: int = 0
    integrated_analysis_paper_count: int = 0
    integrated_analysis_database_evidence_count: int = 0
    integrated_analysis_cnv_count: int = 0
    integrated_analysis_mitochondrial_count: int = 0
    integrated_analysis_mosaicism_count: int = 0
    integrated_analysis_review_proposal_count: int = 0
    integrated_analysis_tool_statuses: list[str] = Field(default_factory=list)
    integrated_analysis_artifact_available: bool = False
    integrated_analysis_integrity_error: str | None = None
    variant_intelligence_request_count: int = 0
    variant_validation_status_counts: dict[str, int] = Field(default_factory=dict)
    variant_normalization_status_counts: dict[str, int] = Field(default_factory=dict)
    variant_equivalence_status_counts: dict[str, int] = Field(default_factory=dict)
    variant_intelligence_artifact_available: bool = False
    pre_test_assessment_outcome: str | None = None
    pre_test_open_missing_information_count: int = 0
    pre_test_linkage_issue_count: int = 0
    pre_test_assessment_artifact_available: bool = False
    test_strategy_workspace_status: str | None = None
    test_strategy_proposed_option_count: int = 0
    test_strategy_constrained_option_count: int = 0
    test_strategy_rule_review_item_count: int = 0
    test_strategy_workspace_artifact_available: bool = False
    result_intake_count: int = 0
    result_finding_count: int = 0
    result_normalization_status_counts: dict[str, int] = Field(default_factory=dict)
    result_retrieval_status_counts: dict[str, int] = Field(default_factory=dict)
    evidence_ledger_entry_count: int = 0
    evidence_conflict_count: int = 0
    evidence_duplicate_count: int = 0
    result_evidence_workspace_artifact_available: bool = False
    result_gateway_package_status: str | None = None
    result_gateway_record_count: int = 0
    result_gateway_out_of_scope_record_count: int = 0
    result_gateway_manifest_verified: bool = False
    result_gateway_artifact_available: bool = False
    specialist_agent_spawn_request_count: int = 0
    specialist_agent_output_count: int = 0
    specialist_agent_review_ready_output_count: int = 0
    candidate_acmg_evidence_count: int = 0
    specialist_disagreement_group_count: int = 0
    specialist_applied_review_action_count: int = 0
    specialist_rejected_review_action_count: int = 0
    specialist_agent_workspace_artifact_available: bool = False
    jarvis_briefing_item_count: int = 0
    synthesis_claim_count: int = 0
    excluded_proposed_claim_count: int = 0
    evidence_eligibility_decision_count: int = 0
    context_only_evidence_input_count: int = 0
    excluded_evidence_input_count: int = 0
    critic_finding_count: int = 0
    draft_report_section_count: int = 0
    pending_report_human_decision_count: int = 0
    report_applied_review_action_count: int = 0
    report_rejected_review_action_count: int = 0
    jarvis_synthesis_report_workspace_artifact_available: bool = False
    handoff_state: str | None = None
    handoff_revision: int = 0
    handoff_snapshot_hash: str | None = None
    handoff_ready_for_external_handoff: bool = False
    handoff_blocker_count: int = 0
    handoff_unacknowledged_uncertainty_count: int = 0
    handoff_pending_human_decision_count: int = 0
    handoff_external_event_count: int = 0
    handoff_requested_action_count: int = 0
    handoff_applied_action_count: int = 0
    handoff_rejected_action_count: int = 0
    handoff_workspace_artifact_available: bool = False
    human_review_required: bool = True
    selected_recipe_id: str | None = None
    selected_recipe_maturity_tier: str | None = None
    selected_recipe_status: str | None = None
    artifact_count: int = 0
    has_final_report: bool = False
    has_reproducibility_bundle: bool = False


class AgentRunDetail(AgentRunSummary):
    query: str | None = None
    uploaded_files: dict[str, str] = Field(default_factory=dict)
    selected_recipe: dict[str, Any] | None = None
    claim_audit: dict[str, Any] | None = None
    results_audit: dict[str, Any] | None = None
    data_governance_audit: dict[str, Any] | None = None
    metadata_registry_audit: dict[str, Any] | None = None
    evidence_retrieval: dict[str, Any] | None = None
    orchestration_trace: dict[str, Any] | None = None
    clinical_case_intake: dict[str, Any] | None = None
    phenotype_hpo_curation: dict[str, Any] | None = None
    pedigree_inheritance_audit: dict[str, Any] | None = None
    candidate_analysis: dict[str, Any] | None = None
    integrated_analysis_workspace: dict[str, Any] | None = None
    variant_intelligence: dict[str, Any] | None = None
    pre_test_assessment: dict[str, Any] | None = None
    test_strategy_workspace: dict[str, Any] | None = None
    result_evidence_workspace: dict[str, Any] | None = None
    result_gateway: dict[str, Any] | None = None
    specialist_agent_workspace: dict[str, Any] | None = None
    jarvis_synthesis_report_workspace: dict[str, Any] | None = None
    handoff_workspace: dict[str, Any] | None = None
    byok_runtime: dict[str, Any] | None = None
    artifact_names: list[str] = Field(default_factory=list)


class AgentArtifactSummary(BaseModel):
    artifact_name: str
    file_type: str
    size_bytes: int
    created: bool = True


class AgentArtifactContent(BaseModel):
    artifact_name: str
    file_type: str
    content: Any
    size_bytes: int
    integrity_status: str = "not_applicable"
    integrity_error: str | None = None


class HandoffActionResponse(BaseModel):
    run_id: str
    action_result: HandoffReviewActionResult
    handoff_workspace: HandoffWorkspaceResult


class ReproducibilityBundleSummary(BaseModel):
    run_id: str
    generated: bool
    files: list[str] = Field(default_factory=list)
    file_count: int = 0
    runtime_lock: dict[str, Any] | None = None


class WorkbenchRunStore:
    def __init__(self, generated_root: Path | None = None) -> None:
        self.generated_root = generated_root or Path(__file__).resolve().parents[2] / "generated" / "agents"

    def list_runs(self) -> list[AgentRunSummary]:
        if not self.generated_root.exists():
            return []
        run_dirs = [path for path in self.generated_root.iterdir() if path.is_dir()]
        run_dirs.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        return [self._summary(run_dir) for run_dir in run_dirs if (run_dir / "agent_state.json").is_file()]

    def run_detail(self, run_id: str) -> AgentRunDetail:
        run_dir = self._run_dir(run_id)
        summary = self._summary(run_dir)
        state = self._read_json_if_available(run_dir / "agent_state.json")
        candidate_analysis, candidate_analysis_error = _verified_candidate_from_payload(
            state.get("candidate_analysis") if isinstance(state.get("candidate_analysis"), dict) else None
        )
        integrated_workspace, integrated_workspace_error = _verified_integrated_from_payload(
            state.get("integrated_analysis_workspace")
            if isinstance(state.get("integrated_analysis_workspace"), dict)
            else None
        )
        return AgentRunDetail(
            **summary.model_dump(),
            query=state.get("query"),
            uploaded_files=_string_dict(state.get("uploaded_files", {})),
            selected_recipe=state.get("selected_recipe") if isinstance(state.get("selected_recipe"), dict) else None,
            claim_audit=state.get("claim_audit") if isinstance(state.get("claim_audit"), dict) else None,
            results_audit=state.get("results_audit") if isinstance(state.get("results_audit"), dict) else None,
            data_governance_audit=state.get("data_governance_audit") if isinstance(state.get("data_governance_audit"), dict) else None,
            metadata_registry_audit=state.get("metadata_registry_audit") if isinstance(state.get("metadata_registry_audit"), dict) else None,
            evidence_retrieval=state.get("evidence_retrieval") if isinstance(state.get("evidence_retrieval"), dict) else None,
            orchestration_trace=state.get("orchestration_trace") if isinstance(state.get("orchestration_trace"), dict) else None,
            clinical_case_intake=state.get("clinical_case_intake") if isinstance(state.get("clinical_case_intake"), dict) else None,
            phenotype_hpo_curation=state.get("phenotype_hpo_curation") if isinstance(state.get("phenotype_hpo_curation"), dict) else None,
            pedigree_inheritance_audit=state.get("pedigree_inheritance_audit") if isinstance(state.get("pedigree_inheritance_audit"), dict) else None,
            candidate_analysis=candidate_analysis,
            integrated_analysis_workspace=(
                integrated_workspace
                if integrated_workspace is not None
                else ({"integrity_error": integrated_workspace_error} if integrated_workspace_error else None)
            ),
            variant_intelligence=state.get("variant_intelligence") if isinstance(state.get("variant_intelligence"), dict) else None,
            pre_test_assessment=state.get("pre_test_assessment") if isinstance(state.get("pre_test_assessment"), dict) else None,
            test_strategy_workspace=state.get("test_strategy_workspace") if isinstance(state.get("test_strategy_workspace"), dict) else None,
            result_evidence_workspace=state.get("result_evidence_workspace") if isinstance(state.get("result_evidence_workspace"), dict) else None,
            result_gateway=state.get("result_gateway") if isinstance(state.get("result_gateway"), dict) else None,
            specialist_agent_workspace=state.get("specialist_agent_workspace") if isinstance(state.get("specialist_agent_workspace"), dict) else None,
            jarvis_synthesis_report_workspace=state.get("jarvis_synthesis_report_workspace") if isinstance(state.get("jarvis_synthesis_report_workspace"), dict) else None,
            handoff_workspace=state.get("handoff_workspace") if isinstance(state.get("handoff_workspace"), dict) else None,
            byok_runtime=state.get("byok_runtime") if isinstance(state.get("byok_runtime"), dict) else None,
            artifact_names=[artifact.artifact_name for artifact in self.list_artifacts(run_id)],
        )

    def list_artifacts(self, run_id: str) -> list[AgentArtifactSummary]:
        run_dir = self._run_dir(run_id)
        artifacts = []
        for relative_path in sorted(ALLOWED_ARTIFACTS | ALLOWED_REPRODUCIBILITY_ARTIFACTS):
            path = run_dir / relative_path
            if path.is_file():
                artifacts.append(
                    AgentArtifactSummary(
                        artifact_name=relative_path,
                        file_type=_file_type(path),
                        size_bytes=path.stat().st_size,
                    )
                )
        return artifacts

    def read_artifact(self, run_id: str, artifact_name: str) -> AgentArtifactContent:
        run_dir = self._run_dir(run_id)
        relative_path = self._allowed_relative_artifact(artifact_name)
        path = (run_dir / relative_path).resolve()
        if not _is_relative_to(path, run_dir.resolve()) or not path.is_file():
            raise FileNotFoundError(relative_path)
        content = _read_safe_content(path)
        integrity_status = "not_applicable"
        integrity_error = None
        if relative_path == "reproducibility/candidate_analysis.json":
            checksum_error = _verify_reproducibility_checksum(run_dir, relative_path, path)
            verified, model_error = _verified_candidate_from_payload(content if isinstance(content, dict) else None)
            integrity_error = checksum_error or model_error
            if integrity_error:
                content = {"integrity_error": integrity_error}
                integrity_status = "integrity_error"
            else:
                content = verified
                integrity_status = "verified"
        elif relative_path == "reproducibility/integrated_analysis_workspace.json":
            checksum_error = _verify_reproducibility_checksum_for_path(run_dir, relative_path, path)
            verified, model_error = _verified_integrated_from_payload(content if isinstance(content, dict) else None)
            integrity_error = checksum_error or model_error
            if integrity_error:
                content = {"integrity_error": integrity_error}
                integrity_status = "integrity_error"
            else:
                content = verified
                integrity_status = "verified"
        return AgentArtifactContent(
            artifact_name=relative_path,
            file_type=_file_type(path),
            content=_redact(content),
            size_bytes=path.stat().st_size,
            integrity_status=integrity_status,
            integrity_error=integrity_error,
        )

    def final_report(self, run_id: str) -> AgentArtifactContent:
        return self.read_artifact(run_id, "final_report.md")

    def workflow_selection(self, run_id: str) -> dict[str, Any]:
        content = self.read_artifact(run_id, "workflow_selection.json").content
        return content if isinstance(content, dict) else {}

    def handoff_workspace(self, run_id: str) -> HandoffWorkspaceResult:
        run_dir = self._run_dir(run_id)
        path = run_dir / "reproducibility" / "handoff_workspace.json"
        payload = self._read_json_if_available(path)
        if not payload:
            state = self._read_json_if_available(run_dir / "agent_state.json")
            payload = state.get("handoff_workspace", {}) if isinstance(state, dict) else {}
        if not payload:
            raise FileNotFoundError("reproducibility/handoff_workspace.json")
        return HandoffWorkspaceResult.model_validate(payload)

    def apply_handoff_action(self, run_id: str, action: HandoffReviewAction) -> HandoffActionResponse:
        run_dir = self._run_dir(run_id)
        workspace = self.handoff_workspace(run_id)
        updated_workspace, action_result = apply_handoff_action(workspace, action)
        workspace_payload = updated_workspace.model_dump(mode="json")
        self._write_json_atomic(
            run_dir / "reproducibility" / "handoff_workspace.json",
            workspace_payload,
        )
        self._write_json_atomic(
            run_dir / "reproducibility" / "handoff_packet.json",
            updated_workspace.handoff_packet.model_dump(mode="json"),
        )
        self._write_json_atomic(
            run_dir / "reproducibility" / "handoff_receipt.json",
            updated_workspace.handoff_receipt.model_dump(mode="json"),
        )

        state_path = run_dir / "agent_state.json"
        state = self._read_json_if_available(state_path)
        state["handoff_workspace"] = workspace_payload
        self._write_json_atomic(state_path, state)
        self._refresh_handoff_provenance(run_dir, updated_workspace)
        self._refresh_checksums(run_dir)
        return HandoffActionResponse(
            run_id=run_id,
            action_result=action_result,
            handoff_workspace=updated_workspace,
        )

    def reproducibility(self, run_id: str) -> ReproducibilityBundleSummary:
        run_dir = self._run_dir(run_id)
        files = [name for name in sorted(ALLOWED_REPRODUCIBILITY_ARTIFACTS) if (run_dir / name).is_file()]
        runtime_lock = None
        runtime_lock_path = run_dir / "reproducibility" / "runtime_lock.json"
        if runtime_lock_path.is_file():
            runtime_lock = _redact(self._read_json_if_available(runtime_lock_path))
        return ReproducibilityBundleSummary(
            run_id=run_id,
            generated=bool(files),
            files=files,
            file_count=len(files),
            runtime_lock=runtime_lock,
        )

    def _summary(self, run_dir: Path) -> AgentRunSummary:
        state = self._read_json_if_available(run_dir / "agent_state.json")
        workflow_selection = state.get("workflow_selection", {}) if isinstance(state, dict) else {}
        selected_recipe = state.get("selected_recipe", {}) if isinstance(state, dict) else {}
        selected_recipe = selected_recipe if isinstance(selected_recipe, dict) else {}
        evidence_retrieval = state.get("evidence_retrieval", {}) if isinstance(state, dict) else {}
        evidence_retrieval = evidence_retrieval if isinstance(evidence_retrieval, dict) else {}
        orchestration_trace = state.get("orchestration_trace", {}) if isinstance(state, dict) else {}
        orchestration_trace = orchestration_trace if isinstance(orchestration_trace, dict) else {}
        clinical_case_intake = state.get("clinical_case_intake", {}) if isinstance(state, dict) else {}
        clinical_case_intake = clinical_case_intake if isinstance(clinical_case_intake, dict) else {}
        phenotype_hpo_curation = state.get("phenotype_hpo_curation", {}) if isinstance(state, dict) else {}
        phenotype_hpo_curation = phenotype_hpo_curation if isinstance(phenotype_hpo_curation, dict) else {}
        pedigree_inheritance_audit = state.get("pedigree_inheritance_audit", {}) if isinstance(state, dict) else {}
        pedigree_inheritance_audit = pedigree_inheritance_audit if isinstance(pedigree_inheritance_audit, dict) else {}
        raw_candidate_analysis = state.get("candidate_analysis", {}) if isinstance(state, dict) else {}
        candidate_analysis, candidate_analysis_error = _verified_candidate_from_payload(
            raw_candidate_analysis if isinstance(raw_candidate_analysis, dict) else None
        )
        candidate_analysis = candidate_analysis or {}
        raw_integrated_workspace = state.get("integrated_analysis_workspace", {}) if isinstance(state, dict) else {}
        integrated_workspace, integrated_workspace_error = _verified_integrated_from_payload(
            raw_integrated_workspace if isinstance(raw_integrated_workspace, dict) else None
        )
        integrated_workspace = integrated_workspace or {}
        variant_intelligence = state.get("variant_intelligence", {}) if isinstance(state, dict) else {}
        variant_intelligence = variant_intelligence if isinstance(variant_intelligence, dict) else {}
        pre_test_assessment = state.get("pre_test_assessment", {}) if isinstance(state, dict) else {}
        pre_test_assessment = pre_test_assessment if isinstance(pre_test_assessment, dict) else {}
        test_strategy_workspace = state.get("test_strategy_workspace", {}) if isinstance(state, dict) else {}
        test_strategy_workspace = test_strategy_workspace if isinstance(test_strategy_workspace, dict) else {}
        result_evidence_workspace = state.get("result_evidence_workspace", {}) if isinstance(state, dict) else {}
        result_evidence_workspace = result_evidence_workspace if isinstance(result_evidence_workspace, dict) else {}
        result_gateway = state.get("result_gateway", {}) if isinstance(state, dict) else {}
        result_gateway = result_gateway if isinstance(result_gateway, dict) else {}
        specialist_agent_workspace = state.get("specialist_agent_workspace", {}) if isinstance(state, dict) else {}
        specialist_agent_workspace = specialist_agent_workspace if isinstance(specialist_agent_workspace, dict) else {}
        jarvis_workspace = state.get("jarvis_synthesis_report_workspace", {}) if isinstance(state, dict) else {}
        jarvis_workspace = jarvis_workspace if isinstance(jarvis_workspace, dict) else {}
        handoff_workspace = state.get("handoff_workspace", {}) if isinstance(state, dict) else {}
        handoff_workspace = handoff_workspace if isinstance(handoff_workspace, dict) else {}
        handoff_readiness = handoff_workspace.get("review_readiness", {}) or {}
        handoff_action_results = handoff_workspace.get("review_action_results", []) or []
        byok_runtime = state.get("byok_runtime", {}) if isinstance(state, dict) else {}
        byok_runtime = byok_runtime if isinstance(byok_runtime, dict) else {}
        inheritance_audits = pedigree_inheritance_audit.get("inheritance_audits", []) or []
        inheritance_status_counts: dict[str, int] = {}
        for item in inheritance_audits:
            if isinstance(item, dict):
                status = str(item.get("status", "cannot_evaluate"))
                inheritance_status_counts[status] = inheritance_status_counts.get(status, 0) + 1
        transmission_summary = pedigree_inheritance_audit.get("available_parent_child_transmission_summary", {}) or {}
        candidate_rule = candidate_analysis.get("ranking_rule", {}) or {}
        candidate_ranked = candidate_analysis.get("ranked_candidates", []) or []
        candidate_excluded = candidate_analysis.get("excluded_candidates", []) or []
        candidate_negative = candidate_analysis.get("negative_unresolved_result", {}) or {}
        normalized_findings = result_evidence_workspace.get("normalized_findings", []) or []
        retrieval_records = result_evidence_workspace.get("retrieval_records", []) or []
        ledger_entries = result_evidence_workspace.get("ledger_entries", []) or []
        normalization_status_counts: dict[str, int] = {}
        retrieval_status_counts: dict[str, int] = {}
        for item in normalized_findings:
            if isinstance(item, dict):
                status = str(item.get("normalization_status", "requires_rule_review"))
                normalization_status_counts[status] = normalization_status_counts.get(status, 0) + 1
        for item in retrieval_records:
            if isinstance(item, dict):
                status = str(item.get("state", "not_attempted"))
                retrieval_status_counts[status] = retrieval_status_counts.get(status, 0) + 1
        artifacts = [name for name in ALLOWED_ARTIFACTS | ALLOWED_REPRODUCIBILITY_ARTIFACTS if (run_dir / name).is_file()]
        return AgentRunSummary(
            run_id=run_dir.name,
            created_at=_created_at(run_dir),
            workflow_family=workflow_selection.get("workflow_family") if isinstance(workflow_selection, dict) else None,
            llm_provider=str(state.get("llm_provider", "mock")),
            external_llm_called=bool(state.get("external_llm_called", False)),
            external_tools_executed=bool(state.get("external_tools_executed", False)),
            byok_provider=byok_runtime.get("provider"),
            byok_model=byok_runtime.get("model"),
            byok_request_count=int(byok_runtime.get("request_count", 0) or 0),
            byok_estimated_cost_usd=float(byok_runtime.get("estimated_cost_usd", 0) or 0),
            current_step=state.get("current_step"),
            research_lane=state.get("research_lane"),
            evidence_retrieval_mode=evidence_retrieval.get("retrieval_mode"),
            evidence_snippet_count=int(evidence_retrieval.get("snippets_returned", 0) or 0),
            evidence_local_only=bool(evidence_retrieval.get("local_only", True)),
            orchestration_backend=orchestration_trace.get("orchestration_backend"),
            orchestration_fallback_used=bool(orchestration_trace.get("fallback_used", True)),
            orchestration_node_count=len(orchestration_trace.get("graph_nodes_executed", []) or []),
            orchestration_blocked_nodes=[str(item) for item in orchestration_trace.get("blocked_nodes", []) or []],
            orchestration_safety_flags=orchestration_trace.get("safety_flags", {}) if isinstance(orchestration_trace.get("safety_flags"), dict) else {},
            clinical_intake_completeness=clinical_case_intake.get("intake_completeness"),
            clinical_policy_block_count=len(clinical_case_intake.get("policy_blocks", []) or []),
            hpo_suggestion_count=len(phenotype_hpo_curation.get("hpo_suggestions", []) or []),
            hpo_contradiction_count=len(phenotype_hpo_curation.get("contradictions", []) or []),
            hpo_promoted_observation_count=len(phenotype_hpo_curation.get("promoted_observations", []) or []),
            hpo_curation_artifact_available=(run_dir / "reproducibility" / "phenotype_hpo_curation.json").is_file(),
            inheritance_audit_count=len(inheritance_audits),
            inheritance_audit_status_counts={key: inheritance_status_counts[key] for key in sorted(inheritance_status_counts)},
            relationship_issue_count=len(pedigree_inheritance_audit.get("relationship_issues", []) or []),
            mendelian_inconsistency_count=len(pedigree_inheritance_audit.get("mendelian_inconsistencies", []) or []),
            evaluable_parent_child_transmission_count=int(transmission_summary.get("evaluable_transmission_count", 0) or 0) if isinstance(transmission_summary, dict) else 0,
            pedigree_inheritance_audit_artifact_available=(run_dir / "reproducibility" / "pedigree_inheritance_audit.json").is_file(),
            candidate_analysis_status=candidate_analysis.get("analysis_status"),
            candidate_analysis_ranked_count=len(candidate_ranked),
            candidate_analysis_excluded_count=len(candidate_excluded),
            candidate_analysis_tied_count=sum(
                1 for item in candidate_ranked if isinstance(item, dict) and item.get("tied")
            ),
            candidate_analysis_no_sufficiently_supported_candidate=bool(
                candidate_negative.get("no_sufficiently_supported_candidate", False)
            ),
            candidate_analysis_rule_version=candidate_rule.get("rule_version"),
            candidate_analysis_weight_version=candidate_rule.get("weight_version"),
            candidate_analysis_identity_sha256=candidate_analysis.get("analysis_identity_sha256"),
            candidate_analysis_input_identity_sha256=candidate_analysis.get("ranking_input_identity_sha256"),
            candidate_analysis_output_identity_sha256=candidate_analysis.get("ranking_output_identity_sha256"),
            candidate_analysis_artifact_available=(run_dir / "reproducibility" / "candidate_analysis.json").is_file(),
            candidate_analysis_integrity_error=candidate_analysis_error,
            integrated_analysis_status=integrated_workspace.get("status"),
            integrated_analysis_workspace_id=integrated_workspace.get("workspace_id"),
            integrated_analysis_identity_sha256=integrated_workspace.get("integrated_workspace_identity_sha256"),
            integrated_analysis_final_integrity_sha256=integrated_workspace.get("final_integrity_sha256"),
            integrated_analysis_ranked_count=len(integrated_workspace.get("ranked_candidates", []) or []),
            integrated_analysis_excluded_count=len(integrated_workspace.get("excluded_candidates", []) or []),
            integrated_analysis_paper_count=len(integrated_workspace.get("papers", []) or []),
            integrated_analysis_database_evidence_count=len(integrated_workspace.get("database_evidence", []) or []),
            integrated_analysis_cnv_count=len(integrated_workspace.get("supplied_cnv_findings", []) or []),
            integrated_analysis_mitochondrial_count=len(integrated_workspace.get("supplied_mitochondrial_findings", []) or []),
            integrated_analysis_mosaicism_count=len(integrated_workspace.get("mosaicism_measurements", []) or []),
            integrated_analysis_review_proposal_count=len(integrated_workspace.get("human_review_proposals", []) or []),
            integrated_analysis_tool_statuses=[
                str(item.get("execution_status"))
                for item in integrated_workspace.get("external_tool_executions", []) or []
                if isinstance(item, dict)
            ],
            integrated_analysis_artifact_available=(run_dir / "reproducibility" / "integrated_analysis_workspace.json").is_file(),
            integrated_analysis_integrity_error=integrated_workspace_error,
            variant_intelligence_request_count=len(variant_intelligence.get("normalization_results", []) or []),
            variant_validation_status_counts=_safe_count_dict(variant_intelligence.get("validation_status_counts", {})),
            variant_normalization_status_counts=_safe_count_dict(variant_intelligence.get("normalization_status_counts", {})),
            variant_equivalence_status_counts=_safe_count_dict(variant_intelligence.get("equivalence_status_counts", {})),
            variant_intelligence_artifact_available=(run_dir / "reproducibility" / "variant_intelligence.json").is_file(),
            pre_test_assessment_outcome=pre_test_assessment.get("assessment_outcome"),
            pre_test_open_missing_information_count=int(pre_test_assessment.get("open_missing_information_count", 0) or 0),
            pre_test_linkage_issue_count=len(pre_test_assessment.get("linkage_issues", []) or []),
            pre_test_assessment_artifact_available=(run_dir / "reproducibility" / "pre_test_assessment.json").is_file(),
            test_strategy_workspace_status=test_strategy_workspace.get("workspace_status"),
            test_strategy_proposed_option_count=int(test_strategy_workspace.get("proposed_option_count", 0) or 0),
            test_strategy_constrained_option_count=int(test_strategy_workspace.get("constrained_option_count", 0) or 0),
            test_strategy_rule_review_item_count=len(test_strategy_workspace.get("rule_review_items", []) or []),
            test_strategy_workspace_artifact_available=(run_dir / "reproducibility" / "test_strategy_workspace.json").is_file(),
            result_intake_count=len(result_evidence_workspace.get("source_results", []) or []),
            result_finding_count=len(normalized_findings),
            result_normalization_status_counts={
                key: normalization_status_counts[key] for key in sorted(normalization_status_counts)
            },
            result_retrieval_status_counts={
                key: retrieval_status_counts[key] for key in sorted(retrieval_status_counts)
            },
            evidence_ledger_entry_count=len(ledger_entries),
            evidence_conflict_count=sum(
                1 for item in ledger_entries if isinstance(item, dict) and item.get("conflict_detected")
            ),
            evidence_duplicate_count=sum(
                1 for item in ledger_entries if isinstance(item, dict) and item.get("duplicate_of")
            ),
            result_evidence_workspace_artifact_available=(
                run_dir / "reproducibility" / "result_evidence_workspace.json"
            ).is_file(),
            result_gateway_package_status=result_gateway.get("package_status"),
            result_gateway_record_count=len((result_gateway.get("vcf", {}) or {}).get("records", []) or []) if isinstance(result_gateway.get("vcf"), dict) else 0,
            result_gateway_out_of_scope_record_count=len(result_gateway.get("retained_out_of_scope_record_ids", []) or []),
            result_gateway_manifest_verified=bool(result_gateway.get("manifest_verified", False)),
            result_gateway_artifact_available=(run_dir / "reproducibility" / "result_gateway.json").is_file(),
            specialist_agent_spawn_request_count=len(specialist_agent_workspace.get("spawn_requests", []) or []),
            specialist_agent_output_count=len(specialist_agent_workspace.get("agent_outputs", []) or []),
            specialist_agent_review_ready_output_count=len(specialist_agent_workspace.get("review_ready_output_ids", []) or []),
            candidate_acmg_evidence_count=len(specialist_agent_workspace.get("candidate_criteria", []) or []),
            specialist_disagreement_group_count=len(specialist_agent_workspace.get("disagreement_groups", []) or []),
            specialist_applied_review_action_count=len(
                specialist_agent_workspace.get("applied_review_actions", []) or []
            ),
            specialist_rejected_review_action_count=sum(
                1
                for item in (
                    specialist_agent_workspace.get("review_action_results", []) or []
                )
                if isinstance(item, dict) and item.get("result_status") == "rejected"
            ),
            specialist_agent_workspace_artifact_available=(
                run_dir / "reproducibility" / "specialist_agent_workspace.json"
            ).is_file(),
            jarvis_briefing_item_count=len(
                (jarvis_workspace.get("briefing", {}) or {}).get("items", []) or []
            ),
            synthesis_claim_count=len(
                jarvis_workspace.get("synthesis_claims", []) or []
            ),
            excluded_proposed_claim_count=len(
                jarvis_workspace.get("excluded_proposed_claims", []) or []
            ),
            evidence_eligibility_decision_count=len(
                jarvis_workspace.get("eligibility_decisions", []) or []
            ),
            context_only_evidence_input_count=len(
                (
                    jarvis_workspace.get("reproducibility", {}) or {}
                ).get("context_only_input_ids", [])
                or []
            ),
            excluded_evidence_input_count=len(
                (
                    jarvis_workspace.get("reproducibility", {}) or {}
                ).get("excluded_input_ids", [])
                or []
            ),
            critic_finding_count=len(
                jarvis_workspace.get("critic_findings", []) or []
            ),
            draft_report_section_count=len(
                jarvis_workspace.get("report_sections", []) or []
            ),
            pending_report_human_decision_count=len(
                jarvis_workspace.get("pending_human_decision_ids", []) or []
            ),
            report_applied_review_action_count=len(
                jarvis_workspace.get("applied_review_actions", []) or []
            ),
            report_rejected_review_action_count=sum(
                1
                for item in jarvis_workspace.get("review_action_results", []) or []
                if isinstance(item, dict) and item.get("result_status") == "rejected"
            ),
            jarvis_synthesis_report_workspace_artifact_available=(
                run_dir
                / "reproducibility"
                / "jarvis_synthesis_report_workspace.json"
            ).is_file(),
            handoff_state=handoff_workspace.get("status"),
            handoff_revision=int(handoff_workspace.get("revision", 0) or 0),
            handoff_snapshot_hash=handoff_workspace.get("snapshot_hash"),
            handoff_ready_for_external_handoff=bool(
                handoff_readiness.get("ready_for_external_handoff", False)
            ),
            handoff_blocker_count=sum(
                1
                for item in handoff_workspace.get("blockers", []) or []
                if isinstance(item, dict) and item.get("resolution_status", "open") == "open"
            ),
            handoff_unacknowledged_uncertainty_count=int(
                handoff_readiness.get("unacknowledged_uncertainty_count", 0) or 0
            ),
            handoff_pending_human_decision_count=int(
                handoff_readiness.get("pending_human_decision_count", 0) or 0
            ),
            handoff_external_event_count=len(
                handoff_workspace.get("external_handoff_events", []) or []
            ),
            handoff_requested_action_count=len(
                handoff_workspace.get("requested_review_actions", []) or []
            ),
            handoff_applied_action_count=len(
                handoff_workspace.get("applied_review_actions", []) or []
            ),
            handoff_rejected_action_count=sum(
                1
                for item in handoff_action_results
                if isinstance(item, dict) and item.get("result_status") == "rejected"
            ),
            handoff_workspace_artifact_available=(
                run_dir / "reproducibility" / "handoff_workspace.json"
            ).is_file(),
            human_review_required=True,
            selected_recipe_id=selected_recipe.get("recipe_id"),
            selected_recipe_maturity_tier=selected_recipe.get("maturity_tier"),
            selected_recipe_status=selected_recipe.get("status"),
            artifact_count=len(artifacts),
            has_final_report=(run_dir / "final_report.md").is_file(),
            has_reproducibility_bundle=(run_dir / "reproducibility").is_dir(),
        )

    def _write_json_atomic(self, path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_name(f".{path.name}.tmp")
        temporary_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True),
            encoding="utf-8",
        )
        temporary_path.replace(path)

    def _refresh_handoff_provenance(
        self,
        run_dir: Path,
        workspace: HandoffWorkspaceResult,
    ) -> None:
        provenance_path = run_dir / "reproducibility" / "provenance_index.json"
        provenance = self._read_json_if_available(provenance_path)
        provenance["handoff_workspace"] = {
            "path": "reproducibility/handoff_workspace.json",
            "json_pointer": "/",
            "artifact_class": "structured_human_review_handoff_workspace",
            "schema_version": workspace.schema_version,
            "handoff_state": workspace.status.value,
            "revision": workspace.revision,
            "snapshot_hash": workspace.snapshot_hash,
            "packet_sha256": workspace.handoff_packet.packet_sha256,
            "receipt_sha256": workspace.handoff_receipt.receipt_sha256,
            "report_status": workspace.report_status,
            "human_review_required": True,
            "clinical_approval_granted": False,
        }
        provenance["handoff_packet"] = {
            "path": "reproducibility/handoff_packet.json",
            "json_pointer": "/handoff_packet",
            "artifact_class": "deterministic_handoff_packet",
            "packet_version": workspace.handoff_packet.packet_version,
            "packet_sha256": workspace.handoff_packet.packet_sha256,
            "current_handoff_state": workspace.status.value,
            "artifact_count": len(workspace.handoff_packet.artifact_manifest),
            "report_status": workspace.handoff_packet.report_status,
            "human_review_required": True,
        }
        provenance["handoff_receipt"] = {
            "path": "reproducibility/handoff_receipt.json",
            "json_pointer": "/handoff_receipt",
            "artifact_class": "deterministic_handoff_receipt",
            "receipt_version": workspace.handoff_receipt.receipt_version,
            "receipt_status": workspace.handoff_receipt.receipt_status.value,
            "receipt_sha256": workspace.handoff_receipt.receipt_sha256,
            "handoff_state": workspace.handoff_receipt.handoff_state.value,
            "report_status": workspace.handoff_receipt.report_status,
            "human_review_required": True,
        }
        self._write_json_atomic(provenance_path, provenance)

        runtime_lock_path = run_dir / "reproducibility" / "runtime_lock.json"
        runtime_lock = self._read_json_if_available(runtime_lock_path)
        runtime_lock.update(
            {
                "handoff_state": workspace.status.value,
                "handoff_revision": workspace.revision,
                "handoff_snapshot_hash": workspace.snapshot_hash,
                "handoff_blocker_ids": [item.blocker_id for item in workspace.blockers],
                "handoff_pending_human_decision_ids": [
                    item.decision_id for item in workspace.pending_human_decisions
                ],
                "handoff_uncertainty_ids": [
                    item.uncertainty_id
                    for item in workspace.acknowledgement_required_uncertainties
                ],
                "handoff_external_event_ids": [
                    item.event_id for item in workspace.external_handoff_events
                ],
                "handoff_requested_review_action_ids": [
                    item.action_id for item in workspace.requested_review_actions
                ],
                "handoff_applied_review_action_ids": [
                    item.action_id for item in workspace.applied_review_actions
                ],
                "handoff_rejected_review_action_ids": [
                    item.action_id
                    for item in workspace.review_action_results
                    if item.result_status.value == "rejected"
                ],
                "handoff_ready_for_external_handoff": workspace.review_readiness.ready_for_external_handoff,
                "handoff_report_status": workspace.report_status,
                "handoff_clinical_approval_granted": False,
            }
        )
        self._write_json_atomic(runtime_lock_path, runtime_lock)

    def _refresh_checksums(self, run_dir: Path) -> None:
        checksum_path = run_dir / "reproducibility" / "checksums.sha256"
        if not checksum_path.is_file():
            return
        rows: list[str] = []
        for line in checksum_path.read_text(encoding="utf-8").splitlines():
            if "  " not in line:
                continue
            _, relative_path = line.split("  ", 1)
            path = (run_dir / relative_path).resolve()
            if not _is_relative_to(path, run_dir.resolve()) or not path.is_file():
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            rows.append(f"{digest}  {relative_path.replace(chr(92), '/')}")
        checksum_path.write_text(
            "\n".join(sorted(rows)) + ("\n" if rows else ""),
            encoding="utf-8",
        )

    def _run_dir(self, run_id: str) -> Path:
        if not run_id or any(part in {".", ".."} for part in PurePosixPath(run_id.replace("\\", "/")).parts):
            raise FileNotFoundError(run_id)
        run_dir = (self.generated_root / run_id).resolve()
        root = self.generated_root.resolve()
        if not _is_relative_to(run_dir, root) or not run_dir.is_dir():
            raise FileNotFoundError(run_id)
        return run_dir

    def _allowed_relative_artifact(self, artifact_name: str) -> str:
        normalized = artifact_name.replace("\\", "/").lstrip("/")
        path = PurePosixPath(normalized)
        if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
            raise PermissionError(artifact_name)
        relative_path = path.as_posix()
        if relative_path not in ALLOWED_ARTIFACTS and relative_path not in ALLOWED_REPRODUCIBILITY_ARTIFACTS:
            raise PermissionError(artifact_name)
        return relative_path

    def _read_json_if_available(self, path: Path) -> dict[str, Any]:
        if not path.is_file():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        return payload if isinstance(payload, dict) else {}


def _verified_candidate_from_payload(
    payload: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, str | None]:
    if payload is None:
        return None, None
    try:
        result = CandidateAnalysisResult.verified_load(payload)
    except (TypeError, ValueError) as exc:
        return None, f"candidate analysis integrity verification failed: {exc}"
    return result.model_dump(mode="json"), None


def _verified_integrated_from_payload(
    payload: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, str | None]:
    if payload is None:
        return None, None
    try:
        result = IntegratedAnalysisWorkspace.verified_load(payload)
    except (TypeError, ValueError) as exc:
        return None, f"integrated analysis workspace integrity verification failed: {exc}"
    return result.model_dump(mode="json"), None


def _verify_reproducibility_checksum(run_dir: Path, relative_path: str, path: Path) -> str | None:
    checksum_path = run_dir / "reproducibility" / "checksums.sha256"
    if not checksum_path.is_file():
        return "candidate analysis reproducibility checksum manifest is missing"
    expected = None
    for line in checksum_path.read_text(encoding="utf-8").splitlines():
        if "  " not in line:
            continue
        digest, recorded_path = line.split("  ", 1)
        if recorded_path.replace("\\", "/") == relative_path:
            expected = digest.strip().casefold()
            break
    if expected is None:
        return "candidate analysis is not covered by the reproducibility checksum manifest"
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected:
        return "candidate analysis reproducibility checksum does not match the persisted artifact"
    return None


def _verify_reproducibility_checksum_for_path(run_dir: Path, relative_path: str, path: Path) -> str | None:
    checksum_path = run_dir / "reproducibility" / "checksums.sha256"
    if not checksum_path.is_file():
        return "integrated analysis reproducibility checksum manifest is missing"
    expected = None
    for line in checksum_path.read_text(encoding="utf-8").splitlines():
        if "  " not in line:
            continue
        digest, recorded_path = line.split("  ", 1)
        if recorded_path.replace("\\", "/") == relative_path:
            expected = digest.strip().casefold()
            break
    if expected is None:
        return "integrated analysis workspace is not covered by the reproducibility checksum manifest"
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected:
        return "integrated analysis workspace reproducibility checksum does not match the persisted artifact"
    return None


def _read_safe_content(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix == ".json":
        return json.loads(text)
    if suffix in {".yaml", ".yml"}:
        return yaml.safe_load(text) or []
    return _redact_text(text)


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            if _is_secret_key(str(key)):
                redacted[key] = REDACTED
            else:
                redacted[key] = _redact(item)
        return redacted
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        return _redact_text(value)
    return value


def _redact_text(text: str) -> str:
    redacted_lines = []
    for line in text.splitlines():
        lowered = line.lower()
        if SECRET_TEXT_PATTERN.search(line):
            redacted_lines.append(REDACTED)
        else:
            redacted_lines.append(line)
    return "\n".join(redacted_lines) + ("\n" if text.endswith("\n") else "")


def _is_secret_key(key: str) -> bool:
    separated = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", key)
    lowered = re.sub(r"[_\-\s]+", "_", separated).strip("_").lower()
    return lowered in SECRET_KEY_NAMES or lowered.endswith(("_api_key", "_token", "_secret", "_password", "_credential"))


def _file_type(path: Path) -> str:
    if path.name == "checksums.sha256":
        return "sha256"
    return path.suffix.lstrip(".") or "text"


def _created_at(path: Path) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).replace(microsecond=0).isoformat()


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _string_dict(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): str(item) for key, item in value.items()}


def _safe_count_dict(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, int] = {}
    for key, item in value.items():
        try:
            result[str(key)] = int(item)
        except (TypeError, ValueError):
            continue
    return {key: result[key] for key in sorted(result)}
