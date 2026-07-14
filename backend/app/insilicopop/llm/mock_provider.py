from __future__ import annotations

from typing import Any

from app.insilicopop.llm.prompt_builder import build_orchestration_prompt
from app.insilicopop.llm.schemas import LLMActionProposal


class MockLLMProvider:
    def __init__(self) -> None:
        self.provider_name = "mock"
        self.external_call_made = False
        self.last_prompt: dict[str, Any] | None = None

    def propose_actions(self, *, compact_memory: dict[str, Any], audit_summary: dict[str, Any], query: str | None) -> list[LLMActionProposal]:
        self.last_prompt = build_orchestration_prompt(compact_memory=compact_memory, audit_summary=audit_summary, query=query)
        codes = {str(flag.get("code")) for flag in audit_summary.get("risk_flags", []) if isinstance(flag, dict)}
        proposals: list[LLMActionProposal] = []
        if "admixture_k_sweep_too_narrow" in codes or "admixture_only_low_k_tested" in codes:
            proposals.append(
                LLMActionProposal(
                    action_type="run_admixture",
                    rationale="Current ADMIXTURE K sweep is too narrow for Indian fine-scale structure.",
                    required_inputs=["LD-pruned genotype data"],
                    expected_outputs=["Q matrix", "CV errors"],
                    confidence=0.82,
                )
            )
        if "pca_ld_pruning_not_documented" in codes:
            proposals.append(
                LLMActionProposal(
                    action_type="interpret_pca",
                    rationale="PCA output exists but LD pruning is unknown.",
                    required_inputs=["PCA coordinates", "LD pruning status"],
                    expected_outputs=["Cautious PCA interpretation"],
                    claim_intent="interpret PCA clusters",
                    confidence=0.74,
                )
            )
        if "fst_tiny_sample_size_caveat" in codes:
            proposals.append(
                LLMActionProposal(
                    action_type="interpret_fst",
                    rationale="FST output exists but tiny groups reduce reliability.",
                    required_inputs=["FST table", "sample sizes"],
                    expected_outputs=["Differentiation interpretation"],
                    claim_intent="strong differentiation claim",
                    confidence=0.7,
                )
            )
        if query and "selection" in query.lower():
            proposals.append(
                LLMActionProposal(
                    action_type="interpret_selection",
                    rationale="User query requests selection interpretation.",
                    required_inputs=["selection scan table", "correction status", "demographic controls"],
                    expected_outputs=["Selection candidate interpretation"],
                    claim_intent=query,
                    confidence=0.78,
                )
            )
        if not proposals:
            proposals.append(
                LLMActionProposal(
                    action_type="generate_report",
                    rationale="Audit evidence can be summarized with deterministic caveats.",
                    expected_outputs=["final_report.md"],
                    confidence=0.8,
                )
            )
        return proposals
