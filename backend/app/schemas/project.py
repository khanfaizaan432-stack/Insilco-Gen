from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class FastaRecord(BaseModel):
    sample_id: str
    description: str = ""
    sequence: str


class LabelRecord(BaseModel):
    sample_id: str
    label: str


class ValidationFinding(BaseModel):
    code: str
    severity: Literal["info", "warning", "error"]
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class DataHealthReport(BaseModel):
    workflow_pack: str = "Dry-Biotics"
    total_fasta_records: int
    total_labels: int
    unique_fasta_ids: int
    unique_sequences: int
    class_balance: dict[str, int]
    findings: list[ValidationFinding]
    passed: bool


class GeneratedReports(BaseModel):
    data_health_report: dict[str, Any]
    workflow_yaml: str
    experiment_plan_md: str
    codex_tasks_md: str
    agent_debate_log_md: str

