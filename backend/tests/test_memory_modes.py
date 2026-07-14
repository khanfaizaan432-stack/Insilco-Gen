from app.insilicopop.memory.compressor import DomainMemoryCompressor
from app.schemas.memory import MemoryCompressRequest


def response(mode):
    return DomainMemoryCompressor().compress(
        MemoryCompressRequest(
            tool_name="admixture",
            step_name="audit",
            raw_output={
                "summary": {
                    "k_values_tested": [2, 3],
                    "best_k_by_cv": 3,
                    "cv_error_by_k": {2: 0.6, 3: 0.5},
                    "seed_count_by_k": {},
                    "narrow_k_sweep_warning": "K sweep is too narrow for Indian fine-scale structure.",
                    "missing_seed_replicates_warning": "Seed replicates missing.",
                },
                "rows": [{"K": 2, "cv_error": 0.6}, {"K": 3, "cv_error": 0.5}],
            },
            memory_mode=mode,
        )
    )


def test_memory_modes_all_work_and_shrink():
    verbose = response("verbose")
    compact = response("compact")
    ultra = response("ultra_compact")

    assert verbose.memory_mode == "verbose"
    assert compact.memory_mode == "compact"
    assert ultra.memory_mode == "ultra_compact"
    assert compact.compressed_size_chars < verbose.compressed_size_chars
    assert ultra.compressed_size_chars < compact.compressed_size_chars


def test_critical_facts_remain_in_compact_mode():
    compact = response("compact")
    text = str(compact.compressed_memory).lower()

    assert "best k" in text
    assert "narrow k" in text
    assert compact.critical_facts_retained

