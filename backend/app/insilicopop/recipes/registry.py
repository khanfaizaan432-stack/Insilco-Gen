from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.insilicopop.recipes.models import RecipeSpec
from app.insilicopop.workflows.workflow_family import WorkflowFamily


RECIPES_ROOT = Path(__file__).resolve().parent
CATALOG_PATH = RECIPES_ROOT / "catalog.json"
SPECS_ROOT = RECIPES_ROOT / "specs"
DEFAULT_RECIPE_BY_WORKFLOW_FAMILY: dict[str, str] = {
    "insufficient_inputs": "insufficient_inputs_basic",
    "results_only_audit": "results_only_audit_basic",
    "vcf_population_structure": "vcf_population_structure_basic",
    "hard_called_snp": "hard_called_snp_pca_basic",
    "genotype_likelihood_low_depth": "genotype_likelihood_low_depth_basic",
}


def load_recipe_catalog() -> dict[str, Any]:
    with CATALOG_PATH.open(encoding="utf-8") as handle:
        catalog = json.load(handle)
    if not isinstance(catalog, dict) or not isinstance(catalog.get("recipes"), list):
        raise ValueError("Recipe catalog must contain a recipes list.")
    return catalog


@lru_cache(maxsize=1)
def load_all_recipes() -> tuple[RecipeSpec, ...]:
    catalog = load_recipe_catalog()
    recipes = tuple(load_recipe(entry["recipe_id"]) for entry in catalog["recipes"])
    recipe_ids = [recipe.recipe_id for recipe in recipes]
    if len(recipe_ids) != len(set(recipe_ids)):
        raise ValueError("Recipe IDs must be unique.")
    return recipes


def load_recipe(recipe_id: str) -> RecipeSpec:
    if not recipe_id or any(part in {".", "..", ""} for part in recipe_id.replace("\\", "/").split("/")):
        raise FileNotFoundError(recipe_id)
    catalog = load_recipe_catalog()
    matches = [entry for entry in catalog["recipes"] if entry.get("recipe_id") == recipe_id]
    if not matches:
        raise KeyError(recipe_id)
    relative_path = matches[0].get("path")
    if not isinstance(relative_path, str):
        raise ValueError(f"Recipe {recipe_id} is missing a path.")
    path = (RECIPES_ROOT / relative_path).resolve()
    if not _is_relative_to(path, SPECS_ROOT.resolve()) or path.suffix != ".json":
        raise PermissionError(relative_path)
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    recipe = validate_recipe(payload)
    if recipe.recipe_id != recipe_id:
        raise ValueError(f"Catalog recipe_id {recipe_id} does not match spec {recipe.recipe_id}.")
    return recipe


def get_recipes_for_workflow_family(workflow_family: WorkflowFamily) -> tuple[RecipeSpec, ...]:
    return tuple(recipe for recipe in load_all_recipes() if recipe.workflow_family == workflow_family)


def select_default_recipe_for_workflow_family(workflow_family: str | None) -> RecipeSpec | None:
    if not workflow_family:
        return None
    recipe_id = DEFAULT_RECIPE_BY_WORKFLOW_FAMILY.get(workflow_family)
    if recipe_id is None:
        return None
    try:
        recipe = load_recipe(recipe_id)
    except (FileNotFoundError, KeyError, PermissionError, ValueError):
        return None
    if recipe.workflow_family != workflow_family:
        return None
    return recipe


def selected_recipe_metadata(recipe: RecipeSpec) -> dict[str, Any]:
    return {
        "recipe_id": recipe.recipe_id,
        "version": recipe.version,
        "workflow_family": recipe.workflow_family,
        "status": recipe.status,
        "maturity_tier": recipe.maturity_tier,
        "dry_run_only": True,
        "selected_deterministic_recipe_preview": True,
        "external_tools_executed": False,
        "raw_genomic_files_parsed": False,
        "human_review_required": True,
        "provenance_sources": [source.model_dump() for source in recipe.provenance_sources],
        "dry_run_steps": [step.model_dump() for step in recipe.dry_run_steps],
        "command_preview_templates": [template.model_dump() for template in recipe.command_preview_templates],
        "blocked_interpretations": list(recipe.blocked_interpretations),
        "scientific_validity_notes": list(recipe.scientific_validity_notes),
        "human_review_checklist": list(recipe.human_review_checklist),
    }


def validate_recipe(recipe: RecipeSpec | dict[str, Any]) -> RecipeSpec:
    if isinstance(recipe, RecipeSpec):
        return recipe
    return RecipeSpec.model_validate(recipe)


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True
