from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi.encoders import jsonable_encoder

from app.insilicopop.audit_service import InSilicoPopAuditService
from app.insilicopop.benchmarks.baselines import naive_summary_memory, raw_trace_text
from app.insilicopop.benchmarks.fixtures import benchmark_scenarios
from app.insilicopop.benchmarks.tasks import BenchmarkScenario
from app.insilicopop.memory.governor import CarriedMemory, CompressedMemoryItem, MemoryGovernor


TRACE_ORDER = ["metadata", "plink_qc", "pca", "admixture", "fst", "roh", "selection_scan"]


class AgentMemoryBenchmarkRunner:
    def __init__(self, generated_root: Path | None = None) -> None:
        self.generated_root = generated_root or Path(__file__).resolve().parents[2] / "generated" / "benchmarks"

    def run(self, scenario: str = "all", budget_chars: int = 1500, memory_mode: str = "compact") -> dict[str, Any]:
        run_id = uuid4().hex[:12]
        selected = self._select_scenarios(scenario)
        results: dict[str, Any] = {method: {"scenarios": []} for method in METHODS}
        trace_payload: dict[str, Any] = {}
        decision_trace: dict[str, Any] = {}
        dropped_log: dict[str, Any] = {}
        provenance_index: dict[str, Any] = {}

        for item in selected:
            scenario_outputs = {
                "domain_aware_governed_memory": governed_memory(item, budget_chars, memory_mode),
                "raw_truncation_carried_memory": raw_truncation_carried_memory(item, budget_chars, memory_mode),
                "naive_summary_carried_memory": naive_summary_carried_memory(item, budget_chars, memory_mode),
                "oracle_full": oracle_carried_memory(item, budget_chars, memory_mode),
            }
            for method, output in scenario_outputs.items():
                results[method]["scenarios"].append(evaluate_final_memory(item, method, output, budget_chars))
            trace_payload[item.name] = scenario_outputs["domain_aware_governed_memory"].get("carried_memory", {})
            decision_trace[item.name] = scenario_outputs["domain_aware_governed_memory"].get("decision_trace", [])
            dropped_log[item.name] = scenario_outputs["domain_aware_governed_memory"].get("dropped_facts_log", [])
            provenance_index[item.name] = scenario_outputs["domain_aware_governed_memory"].get("provenance_index", {})

        for method, result in results.items():
            result["aggregate"] = _aggregate_agent(method, result["scenarios"])
        winner = max(results, key=lambda method: results[method]["aggregate"]["final_score"])
        payload = {
            "run_id": run_id,
            "benchmark_type": "agent_memory",
            "scenario": scenario,
            "budget_chars": budget_chars,
            "memory_mode": memory_mode,
            "results": results,
            "winner": winner,
            "summary": _summary(results, winner),
        }
        payload["generated_files"] = write_agent_memory_outputs(
            self.generated_root / run_id,
            payload,
            trace_payload,
            decision_trace,
            dropped_log,
            provenance_index,
        )
        return payload

    def _select_scenarios(self, scenario: str) -> list[BenchmarkScenario]:
        scenarios = benchmark_scenarios()
        if scenario == "all":
            return list(scenarios.values())
        if scenario not in scenarios:
            valid = ", ".join(["all", *sorted(scenarios)])
            raise ValueError(f"Unknown benchmark scenario '{scenario}'. Valid options: {valid}")
        return [scenarios[scenario]]


METHODS = ["domain_aware_governed_memory", "raw_truncation_carried_memory", "naive_summary_carried_memory", "oracle_full"]


def governed_memory(scenario: BenchmarkScenario, budget_chars: int, memory_mode: str) -> dict[str, Any]:
    uploads = {
        name: {"content": content.encode("utf-8"), "filename": f"{name}.csv"}
        for name, content in scenario.tool_outputs.items()
    }
    audit = InSilicoPopAuditService().run(scenario.query, uploads, memory_mode=memory_mode, include_memory_provenance=True).model_dump()
    current = CarriedMemory(memory_mode=memory_mode)
    governor = MemoryGovernor()
    carried_trace = []
    provenance: dict[str, Any] = {}
    for step in TRACE_ORDER:
        if step not in audit["compressed_memory"]["tools"]:
            continue
        item = audit["compressed_memory"]["tools"][step]
        provenance.update(item.get("provenance_index") or {})
        update = governor.update(
            current,
            CompressedMemoryItem(
                step_name=step,
                memory_mode=memory_mode,
                compressed_memory=item["compressed_memory"],
            ),
            budget_chars,
        )
        current = update.carried_memory
        carried_trace.append(update.model_dump())
    final_text = json.dumps(current.model_dump(), sort_keys=True)
    return {
        "text": final_text,
        "carried_memory": current.model_dump(),
        "decision_trace": current.memory_decision_trace,
        "dropped_facts_log": current.dropped_facts_log,
        "provenance_index": provenance,
        "budget_violation_count": 1 if current.size_chars > budget_chars else 0,
        "dropped_critical_fact_count": sum(1 for fact in current.dropped_facts_log if _is_critical_text(fact.get("text", ""))),
        "trace": carried_trace,
    }


def raw_truncation_carried_memory(scenario: BenchmarkScenario, budget_chars: int, memory_mode: str) -> dict[str, Any]:
    text = raw_trace_text(scenario)[:budget_chars]
    return {"text": text, "budget_violation_count": 0, "dropped_critical_fact_count": 0}


def naive_summary_carried_memory(scenario: BenchmarkScenario, budget_chars: int, memory_mode: str) -> dict[str, Any]:
    text = naive_summary_memory(scenario, budget_chars)["text"][:budget_chars]
    return {"text": text, "budget_violation_count": 0, "dropped_critical_fact_count": 0}


def oracle_carried_memory(scenario: BenchmarkScenario, budget_chars: int, memory_mode: str) -> dict[str, Any]:
    text = json.dumps(
        {
            "expected_facts": [fact.text for fact in scenario.expected_facts],
            "expected_fact_keywords": {fact.fact_id: fact.keywords for fact in scenario.expected_facts},
            "dependencies": scenario.expected_next_step_keywords,
        },
        sort_keys=True,
    )
    return {
        "text": text,
        "budget_violation_count": 1 if len(text) > budget_chars else 0,
        "dropped_critical_fact_count": 0,
    }


def evaluate_final_memory(scenario: BenchmarkScenario, method: str, output: dict[str, Any], budget_chars: int) -> dict[str, Any]:
    text = output["text"].lower()
    carried = output.get("carried_memory", {})
    dependency_text = _dependency_text(carried).lower() if carried else text
    preserved = [fact for fact in scenario.expected_facts if all(keyword.lower() in text for keyword in fact.keywords)]
    critical = scenario.critical_facts
    warnings = scenario.expected_warnings
    deps = scenario.expected_next_step_keywords
    final_fact_recall = _ratio(len(preserved), len(scenario.expected_facts))
    final_critical = _ratio(len([fact for fact in critical if fact in preserved]), len(critical))
    warning_recall = _ratio(len([fact for fact in warnings if fact in preserved]), len(warnings))
    dependency_recall = _ratio(sum(1 for dep in deps if dep.lower() in dependency_text), len(deps))
    blocked_recall = _blocked_interpretation_recall(scenario, carried, text)
    next_step_recall = _next_step_dependency_recall(scenario, carried, text)
    capsule_recall = _dependency_capsule_recall(scenario, carried, text)
    hallucination_penalty = 0.0
    if "clinical diagnosis" in text or "proven disease" in text:
        hallucination_penalty += 0.1
    budget_violations = int(output.get("budget_violation_count", 0))
    dropped_critical = int(output.get("dropped_critical_fact_count", 0))
    critical_dependency_loss = _critical_dependency_loss(scenario, carried, text)
    final_score = (
        0.30 * final_critical
        + 0.20 * dependency_recall
        + 0.15 * blocked_recall
        + 0.10 * next_step_recall
        + 0.10 * warning_recall
        + 0.10 * (1.0 if budget_violations == 0 else 0.5)
        + 0.05 * (1.0 - hallucination_penalty)
        - 0.10 * critical_dependency_loss
        - 0.05 * budget_violations
        - 0.10 * dropped_critical
    )
    return {
        "method": method,
        "scenario": scenario.name,
        "final_fact_recall": round(final_fact_recall, 4),
        "final_critical_fact_recall": round(final_critical, 4),
        "warning_recall": round(warning_recall, 4),
        "downstream_dependency_recall": round(dependency_recall, 4),
        "blocked_interpretation_recall": round(blocked_recall, 4),
        "next_step_dependency_recall": round(next_step_recall, 4),
        "dependency_capsule_recall": round(capsule_recall, 4),
        "critical_dependency_loss_count": critical_dependency_loss,
        "budget_violation_count": budget_violations,
        "dropped_critical_fact_count": dropped_critical,
        "hallucination_penalty": hallucination_penalty,
        "final_score": round(max(final_score, 0), 4),
        "preserved_facts": [fact.fact_id for fact in preserved],
        "missed_facts": [fact.fact_id for fact in scenario.expected_facts if fact not in preserved],
    }


def write_agent_memory_outputs(
    run_dir: Path,
    payload: dict[str, Any],
    carried_memory_trace: dict[str, Any],
    decision_trace: dict[str, Any],
    dropped_log: dict[str, Any],
    provenance_index: dict[str, Any],
) -> dict[str, dict[str, object]]:
    run_dir.mkdir(parents=True, exist_ok=True)
    files = {
        "agent_memory_benchmark_results": run_dir / "agent_memory_benchmark_results.json",
        "carried_memory_trace": run_dir / "carried_memory_trace.json",
        "memory_decision_trace": run_dir / "memory_decision_trace.json",
        "dropped_facts_log": run_dir / "dropped_facts_log.json",
        "provenance_index": run_dir / "provenance_index.json",
        "agent_memory_summary": run_dir / "agent_memory_summary.md",
    }
    files["agent_memory_benchmark_results"].write_text(json.dumps(jsonable_encoder(payload), indent=2), encoding="utf-8")
    files["carried_memory_trace"].write_text(json.dumps(jsonable_encoder(carried_memory_trace), indent=2), encoding="utf-8")
    files["memory_decision_trace"].write_text(json.dumps(jsonable_encoder(decision_trace), indent=2), encoding="utf-8")
    files["dropped_facts_log"].write_text(json.dumps(jsonable_encoder(dropped_log), indent=2), encoding="utf-8")
    files["provenance_index"].write_text(json.dumps(jsonable_encoder(provenance_index), indent=2), encoding="utf-8")
    files["agent_memory_summary"].write_text(_agent_summary_markdown(payload), encoding="utf-8")
    _append_agent_history(run_dir.parent / "benchmark_history.jsonl", payload)
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


def _append_agent_history(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for method, result in payload["results"].items():
            aggregate = result["aggregate"]
            row = {
                "benchmark_type": "agent_memory",
                "run_id": payload["run_id"],
                "scenario": payload["scenario"],
                "method": method,
                "budget_chars": payload["budget_chars"],
                "memory_mode": payload["memory_mode"],
                "final_critical_fact_recall": aggregate["final_critical_fact_recall"],
                "downstream_dependency_recall": aggregate["downstream_dependency_recall"],
                "blocked_interpretation_recall": aggregate["blocked_interpretation_recall"],
                "next_step_dependency_recall": aggregate["next_step_dependency_recall"],
                "budget_violation_count": aggregate["budget_violation_count"],
                "final_score": aggregate["final_score"],
            }
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def _aggregate_agent(method: str, results: list[dict[str, Any]]) -> dict[str, Any]:
    metrics = [
        "final_fact_recall",
        "final_critical_fact_recall",
        "warning_recall",
        "downstream_dependency_recall",
        "blocked_interpretation_recall",
        "next_step_dependency_recall",
        "dependency_capsule_recall",
        "critical_dependency_loss_count",
        "budget_violation_count",
        "dropped_critical_fact_count",
        "hallucination_penalty",
        "final_score",
    ]
    return {
        "method": method,
        **{metric: round(sum(result[metric] for result in results) / max(len(results), 1), 4) for metric in metrics},
    }


def _summary(results: dict[str, Any], winner: str) -> str:
    governed = results["domain_aware_governed_memory"]["aggregate"]
    raw = results["raw_truncation_carried_memory"]["aggregate"]
    naive = results["naive_summary_carried_memory"]["aggregate"]
    return (
        f"Winner is {winner}. Governed critical recall={governed['final_critical_fact_recall']} "
        f"vs raw={raw['final_critical_fact_recall']} and naive={naive['final_critical_fact_recall']}."
    )


def _agent_summary_markdown(payload: dict[str, Any]) -> str:
    lines = ["# InSilicoPop Agent Memory Benchmark", "", f"Run ID: {payload['run_id']}", f"Winner: {payload['winner']}", "", payload["summary"], ""]
    for method, result in payload["results"].items():
        agg = result["aggregate"]
        lines.append(
        f"- {method}: critical_recall={agg['final_critical_fact_recall']}, dependency_recall={agg['downstream_dependency_recall']}, blocked_recall={agg['blocked_interpretation_recall']}, next_step_recall={agg['next_step_dependency_recall']}, final_score={agg['final_score']}"
        )
    lines.extend(["", "## Governor Details"])
    lines.append("- Reports include critical facts retained/lost, downstream dependencies, blocked interpretations, next-step dependencies, budget usage, dropped facts, and decision traces in JSON artifacts.")
    return "\n".join(lines) + "\n"


def _ratio(num: int, den: int) -> float:
    if den == 0:
        return 1.0
    return num / den


def _is_critical_text(text: str) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in ["selection", "proven", "ld pruning", "tiny", "high roh", "narrow k", "highest fst", "best k", "correction", "seed"])


def _dependency_text(carried: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ["downstream_dependencies", "blocked_interpretations", "enables_next_steps"]:
        parts.extend(str(item) for item in carried.get(key, []) or [])
    for capsule in carried.get("dependency_capsules", []) or []:
        parts.extend(str(capsule.get(key, "")) for key in ["trigger_fact", "implication", "blocked_interpretation", "required_next_step"])
    return " ".join(parts)


def _blocked_interpretation_recall(scenario: BenchmarkScenario, carried: dict[str, Any], text: str) -> float:
    expected = _expected_block_keywords(scenario)
    source = (_dependency_text(carried) if carried else text).lower()
    return _ratio(sum(1 for item in expected if item.lower() in source), len(expected))


def _next_step_dependency_recall(scenario: BenchmarkScenario, carried: dict[str, Any], text: str) -> float:
    expected = scenario.expected_next_step_keywords
    source = (_dependency_text(carried) if carried else text).lower()
    return _ratio(sum(1 for item in expected if item.lower() in source), len(expected))


def _dependency_capsule_recall(scenario: BenchmarkScenario, carried: dict[str, Any], text: str) -> float:
    capsules = carried.get("dependency_capsules", []) if carried else []
    if not scenario.expected_next_step_keywords:
        return 1.0
    capsule_text = " ".join(
        f"{capsule.get('trigger_fact', '')} {capsule.get('implication', '')} {capsule.get('blocked_interpretation', '')} {capsule.get('required_next_step', '')}"
        for capsule in capsules
    ).lower()
    return _ratio(sum(1 for item in scenario.expected_next_step_keywords if item.lower() in capsule_text), len(scenario.expected_next_step_keywords))


def _critical_dependency_loss(scenario: BenchmarkScenario, carried: dict[str, Any], text: str) -> int:
    source = (_dependency_text(carried) if carried else text).lower()
    losses = 0
    for fact in scenario.critical_facts:
        if not any(keyword.lower() in source for keyword in fact.keywords):
            losses += 1
    return losses


def _expected_block_keywords(scenario: BenchmarkScenario) -> list[str]:
    expected: list[str] = []
    ids = {fact.fact_id for fact in scenario.expected_facts}
    if "ld_unknown" in ids:
        expected.append("Strong PCA")
    if "admixture_narrow_k" in ids:
        expected.append("Strong ancestry")
    if "high_roh" in ids:
        expected.append("ROH")
    if "selection_overclaim" in ids or "selection_no_correction" in ids:
        expected.append("Selection")
    if "tiny_population" in ids or "highest_fst" in ids:
        expected.append("FST")
    return expected or ["interpretation"]
