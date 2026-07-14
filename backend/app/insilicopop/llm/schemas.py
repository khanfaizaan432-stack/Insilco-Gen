from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class LLMActionProposal(BaseModel):
    action_type: str
    rationale: str
    required_inputs: list[str] = Field(default_factory=list)
    expected_outputs: list[str] = Field(default_factory=list)
    claim_intent: str | None = None
    confidence: float = 0.8
    metadata: dict[str, Any] = Field(default_factory=dict)


class ValidatedAction(BaseModel):
    status: Literal["approved", "modified", "blocked", "needs_clarification"]
    original_proposal: dict[str, Any]
    final_action: dict[str, Any] | None = None
    blocking_reasons: list[str] = Field(default_factory=list)
    required_fixes: list[str] = Field(default_factory=list)
    provenance_refs: list[str] = Field(default_factory=list)
    memory_dependencies: list[str] = Field(default_factory=list)
