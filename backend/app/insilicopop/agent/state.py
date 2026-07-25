from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.insilicopop.agent.actions import AgentAction
from app.insilicopop.clinical.models import ClinicalCaseIntakeResult
from app.insilicopop.clinical.hpo_models import PhenotypeHpoCurationResult
from app.insilicopop.clinical.pedigree_models import PedigreeInheritanceAuditResult
from app.insilicopop.clinical.variant_models import VariantIntelligenceResult
from app.insilicopop.clinical.pretest_models import PreTestAssessmentResult
from app.insilicopop.clinical.test_strategy_models import TestStrategyWorkspaceResult
from app.insilicopop.llm.byok_runtime import BYOKPublicStatus


class AgentState(BaseModel):
    run_id: str
    query: str | None = None
    current_step: str = "initialized"
    uploaded_files: dict[str, str] = Field(default_factory=dict)
    parsed_inputs: dict[str, Any] = Field(default_factory=dict)
    audit_report: dict[str, Any] = Field(default_factory=dict)
    reliability_score: int | None = None
    risk_flags: list[dict[str, Any]] = Field(default_factory=list)
    carried_memory: dict[str, Any] = Field(default_factory=dict)
    workflow_selection: dict[str, Any] = Field(default_factory=dict)
    research_lane: str = "insufficient_inputs"
    selected_recipe: dict[str, Any] | None = None
    recipe_selection_warning: str | None = None
    planned_actions: list[AgentAction] = Field(default_factory=list)
    completed_actions: list[AgentAction] = Field(default_factory=list)
    blocked_actions: list[AgentAction] = Field(default_factory=list)
    failure_reasons: list[dict[str, Any]] = Field(default_factory=list)
    provenance_trace: list[dict[str, Any]] = Field(default_factory=list)
    decision_trace: list[dict[str, Any]] = Field(default_factory=list)
    llm_provider: str = "mock"
    external_llm_called: bool = False
    external_tools_executed: bool = False
    llm_action_proposals: list[dict[str, Any]] = Field(default_factory=list)
    validated_actions: list[dict[str, Any]] = Field(default_factory=list)
    command_previews: list[dict[str, Any]] = Field(default_factory=list)
    claim_audit: dict[str, Any] = Field(default_factory=dict)
    results_audit: dict[str, Any] | None = None
    data_governance_audit: dict[str, Any] = Field(default_factory=dict)
    metadata_registry_audit: dict[str, Any] = Field(default_factory=dict)
    evidence_retrieval: dict[str, Any] = Field(default_factory=dict)
    orchestration_trace: dict[str, Any] = Field(default_factory=dict)
    clinical_case_intake: ClinicalCaseIntakeResult | None = None
    phenotype_hpo_curation: PhenotypeHpoCurationResult | None = None
    pedigree_inheritance_audit: PedigreeInheritanceAuditResult | None = None
    variant_intelligence: VariantIntelligenceResult | None = None
    pre_test_assessment: PreTestAssessmentResult | None = None
    test_strategy_workspace: TestStrategyWorkspaceResult | None = None
    byok_runtime: BYOKPublicStatus | None = None

    def record_action(self, action: AgentAction) -> None:
        self.planned_actions.append(action)
        self.decision_trace.append({"event": "action_planned", "action_id": action.action_id, "action_type": action.action_type})

    def complete_action(self, action: AgentAction) -> None:
        action.status = "completed"
        self.completed_actions.append(action)
        self.decision_trace.append({"event": "action_completed", "action_id": action.action_id})

    def block_action(self, action: AgentAction, reason: str) -> None:
        action.status = "blocked"
        action.blocked_reason = reason
        self.blocked_actions.append(action)
        self.decision_trace.append({"event": "action_blocked", "action_id": action.action_id, "reason": reason})

    def carry_memory(self, memory: dict[str, Any]) -> None:
        self.carried_memory = memory
        self.decision_trace.append({"event": "memory_carried", "size_chars": memory.get("size_chars", 0)})
