from __future__ import annotations

import json
from pathlib import Path

from app.insilicopop.agent.loop import AgentLoop


EXPECTED_RECIPE_BY_WORKFLOW = {
    "insufficient_inputs": "insufficient_inputs_basic",
    "results_only_audit": "results_only_audit_basic",
    "vcf_population_structure": "vcf_population_structure_basic",
    "hard_called_snp": "hard_called_snp_pca_basic",
    "genotype_likelihood_low_depth": "genotype_likelihood_low_depth_basic",
}


def run_agent(tmp_path: Path, query: str, uploads: dict[str, dict[str, bytes | str] | None]) -> dict[str, object]:
    return AgentLoop(generated_root=tmp_path).run(
        query=query,
        uploads=uploads,
        max_steps=8,
        memory_budget_chars=1500,
        memory_mode="compact",
        llm_provider="mock",
    )


def test_workflow_families_map_to_expected_default_recipes(tmp_path):
    cases = [
        ("insufficient_inputs", "study population structure", {}),
        ("results_only_audit", "audit existing PCA and ADMIXTURE outputs", {"pca": {"content": b"x,y\n", "filename": "demo.evec"}}),
        ("vcf_population_structure", "plan VCF PCA", {"vcf": {"content": b"placeholder\n", "filename": "cohort.vcf.gz"}}),
        (
            "hard_called_snp",
            "plan PLINK PCA",
            {
                "plink_bed": {"content": b"placeholder\n", "filename": "cohort.bed"},
                "plink_bim": {"content": b"placeholder\n", "filename": "cohort.bim"},
                "plink_fam": {"content": b"placeholder\n", "filename": "cohort.fam"},
            },
        ),
        ("genotype_likelihood_low_depth", "low-depth ANGSD planning", {"bam": {"content": b"placeholder\n", "filename": "sample.bam"}}),
    ]

    for workflow_family, query, uploads in cases:
        result = run_agent(tmp_path, query, uploads)

        assert result["workflow_selection"]["workflow_family"] == workflow_family
        assert result["selected_recipe"]["recipe_id"] == EXPECTED_RECIPE_BY_WORKFLOW[workflow_family]
        assert result["selected_recipe"]["workflow_family"] == workflow_family
        assert result["selected_recipe"]["dry_run_only"] is True
        assert result["selected_recipe"]["external_tools_executed"] is False
        assert result["selected_recipe"]["raw_genomic_files_parsed"] is False
        assert result["selected_recipe"]["human_review_required"] is True
        assert result["final_state"]["selected_recipe"]["recipe_id"] == EXPECTED_RECIPE_BY_WORKFLOW[workflow_family]


def test_selected_recipe_appears_in_report_and_does_not_claim_execution(tmp_path):
    result = run_agent(tmp_path, "plan VCF PCA", {"vcf": {"content": b"placeholder\n", "filename": "cohort.vcf.gz"}})
    report_path = Path(result["generated_files"]["final_report"]["absolute_path"])
    report = report_path.read_text(encoding="utf-8")

    assert "## Recipe Preview" in report
    assert "selected recipe ID: `vcf_population_structure_basic`" in report
    assert "dry-run-only: true" in report
    assert "selected deterministic dry-run recipe preview" in report
    assert "external_tools_executed: false" in report
    assert "raw_genomic_files_parsed: false" in report
    assert "human_review_required: true" in report
    assert "executed recipe" not in report.lower()
    assert "ran recipe" not in report.lower()
    assert "completed analysis" not in report.lower()


def test_selected_recipe_metadata_appears_in_reproducibility_bundle(tmp_path):
    result = run_agent(tmp_path, "plan VCF PCA", {"vcf": {"content": b"placeholder\n", "filename": "cohort.vcf.gz"}})
    repro_dir = Path(result["reproducibility_bundle"]["path"])
    selected_recipe_path = repro_dir / "selected_recipe.json"

    assert selected_recipe_path.is_file()
    selected_recipe = json.loads(selected_recipe_path.read_text(encoding="utf-8"))
    assert selected_recipe["recipe_id"] == "vcf_population_structure_basic"
    assert selected_recipe["dry_run_only"] is True
    assert selected_recipe["external_tools_executed"] is False
    assert selected_recipe["raw_genomic_files_parsed"] is False
    assert selected_recipe["human_review_required"] is True
    assert selected_recipe["provenance_sources"]
    assert selected_recipe["blocked_interpretations"]
    assert selected_recipe["human_review_checklist"]
    assert "reproducibility/selected_recipe.json" in result["reproducibility_bundle"]["files"]

    provenance_index = json.loads((repro_dir / "provenance_index.json").read_text(encoding="utf-8"))
    assert provenance_index["selected_recipe"]["path"] == "reproducibility/selected_recipe.json"

    runtime_lock = json.loads((repro_dir / "runtime_lock.json").read_text(encoding="utf-8"))
    assert runtime_lock["selected_recipe_id"] == "vcf_population_structure_basic"
    assert runtime_lock["external_tools_executed"] is False


def test_selected_recipe_json_is_in_checksum_scope_without_raw_inputs(tmp_path):
    result = run_agent(tmp_path, "low-depth ANGSD planning", {"bam": {"content": b"placeholder\n", "filename": "sample.bam"}})
    repro_dir = Path(result["reproducibility_bundle"]["path"])
    checksums = (repro_dir / "checksums.sha256").read_text(encoding="utf-8")

    assert "reproducibility/selected_recipe.json" in checksums
    assert "sample.bam" not in checksums


def test_selected_recipe_unknown_handling_does_not_crash():
    from app.insilicopop.recipes.registry import select_default_recipe_for_workflow_family

    assert select_default_recipe_for_workflow_family("unknown_family") is None
