from __future__ import annotations

from app.insilicopop.provenance import make_provenance
from app.schemas.insilicopop import AuditFinding


class NextStepPlanner:
    def plan(self, findings: list[AuditFinding]) -> dict[str, object]:
        by_code = {finding.code: finding for finding in findings}
        steps: list[dict[str, object]] = []
        blocked: list[dict[str, object]] = []
        rationale: list[str] = []

        def add_step(code: str, title: str, reason: str, priority: str = "high") -> None:
            finding = by_code.get(code)
            provenance = _provenance(finding, "NEXT_STEP_" + code.upper())
            steps.append(
                {
                    "step_id": f"step_{len(steps) + 1}_{code}",
                    "title": title,
                    "step": title,
                    "rationale": reason,
                    "reason": reason,
                    "priority": priority,
                    "triggered_by_rule_ids": [provenance["rule_id"]],
                    "provenance": provenance,
                }
            )
            rationale.append(reason)

        def add_block(code: str, blocked_step: str, reason: str, required_fix: str) -> None:
            finding = by_code.get(code)
            blocked.append(
                {
                    "blocked_step": blocked_step,
                    "reason": reason,
                    "required_fix": required_fix,
                    "provenance": _provenance(finding, "BLOCK_" + code.upper()),
                }
            )

        if "tiny_population_groups" in by_code:
            add_step("tiny_population_groups", "Increase tiny population group sample sizes or justify merges.", "Tiny groups make PCA, FST, ADMIXTURE, and ROH summaries unstable.", "high")
        if "broad_indian_population_labels" in by_code:
            add_step("broad_indian_population_labels", "Collect finer-grained community/endogamous group metadata.", "Broad labels may be insufficient for Indian fine-scale structure.")
        if "pca_ld_pruning_not_documented" in by_code:
            add_step("pca_ld_pruning_not_documented", "Run or document LD pruning with PLINK before PCA.", "LD structure can distort PCA axes.")
            add_block("pca_ld_pruning_not_documented", "Strong PCA interpretation", "LD pruning is unknown.", "Run or document LD pruning before strong PCA claims.")
        if "pca_relatedness_removal_not_documented" in by_code:
            add_step("pca_relatedness_removal_not_documented", "Run KING/PLINK relatedness or IBD filtering, or report relatedness explicitly.", "Relatedness can inflate structure in endogamous datasets.")
        if "admixture_k_sweep_too_narrow" in by_code or "admixture_only_low_k_tested" in by_code:
            add_step("admixture_k_sweep_too_narrow", "Run ADMIXTURE K=2-10 with multiple seeds.", "Indian fine-scale structure may require a broader K sweep and stability checks.")
        if "admixture_multiple_seeds_not_documented" in by_code:
            add_step("admixture_multiple_seeds_not_documented", "Repeat ADMIXTURE runs with multiple seeds per K.", "Seed stability should be checked before interpreting components.", "medium")
        if "roh_ibd_analysis_recommended" in by_code:
            add_step("roh_ibd_analysis_recommended", "Run ROH/IBD analysis.", "Endogamy and founder effects can affect downstream interpretation.")
        if "high_roh_burden" in by_code:
            add_step("high_roh_burden", "Summarize ROH/IBD burden by population with founder-effect caveats.", "High ROH can reflect endogamy/founder effects and must not be overinterpreted.", "high")
        if "fst_tiny_sample_size_caveat" in by_code:
            add_step("fst_tiny_sample_size_caveat", "Use larger groups or strong caution for pairwise FST interpretation.", "Pairwise FST estimates are fragile for tiny groups.", "medium")
        if "selection_multiple_testing_missing" in by_code:
            add_step("selection_multiple_testing_missing", "Add multiple-testing correction before interpreting selection candidates.", "Uncorrected selection scans are overclaim-prone.")
        if "selection_overclaim_proven" in by_code or "overclaim_selection_proven" in by_code:
            add_step("selection_overclaim_proven", "Reframe selection language as a candidate signal pending demographic controls.", "Selection is not proven by scan statistics alone.")
            add_block("selection_overclaim_proven", "Claiming selection is proven", "Demographic correction and replication are required.", "Add multiple-testing correction, demographic controls, and cautious language.")
        if "population_column_missing" in by_code or "missing_population_labels" in by_code:
            add_block("population_column_missing", "Strong FST interpretation", "Population labels are missing or incomplete.", "Provide complete population/community labels.")
        if not steps:
            steps.append(
                {
                    "step_id": "step_1_default",
                    "title": "Proceed to cautious interpretation.",
                    "step": "Proceed to cautious interpretation.",
                    "rationale": "No blocking deterministic reliability issue was detected.",
                    "reason": "No blocking deterministic reliability issue was detected.",
                    "priority": "low",
                    "triggered_by_rule_ids": ["NEXT_STEP_DEFAULT"],
                    "provenance": make_provenance(
                        source_file="audit",
                        source_section="planner",
                        parser_name="planner",
                        auditor_name="NextStepPlanner",
                        field_or_column=None,
                        evidence_value="no blocking findings",
                        rule_id="NEXT_STEP_DEFAULT",
                        rule_description="Planner emits at least one next step.",
                        severity="info",
                    ).model_dump(),
                }
            )
        return {"recommended_steps": steps, "blocked_steps": blocked, "rationale": rationale}


def _provenance(finding: AuditFinding | None, fallback_rule: str) -> dict[str, object]:
    if finding and finding.provenance:
        return finding.provenance.model_dump()
    return make_provenance(
        source_file="audit",
        source_section="planner",
        parser_name="planner",
        auditor_name="NextStepPlanner",
        field_or_column=None,
        evidence_value=fallback_rule,
        rule_id=fallback_rule,
        rule_description="Planner recommendation derived from audit state.",
        severity="info",
    ).model_dump()
