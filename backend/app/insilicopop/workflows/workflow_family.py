from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


WorkflowFamily = Literal[
    "results_only_audit",
    "vcf_population_structure",
    "hard_called_snp",
    "genotype_likelihood_low_depth",
    "insufficient_inputs",
]

SelectableWorkflowFamily = Literal[
    "clinical_case_intake",
    "results_only_audit",
    "vcf_population_structure",
    "hard_called_snp",
    "genotype_likelihood_low_depth",
    "insufficient_inputs",
]


class WorkflowSelection(BaseModel):
    workflow_family: SelectableWorkflowFamily
    confidence: float = Field(ge=0, le=1)
    matched_inputs: list[str] = Field(default_factory=list)
    missing_inputs: list[str] = Field(default_factory=list)
    recommended_next_steps: list[str] = Field(default_factory=list)
    blocked_until: list[str] = Field(default_factory=list)
    rationale: str
