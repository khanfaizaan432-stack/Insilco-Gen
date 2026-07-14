from __future__ import annotations

from typing import Any

from app.insilicopop.benchmarks.baselines import raw_trace_text
from app.insilicopop.benchmarks.tasks import BenchmarkScenario, ExpectedFact


def evaluate_memory(
    scenario: BenchmarkScenario,
    method_output: dict[str, Any],
) -> dict[str, Any]:
    text = method_output["text"]
    raw_size = max(int(method_output.get("raw_size_chars") or len(raw_trace_text(scenario))), 1)
    compressed_size = int(method_output.get("compressed_size_chars") or len(text))
    preserved = [fact for fact in scenario.expected_facts if _fact_present(fact, text)]
    critical = scenario.critical_facts
    warnings = scenario.expected_warnings
    hallucination_penalty = _hallucination_penalty(scenario, text)
    compression_ratio = compressed_size / raw_size
    compression_efficiency = compression_efficiency_score(compression_ratio)
    fact_recall = _ratio(len(preserved), len(scenario.expected_facts))
    critical_recall = _ratio(len([fact for fact in critical if fact in preserved]), len(critical))
    warning_recall = _ratio(len([fact for fact in warnings if fact in preserved]), len(warnings))
    next_step_accuracy = _next_step_accuracy(scenario, text)
    final_score = (
        0.35 * critical_recall
        + 0.20 * fact_recall
        + 0.15 * warning_recall
        + 0.10 * next_step_accuracy
        + 0.20 * compression_efficiency
        - hallucination_penalty
    )
    return {
        "method": method_output["method"],
        "scenario": scenario.name,
        "fact_recall": round(fact_recall, 4),
        "critical_fact_recall": round(critical_recall, 4),
        "warning_recall": round(warning_recall, 4),
        "next_step_accuracy": round(next_step_accuracy, 4),
        "compression_ratio": round(compression_ratio, 4),
        "compression_efficiency": round(compression_efficiency, 4),
        "hallucination_penalty": round(hallucination_penalty, 4),
        "final_score": round(max(final_score, 0.0), 4),
        "preserved_facts": [fact.fact_id for fact in preserved],
        "missed_facts": [fact.fact_id for fact in scenario.expected_facts if fact not in preserved],
    }


def _fact_present(fact: ExpectedFact, text: str) -> bool:
    lowered = text.lower()
    return all(keyword.lower() in lowered for keyword in fact.keywords)


def _next_step_accuracy(scenario: BenchmarkScenario, text: str) -> float:
    if not scenario.expected_next_step_keywords:
        return 1.0
    lowered = text.lower()
    hits = sum(1 for keyword in scenario.expected_next_step_keywords if keyword.lower() in lowered)
    return _ratio(hits, len(scenario.expected_next_step_keywords))


def _hallucination_penalty(scenario: BenchmarkScenario, text: str) -> float:
    expected_ids = {fact.fact_id for fact in scenario.expected_facts}
    unsupported_patterns = {
        "selection_overclaim": ["selection", "proven"],
        "high_roh": ["high roh"],
        "ld_unknown": ["ld pruning", "unknown"],
        "admixture_narrow_k": ["narrow", "k"],
        "tiny_population": ["tiny", "population"],
    }
    penalty = 0.0
    lowered = text.lower()
    for fact_id, patterns in unsupported_patterns.items():
        if fact_id not in expected_ids and all(pattern in lowered for pattern in patterns):
            penalty += 0.05
    return min(penalty, 0.25)


def _ratio(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 1.0
    return numerator / denominator


def compression_efficiency_score(compression_ratio: float) -> float:
    if compression_ratio <= 0.15:
        return 1.0
    if compression_ratio <= 0.25:
        return 0.8
    if compression_ratio <= 0.40:
        return 0.6
    if compression_ratio <= 0.60:
        return 0.4
    return 0.2
