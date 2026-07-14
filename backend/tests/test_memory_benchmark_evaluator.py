from app.insilicopop.benchmarks.baselines import domain_aware_memory, oracle_full_memory
from app.insilicopop.benchmarks.evaluator import evaluate_memory
from app.insilicopop.benchmarks.fixtures import benchmark_scenarios


def test_fact_recall_and_critical_recall_work():
    scenario = benchmark_scenarios()["admixture_underfit"]
    result = evaluate_memory(
        scenario,
        {"method": "manual", "text": "ADMIXTURE K 2 3 narrow best K 3 seed missing", "payload": {}},
    )

    assert result["fact_recall"] == 1.0
    assert result["critical_fact_recall"] == 1.0


def test_hallucination_penalty_detects_unsupported_claims():
    scenario = benchmark_scenarios()["cleanish_reference_case"]
    result = evaluate_memory(
        scenario,
        {"method": "manual", "text": "selection proven high roh ld pruning unknown narrow k tiny population", "payload": {}},
    )

    assert result["hallucination_penalty"] > 0


def test_oracle_full_ranks_high():
    scenario = benchmark_scenarios()["indian_endogamy_overclaim"]
    result = evaluate_memory(scenario, oracle_full_memory(scenario, 1000))

    assert result["critical_fact_recall"] == 1.0
    assert result["final_score"] > 0.8


def test_domain_aware_preserves_admixture_and_ld_facts():
    scenario = benchmark_scenarios()["indian_endogamy_overclaim"]
    result = evaluate_memory(scenario, domain_aware_memory(scenario, 1000))

    assert "admixture_narrow_k" in result["preserved_facts"]
    assert "ld_unknown" in result["preserved_facts"]

