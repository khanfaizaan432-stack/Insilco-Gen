from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any
from datetime import datetime, UTC

from fastapi.encoders import jsonable_encoder


def write_benchmark_report(run_dir: Path, payload: dict[str, Any]) -> dict[str, dict[str, object]]:
    run_dir.mkdir(parents=True, exist_ok=True)
    history_path = run_dir.parent / "benchmark_history.jsonl"
    files = {
        "benchmark_results": run_dir / "benchmark_results.json",
        "benchmark_summary": run_dir / "benchmark_summary.md",
        "method_comparison": run_dir / "method_comparison.csv",
        "scenario_details": run_dir / "scenario_details.json",
        "benchmark_history": history_path,
    }
    files["benchmark_results"].write_text(json.dumps(jsonable_encoder(payload), indent=2), encoding="utf-8")
    files["benchmark_summary"].write_text(_summary_markdown(payload), encoding="utf-8")
    _write_csv(files["method_comparison"], payload)
    files["scenario_details"].write_text(json.dumps(jsonable_encoder(payload.get("scenario_details", {})), indent=2), encoding="utf-8")
    _append_history(history_path, payload)
    return {
        key: {
            "filename": path.name,
            "absolute_path": str(path.resolve()),
            "relative_path": str(path),
            "file_type": path.suffix.lstrip(".") or "text",
            "created": path.exists(),
        }
        for key, path in files.items()
    }


def _summary_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# InSilicoPop Memory Benchmark",
        "",
        f"Run ID: {payload['run_id']}",
        f"Winner: {payload['winner']}",
        "",
        payload["summary"],
        "",
        "## Method Scores",
    ]
    for method, result in payload["results"].items():
        lines.append(f"- {method}: final_score={result['aggregate']['final_score']}, critical_fact_recall={result['aggregate']['critical_fact_recall']}")
    lines.extend(["", "## Compact Memory Report"])
    for scenario, report in payload.get("compact_memory_report", {}).items():
        lines.append(f"- {scenario}: recommended={report['recommended_memory_mode']}, compression_ratio={report['compression_ratio']}, critical_retained={report['critical_facts_retained']}")
    return "\n".join(lines) + "\n"


def _write_csv(path: Path, payload: dict[str, Any]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["method", "scenario", "final_score", "critical_fact_recall", "fact_recall", "warning_recall", "compression_ratio", "compression_efficiency"],
        )
        writer.writeheader()
        for method, result in payload["results"].items():
            for scenario_result in result["scenarios"]:
                writer.writerow(
                    {
                        "method": method,
                        "scenario": scenario_result["scenario"],
                        "final_score": scenario_result["final_score"],
                        "critical_fact_recall": scenario_result["critical_fact_recall"],
                        "fact_recall": scenario_result["fact_recall"],
                        "warning_recall": scenario_result["warning_recall"],
                        "compression_ratio": scenario_result["compression_ratio"],
                        "compression_efficiency": scenario_result["compression_efficiency"],
                    }
                )


def _append_history(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).isoformat()
    with path.open("a", encoding="utf-8") as handle:
        for method, result in payload["results"].items():
            aggregate = result["aggregate"]
            row = {
                "run_id": payload["run_id"],
                "timestamp": timestamp,
                "scenario": payload["scenario"],
                "token_budget": payload["token_budget"],
                "method": method,
                "fact_recall": aggregate["fact_recall"],
                "critical_fact_recall": aggregate["critical_fact_recall"],
                "warning_recall": aggregate["warning_recall"],
                "compression_ratio": aggregate["compression_ratio"],
                "final_score": aggregate["final_score"],
            }
            handle.write(json.dumps(row, sort_keys=True) + "\n")
