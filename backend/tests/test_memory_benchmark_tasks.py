from app.insilicopop.benchmarks.fixtures import benchmark_scenarios


def test_each_benchmark_scenario_has_trace_and_expected_facts():
    scenarios = benchmark_scenarios()

    assert set(scenarios) == {
        "indian_endogamy_overclaim",
        "admixture_underfit",
        "pca_without_ld_pruning",
        "fst_tiny_sample_trap",
        "cleanish_reference_case",
    }
    for scenario in scenarios.values():
        assert scenario.tool_outputs
        assert scenario.expected_facts
        assert scenario.critical_facts or scenario.name == "cleanish_reference_case"
        assert scenario.expected_next_step_keywords

