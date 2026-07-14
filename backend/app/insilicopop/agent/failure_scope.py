from __future__ import annotations

from typing import Any

from app.insilicopop.agent.actions import AgentAction


class FailureScope:
    def evaluate(
        self,
        *,
        risk_flags: list[dict[str, Any]],
        actions: list[AgentAction],
        carried_memory: dict[str, Any],
    ) -> list[dict[str, Any]]:
        failures: list[dict[str, Any]] = []
        codes = {str(flag.get("code")) for flag in risk_flags}
        by_code = {str(flag.get("code")): flag for flag in risk_flags}
        if "selection_overclaim_proven" in codes or "overclaim_selection_proven" in codes:
            failures.append(_failure("unsupported_selection_claim", "critical", "Selection is claimed as proven without sufficient corrected/demographic evidence.", ["selection_overclaim_proven"], "Block strong selection interpretation and require correction plus demographic controls."))
        if "selection_multiple_testing_missing" in codes:
            failures.append(_failure("unsupported_selection_claim", "high", "Selection scan lacks multiple-testing correction.", ["selection_multiple_testing_missing"], "Add FDR/Bonferroni or equivalent correction before interpretation."))
        if "pca_ld_pruning_not_documented" in codes:
            failures.append(_failure("missing_ld_pruning", "high", "PCA interpretation is unsafe because LD pruning is not documented.", ["pca_ld_pruning_not_documented"], "Dry-run or document PLINK LD pruning before PCA interpretation."))
        if "admixture_k_sweep_too_narrow" in codes or "admixture_multiple_seeds_not_documented" in codes:
            failures.append(_failure("missing_admixture_stability_check", "warning", "ADMIXTURE stability is incomplete.", ["admixture_k_sweep_too_narrow", "admixture_multiple_seeds_not_documented"], "Plan K=2-10 with multiple seeds."))
        if "tiny_population_groups" in codes or "fst_tiny_sample_size_caveat" in codes:
            failures.append(_failure("insufficient_sample_size", "warning", "Population-genetic interpretation is fragile for tiny groups.", ["tiny_population_groups", "fst_tiny_sample_size_caveat"], "Increase group N or keep claims cautious."))
        if _wrong_tool_order(actions):
            failures.append(_failure("wrong_tool_order", "warning", "A downstream interpretation is planned before a prerequisite dry-run step.", ["planned_actions"], "Run QC/LD pruning/stability actions before interpretation."))
        if not carried_memory.get("dependency_capsules") and any(code in codes for code in ["pca_ld_pruning_not_documented", "selection_multiple_testing_missing", "admixture_k_sweep_too_narrow"]):
            failures.append(_failure("memory_dependency_missing", "high", "Dependency-bearing audit warnings were not retained in carried memory.", ["carried_memory"], "Re-run memory governor with dependency capsules enabled."))
        for code, flag in by_code.items():
            if code in {"pca_ld_pruning_not_documented", "selection_multiple_testing_missing", "admixture_k_sweep_too_narrow", "fst_tiny_sample_size_caveat"} and not flag.get("provenance"):
                failures.append(_failure("provenance_missing_for_key_warning", "high", f"Key warning {code} lacks provenance.", [code], "Attach row/table-level provenance before using this warning."))
        return failures


def _failure(failure_type: str, severity: str, message: str, triggered_by: list[str], recommended_fix: str, blocked_action_id: str | None = None) -> dict[str, Any]:
    return {
        "failure_type": failure_type,
        "severity": severity,
        "message": message,
        "triggered_by": triggered_by,
        "recommended_fix": recommended_fix,
        "blocked_action_id": blocked_action_id,
    }


def _wrong_tool_order(actions: list[AgentAction]) -> bool:
    order = [action.action_type for action in actions]
    return "interpret_results" in order and "dry_run_ld_pruning" in order and order.index("interpret_results") < order.index("dry_run_ld_pruning")
