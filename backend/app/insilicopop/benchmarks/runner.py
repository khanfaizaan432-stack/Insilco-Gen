from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from app.insilicopop.benchmarks.baselines import (
    domain_aware_compact_memory,
    domain_aware_ultra_compact_memory,
    domain_aware_verbose_memory,
    naive_summary_memory,
    oracle_full_memory,
    raw_truncation_memory,
)
from app.insilicopop.benchmarks.evaluator import evaluate_memory
from app.insilicopop.benchmarks.fixtures import benchmark_scenarios
from app.insilicopop.benchmarks.report import write_benchmark_report
from app.insilicopop.benchmarks.tasks import BenchmarkScenario


METHODS = {
    "domain_aware_verbose": domain_aware_verbose_memory,
    "domain_aware_compact": domain_aware_compact_memory,
    "domain_aware_ultra_compact": domain_aware_ultra_compact_memory,
    "raw_truncation": raw_truncation_memory,
    "naive_summary": naive_summary_memory,
    "oracle_full": oracle_full_memory,
}


class MemoryBenchmarkRunner:
    def __init__(self, generated_root: Path | None = None) -> None:
        self.generated_root = generated_root or Path(__file__).resolve().parents[2] / "generated" / "benchmarks"

    def run(self, scenario: str = "all", token_budget: int = 1000) -> dict[str, Any]:
        run_id = uuid4().hex[:12]
        selected = self._select_scenarios(scenario)
        results: dict[str, Any] = {}
        for method_name, method in METHODS.items():
            scenario_results = [
                evaluate_memory(item, method(item, token_budget))
                for item in selected
            ]
            results[method_name] = {
                "aggregate": _aggregate(method_name, scenario_results),
                "scenarios": scenario_results,
            }
        winner = max(results, key=lambda method: results[method]["aggregate"]["final_score"])
        payload = {
            "run_id": run_id,
            "scenario": scenario,
            "token_budget": token_budget,
            "results": results,
            "winner": winner,
            "summary": _summary(results, winner),
            "scenario_details": {item.name: item.model_dump() for item in selected},
        }
        payload["compact_memory_report"] = _compact_memory_report(results)
        payload["generated_files"] = write_benchmark_report(self.generated_root / run_id, payload)
        return payload

    def _select_scenarios(self, scenario: str) -> list[BenchmarkScenario]:
        scenarios = benchmark_scenarios()
        if scenario == "all":
            return list(scenarios.values())
        if scenario not in scenarios:
            valid = ", ".join(["all", *sorted(scenarios)])
            raise ValueError(f"Unknown benchmark scenario '{scenario}'. Valid options: {valid}")
        return [scenarios[scenario]]


def _aggregate(method_name: str, scenario_results: list[dict[str, Any]]) -> dict[str, float | str]:
    metrics = ["fact_recall", "critical_fact_recall", "warning_recall", "next_step_accuracy", "compression_ratio", "compression_efficiency", "hallucination_penalty", "final_score"]
    return {
        "method": method_name,
        **{
            metric: round(sum(result[metric] for result in scenario_results) / max(len(scenario_results), 1), 4)
            for metric in metrics
        },
    }


def _summary(results: dict[str, Any], winner: str) -> str:
    domain = results["domain_aware_compact"]["aggregate"]
    raw = results["raw_truncation"]["aggregate"]
    naive = results["naive_summary"]["aggregate"]
    return (
        f"Winner is {winner}. Domain-aware compact critical recall={domain['critical_fact_recall']} "
        f"vs raw_truncation={raw['critical_fact_recall']} and naive_summary={naive['critical_fact_recall']}."
    )


def _compact_memory_report(results: dict[str, Any]) -> dict[str, Any]:
    compact = results["domain_aware_compact"]["scenarios"]
    ultra = results["domain_aware_ultra_compact"]["scenarios"]
    report: dict[str, Any] = {}
    for compact_result in compact:
        ultra_result = next(item for item in ultra if item["scenario"] == compact_result["scenario"])
        report[compact_result["scenario"]] = {
            "facts_retained_by_compact": compact_result["preserved_facts"],
            "facts_lost_by_compact": compact_result["missed_facts"],
            "critical_facts_retained": compact_result["critical_fact_recall"],
            "compression_ratio": compact_result["compression_ratio"],
            "recommended_memory_mode": "compact" if compact_result["critical_fact_recall"] >= ultra_result["critical_fact_recall"] else "ultra_compact",
        }
    return report
