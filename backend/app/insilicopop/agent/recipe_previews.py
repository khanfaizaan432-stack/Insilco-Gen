from __future__ import annotations

from typing import Any


SAFETY_PREAMBLE = "# DRY-RUN PREVIEW ONLY - do not execute without human review"


def build_recipe_command_previews(
    *,
    selected_recipe: dict[str, Any] | None,
    input_inventory: dict[str, str],
) -> list[dict[str, Any]]:
    if not selected_recipe:
        return []

    recipe_id = str(selected_recipe.get("recipe_id") or "")
    templates = selected_recipe.get("command_preview_templates", []) or []
    dry_run_steps = selected_recipe.get("dry_run_steps", []) or []
    step_ids = [str(step.get("step_id")) for step in dry_run_steps if isinstance(step, dict) and step.get("step_id")]
    inventory_categories = _inventory_categories(input_inventory)

    builders = {
        "insufficient_inputs_basic": _insufficient_inputs_previews,
        "results_only_audit_basic": _results_only_audit_previews,
        "vcf_population_structure_basic": _vcf_population_structure_previews,
        "hard_called_snp_pca_basic": _hard_called_snp_previews,
        "genotype_likelihood_low_depth_basic": _low_depth_previews,
    }
    builder = builders.get(recipe_id, _template_fallback_previews)
    previews = builder(selected_recipe, templates, step_ids, inventory_categories)
    return apply_command_preview_safety_metadata(previews, selected_recipe=selected_recipe)


def apply_command_preview_safety_metadata(
    command_previews: list[dict[str, Any]],
    *,
    selected_recipe: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    recipe_id = (selected_recipe or {}).get("recipe_id")
    normalized: list[dict[str, Any]] = []
    for preview in command_previews:
        item = dict(preview)
        if recipe_id and not item.get("selected_recipe_id"):
            item["selected_recipe_id"] = recipe_id
        item.setdefault("dry_run_only", True)
        item.setdefault("external_tools_executed", False)
        item.setdefault("raw_genomic_files_parsed", False)
        item.setdefault("human_review_required", True)
        item["execution_enabled"] = False
        command = str(item.get("command", "")).strip()
        if command:
            item["command"] = _commented_command(command)
        normalized.append(item)
    return normalized


def _insufficient_inputs_previews(
    recipe: dict[str, Any],
    templates: list[dict[str, Any]],
    step_ids: list[str],
    inventory_categories: list[str],
) -> list[dict[str, Any]]:
    template = _template(templates, 0)
    return [
        _preview(
            recipe,
            template=template,
            recipe_step_id=_step_id(step_ids, 0, "collect_inventory"),
            tool="none",
            purpose="Explain why no genomics command preview is appropriate until input inventory is declared.",
            command_lines=[
                SAFETY_PREAMBLE,
                "# No PLINK, ADMIXTURE, smartpca, vcftools, ANGSD, PCAngsd, or NGSadmix command is previewed.",
                "# Declare inventory-only VCF, PLINK/PED/PGEN, BAM/CRAM, genotype-likelihood, metadata, or existing-result inputs first.",
            ],
            required_inputs=["inventory-only declared input paths/names"],
            expected_outputs=["missing input notes", "recommended input inventory"],
            inventory_categories=inventory_categories,
        )
    ]


def _results_only_audit_previews(
    recipe: dict[str, Any],
    templates: list[dict[str, Any]],
    step_ids: list[str],
    inventory_categories: list[str],
) -> list[dict[str, Any]]:
    template = _template(templates, 0)
    return [
        _preview(
            recipe,
            template=template,
            recipe_step_id=_step_id(step_ids, 0, "inventory_results"),
            tool="results-audit",
            purpose="Audit declared existing result files and claims without running genomics tools.",
            command_lines=[
                SAFETY_PREAMBLE,
                "# Inventory existing PCA, ADMIXTURE, PLINK summary, FST, ROH, selection, report, or manuscript result files only.",
                "# Audit provenance, metadata, sample-size context, and unsafe claims.",
                "# Do not execute PLINK, ADMIXTURE, smartpca, vcftools, ANGSD, PCAngsd, NGSadmix, or other genomics tools.",
            ],
            required_inputs=["declared existing result files", "<population_metadata>"],
            expected_outputs=["result inventory", "claim audit", "blocked interpretations", "researcher report"],
            inventory_categories=inventory_categories,
        )
    ]


def _vcf_population_structure_previews(
    recipe: dict[str, Any],
    templates: list[dict[str, Any]],
    step_ids: list[str],
    inventory_categories: list[str],
) -> list[dict[str, Any]]:
    return [
        _preview(
            recipe,
            template=_template_by_id(templates, "plink_convert_preview"),
            recipe_step_id=_step_id(step_ids, 0, "inventory_vcf"),
            tool="plink",
            purpose="Preview inventory-only VCF conversion to a PLINK working prefix for later human review.",
            command_lines=[
                SAFETY_PREAMBLE,
                "# plink --vcf <declared_vcf> --make-bed --out <planned_output_prefix>",
            ],
            required_inputs=["<declared_vcf>", "<population_metadata>"],
            expected_outputs=["<planned_output_prefix>.bed", "<planned_output_prefix>.bim", "<planned_output_prefix>.fam"],
            blocked_if=["declared VCF is missing", "human reviewer has not approved conversion assumptions"],
            inventory_categories=inventory_categories,
        ),
        _preview(
            recipe,
            template=_template_by_id(templates, "pca_preview"),
            recipe_step_id=_step_id(step_ids, 2, "preview_qc_ld_pca_admixture"),
            tool="plink/eigensoft/admixture",
            purpose="Preview VCF-derived QC, LD pruning, PCA, and optional ADMIXTURE K sweep.",
            command_lines=[
                SAFETY_PREAMBLE,
                "# plink --bfile <planned_output_prefix> --missing --hardy --out <planned_output_prefix>.qc",
                "# plink --bfile <planned_output_prefix> --indep-pairwise 50 5 0.2 --out <planned_output_prefix>.ld",
                "# smartpca -p <planned_output_prefix>.smartpca.par",
                "# admixture --cv <planned_output_prefix>.ld.pruned.bed <k_min> # repeat through <k_max> with reviewed seeds",
            ],
            required_inputs=["<declared_vcf>", "<population_metadata>", "<human_reviewed_thresholds>"],
            expected_outputs=["QC summaries", "LD-pruned marker list", "PCA eigenvectors/eigenvalues", "optional ADMIXTURE CV summaries"],
            blocked_if=["metadata is missing for population interpretation", "QC/LD thresholds lack human review"],
            inventory_categories=inventory_categories,
        ),
    ]


def _hard_called_snp_previews(
    recipe: dict[str, Any],
    templates: list[dict[str, Any]],
    step_ids: list[str],
    inventory_categories: list[str],
) -> list[dict[str, Any]]:
    return [
        _preview(
            recipe,
            template=_template_by_id(templates, "plink_qc_preview"),
            recipe_step_id=_step_id(step_ids, 1, "preview_qc"),
            tool="plink",
            purpose="Preview hard-called SNP QC, relatedness, and outlier caution checks.",
            command_lines=[
                SAFETY_PREAMBLE,
                "# plink --bfile <declared_plink_prefix> --missing --het --hardy --out <planned_output_prefix>.qc",
                "# plink --bfile <declared_plink_prefix> --genome --out <planned_output_prefix>.relatedness",
            ],
            required_inputs=["<declared_plink_prefix>", "<population_metadata>", "<human_reviewed_thresholds>"],
            expected_outputs=["missingness summaries", "heterozygosity summary", "HWE summary", "relatedness summary"],
            blocked_if=["paired/trio PLINK, PED/MAP, or PGEN companion files are incomplete", "relatedness thresholds lack human review"],
            inventory_categories=inventory_categories,
        ),
        _preview(
            recipe,
            template=_template_by_id(templates, "ld_pca_preview"),
            recipe_step_id=_step_id(step_ids, 2, "preview_ld_pruned_pca"),
            tool="plink/eigensoft",
            purpose="Preview LD pruning and PCA for hard-called SNP inputs after QC review.",
            command_lines=[
                SAFETY_PREAMBLE,
                "# plink --bfile <declared_plink_prefix> --indep-pairwise 50 5 0.2 --out <planned_output_prefix>.ld",
                "# plink --bfile <declared_plink_prefix> --extract <planned_output_prefix>.ld.prune.in --make-bed --out <planned_output_prefix>.ld.pruned",
                "# smartpca -p <planned_output_prefix>.smartpca.par",
            ],
            required_inputs=["<declared_plink_prefix>", "<population_metadata>", "<human_reviewed_thresholds>"],
            expected_outputs=["LD-pruned marker list", "LD-pruned PLINK prefix", "PCA eigenvectors/eigenvalues"],
            blocked_if=["QC is not reviewed", "relatedness/outlier policy is not documented"],
            inventory_categories=inventory_categories,
        ),
    ]


def _low_depth_previews(
    recipe: dict[str, Any],
    templates: list[dict[str, Any]],
    step_ids: list[str],
    inventory_categories: list[str],
) -> list[dict[str, Any]]:
    return [
        _preview(
            recipe,
            template=_template_by_id(templates, "angsd_preview"),
            recipe_step_id=_step_id(step_ids, 1, "warn_against_hard_calls"),
            tool="angsd",
            purpose="Preview a genotype-likelihood-aware path and warn against default hard-call assumptions.",
            command_lines=[
                SAFETY_PREAMBLE,
                "# Low-depth or ancient-DNA contexts should not default to hard-called SNP PCA without expert review.",
                "# angsd -bam <declared_bam_or_cram> -GL 2 -doGlf 2 -out <planned_output_prefix>",
            ],
            required_inputs=["<declared_bam_or_cram>", "<population_metadata>", "depth/missingness context"],
            expected_outputs=["genotype likelihood preview outputs", "low-depth caveat notes"],
            blocked_if=["depth context is missing", "BAM/CRAM inventory is not human reviewed"],
            inventory_categories=inventory_categories,
        ),
        _preview(
            recipe,
            template=_template_by_id(templates, "pcangsd_ngsadmix_preview"),
            recipe_step_id=_step_id(step_ids, 2, "preview_likelihood_methods"),
            tool="pcangsd/ngsadmix",
            purpose="Preview PCAngsd/NGSadmix-style planning with depth, missingness, and metadata caveats.",
            command_lines=[
                SAFETY_PREAMBLE,
                "# pcangsd -b <planned_output_prefix>.beagle.gz -o <planned_output_prefix>.pcangsd",
                "# NGSadmix -likes <planned_output_prefix>.beagle.gz -K <k_min> -o <planned_output_prefix>.ngsadmix.K<k_min>",
                "# Repeat K only through <k_max> after human review of depth, missingness, contamination/damage, and metadata.",
            ],
            required_inputs=["<declared_bam_or_cram>", "<population_metadata>", "<k_min>", "<k_max>", "<human_reviewed_thresholds>"],
            expected_outputs=["PCAngsd preview summary", "NGSadmix preview summaries", "low-depth reproducibility notes"],
            blocked_if=["metadata is missing", "depth/missingness caveats are unresolved"],
            inventory_categories=inventory_categories,
        ),
    ]


def _template_fallback_previews(
    recipe: dict[str, Any],
    templates: list[dict[str, Any]],
    step_ids: list[str],
    inventory_categories: list[str],
) -> list[dict[str, Any]]:
    previews = []
    for index, template in enumerate(templates):
        previews.append(
            _preview(
                recipe,
                template=template,
                recipe_step_id=_step_id(step_ids, index, f"recipe_step_{index + 1}"),
                tool="recipe-template",
                purpose=str(template.get("description") or "Recipe command preview template."),
                command_lines=[SAFETY_PREAMBLE, str(template.get("preview") or "# no preview text recorded")],
                required_inputs=["inventory-only declared inputs"],
                expected_outputs=list(recipe.get("expected_outputs", []) or ["researcher report"]),
                inventory_categories=inventory_categories,
            )
        )
    return previews


def _preview(
    recipe: dict[str, Any],
    *,
    template: dict[str, Any],
    recipe_step_id: str,
    tool: str,
    purpose: str,
    command_lines: list[str],
    required_inputs: list[str],
    expected_outputs: list[str],
    inventory_categories: list[str],
    blocked_if: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "tool": tool,
        "purpose": purpose,
        "command": "\n".join(command_lines),
        "required_inputs": required_inputs,
        "expected_outputs": expected_outputs,
        "blocked_if": blocked_if or [],
        "assumptions": [
            "Inventory-only file paths/names are used as declared labels; raw genomic contents are not parsed.",
            "Commands are previews for human review and are not executed by InSilicoPop.",
        ],
        "selected_recipe_id": recipe.get("recipe_id"),
        "recipe_step_id": recipe_step_id,
        "template_id": template.get("template_id"),
        "template_description": template.get("description"),
        "recipe_aware_preview": True,
        "input_inventory_categories": inventory_categories,
    }


def _template(templates: list[dict[str, Any]], index: int) -> dict[str, Any]:
    try:
        template = templates[index]
    except IndexError:
        return {}
    return template if isinstance(template, dict) else {}


def _template_by_id(templates: list[dict[str, Any]], template_id: str) -> dict[str, Any]:
    for template in templates:
        if isinstance(template, dict) and template.get("template_id") == template_id:
            return template
    return {}


def _step_id(step_ids: list[str], index: int, fallback: str) -> str:
    try:
        return step_ids[index]
    except IndexError:
        return fallback


def _commented_command(command: str) -> str:
    lines = []
    for raw_line in command.splitlines():
        line = raw_line.rstrip()
        if not line:
            continue
        lines.append(line if line.lstrip().startswith("#") else f"# {line}")
    return "\n".join(lines)


def _inventory_categories(input_inventory: dict[str, str]) -> list[str]:
    if not input_inventory:
        return ["none declared"]
    categories = []
    for field_name, filename in sorted(input_inventory.items()):
        categories.append(f"{field_name}:{filename}")
    return categories
