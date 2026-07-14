from __future__ import annotations

from typing import Any


REQUIRED_BLOCKED_INTERPRETATIONS = [
    "clinical diagnosis",
    "treatment recommendation",
    "consumer ancestry claim",
    "caste/community/religion inference",
    "genetic purity/superiority language",
    "literal ancestry from ADMIXTURE components",
    "PCA cluster identity claims",
    "unsupported selection claims",
    "unsupported endogamy claims",
]

COMMON_REQUIRED_CAVEATS = [
    "PCA shows structure/clustering, not identity.",
    "ADMIXTURE components are model components, not literal ancestry.",
    "FST/selection scans require adequate controls and cannot alone prove selection.",
    "ROH/founder-effect signals require careful cohort/context review and cannot alone prove endogamy.",
    "India-specific population labels must be handled cautiously and ethically.",
]

UNSUPPORTED_CATEGORY_RULES = [
    ("clinical diagnosis", ("clinical", "diagnos", "disease risk", "medical risk")),
    ("treatment recommendation", ("treatment", "therapy", "medication", "prescribe")),
    ("consumer ancestry claim", ("consumer ancestry", "ancestry report", "ethnicity estimate", "my ancestry")),
    ("caste/community/religion inference", ("caste", "community", "religion", "religious")),
    ("genetic purity/superiority language", ("purity", "pure", "superior", "inferior", "genetic purity")),
    ("literal ancestry from ADMIXTURE components", ("literal ancestry", "admixture proves", "admixture component", "ancestry component")),
    ("PCA cluster identity claims", ("pca cluster", "cluster identity", "identity from pca", "pca proves")),
    ("unsupported selection claims", ("selection is proven", "proves selection", "selected gene", "positive selection proven")),
    ("unsupported endogamy claims", ("endogamy is proven", "proves endogamy", "founder effect proves", "roh proves")),
]


def build_recipe_claim_audit(
    *,
    selected_recipe: dict[str, Any] | None,
    workflow_selection: dict[str, Any],
    query: str | None,
    planned_actions: list[Any],
    blocked_actions: list[Any],
    failure_reasons: list[dict[str, Any]],
    validated_actions: list[dict[str, Any]],
) -> dict[str, Any]:
    selected_recipe = selected_recipe or {}
    workflow_family = str(workflow_selection.get("workflow_family") or selected_recipe.get("workflow_family") or "unknown")
    selected_recipe_id = selected_recipe.get("recipe_id")
    blocked_interpretations = _merge_unique(
        REQUIRED_BLOCKED_INTERPRETATIONS,
        _string_list(selected_recipe.get("blocked_interpretations", [])),
    )
    unsupported_categories = _unsupported_claim_categories(
        query=query,
        blocked_actions=blocked_actions,
        failure_reasons=failure_reasons,
        validated_actions=validated_actions,
        selected_recipe=selected_recipe,
    )
    required_caveats = _required_caveats(workflow_family, selected_recipe)
    human_review_flags = _human_review_flags(selected_recipe, workflow_selection, planned_actions, blocked_actions, failure_reasons)

    return {
        "selected_recipe_id": selected_recipe_id,
        "workflow_family": workflow_family,
        "dry_run_only": True,
        "human_review_required": True,
        "external_tools_executed": False,
        "raw_genomic_files_parsed": False,
        "clinical_or_treatment_claims_blocked": True,
        "clinical_or_consumer_claims_blocked": True,
        "consumer_ancestry_claims_blocked": True,
        "identity_inference_claims_blocked": True,
        "blocked_interpretations": blocked_interpretations,
        "unsupported_claim_categories": unsupported_categories,
        "required_caveats": required_caveats,
        "human_review_flags": human_review_flags,
        "source": "selected_deterministic_recipe",
        "existing_blocked_action_count": len(blocked_actions),
        "failure_reason_count": len(failure_reasons),
    }


def _unsupported_claim_categories(
    *,
    query: str | None,
    blocked_actions: list[Any],
    failure_reasons: list[dict[str, Any]],
    validated_actions: list[dict[str, Any]],
    selected_recipe: dict[str, Any],
) -> list[str]:
    text_fragments = [query or ""]
    text_fragments.extend(str(item) for item in _string_list(selected_recipe.get("blocked_interpretations", [])))
    text_fragments.extend(str(item) for item in _string_list(selected_recipe.get("scientific_validity_notes", [])))
    for action in blocked_actions:
        item = _object_dict(action)
        text_fragments.extend(str(item.get(key, "")) for key in ("action_type", "title", "rationale", "blocked_reason"))
    for failure in failure_reasons:
        text_fragments.extend(str(failure.get(key, "")) for key in ("failure_type", "message", "recommended_fix"))
    for validated in validated_actions:
        text_fragments.extend(str(item) for item in validated.get("blocking_reasons", []) or [])
        text_fragments.append(str(validated.get("claim_intent", "")))
    combined = " ".join(text_fragments).lower()
    matched = [category for category, markers in UNSUPPORTED_CATEGORY_RULES if any(marker in combined for marker in markers)]
    return _merge_unique(matched, REQUIRED_BLOCKED_INTERPRETATIONS)


def _required_caveats(workflow_family: str, selected_recipe: dict[str, Any]) -> list[str]:
    recipe_notes = _string_list(selected_recipe.get("scientific_validity_notes", []))
    caveats = list(COMMON_REQUIRED_CAVEATS)
    if workflow_family == "genotype_likelihood_low_depth":
        caveats.append("Low-depth or ancient-DNA contexts require genotype-likelihood-aware methods, depth/missingness review, and metadata review.")
    if workflow_family == "results_only_audit":
        caveats.append("Existing result files require provenance, metadata, and sample-size review before any scientific claim is used.")
    if workflow_family == "insufficient_inputs":
        caveats.append("No population-genetics conclusion is valid until usable input inventory and metadata are declared.")
    return _merge_unique(caveats, recipe_notes)


def _human_review_flags(
    selected_recipe: dict[str, Any],
    workflow_selection: dict[str, Any],
    planned_actions: list[Any],
    blocked_actions: list[Any],
    failure_reasons: list[dict[str, Any]],
) -> list[str]:
    flags = [
        "Human expert review is mandatory before any real-world command use or scientific interpretation.",
        "Confirm sample metadata, population labels, cohort design, and ethical framing.",
        "Confirm blocked clinical, treatment, consumer ancestry, caste/community/religion, purity/superiority, selection, and endogamy claims remain excluded.",
    ]
    flags.extend(_string_list(selected_recipe.get("human_review_checklist", [])))
    if workflow_selection.get("missing_inputs"):
        flags.append("Resolve workflow-level missing inputs before interpretation.")
    if blocked_actions:
        flags.append("Review blocked planner actions before using report language.")
    if failure_reasons:
        flags.append("Review failure-scope warnings and required fixes before publication or sharing.")
    if planned_actions:
        flags.append("Treat planned actions as dry-run planning records, not completed analyses.")
    return _merge_unique(flags)


def _merge_unique(*groups: list[str]) -> list[str]:
    seen = set()
    merged = []
    for group in groups:
        for item in group:
            value = str(item).strip()
            if not value:
                continue
            key = value.lower()
            if key in seen:
                continue
            seen.add(key)
            merged.append(value)
    return merged


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item is not None]


def _object_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    return {}
