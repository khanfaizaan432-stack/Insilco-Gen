from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


ALLOWED_GRAPH_NODES: tuple[str, ...] = (
    "intake_interpretation",
    "workflow_selection",
    "recipe_selection",
    "metadata_registry_audit",
    "data_governance_audit",
    "claim_audit",
    "results_only_audit",
    "evidence_retrieval",
    "report_assembly",
    "reproducibility_bundle",
)

DEFAULT_GRAPH_EDGES: tuple[tuple[str, str], ...] = (
    ("intake_interpretation", "workflow_selection"),
    ("workflow_selection", "recipe_selection"),
    ("recipe_selection", "metadata_registry_audit"),
    ("recipe_selection", "data_governance_audit"),
    ("recipe_selection", "claim_audit"),
    ("claim_audit", "results_only_audit"),
    ("metadata_registry_audit", "evidence_retrieval"),
    ("data_governance_audit", "evidence_retrieval"),
    ("evidence_retrieval", "report_assembly"),
    ("report_assembly", "reproducibility_bundle"),
)

SAFETY_FLAGS: dict[str, bool] = {
    "autonomous_tool_execution": False,
    "external_tools_executed": False,
    "external_llm_called": False,
    "raw_genomic_files_parsed": False,
    "raw_data_ingested": False,
    "free_form_node_spawning": False,
    "self_modification_allowed": False,
    "arbitrary_tool_access_allowed": False,
    "external_api_call_made": False,
    "biological_or_clinical_conclusion_made": False,
    "clinical_decision_made": False,
    "final_acmg_classification_made": False,
    "diagnosis_or_treatment_recommendation_made": False,
    "ancestry_caste_purity_claim_made": False,
    "deterministic_audits_authoritative": True,
    "human_review_required": True,
}


class OrchestrationNodeRecord(BaseModel):
    node_name: str
    status: Literal["completed", "skipped", "blocked"]
    input_summary: dict[str, Any] = Field(default_factory=dict)
    output_summary: dict[str, Any] = Field(default_factory=dict)
    safety_flags: dict[str, bool] = Field(default_factory=lambda: dict(SAFETY_FLAGS))


class ControlledOrchestrationTrace(BaseModel):
    orchestration_enabled: bool = True
    orchestration_backend: str = "deterministic_controlled_graph"
    langgraph_available: bool = False
    fallback_used: bool = True
    graph_nodes_declared: list[str] = Field(default_factory=lambda: list(ALLOWED_GRAPH_NODES))
    graph_nodes_executed: list[str] = Field(default_factory=list)
    graph_edges_declared: list[dict[str, str]] = Field(default_factory=list)
    blocked_nodes: list[str] = Field(default_factory=list)
    node_statuses: list[OrchestrationNodeRecord] = Field(default_factory=list)
    safety_flags: dict[str, bool] = Field(default_factory=lambda: dict(SAFETY_FLAGS))
    trace_scope: str = (
        "Controlled orchestration preview records node status summaries only. "
        "It does not contain raw genomic content, raw result content, or final biological/clinical decisions."
    )


def validate_graph_nodes(nodes: list[str] | tuple[str, ...]) -> list[str]:
    invalid = sorted({node for node in nodes if node not in ALLOWED_GRAPH_NODES})
    if invalid:
        raise ValueError(f"Unsupported orchestration node(s): {', '.join(invalid)}")
    return list(nodes)


def declared_edges() -> list[dict[str, str]]:
    return [{"from": source, "to": target} for source, target in DEFAULT_GRAPH_EDGES]


def safety_flags() -> dict[str, bool]:
    return dict(SAFETY_FLAGS)
