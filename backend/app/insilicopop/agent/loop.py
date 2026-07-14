from __future__ import annotations

from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from app.insilicopop.agent.actions import AgentAction, make_action
from app.insilicopop.agent.claim_audit import build_recipe_claim_audit
from app.insilicopop.agent.data_governance_audit import build_data_governance_audit
from app.insilicopop.agent.failure_scope import FailureScope
from app.insilicopop.agent.metadata_registry_audit import build_metadata_registry_audit
from app.insilicopop.agent.planner import AgentPlanner
from app.insilicopop.agent.recipe_previews import apply_command_preview_safety_metadata, build_recipe_command_previews
from app.insilicopop.agent.results_audit import build_results_audit
from app.insilicopop.agent.state import AgentState
from app.insilicopop.agent.tool_router import ToolRouter
from app.insilicopop.agent.trace import build_trace, write_agent_outputs
from app.insilicopop.audit_service import InSilicoPopAuditService
from app.insilicopop.clinical.service import build_clinical_case_bundle
from app.insilicopop.llm.action_validator import ActionValidator
from app.insilicopop.llm.base import LLMProviderError
from app.insilicopop.llm.provider_factory import build_llm_provider
from app.insilicopop.memory.governor import CarriedMemory, CompressedMemoryItem, MemoryGovernor
from app.insilicopop.orchestration import build_orchestration_trace
from app.insilicopop.rag.retrieval_adapter import retrieve_evidence
from app.insilicopop.recipes.registry import select_default_recipe_for_workflow_family, selected_recipe_metadata
from app.insilicopop.workflows.workflow_selector import WorkflowFamilySelector


class AgentLoop:
    def __init__(self, generated_root: Path | None = None) -> None:
        self.generated_root = generated_root or Path(__file__).resolve().parents[2] / "generated" / "agents"

    def run(
        self,
        *,
        query: str | None,
        uploads: dict[str, bytes | dict[str, bytes | str] | None],
        max_steps: int = 8,
        memory_budget_chars: int = 1500,
        memory_mode: Literal["compact", "ultra_compact"] = "compact",
        llm_provider: str = "mock",
        data_use_agreement_scope: dict[str, Any] | None = None,
        metadata_registry: dict[str, Any] | None = None,
        clinical_case_intake: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        run_id = uuid4().hex[:12]
        state = AgentState(run_id=run_id, query=query, uploaded_files=_uploaded_file_names(uploads), llm_provider=llm_provider)
        self._step(state, "initialize_state", {"max_steps": max_steps, "memory_budget_chars": memory_budget_chars, "memory_mode": memory_mode, "llm_provider": llm_provider})

        if max_steps <= 0:
            state.failure_reasons.append(
                {
                    "failure_type": "max_steps_exhausted",
                    "severity": "warning",
                    "message": "Agent loop stopped before running any deterministic step.",
                    "triggered_by": ["max_steps"],
                    "recommended_fix": "Run with max_steps >= 1.",
                    "blocked_action_id": None,
                }
            )
            generated = write_agent_outputs(self.generated_root / run_id, state)
            return self._response(state, generated)

        if clinical_case_intake is not None:
            return self._run_clinical_intake(state, clinical_case_intake)

        parse_action = make_action(1, "parse_inputs", "Parse uploaded population-genetics inputs.", "Use existing native parsers through the audit service.", expected_outputs=["ParsedTable objects"])
        audit_action = make_action(2, "audit_inputs", "Audit parsed inputs.", "Run deterministic InSilicoPop auditors.", expected_outputs=["audit_report", "risk_flags", "reliability_score"])
        memory_action = make_action(3, "compress_memory", "Compress and govern audit memory.", "Use domain compressor plus memory governor.", expected_outputs=["carried_memory"])
        for action in [parse_action, audit_action, memory_action]:
            state.record_action(action)

        audit_result = InSilicoPopAuditService().run(query, uploads, memory_mode=memory_mode, include_memory_provenance=True)
        state.current_step = "audit_inputs"
        state.parsed_inputs = {"uploaded_fields": sorted(name for name, upload in uploads.items() if upload)}
        state.workflow_selection = WorkflowFamilySelector().select(query=query, uploaded_files=state.uploaded_files).model_dump()
        self._select_recipe_preview(state)
        state.audit_report = audit_result.audit_report
        state.reliability_score = audit_result.reliability_score
        state.risk_flags = [finding.model_dump() for finding in audit_result.risk_flags]
        state.provenance_trace = _provenance_trace(state.risk_flags, audit_result.audit_report.get("reliability", {}))
        state.complete_action(parse_action)
        state.complete_action(audit_action)

        carried = self._govern_memory(audit_result.compressed_memory, memory_budget_chars, memory_mode)
        state.carry_memory(carried.model_dump())
        state.complete_action(memory_action)

        provider = build_llm_provider(llm_provider)
        state.llm_provider = provider.provider_name
        proposals = []
        try:
            proposals = provider.propose_actions(
                compact_memory=state.carried_memory,
                audit_summary={
                    "reliability_score": state.reliability_score,
                    "risk_flags": state.risk_flags,
                    "input_inventory": sorted(state.uploaded_files),
                },
                query=query,
            )
        except LLMProviderError as exc:
            state.failure_reasons.append(exc.failure_reason())
        state.external_llm_called = provider.external_call_made
        state.llm_action_proposals = [proposal.model_dump() for proposal in proposals]
        validator = ActionValidator()
        state.validated_actions = [
            validator.validate(proposal, risk_flags=state.risk_flags, carried_memory=state.carried_memory, uploaded_files=state.uploaded_files).model_dump()
            for proposal in proposals
        ]
        state.decision_trace.append({"event": "mock_llm_proposals_validated", "proposal_count": len(state.llm_action_proposals), "external_llm_called": False})

        planned = AgentPlanner().plan(audit_report=state.audit_report, risk_flags=state.risk_flags, carried_memory=state.carried_memory)
        state.record_action(make_action(4, "plan_next_analysis", "Plan next analysis actions.", "Apply deterministic population-genetics planning rules.", expected_outputs=["planned_actions"]))
        state.complete_action(state.planned_actions[-1])

        router = ToolRouter()
        executed_steps = 4
        for action in planned:
            if action.status == "blocked":
                state.record_action(action)
                state.block_action(action, action.blocked_reason or "blocked by deterministic planner")
                continue
            if executed_steps >= max_steps:
                action.status = "skipped"
                action.blocked_reason = "max_steps reached"
                state.record_action(action)
                continue
            state.record_action(action)
            if action.action_type.startswith("dry_run_"):
                router.dry_run(action)
                state.command_previews.extend(_flatten_previews(action.command_preview))
                state.complete_action(action)
            elif action.action_type == "generate_report":
                state.complete_action(action)
            else:
                state.complete_action(action)
            executed_steps += 1

        recipe_command_previews = build_recipe_command_previews(
            selected_recipe=state.selected_recipe,
            input_inventory=state.uploaded_files,
        )
        if recipe_command_previews:
            state.command_previews.extend(recipe_command_previews)
        state.command_previews = apply_command_preview_safety_metadata(
            state.command_previews,
            selected_recipe=state.selected_recipe,
        )
        state.decision_trace.append(
            {
                "event": "recipe_aware_command_previews_built",
                "selected_recipe_id": (state.selected_recipe or {}).get("recipe_id"),
                "recipe_aware_preview_count": len(recipe_command_previews),
                "total_command_preview_count": len(state.command_previews),
                "dry_run_only": True,
                "external_tools_executed": False,
                "raw_genomic_files_parsed": False,
            }
        )

        provider_failures = list(state.failure_reasons)
        state.failure_reasons = provider_failures + FailureScope().evaluate(risk_flags=state.risk_flags, actions=state.planned_actions, carried_memory=state.carried_memory)
        for failure in state.failure_reasons:
            for action in state.blocked_actions:
                if not failure.get("blocked_action_id") and action.blocked_reason and failure["failure_type"] in action.blocked_reason:
                    failure["blocked_action_id"] = action.action_id
        state.claim_audit = build_recipe_claim_audit(
            selected_recipe=state.selected_recipe,
            workflow_selection=state.workflow_selection,
            query=query,
            planned_actions=state.planned_actions,
            blocked_actions=state.blocked_actions,
            failure_reasons=state.failure_reasons,
            validated_actions=state.validated_actions,
        )
        state.decision_trace.append(
            {
                "event": "recipe_aware_claim_audit_built",
                "selected_recipe_id": state.claim_audit.get("selected_recipe_id"),
                "blocked_interpretation_count": len(state.claim_audit.get("blocked_interpretations", [])),
                "unsupported_claim_category_count": len(state.claim_audit.get("unsupported_claim_categories", [])),
                "dry_run_only": True,
                "human_review_required": True,
            }
        )
        state.results_audit = build_results_audit(
            workflow_selection=state.workflow_selection,
            selected_recipe=state.selected_recipe,
            uploaded_files=state.uploaded_files,
            claim_audit=state.claim_audit,
            query=query,
        )
        if state.results_audit:
            state.decision_trace.append(
                {
                    "event": "results_only_audit_artifact_built",
                    "selected_recipe_id": state.results_audit.get("selected_recipe_id"),
                    "declared_result_artifact_count": state.results_audit.get("results_audit_summary", {}).get("declared_result_artifact_count", 0),
                    "dry_run_only": True,
                    "raw_file_read": False,
                }
            )
        state.data_governance_audit = build_data_governance_audit(
            query=query,
            uploaded_files=state.uploaded_files,
            workflow_selection=state.workflow_selection,
            selected_recipe=state.selected_recipe,
            data_use_agreement_scope=data_use_agreement_scope,
        )
        state.metadata_registry_audit = build_metadata_registry_audit(
            query=query,
            uploaded_files=state.uploaded_files,
            workflow_selection=state.workflow_selection,
            metadata_registry=metadata_registry,
        )
        state.research_lane = str(state.metadata_registry_audit.get("research_lane", "insufficient_inputs"))
        state.evidence_retrieval = retrieve_evidence(
            query=query,
            lane=state.research_lane,
            safety_terms=[
                *state.metadata_registry_audit.get("blocked_out_of_scope_categories", []),
                *state.claim_audit.get("unsupported_claim_categories", []),
            ],
        ).model_dump()
        state.decision_trace.append(
            {
                "event": "data_governance_audit_built",
                "status": state.data_governance_audit.get("status"),
                "blocked_count": len(state.data_governance_audit.get("blocked", [])),
                "caveat_count": len(state.data_governance_audit.get("caveats", [])),
                "human_review_required": True,
                "dataset_terms_verified": False,
            }
        )
        state.decision_trace.append(
            {
                "event": "metadata_registry_audit_built",
                "status": state.metadata_registry_audit.get("status"),
                "research_lane": state.research_lane,
                "missing_required_metadata_count": len(state.metadata_registry_audit.get("missing_required_metadata", [])),
                "caveat_count": len(state.metadata_registry_audit.get("caveats", [])),
                "human_review_required": True,
            }
        )
        state.decision_trace.append(
            {
                "event": "evidence_retrieval_built",
                "retrieval_mode": state.evidence_retrieval.get("retrieval_mode"),
                "snippet_count": state.evidence_retrieval.get("snippets_returned", 0),
                "source_ids": state.evidence_retrieval.get("source_ids", []),
                "local_only": True,
                "external_call_made": False,
                "raw_data_ingested": False,
                "human_review_required": True,
            }
        )
        state.orchestration_trace = build_orchestration_trace(state).model_dump()
        state.decision_trace.append(
            {
                "event": "controlled_orchestration_trace_built",
                "orchestration_backend": state.orchestration_trace.get("orchestration_backend"),
                "langgraph_available": state.orchestration_trace.get("langgraph_available", False),
                "fallback_used": state.orchestration_trace.get("fallback_used", True),
                "executed_node_count": len(state.orchestration_trace.get("graph_nodes_executed", [])),
                "blocked_nodes": state.orchestration_trace.get("blocked_nodes", []),
                "external_tools_executed": False,
                "external_llm_called": False,
                "raw_genomic_files_parsed": False,
                "human_review_required": True,
            }
        )
        state.external_tools_executed = False
        if state.blocked_actions or state.data_governance_audit.get("status") == "blocked" or state.metadata_registry_audit.get("status") == "blocked":
            state.current_step = "blocked"
        elif any(action.action_type == "generate_report" and action.status == "completed" for action in state.completed_actions):
            state.current_step = "report_generated"
        else:
            state.current_step = "completed"
        generated = write_agent_outputs(self.generated_root / run_id, state)
        return self._response(state, generated)

    def _govern_memory(self, compressed_memory: dict[str, Any], budget_chars: int, memory_mode: Literal["compact", "ultra_compact"]) -> CarriedMemory:
        governor = MemoryGovernor()
        carried = CarriedMemory(memory_mode=memory_mode)
        for tool_name, item in compressed_memory.get("tools", {}).items():
            compressed = item.get("compressed_memory", {}) if isinstance(item, dict) else {}
            result = governor.update(
                carried,
                CompressedMemoryItem(step_name=str(tool_name), memory_mode=memory_mode, compressed_memory=compressed),
                budget_chars,
            )
            carried = result.carried_memory
        return carried

    def _run_clinical_intake(self, state: AgentState, payload: dict[str, Any]) -> dict[str, Any]:
        state.llm_provider = "mock"
        state.research_lane = "clinical_genetics_research_curation"
        state.workflow_selection = WorkflowFamilySelector().select(
            query=None,
            uploaded_files={},
            clinical_intake_declared=True,
        ).model_dump()
        self._select_recipe_preview(state)
        state.clinical_case_intake, state.phenotype_hpo_curation, state.pedigree_inheritance_audit = build_clinical_case_bundle(payload, request_text=state.query)
        result = state.clinical_case_intake
        state.parsed_inputs = {
            "structured_clinical_intake": True,
            "raw_genomic_files_parsed": False,
            "uploaded_file_parsing_used": False,
        }
        state.decision_trace.append(
            {
                "event": "clinical_case_intake_validated",
                "schema_version": result.schema_version,
                "pseudonymous_case_id": result.pseudonymous_case_id,
                "intake_completeness": result.intake_completeness,
                "phenotype_count": sum(result.phenotype_state_counts.values()),
                "candidate_variant_count": result.candidate_variant_count,
                "pedigree_record_count": result.pedigree_record_count,
                "validation_error_count": len(result.validation_errors),
                "policy_block_count": len(result.policy_blocks),
                "external_llm_called": False,
                "external_tools_executed": False,
                "raw_genomic_files_parsed": False,
                "human_review_required": True,
            }
        )
        if state.phenotype_hpo_curation:
            curation = state.phenotype_hpo_curation
            state.decision_trace.append(
                {
                    "event": "phenotype_hpo_curation_completed",
                    "schema_version": curation.schema_version,
                    "registry_version": curation.registry_version,
                    "algorithm_version": curation.algorithm_version,
                    "pseudonymous_case_id": curation.pseudonymous_case_id,
                    "snippet_ids": [item.snippet_id for item in curation.source_snippets],
                    "suggestion_ids": [item.suggestion_id for item in curation.hpo_suggestions],
                    "hpo_ids": sorted({item.hpo_id for item in curation.hpo_suggestions}),
                    "proposed_states": [item.proposed_state for item in curation.hpo_suggestions],
                    "suggestion_count": len(curation.hpo_suggestions),
                    "contradiction_count": len(curation.contradictions),
                    "promoted_observation_count": len(curation.promoted_observations),
                    "human_review_required": True,
                    "research_use_only": True,
                    "external_llm_called": False,
                    "external_tools_executed": False,
                    "raw_genomic_files_parsed": False,
                }
            )
        if state.pedigree_inheritance_audit:
            inheritance_audit = state.pedigree_inheritance_audit
            state.decision_trace.append(
                {
                    "event": "pedigree_inheritance_audit_completed",
                    "schema_version": inheritance_audit.schema_version,
                    "algorithm_version": inheritance_audit.algorithm_version,
                    "pseudonymous_case_id": inheritance_audit.pseudonymous_case_id,
                    "proband_member_id": inheritance_audit.proband_member_id,
                    "member_count": inheritance_audit.member_count,
                    "biological_parent_relationship_count": inheritance_audit.biological_parent_relationship_count,
                    "hypothesis_types": inheritance_audit.supplied_hypothesis_types,
                    "audit_statuses": [item.status.value for item in inheritance_audit.inheritance_audits],
                    "relationship_issue_codes": [item.code for item in inheritance_audit.relationship_issues],
                    "mendelian_inconsistency_codes": [item.code for item in inheritance_audit.mendelian_inconsistencies],
                    "evaluable_transmission_count": inheritance_audit.available_parent_child_transmission_summary.evaluable_transmission_count,
                    "non_evaluable_transmission_count": inheritance_audit.available_parent_child_transmission_summary.non_evaluable_transmission_count,
                    "human_review_required": True,
                    "research_use_only": True,
                    "external_llm_called": False,
                    "external_tools_executed": False,
                    "raw_genomic_files_parsed": False,
                }
            )
        state.external_llm_called = False
        state.external_tools_executed = False
        state.orchestration_trace = build_orchestration_trace(state).model_dump()
        state.current_step = "blocked" if result.policy_blocks or result.validation_errors else "clinical_intake_validated"
        generated = write_agent_outputs(self.generated_root / state.run_id, state)
        return self._response(state, generated)

    def _response(self, state: AgentState, generated_files: dict[str, Any]) -> dict[str, Any]:
        return {
            "run_id": state.run_id,
            "query": state.query,
            "final_state": state.model_dump(),
            "planned_actions": [action.model_dump() for action in state.planned_actions],
            "completed_actions": [action.model_dump() for action in state.completed_actions],
            "blocked_actions": [action.model_dump() for action in state.blocked_actions],
            "failure_reasons": state.failure_reasons,
            "workflow_selection": state.workflow_selection,
            "research_lane": state.research_lane,
            "selected_recipe": state.selected_recipe,
            "recipe_selection_warning": state.recipe_selection_warning,
            "llm_action_proposals": state.llm_action_proposals,
            "validated_actions": state.validated_actions,
            "command_previews": state.command_previews,
            "claim_audit": state.claim_audit,
            "results_audit": state.results_audit,
            "data_governance_audit": state.data_governance_audit,
            "metadata_registry_audit": state.metadata_registry_audit,
            "evidence_retrieval": state.evidence_retrieval,
            "orchestration_trace": state.orchestration_trace,
            "clinical_case_intake": state.clinical_case_intake.model_dump() if state.clinical_case_intake else None,
            "phenotype_hpo_curation": state.phenotype_hpo_curation.model_dump() if state.phenotype_hpo_curation else None,
            "pedigree_inheritance_audit": state.pedigree_inheritance_audit.model_dump() if state.pedigree_inheritance_audit else None,
            "carried_memory": state.carried_memory,
            "agent_trace": build_trace(state),
            "generated_files": generated_files,
            "reproducibility_bundle": generated_files.get("reproducibility_bundle", {"generated": False, "path": None, "files": []}),
            "llm_provider": state.llm_provider,
            "external_llm_called": state.external_llm_called,
            "external_tools_executed": state.external_tools_executed,
        }

    def _step(self, state: AgentState, name: str, details: dict[str, Any]) -> None:
        state.current_step = name
        state.decision_trace.append({"event": name, **details})

    def _select_recipe_preview(self, state: AgentState) -> None:
        workflow_family = state.workflow_selection.get("workflow_family")
        recipe = select_default_recipe_for_workflow_family(str(workflow_family) if workflow_family else None)
        if recipe is None:
            state.selected_recipe = None
            state.recipe_selection_warning = f"No deterministic dry-run recipe was found for workflow family: {workflow_family or 'unknown'}."
            state.decision_trace.append(
                {
                    "event": "recipe_selection_warning",
                    "workflow_family": workflow_family,
                    "warning": state.recipe_selection_warning,
                }
            )
            return
        state.selected_recipe = selected_recipe_metadata(recipe)
        state.recipe_selection_warning = None
        state.decision_trace.append(
            {
                "event": "recipe_preview_selected",
                "workflow_family": recipe.workflow_family,
                "recipe_id": recipe.recipe_id,
                "dry_run_only": True,
            }
        )


def _uploaded_file_names(uploads: dict[str, bytes | dict[str, bytes | str] | None]) -> dict[str, str]:
    names = {}
    for key, upload in uploads.items():
        if isinstance(upload, dict) and upload.get("filename"):
            names[key] = str(upload["filename"])
        elif upload:
            names[key] = key
    return names


def _provenance_trace(risk_flags: list[dict[str, Any]], reliability: dict[str, Any]) -> list[dict[str, Any]]:
    trace = [{"kind": "risk_flag", "code": flag.get("code"), "provenance": flag.get("provenance")} for flag in risk_flags]
    for penalty in reliability.get("penalties", []) or []:
        trace.append({"kind": "reliability_penalty", **penalty})
    return trace


def _flatten_previews(preview: Any) -> list[dict[str, Any]]:
    if isinstance(preview, list):
        return [dict(item) for item in preview if isinstance(item, dict)]
    if isinstance(preview, dict):
        return [dict(preview)]
    return []
