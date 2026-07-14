from __future__ import annotations

from typing import get_args

from app.insilicopop.recipes.models import RecipeMaturityTier, RecipeSpec, RecipeStatus
from app.insilicopop.recipes.registry import (
    get_recipes_for_workflow_family,
    load_all_recipes,
    load_recipe,
    load_recipe_catalog,
)
from app.insilicopop.workflows.workflow_family import WorkflowFamily


REQUIRED_RECIPE_IDS = {
    "insufficient_inputs_basic",
    "results_only_audit_basic",
    "vcf_population_structure_basic",
    "hard_called_snp_pca_basic",
    "genotype_likelihood_low_depth_basic",
}

REQUIRED_FIELDS = {
    "recipe_id",
    "version",
    "workflow_family",
    "status",
    "maturity_tier",
    "intent_triggers",
    "declared_input_requirements",
    "missing_input_rules",
    "preflight_checks",
    "dry_run_steps",
    "command_preview_templates",
    "expected_outputs",
    "reproducibility_artifacts",
    "claim_audit_rules",
    "blocked_interpretations",
    "scientific_validity_notes",
    "human_review_checklist",
    "provenance_sources",
    "tests_required",
}


def test_recipe_catalog_loads_and_contains_required_recipe_ids():
    catalog = load_recipe_catalog()

    recipe_ids = {entry["recipe_id"] for entry in catalog["recipes"]}
    assert REQUIRED_RECIPE_IDS <= recipe_ids


def test_all_required_recipes_load_and_ids_are_unique():
    recipes = load_all_recipes()
    recipe_ids = [recipe.recipe_id for recipe in recipes]

    assert REQUIRED_RECIPE_IDS <= set(recipe_ids)
    assert len(recipe_ids) == len(set(recipe_ids))
    assert all(isinstance(recipe, RecipeSpec) for recipe in recipes)


def test_load_recipe_returns_single_recipe():
    recipe = load_recipe("vcf_population_structure_basic")

    assert recipe.recipe_id == "vcf_population_structure_basic"
    assert recipe.workflow_family == "vcf_population_structure"


def test_recipes_are_queryable_by_existing_workflow_family():
    for workflow_family in get_args(WorkflowFamily):
        recipes = get_recipes_for_workflow_family(workflow_family)

        assert recipes, f"missing recipe for {workflow_family}"
        assert all(recipe.workflow_family == workflow_family for recipe in recipes)


def test_recipe_required_fields_and_enum_values_are_conservative():
    allowed_statuses = set(get_args(RecipeStatus))
    allowed_maturity_tiers = set(get_args(RecipeMaturityTier))
    valid_workflow_families = set(get_args(WorkflowFamily))

    for recipe in load_all_recipes():
        dumped = recipe.model_dump()
        assert REQUIRED_FIELDS <= dumped.keys()
        assert recipe.workflow_family in valid_workflow_families
        assert recipe.status in allowed_statuses
        assert recipe.maturity_tier in allowed_maturity_tiers
        assert recipe.status not in {"production_ready", "execution_ready", "clinically_validated"}
        assert recipe.maturity_tier != "execution_ready_later"


def test_recipes_include_human_review_provenance_and_validity_notes():
    for recipe in load_all_recipes():
        assert recipe.human_review_checklist
        assert recipe.provenance_sources
        assert recipe.scientific_validity_notes
        assert any("human expert review" in item.lower() for item in recipe.human_review_checklist)


def test_blocked_interpretations_cover_required_safety_topics():
    required_fragments = [
        "clinical diagnosis",
        "treatment recommendation",
        "consumer ancestry",
        "caste",
        "community",
        "religion",
        "genetic purity",
        "superiority",
        "admixture",
        "pca cluster",
        "unsupported selection",
        "unsupported endogamy",
    ]

    for recipe in load_all_recipes():
        blocked = " ".join(recipe.blocked_interpretations).lower()

        for fragment in required_fragments:
            assert fragment in blocked, f"{recipe.recipe_id} missing {fragment}"


def test_command_previews_are_dry_run_only_and_do_not_authorize_execution():
    for recipe in load_all_recipes():
        assert recipe.command_preview_templates
        for command_preview in recipe.command_preview_templates:
            assert command_preview.dry_run_only is True
            assert command_preview.external_tools_executed is False
            assert "dry-run only" in command_preview.preview.lower()
            assert "do not execute" in command_preview.preview.lower() or recipe.recipe_id == "insufficient_inputs_basic"


def test_recipes_do_not_authorize_raw_genomic_parsing_or_external_tools():
    for recipe in load_all_recipes():
        text = " ".join(
            [
                *recipe.preflight_checks,
                *recipe.scientific_validity_notes,
                str(recipe.declared_input_requirements),
            ]
        ).lower()

        assert "external_llm_called=false" in text
        assert "external_tools_executed=false" in text
        assert "inventory-only" in text
        assert "not parsed" in text


def test_recipes_do_not_claim_clinical_or_production_readiness():
    forbidden_fragments = [
        "production_ready",
        "execution_ready",
        "clinically_validated",
        "clinical use",
        "treatment-ready",
    ]

    for recipe in load_all_recipes():
        text = str(recipe.model_dump()).lower()

        for fragment in forbidden_fragments:
            assert fragment not in text
