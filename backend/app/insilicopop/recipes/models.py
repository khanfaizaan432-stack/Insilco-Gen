from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.insilicopop.workflows.workflow_family import WorkflowFamily


RecipeStatus = Literal["draft", "dry_run_only", "guardrail_tested"]
RecipeMaturityTier = Literal[
    "spec_only",
    "dry_run_template",
    "guardrail_tested",
    "demo_tested",
    "execution_ready_later",
]


class DryRunStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_id: str
    title: str
    description: str
    dry_run_only: Literal[True] = True


class CommandPreviewTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_id: str
    description: str
    preview: str
    dry_run_only: Literal[True] = True
    external_tools_executed: Literal[False] = False


class ProvenanceSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    source_type: str
    url: str | None = None
    note: str | None = None


class RecipeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipe_id: str
    version: str
    workflow_family: WorkflowFamily
    status: RecipeStatus
    maturity_tier: RecipeMaturityTier
    intent_triggers: list[str] = Field(min_length=1)
    declared_input_requirements: dict[str, Any]
    missing_input_rules: list[str] = Field(min_length=1)
    preflight_checks: list[str] = Field(min_length=1)
    dry_run_steps: list[DryRunStep] = Field(min_length=1)
    command_preview_templates: list[CommandPreviewTemplate] = Field(min_length=1)
    expected_outputs: list[str] = Field(min_length=1)
    reproducibility_artifacts: list[str] = Field(min_length=1)
    claim_audit_rules: dict[str, list[str]]
    blocked_interpretations: list[str] = Field(min_length=1)
    scientific_validity_notes: list[str] = Field(min_length=1)
    human_review_checklist: list[str] = Field(min_length=1)
    provenance_sources: list[ProvenanceSource] = Field(min_length=1)
    tests_required: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_safety_invariants(self) -> "RecipeSpec":
        text = " ".join(
            [
                *self.blocked_interpretations,
                *self.scientific_validity_notes,
                *self.preflight_checks,
                *self.human_review_checklist,
            ]
        ).lower()
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
            "external_llm_called=false",
            "external_tools_executed=false",
            "inventory-only",
            "human expert review",
        ]
        missing = [fragment for fragment in required_fragments if fragment not in text]
        if missing:
            raise ValueError(f"Recipe {self.recipe_id} is missing safety fragments: {missing}")
        if self.maturity_tier == "execution_ready_later":
            raise ValueError("v0.18 recipes must not be marked execution_ready_later")
        return self
