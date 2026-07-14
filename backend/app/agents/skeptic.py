from __future__ import annotations

from app.schemas.project import DataHealthReport


class SkepticAgent:
    name = "SkepticAgent"

    def run(self, health_report: DataHealthReport) -> str:
        lines = [
            "# Agent Debate Log",
            "",
            "## DataCopAgent",
            f"Dataset quality gate passed: {health_report.passed}.",
            "",
            "## WorkflowArchitectAgent",
            "Recommended a deterministic Dry-Biotics AMR sequence classification workflow.",
            "",
            "## SkepticAgent",
        ]
        blocking = [finding for finding in health_report.findings if finding.severity == "error"]
        warnings = [finding for finding in health_report.findings if finding.severity == "warning"]
        if blocking:
            lines.append("Blocking issues must be resolved before model training.")
        elif warnings:
            lines.append("The dataset can proceed only with documented caution around warnings.")
        else:
            lines.append("No blocking data-quality concerns were found.")

        for finding in blocking + warnings:
            lines.append(f"- {finding.severity.upper()}: {finding.code} - {finding.message}")
        return "\n".join(lines) + "\n"

