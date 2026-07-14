from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


ActionType = Literal[
    "parse_inputs",
    "audit_inputs",
    "compress_memory",
    "plan_next_analysis",
    "dry_run_plink_qc",
    "dry_run_ld_pruning",
    "dry_run_pca",
    "dry_run_admixture",
    "dry_run_fst",
    "dry_run_roh",
    "dry_run_selection_scan",
    "interpret_results",
    "block_interpretation",
    "generate_report",
    "run_admixture",
    "interpret_pca",
    "interpret_admixture",
    "interpret_fst",
    "interpret_selection",
]

ActionStatus = Literal["planned", "completed", "blocked", "skipped"]


class AgentAction(BaseModel):
    action_id: str
    action_type: ActionType
    title: str
    rationale: str
    required_inputs: list[str] = Field(default_factory=list)
    expected_outputs: list[str] = Field(default_factory=list)
    command_preview: dict[str, Any] | list[dict[str, Any]] | None = None
    status: ActionStatus = "planned"
    blocked_reason: str | None = None
    provenance_refs: list[str] = Field(default_factory=list)
    memory_dependencies: list[str] = Field(default_factory=list)


def make_action(
    index: int,
    action_type: ActionType,
    title: str,
    rationale: str,
    *,
    required_inputs: list[str] | None = None,
    expected_outputs: list[str] | None = None,
    provenance_refs: list[str] | None = None,
    memory_dependencies: list[str] | None = None,
    status: ActionStatus = "planned",
    blocked_reason: str | None = None,
) -> AgentAction:
    return AgentAction(
        action_id=f"act_{index:03d}_{action_type}",
        action_type=action_type,
        title=title,
        rationale=rationale,
        required_inputs=required_inputs or [],
        expected_outputs=expected_outputs or [],
        provenance_refs=provenance_refs or [],
        memory_dependencies=memory_dependencies or [],
        status=status,
        blocked_reason=blocked_reason,
    )
