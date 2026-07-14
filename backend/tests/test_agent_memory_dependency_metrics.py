from app.insilicopop.benchmarks.agent_trace import evaluate_final_memory
from app.insilicopop.benchmarks.fixtures import benchmark_scenarios


def test_dependency_metrics_count_capsules_blocks_and_next_steps():
    scenario = benchmark_scenarios()["admixture_underfit"]
    output = {
        "text": "ADMIXTURE K 2 3 narrow best K 3 seed missing",
        "carried_memory": {
            "dependency_capsules": [
                {
                    "trigger_fact": "ADMIXTURE K=2-3 only",
                    "implication": "Ancestry components are provisional.",
                    "blocked_interpretation": "Strong ancestry interpretation",
                    "required_next_step": "Run ADMIXTURE K=2-10 with multiple seeds.",
                }
            ],
            "downstream_dependencies": [],
            "blocked_interpretations": [],
            "enables_next_steps": [],
        },
        "budget_violation_count": 0,
        "dropped_critical_fact_count": 0,
    }

    result = evaluate_final_memory(scenario, "test", output, 1500)

    assert result["downstream_dependency_recall"] == 1.0
    assert result["blocked_interpretation_recall"] == 1.0
    assert result["next_step_dependency_recall"] == 1.0
    assert result["dependency_capsule_recall"] == 1.0
    assert result["critical_dependency_loss_count"] == 0

