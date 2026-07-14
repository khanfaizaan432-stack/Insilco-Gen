from __future__ import annotations

from pathlib import Path

import yaml

from app.insilicopop.agent.loop import AgentLoop


def run_agent(tmp_path: Path, query: str, uploads: dict[str, dict[str, bytes | str] | None]) -> dict[str, object]:
    return AgentLoop(generated_root=tmp_path).run(
        query=query,
        uploads=uploads,
        max_steps=8,
        memory_budget_chars=1500,
        memory_mode="compact",
        llm_provider="mock",
    )


def recipe_previews(result: dict[str, object]) -> list[dict[str, object]]:
    previews = result["command_previews"]
    assert isinstance(previews, list)
    return [preview for preview in previews if isinstance(preview, dict) and preview.get("recipe_aware_preview") is True]


def assert_preview_safety(previews: list[dict[str, object]], recipe_id: str) -> None:
    assert previews
    for preview in previews:
        assert preview["selected_recipe_id"] == recipe_id
        assert preview["dry_run_only"] is True
        assert preview["execution_enabled"] is False
        assert preview["external_tools_executed"] is False
        assert preview["raw_genomic_files_parsed"] is False
        assert preview["human_review_required"] is True
        command = str(preview["command"])
        assert command
        assert all(line.startswith("#") for line in command.splitlines() if line.strip())


def joined_commands(previews: list[dict[str, object]]) -> str:
    return "\n".join(str(preview.get("command", "")) for preview in previews)


def test_vcf_recipe_shapes_command_previews_and_reproducibility(tmp_path):
    result = run_agent(
        tmp_path,
        "plan VCF PCA and ADMIXTURE population structure",
        {"vcf": {"content": b"placeholder\n", "filename": "cohort.vcf.gz"}},
    )
    previews = recipe_previews(result)
    commands = joined_commands(previews)

    assert_preview_safety(previews, "vcf_population_structure_basic")
    assert "# plink --vcf <declared_vcf> --make-bed --out <planned_output_prefix>" in commands
    assert "# plink --bfile <planned_output_prefix> --indep-pairwise" in commands
    assert "# smartpca -p <planned_output_prefix>.smartpca.par" in commands
    assert "# admixture --cv <planned_output_prefix>.ld.pruned.bed <k_min>" in commands

    repro_dir = Path(result["reproducibility_bundle"]["path"])
    shell_preview = (repro_dir / "command_previews.sh").read_text(encoding="utf-8")
    yaml_preview = yaml.safe_load((repro_dir / "command_previews.yaml").read_text(encoding="utf-8"))

    assert all(line.startswith("#") for line in shell_preview.splitlines() if line.strip())
    assert any(item["selected_recipe_id"] == "vcf_population_structure_basic" for item in yaml_preview)
    assert all(item["external_tools_executed"] is False for item in yaml_preview)
    assert all(item["raw_genomic_files_parsed"] is False for item in yaml_preview)
    assert all(item["human_review_required"] is True for item in yaml_preview)


def test_hard_called_recipe_previews_qc_ld_pca_and_cautions(tmp_path):
    result = run_agent(
        tmp_path,
        "plan hard-called SNP PLINK PCA workflow",
        {
            "plink_bed": {"content": b"placeholder\n", "filename": "cohort.bed"},
            "plink_bim": {"content": b"placeholder\n", "filename": "cohort.bim"},
            "plink_fam": {"content": b"placeholder\n", "filename": "cohort.fam"},
        },
    )
    previews = recipe_previews(result)
    commands = joined_commands(previews)
    purposes = " ".join(str(preview.get("purpose", "")) for preview in previews)

    assert_preview_safety(previews, "hard_called_snp_pca_basic")
    assert "# plink --bfile <declared_plink_prefix> --missing --het --hardy" in commands
    assert "# plink --bfile <declared_plink_prefix> --indep-pairwise" in commands
    assert "# smartpca -p <planned_output_prefix>.smartpca.par" in commands
    assert "relatedness" in purposes.lower()
    assert "outlier" in purposes.lower()


def test_low_depth_recipe_warns_against_hard_calls_and_uses_likelihood_placeholders(tmp_path):
    result = run_agent(
        tmp_path,
        "low-depth ANGSD PCAngsd NGSadmix planning",
        {"bam": {"content": b"placeholder\n", "filename": "sample.bam"}},
    )
    previews = recipe_previews(result)
    commands = joined_commands(previews)

    assert_preview_safety(previews, "genotype_likelihood_low_depth_basic")
    assert "hard-called SNP PCA" in commands
    assert "# angsd -bam <declared_bam_or_cram>" in commands
    assert "# pcangsd -b <planned_output_prefix>.beagle.gz" in commands
    assert "# NGSadmix -likes <planned_output_prefix>.beagle.gz" in commands
    assert "depth" in commands.lower()
    assert "missingness" in commands.lower()


def test_results_only_recipe_audits_without_computation_commands(tmp_path):
    result = run_agent(
        tmp_path,
        "audit existing PCA and ADMIXTURE output claims",
        {"pca": {"content": b"x,y\n", "filename": "demo.evec"}},
    )
    previews = recipe_previews(result)
    commands = joined_commands(previews)

    assert_preview_safety(previews, "results_only_audit_basic")
    assert "Audit provenance" in commands
    assert "Do not execute PLINK" in commands
    assert "--bfile" not in commands
    assert "--vcf" not in commands
    assert "--cv" not in commands


def test_insufficient_inputs_recipe_does_not_emit_fake_commands(tmp_path):
    result = run_agent(tmp_path, "study population structure", {})
    previews = recipe_previews(result)
    commands = joined_commands(previews)

    assert_preview_safety(previews, "insufficient_inputs_basic")
    assert "No PLINK, ADMIXTURE, smartpca, vcftools, ANGSD, PCAngsd, or NGSadmix command is previewed" in commands
    assert " --" not in commands


def test_final_report_links_selected_recipe_to_command_previews(tmp_path):
    result = run_agent(
        tmp_path,
        "plan VCF PCA",
        {"vcf": {"content": b"placeholder\n", "filename": "cohort.vcf.gz"}},
    )
    report_path = Path(result["generated_files"]["final_report"]["absolute_path"])
    report = report_path.read_text(encoding="utf-8")

    assert "The selected deterministic recipe shaped these dry-run previews." in report
    assert "The previews were not executed." in report
    assert "Raw genomic files were not parsed." in report
    assert "Human review is required before any real-world command use." in report
    assert "Selected recipe: `vcf_population_structure_basic`" in report
    assert "External tools executed: false" in report
    assert "Raw genomic files parsed: false" in report
