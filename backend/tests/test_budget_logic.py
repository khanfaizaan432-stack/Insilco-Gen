from app.insilicopop.memory.budget import raw_size_bucket, ratio_context
from app.insilicopop.memory.compressor import DomainMemoryCompressor
from app.schemas.memory import MemoryCompressRequest


def test_tiny_raw_input_overhead_ratio_context():
    response = DomainMemoryCompressor().compress(
        MemoryCompressRequest(tool_name="generic", step_name="tiny", raw_output="x", memory_mode="compact")
    )

    assert response.raw_size_chars < 1000
    assert response.compression_ratio > 1
    assert response.ratio_context == "tiny_input_overhead"


def test_medium_large_bucket_and_normal_context():
    assert raw_size_bucket(1000) == "small"
    assert raw_size_bucket(10000) == "medium"
    assert raw_size_bucket(100000) == "large"
    assert ratio_context(5000, 0.5) == "normal"


def test_protected_critical_facts_marked():
    response = DomainMemoryCompressor().compress(
        MemoryCompressRequest(
            tool_name="selection_scan",
            step_name="selection",
            raw_output={"summary": {"top_candidate_regions": ["chr1:1-2"], "statistic_used": "iHS", "multiple_testing_status": "not_documented", "overclaim_warnings": ["selection is proven overclaim"]}},
            memory_mode="compact",
        )
    )

    assert response.protected_facts

