from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.agents.codex_task_agent import CodexTaskAgent
from app.agents.data_cop import DataCopAgent
from app.agents.report_agent import ReportAgent
from app.agents.skeptic import SkepticAgent
from app.agents.workflow_architect import WorkflowArchitectAgent
from app.bio.fasta_parser import parse_fasta
from app.bio.label_parser import parse_labels


class DryBioticsWorkflow:
    workflow_pack = "Dry-Biotics"

    def __init__(self) -> None:
        self.data_cop = DataCopAgent()
        self.architect = WorkflowArchitectAgent()
        self.skeptic = SkepticAgent()
        self.codex_task_agent = CodexTaskAgent()
        self.report_agent = ReportAgent()

    def run(
        self,
        fasta_source: str | bytes | Path,
        labels_source: str | bytes | Path,
        output_dir: str | Path | None = None,
    ) -> dict[str, Any]:
        records = parse_fasta(fasta_source)
        labels = parse_labels(labels_source)
        health_report = self.data_cop.run(records, labels)
        workflow = self.architect.run(health_report)
        workflow_yaml = self.architect.to_yaml(workflow)
        experiment_plan = self.report_agent.experiment_plan(health_report, workflow)
        codex_tasks = self.codex_task_agent.run(health_report)
        debate_log = self.skeptic.run(health_report)
        bundle = self.report_agent.bundle(
            health_report=health_report,
            workflow_yaml=workflow_yaml,
            experiment_plan_md=experiment_plan,
            codex_tasks_md=codex_tasks,
            agent_debate_log_md=debate_log,
        )

        if output_dir is not None:
            self._write_outputs(Path(output_dir), bundle)
        return bundle

    def _write_outputs(self, output_dir: Path, bundle: dict[str, Any]) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "data_health_report.json").write_text(
            json.dumps(bundle["data_health_report"], indent=2),
            encoding="utf-8",
        )
        (output_dir / "workflow.yaml").write_text(bundle["workflow_yaml"], encoding="utf-8")
        (output_dir / "experiment_plan.md").write_text(
            bundle["experiment_plan_md"], encoding="utf-8"
        )
        (output_dir / "codex_tasks.md").write_text(bundle["codex_tasks_md"], encoding="utf-8")
        (output_dir / "agent_debate_log.md").write_text(
            bundle["agent_debate_log_md"], encoding="utf-8"
        )

