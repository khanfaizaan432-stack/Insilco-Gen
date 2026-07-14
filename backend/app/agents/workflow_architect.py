from __future__ import annotations

from typing import Any

import yaml

from app.schemas.project import DataHealthReport


class WorkflowArchitectAgent:
    name = "WorkflowArchitectAgent"

    def run(self, health_report: DataHealthReport) -> dict[str, Any]:
        return {
            "workflow_pack": "Dry-Biotics",
            "workflow_name": "amr_sequence_classification",
            "version": "0.1.0",
            "deterministic": True,
            "inputs": {
                "sequences": {"type": "FASTA", "required": True},
                "labels": {
                    "type": "CSV",
                    "required": True,
                    "required_columns": ["sample_id", "label"],
                },
            },
            "quality_gate": {
                "passed": health_report.passed,
                "blocking_findings": [
                    finding.code
                    for finding in health_report.findings
                    if finding.severity == "error"
                ],
            },
            "steps": [
                {
                    "id": "parse_inputs",
                    "agent": "DataCopAgent",
                    "description": "Parse FASTA records and labels.csv rows.",
                },
                {
                    "id": "validate_dataset",
                    "agent": "DataCopAgent",
                    "description": "Validate IDs, labels, duplicated sequences, conflicts, and class balance.",
                },
                {
                    "id": "plan_experiment",
                    "agent": "WorkflowArchitectAgent",
                    "description": "Prepare a reproducible AMR sequence classification experiment plan.",
                },
                {
                    "id": "skeptical_review",
                    "agent": "SkepticAgent",
                    "description": "Flag leakage, ambiguity, imbalance, and data readiness risks.",
                },
                {
                    "id": "codex_task_breakdown",
                    "agent": "CodexTaskAgent",
                    "description": "Convert the plan into implementation tasks for future model-building iterations.",
                },
                {
                    "id": "report",
                    "agent": "ReportAgent",
                    "description": "Emit JSON, YAML, Markdown plan, task list, and agent debate log.",
                },
            ],
        }

    def to_yaml(self, workflow: dict[str, Any]) -> str:
        return yaml.safe_dump(workflow, sort_keys=False, allow_unicode=False)

