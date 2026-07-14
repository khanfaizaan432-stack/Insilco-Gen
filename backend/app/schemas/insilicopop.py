from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


from app.insilicopop.provenance import Provenance


Severity = Literal["info", "warning", "error", "high", "critical"]


class AuditFinding(BaseModel):
    code: str
    severity: Severity
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    provenance: Provenance | None = None


class ParsedTable(BaseModel):
    name: str
    columns: list[str]
    rows: list[dict[str, Any]]
    metadata: dict[str, Any] = Field(default_factory=dict)


class MetadataAudit(BaseModel):
    sample_id_column: str | None = None
    population_column: str | None = None
    language_columns: list[str] = Field(default_factory=list)
    geography_columns: list[str] = Field(default_factory=list)
    sample_counts: dict[str, int] = Field(default_factory=dict)
    sample_count: int = 0
    population_count: int = 0
    samples_per_population: dict[str, int] = Field(default_factory=dict)
    missing_population_labels: int = 0
    duplicate_sample_ids: list[str] = Field(default_factory=list)
    tiny_population_groups: dict[str, int] = Field(default_factory=dict)
    severe_imbalance: bool = False
    broad_label_warnings: list[str] = Field(default_factory=list)
    recommended_metadata_fixes: list[str] = Field(default_factory=list)
    findings: list[AuditFinding] = Field(default_factory=list)


class InSilicoPopAuditResponse(BaseModel):
    run_id: str
    query: str | None = None
    reliability_score: int
    risk_flags: list[AuditFinding]
    audit_report: dict[str, Any]
    compressed_memory: dict[str, Any]
    next_analysis_plan: dict[str, Any]
    generated_files: dict[str, Any]
