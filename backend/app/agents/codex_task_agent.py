from __future__ import annotations

from app.schemas.project import DataHealthReport


class CodexTaskAgent:
    name = "CodexTaskAgent"

    def run(self, health_report: DataHealthReport) -> str:
        tasks = [
            "# Codex Tasks",
            "",
            "- [ ] Add persistent project storage for uploaded workflow artifacts.",
            "- [ ] Add feature extraction baselines for AMR sequence classification.",
            "- [ ] Add train/validation splitting with duplicate-sequence leakage controls.",
            "- [ ] Add baseline classifiers and metrics reporting.",
            "- [ ] Add workflow-pack registry for RNA-seq, metagenomics, variant annotation, protein properties, and generic CSV ML.",
        ]
        if not health_report.passed:
            tasks.insert(2, "- [ ] Resolve blocking DataCopAgent validation errors before training.")
        return "\n".join(tasks) + "\n"

