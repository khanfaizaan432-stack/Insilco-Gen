from app.insilicopop.benchmarks.agent_trace import AgentMemoryBenchmarkRunner


def test_v07_benchmark_targets_met_for_all_compact():
    result = AgentMemoryBenchmarkRunner().run("all", 1500, "compact")
    governed = result["results"]["domain_aware_governed_memory"]["aggregate"]
    raw = result["results"]["raw_truncation_carried_memory"]["aggregate"]
    naive = result["results"]["naive_summary_carried_memory"]["aggregate"]

    assert governed["final_critical_fact_recall"] >= 0.90
    assert governed["downstream_dependency_recall"] >= 0.70
    assert governed["budget_violation_count"] <= 0.6
    assert governed["final_critical_fact_recall"] > raw["final_critical_fact_recall"]
    assert governed["final_critical_fact_recall"] > naive["final_critical_fact_recall"]
    assert result["winner"] in result["results"]
