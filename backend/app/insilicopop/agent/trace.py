from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from fastapi.encoders import jsonable_encoder

from app.insilicopop.agent.interpreter import AgentInterpreter
from app.insilicopop.agent.reproducibility import write_reproducibility_bundle
from app.insilicopop.agent.state import AgentState


def build_trace(state: AgentState) -> list[dict[str, Any]]:
    return list(state.decision_trace) + [
        {"event": "failure_detected", **failure} for failure in state.failure_reasons
    ]


def write_agent_outputs(root: Path, state: AgentState) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    trace = build_trace(state)
    files = {
        "agent_state": root / "agent_state.json",
        "agent_trace": root / "agent_trace.json",
        "action_proposals": root / "action_proposals.json",
        "llm_action_proposals": root / "llm_action_proposals.json",
        "validated_actions": root / "validated_actions.json",
        "command_previews": root / "command_previews.yaml",
        "workflow_selection": root / "workflow_selection.json",
        "planned_actions": root / "planned_actions.yaml",
        "blocked_actions": root / "blocked_actions.md",
        "failure_scope": root / "failure_scope.md",
        "carried_memory": root / "carried_memory.json",
        "final_report": root / "final_report.md",
    }
    final_report = AgentInterpreter().final_report(
        run_id=state.run_id,
        query=state.query,
        uploaded_files=state.uploaded_files,
        reliability_score=state.reliability_score,
        planned_count=len(state.planned_actions),
        completed_count=len(state.completed_actions),
        blocked_count=len(state.blocked_actions),
        planned_actions=state.planned_actions,
        completed_actions=state.completed_actions,
        blocked_actions=state.blocked_actions,
        failures=state.failure_reasons,
        workflow_selection=state.workflow_selection,
        selected_recipe=state.selected_recipe,
        recipe_selection_warning=state.recipe_selection_warning,
        command_previews=state.command_previews,
        claim_audit=state.claim_audit,
        results_audit=state.results_audit,
        data_governance_audit=state.data_governance_audit,
        metadata_registry_audit=state.metadata_registry_audit,
        evidence_retrieval=state.evidence_retrieval,
        orchestration_trace=state.orchestration_trace,
        clinical_case_intake=state.clinical_case_intake.model_dump(exclude={"supplied_candidate_variants"}) if state.clinical_case_intake else None,
        phenotype_hpo_curation=state.phenotype_hpo_curation.model_dump() if state.phenotype_hpo_curation else None,
        pedigree_inheritance_audit=state.pedigree_inheritance_audit.model_dump() if state.pedigree_inheritance_audit else None,
        variant_intelligence=state.variant_intelligence.model_dump() if state.variant_intelligence else None,
        pre_test_assessment=state.pre_test_assessment.model_dump() if state.pre_test_assessment else None,
        test_strategy_workspace=state.test_strategy_workspace.model_dump() if state.test_strategy_workspace else None,
        result_evidence_workspace=state.result_evidence_workspace.model_dump() if state.result_evidence_workspace else None,
        specialist_agent_workspace=state.specialist_agent_workspace.model_dump() if state.specialist_agent_workspace else None,
        byok_runtime=state.byok_runtime.model_dump() if state.byok_runtime else None,
        carried_memory=state.carried_memory,
        llm_provider=state.llm_provider,
        external_llm_called=state.external_llm_called,
        external_tools_executed=state.external_tools_executed,
        current_step=state.current_step,
        generated_artifact_count=len(files) + 10,
        validated_actions=state.validated_actions,
    )
    files["agent_state"].write_text(json.dumps(jsonable_encoder(state), indent=2), encoding="utf-8")
    files["agent_trace"].write_text(json.dumps(jsonable_encoder(trace), indent=2), encoding="utf-8")
    files["action_proposals"].write_text(json.dumps(jsonable_encoder(state.llm_action_proposals), indent=2), encoding="utf-8")
    files["llm_action_proposals"].write_text(json.dumps(jsonable_encoder(state.llm_action_proposals), indent=2), encoding="utf-8")
    files["validated_actions"].write_text(json.dumps(jsonable_encoder(state.validated_actions), indent=2), encoding="utf-8")
    files["command_previews"].write_text(yaml.safe_dump(jsonable_encoder(state.command_previews), sort_keys=False), encoding="utf-8")
    files["workflow_selection"].write_text(json.dumps(jsonable_encoder(state.workflow_selection), indent=2), encoding="utf-8")
    files["planned_actions"].write_text(yaml.safe_dump(jsonable_encoder(state.planned_actions), sort_keys=False), encoding="utf-8")
    files["blocked_actions"].write_text(_blocked_markdown(state), encoding="utf-8")
    files["failure_scope"].write_text(_failure_markdown(state.failure_reasons), encoding="utf-8")
    files["carried_memory"].write_text(json.dumps(jsonable_encoder(state.carried_memory), indent=2), encoding="utf-8")
    files["final_report"].write_text(final_report, encoding="utf-8")

    repro_files, bundle = write_reproducibility_bundle(
        root,
        state,
        trace=trace,
        generated_artifacts=files,
    )
    files.update(repro_files)
    metadata = {
        key: {
            "filename": path.name,
            "absolute_path": str(path.resolve()),
            "relative_path": str(path),
            "file_type": path.suffix.lstrip(".") or "text",
            "created": path.exists(),
        }
        for key, path in files.items()
    }
    metadata["reproducibility_bundle"] = bundle
    return metadata


def _blocked_markdown(state: AgentState) -> str:
    lines = ["# Blocked Actions", ""]
    if not state.blocked_actions:
        lines.append("- None")
    for action in state.blocked_actions:
        lines.append(f"- {action.action_id}: {action.title}")
        lines.append(f"  Reason: {action.blocked_reason}")
    return "\n".join(lines) + "\n"


def _failure_markdown(failures: list[dict[str, Any]]) -> str:
    lines = ["# Failure Scope", ""]
    if not failures:
        lines.append("- None")
    for failure in failures:
        lines.append(f"- {failure['severity']}: {failure['failure_type']} - {failure['message']}")
        lines.append(f"  Fix: {failure['recommended_fix']}")
    return "\n".join(lines) + "\n"
