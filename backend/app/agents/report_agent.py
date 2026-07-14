from __future__ import annotations

from typing import Any

from app.schemas.project import DataHealthReport


class ReportAgent:
    name = "ReportAgent"

    def experiment_plan(self, health_report: DataHealthReport, workflow: dict[str, Any]) -> str:
        status = "ready for baseline modeling" if health_report.passed else "blocked pending data fixes"
        lines = [
            "# Dry-Biotics Experiment Plan",
            "",
            f"Status: {status}.",
            "",
            "## Objective",
            "Classify antimicrobial resistance labels from biological sequences supplied as FASTA records.",
            "",
            "## Inputs",
            "- sequences.fasta parsed with Biopython SeqIO",
            "- labels.csv parsed with pandas and validated for sample_id,label columns",
            "",
            "## Initial Workflow",
        ]
        for step in workflow["steps"]:
            lines.append(f"- {step['id']}: {step['description']}")
        lines.extend(
            [
                "",
                "## Data Health Summary",
                f"- FASTA records: {health_report.total_fasta_records}",
                f"- Labels: {health_report.total_labels}",
                f"- Unique sequences: {health_report.unique_sequences}",
                f"- Class balance: {health_report.class_balance}",
            ]
        )
        return "\n".join(lines) + "\n"

    def bundle(
        self,
        health_report: DataHealthReport,
        workflow_yaml: str,
        experiment_plan_md: str,
        codex_tasks_md: str,
        agent_debate_log_md: str,
    ) -> dict[str, Any]:
        return {
            "data_health_report": health_report.model_dump(),
            "workflow_yaml": workflow_yaml,
            "experiment_plan_md": experiment_plan_md,
            "codex_tasks_md": codex_tasks_md,
            "agent_debate_log_md": agent_debate_log_md,
        }

