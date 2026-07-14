from app.insilicopop.benchmarks.evaluator import compression_efficiency_score
from app.insilicopop.benchmarks.fixtures import benchmark_scenarios
from app.insilicopop.memory.compressor import DomainMemoryCompressor
from app.schemas.memory import MemoryCompressRequest


def test_compact_ratio_is_computed_and_smaller_on_fixture_like_output():
    scenario = benchmark_scenarios()["admixture_underfit"]
    raw_output = {
        "summary": {
            "k_values_tested": [2, 3],
            "best_k_by_cv": 3,
            "cv_error_by_k": {2: 0.62, 3: 0.48},
            "seed_count_by_k": {},
            "narrow_k_sweep_warning": "K sweep too narrow",
        },
        "rows": [{"raw": scenario.tool_outputs["admixture"] * 200}],
    }

    result = DomainMemoryCompressor().compress(
        MemoryCompressRequest(tool_name="admixture", step_name="audit", raw_output=raw_output, memory_mode="compact")
    )

    assert result.raw_size_chars > result.compressed_size_chars
    assert result.compression_ratio == round(result.compressed_size_chars / result.raw_size_chars, 4)


def test_compression_efficiency_rewards_smaller_outputs():
    assert compression_efficiency_score(0.1) == 1.0
    assert compression_efficiency_score(0.2) == 0.8
    assert compression_efficiency_score(0.35) == 0.6
    assert compression_efficiency_score(0.5) == 0.4
    assert compression_efficiency_score(1.0) == 0.2
