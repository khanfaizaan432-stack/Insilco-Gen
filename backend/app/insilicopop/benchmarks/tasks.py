from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


ToolName = Literal["metadata", "plink_qc", "pca", "admixture", "fst", "roh", "selection_scan"]


class ExpectedFact(BaseModel):
    fact_id: str
    text: str
    keywords: list[str]
    critical: bool = False
    warning: bool = False


class BenchmarkScenario(BaseModel):
    name: str
    description: str
    query: str | None = None
    tool_outputs: dict[ToolName, str]
    expected_facts: list[ExpectedFact]
    expected_next_step_keywords: list[str] = Field(default_factory=list)

    @property
    def critical_facts(self) -> list[ExpectedFact]:
        return [fact for fact in self.expected_facts if fact.critical]

    @property
    def expected_warnings(self) -> list[ExpectedFact]:
        return [fact for fact in self.expected_facts if fact.warning]

