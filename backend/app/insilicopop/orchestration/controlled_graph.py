from __future__ import annotations

from typing import Any

from app.insilicopop.agent.state import AgentState
from app.insilicopop.orchestration.langgraph_adapter import ControlledLangGraphAdapter
from app.insilicopop.orchestration.models import (
    ALLOWED_GRAPH_NODES,
    ControlledOrchestrationTrace,
    OrchestrationNodeRecord,
    declared_edges,
    safety_flags,
    validate_graph_nodes,
)


class ControlledOrchestrationGraph:
    def __init__(
        self,
        *,
        declared_nodes: list[str] | tuple[str, ...] = ALLOWED_GRAPH_NODES,
        langgraph_adapter: ControlledLangGraphAdapter | None = None,
    ) -> None:
        self.declared_nodes = validate_graph_nodes(declared_nodes)
        self.langgraph_adapter = langgraph_adapter or ControlledLangGraphAdapter()

    def build_trace(self, state: AgentState) -> ControlledOrchestrationTrace:
        availability = self.langgraph_adapter.availability()
        fallback_used = not availability.available
        backend = "deterministic_controlled_graph" if fallback_used else "optional_langgraph_controlled_graph"
        node_statuses = _node_statuses(state, self.declared_nodes)
        executed = [record.node_name for record in node_statuses if record.status == "completed"]
        blocked = [record.node_name for record in node_statuses if record.status == "blocked"]
        return ControlledOrchestrationTrace(
            orchestration_enabled=True,
            orchestration_backend=backend,
            langgraph_available=availability.available,
            fallback_used=fallback_used,
            graph_nodes_declared=list(self.declared_nodes),
            graph_nodes_executed=executed,
            graph_edges_declared=declared_edges(),
            blocked_nodes=blocked,
            node_statuses=node_statuses,
            safety_flags=safety_flags(),
        )


def build_orchestration_trace(state: AgentState) -> ControlledOrchestrationTrace:
    return ControlledOrchestrationGraph().build_trace(state)


def _node_statuses(state: AgentState, declared_nodes: list[str]) -> list[OrchestrationNodeRecord]:
    records = {
        "intake_interpretation": _record(
            "intake_interpretation",
            "completed",
            {"query_present": bool(state.query), "declared_input_count": len(state.uploaded_files)},
            {"uploaded_file_fields": sorted(state.uploaded_files), "raw_genomic_files_parsed": False},
        ),
        "workflow_selection": _record(
            "workflow_selection",
            "completed" if state.workflow_selection else "skipped",
            {"declared_input_count": len(state.uploaded_files)},
            {
                "workflow_family": state.workflow_selection.get("workflow_family"),
                "confidence": state.workflow_selection.get("confidence"),
            },
        ),
        "recipe_selection": _record(
            "recipe_selection",
            "completed" if state.selected_recipe else "skipped",
            {"workflow_family": state.workflow_selection.get("workflow_family")},
            {
                "selected_recipe_id": (state.selected_recipe or {}).get("recipe_id"),
                "warning_present": bool(state.recipe_selection_warning),
                "dry_run_only": True,
            },
        ),
        "metadata_registry_audit": _record(
            "metadata_registry_audit",
            "completed" if state.metadata_registry_audit else "skipped",
            {"research_lane": state.research_lane},
            {
                "status": state.metadata_registry_audit.get("status"),
                "missing_required_metadata_count": len(state.metadata_registry_audit.get("missing_required_metadata", []) or []),
                "human_review_required": True,
            },
        ),
        "data_governance_audit": _record(
            "data_governance_audit",
            "completed" if state.data_governance_audit else "skipped",
            {"declared_input_count": len(state.uploaded_files)},
            {
                "status": state.data_governance_audit.get("status"),
                "blocked_count": len(state.data_governance_audit.get("blocked", []) or []),
                "human_review_required": True,
            },
        ),
        "claim_audit": _record(
            "claim_audit",
            "completed" if state.claim_audit else "skipped",
            {"planned_action_count": len(state.planned_actions), "blocked_action_count": len(state.blocked_actions)},
            {
                "unsupported_claim_category_count": len(state.claim_audit.get("unsupported_claim_categories", []) or []),
                "human_review_required": True,
            },
        ),
        "results_only_audit": _record(
            "results_only_audit",
            "completed" if state.results_audit else "skipped",
            {"declared_input_count": len(state.uploaded_files)},
            {
                "declared_result_artifact_count": (state.results_audit or {}).get("results_audit_summary", {}).get("declared_result_artifact_count", 0),
                "raw_file_read": False,
            },
        ),
        "evidence_retrieval": _record(
            "evidence_retrieval",
            "completed" if state.evidence_retrieval else "skipped",
            {"research_lane": state.research_lane},
            {
                "retrieval_mode": state.evidence_retrieval.get("retrieval_mode"),
                "snippets_returned": state.evidence_retrieval.get("snippets_returned", 0),
                "external_call_made": False,
            },
        ),
        "report_assembly": _record(
            "report_assembly",
            "completed",
            {"completed_node_count": _completed_dependency_count(state)},
            {"final_report_section": "Controlled Orchestration Preview"},
        ),
        "reproducibility_bundle": _record(
            "reproducibility_bundle",
            "completed",
            {"trace_file": "reproducibility/orchestration_trace.json"},
            {"checksum_scope": "generated artifacts only", "raw_user_files_checksummed": False},
        ),
    }
    return [records[node] for node in declared_nodes]


def _record(node_name: str, status: str, input_summary: dict[str, Any], output_summary: dict[str, Any]) -> OrchestrationNodeRecord:
    return OrchestrationNodeRecord(
        node_name=node_name,
        status=status,
        input_summary=_summary_only(input_summary),
        output_summary=_summary_only(output_summary),
        safety_flags=safety_flags(),
    )


def _summary_only(values: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key, value in values.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            summary[key] = value
        elif isinstance(value, list):
            summary[key] = [str(item) for item in value[:20]]
        else:
            summary[key] = str(value)
    return summary


def _completed_dependency_count(state: AgentState) -> int:
    count = 1
    for value in (
        state.workflow_selection,
        state.selected_recipe,
        state.metadata_registry_audit,
        state.data_governance_audit,
        state.claim_audit,
        state.evidence_retrieval,
    ):
        if value:
            count += 1
    if state.results_audit:
        count += 1
    return count
