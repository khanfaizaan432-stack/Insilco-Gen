from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


ToolName = Literal[
    "metadata",
    "plink_qc",
    "pca",
    "admixture",
    "fst",
    "roh",
    "selection_scan",
    "generic",
]

MemoryMode = Literal["verbose", "compact", "ultra_compact"]


class MemoryCompressRequest(BaseModel):
    tool_name: ToolName
    step_name: str
    raw_output: str | dict[str, Any] | list[Any]
    previous_memory: dict[str, Any] | None = None
    token_budget: int | None = None
    memory_mode: MemoryMode = "verbose"
    include_provenance: bool = False


class ImportanceScore(BaseModel):
    item: str
    score: float
    reason: str


class MemoryCompressResponse(BaseModel):
    compressed_memory: dict[str, Any]
    memory_mode: MemoryMode = "verbose"
    raw_size_chars: int = 0
    compressed_size_chars: int = 0
    compression_ratio: float = 0.0
    ratio_context: Literal["normal", "tiny_input_overhead"] = "normal"
    raw_size_bucket: Literal["tiny", "small", "medium", "large"] = "tiny"
    critical_facts_retained: list[str] = Field(default_factory=list)
    noncritical_facts_dropped: list[str] = Field(default_factory=list)
    provenance_index: dict[str, Any] | None = None
    fact_ids: list[str] = Field(default_factory=list)
    protected_facts: list[str] = Field(default_factory=list)
    retained_facts: list[str]
    risk_flags: list[str]
    importance_scores: list[ImportanceScore]
    dropped_content_summary: str
    downstream_dependencies: list[str]
