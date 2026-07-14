from __future__ import annotations

from typing import Any

from app.insilicopop.llm.schemas import LLMActionProposal, ValidatedAction


class ActionValidator:
    def validate(
        self,
        proposal: LLMActionProposal,
        *,
        risk_flags: list[dict[str, Any]],
        carried_memory: dict[str, Any],
        uploaded_files: dict[str, str],
    ) -> ValidatedAction:
        codes = {str(flag.get("code")) for flag in risk_flags}
        provenance_refs = _provenance_refs(risk_flags)
        memory_dependencies = _memory_dependencies(carried_memory)
        original = proposal.model_dump()
        action = dict(original)
        required_fixes: list[str] = []
        blocking: list[str] = []
        status = "approved"

        claim = (proposal.claim_intent or proposal.rationale or "").lower()
        if proposal.action_type == "interpret_selection" and "proven" in claim and (
            "selection_multiple_testing_missing" in codes or "selection_overclaim_proven" in codes or "overclaim_selection_proven" in codes
        ):
            status = "blocked"
            blocking.append("selection is claimed as proven without correction/demographic controls")
            required_fixes.append("Add multiple-testing correction, demographic controls, and cautious language.")
        elif proposal.action_type == "interpret_pca" and "pca_ld_pruning_not_documented" in codes:
            status = "modified"
            action.update(
                {
                    "action_type": "dry_run_ld_pruning",
                    "rationale": "LD pruning is unknown, so run LD-pruning dry-run before PCA interpretation.",
                    "required_inputs": ["PLINK binary genotype prefix"],
                    "expected_outputs": ["prune.prune.in", "prune.prune.out"],
                }
            )
            required_fixes.append("Run or document LD pruning before PCA interpretation.")
        elif proposal.action_type in {"run_admixture", "interpret_admixture"} and (
            "admixture_k_sweep_too_narrow" in codes or "admixture_only_low_k_tested" in codes
        ):
            status = "modified"
            action.update(
                {
                    "action_type": "dry_run_admixture",
                    "rationale": "Broaden ADMIXTURE to K=2-10 with multiple seeds before interpretation.",
                    "required_inputs": ["LD-pruned genotype data"],
                    "expected_outputs": ["Q matrix", "CV errors", "seed stability summary"],
                    "k_range": "2-10",
                    "seeds": [1, 2, 3],
                }
            )
            required_fixes.append("Use K=2-10 and multiple seeds.")
        elif proposal.action_type == "interpret_fst" and (
            "fst_tiny_sample_size_caveat" in codes or "tiny_population_groups" in codes
        ):
            status = "blocked"
            blocking.append("strong FST differentiation claim with tiny population groups")
            required_fixes.append("Increase group N or keep FST interpretation explicitly cautious.")
        if proposal.action_type == "interpret_fst" and ("population_column_missing" in codes or "missing_population_labels" in codes):
            status = "blocked"
            blocking.append("FST interpretation requires complete population labels")
            required_fixes.append("Repair population/community metadata labels.")
        if "high_roh_burden" in codes or "high_roh_sample_burden" in codes:
            action["required_caveat"] = "Interpret ROH with endogamy/founder-effect context; no clinical claim."
            if status == "approved":
                status = "modified"
            required_fixes.append("Retain endogamy/founder-effect caveat.")
        action["execution_enabled"] = False
        if _needs_genotype(proposal.action_type) and not _has_genotype_placeholder(uploaded_files):
            action["execution_enabled"] = False
            action["dry_run_only_reason"] = "Genotype/VCF/PLINK bed input is not uploaded; command preview remains allowed."
            if status == "approved":
                status = "modified"
            required_fixes.append("Provide genotype/VCF/PLINK bed input before real execution is enabled in a future version.")

        return ValidatedAction(
            status=status,  # type: ignore[arg-type]
            original_proposal=original,
            final_action=None if status == "blocked" else action,
            blocking_reasons=blocking,
            required_fixes=required_fixes,
            provenance_refs=provenance_refs,
            memory_dependencies=memory_dependencies,
        )


def _provenance_refs(risk_flags: list[dict[str, Any]]) -> list[str]:
    refs = []
    for flag in risk_flags:
        provenance = flag.get("provenance") if isinstance(flag, dict) else None
        if isinstance(provenance, dict):
            refs.append(str(provenance.get("provenance_id") or provenance.get("rule_id")))
    return sorted({ref for ref in refs if ref and ref != "None"})


def _memory_dependencies(memory: dict[str, Any]) -> list[str]:
    deps = memory.get("downstream_dependencies", [])
    if isinstance(deps, list):
        return [str(dep) for dep in deps]
    return []


def _needs_genotype(action_type: str) -> bool:
    return action_type in {"run_admixture", "interpret_admixture", "interpret_pca", "interpret_fst", "dry_run_admixture", "dry_run_ld_pruning"}


def _has_genotype_placeholder(uploaded_files: dict[str, str]) -> bool:
    names = " ".join(uploaded_files.values()).lower()
    return any(marker in names for marker in [".bed", ".vcf", ".bfile", "plink"])
