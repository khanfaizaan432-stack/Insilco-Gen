from __future__ import annotations

from typing import Any

from app.insilicopop.agent.actions import AgentAction, make_action


class AgentPlanner:
    def plan(self, *, audit_report: dict[str, Any], risk_flags: list[dict[str, Any]], carried_memory: dict[str, Any]) -> list[AgentAction]:
        actions: list[AgentAction] = []
        codes = {str(flag.get("code")) for flag in risk_flags}
        next_index = 1

        def add(action_type, title, rationale, inputs=None, outputs=None, blocked=False, reason=None, deps=None, prov=None):
            nonlocal next_index
            actions.append(
                make_action(
                    next_index,
                    action_type,
                    title,
                    rationale,
                    required_inputs=inputs or [],
                    expected_outputs=outputs or [],
                    memory_dependencies=deps or _memory_dependencies(carried_memory),
                    provenance_refs=prov or _provenance_refs(risk_flags),
                    status="blocked" if blocked else "planned",
                    blocked_reason=reason,
                )
            )
            next_index += 1

        if {"population_column_missing", "missing_population_labels"} & codes:
            add("block_interpretation", "Block strong FST/PCA interpretation until metadata labels are repaired.", "Population labels are missing or incomplete.", blocked=True, reason="metadata population labels missing", deps=["population metadata"])
        if "pca_ld_pruning_not_documented" in codes:
            add("dry_run_ld_pruning", "Dry-run PLINK LD pruning before PCA interpretation.", "LD pruning status is unknown.", ["PLINK binary genotype prefix"], ["prune.prune.in", "prune.prune.out"], deps=["LD pruning status"])
            add("dry_run_pca", "Dry-run smartpca after LD pruning and relatedness handling.", "PCA can be planned after prerequisites are made explicit.", ["LD-pruned genotype set"], ["smartpca.evec", "smartpca.eval", "smartpca.log"], deps=["LD pruning status", "relatedness removal status"])
        if "pca_relatedness_removal_not_documented" in codes:
            add("dry_run_plink_qc", "Dry-run PLINK relatedness/QC checks.", "Relatedness removal is unknown.", ["PLINK binary genotype prefix"], ["relatedness.genome"], deps=["relatedness removal status"])
        if {"admixture_k_sweep_too_narrow", "admixture_only_low_k_tested", "admixture_multiple_seeds_not_documented"} & codes:
            add("dry_run_admixture", "Dry-run ADMIXTURE K=2-10 with multiple seeds.", "K sweep or seed stability is incomplete.", ["LD-pruned genotype set"], ["K-specific .Q/.P outputs", "CV curve"], deps=["K sweep", "multiple seeds"])
        if "high_roh_burden" in codes or "high_roh_sample_burden" in codes or "roh_ibd_analysis_recommended" in codes:
            add("dry_run_roh", "Dry-run PLINK ROH/IBD-aware summary.", "ROH/endogamy context should be retained before relatedness-sensitive interpretation.", ["PLINK binary genotype prefix"], ["roh.hom"], deps=["ROH context"])
        if "fst_tiny_sample_size_caveat" in codes:
            add("block_interpretation", "Block strong FST differentiation claim.", "FST has tiny population sample-size caveats.", blocked=True, reason="tiny population sample size", deps=["sample-size context"])
            add("dry_run_fst", "Dry-run cautious pairwise/windowed FST plan.", "FST can be planned with explicit sample-size caveats.", ["VCF", "population sample lists"], ["fst.weir.fst", "windowed_fst.windowed.weir.fst"], deps=["sample-size context"])
        if "selection_multiple_testing_missing" in codes or "selection_overclaim_proven" in codes or "overclaim_selection_proven" in codes:
            add("dry_run_selection_scan", "Dry-run selection scan with correction/demographic controls.", "Selection claims require correction and demographic caveats.", ["phased VCF", "population labels"], ["iHS/XP-EHH normalized outputs"], deps=["multiple-testing correction", "demographic null model"])
        if "selection_overclaim_proven" in codes or "overclaim_selection_proven" in codes:
            add("block_interpretation", "Block claim that selection is proven.", "Selection scan statistics do not prove selection without correction and demographic controls.", blocked=True, reason="unsupported selection claim", deps=["selection correction"])
        if audit_report:
            add("generate_report", "Generate deterministic agent report.", "Parsed/audited evidence is available for a cautious report.", outputs=["final_report.md"])
        if not actions:
            add("interpret_results", "Proceed to cautious research interpretation.", "No blocking deterministic finding was detected.", deps=["audit provenance"])
        return actions


def _provenance_refs(risk_flags: list[dict[str, Any]]) -> list[str]:
    refs = []
    for flag in risk_flags:
        provenance = flag.get("provenance") if isinstance(flag, dict) else None
        if isinstance(provenance, dict):
            refs.append(str(provenance.get("provenance_id") or provenance.get("rule_id")))
    return sorted({ref for ref in refs if ref and ref != "None"})


def _memory_dependencies(memory: dict[str, Any]) -> list[str]:
    deps = memory.get("downstream_dependencies", [])
    return [str(dep) for dep in deps[:5]] if isinstance(deps, list) else []
