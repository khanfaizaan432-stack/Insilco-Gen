from app.insilicopop.memory.compressor import DomainMemoryCompressor
from app.schemas.memory import MemoryCompressRequest


RAW = {
    "summary": {
        "k_values_tested": [2, 3],
        "best_k_by_cv": 3,
        "cv_error_by_k": {2: 0.6, 3: 0.5},
        "seed_count_by_k": {},
        "narrow_k_sweep_warning": "K sweep is too narrow",
    },
    "findings": [
        {
            "code": "admixture_k_sweep_too_narrow",
            "message": "K sweep is too narrow",
            "provenance": {
                "source_file": "admixture.csv",
                "auditor_name": "ADMIXTUREAuditor",
                "rule_id": "ADMIXTURE_K_SWEEP_TOO_NARROW",
                "evidence_value": "K=[2,3]",
            },
        }
    ],
}


def test_compact_facts_reference_provenance_ids():
    response = DomainMemoryCompressor().compress(
        MemoryCompressRequest(tool_name="admixture", step_name="audit", raw_output=RAW, memory_mode="compact")
    )

    fact_items = response.compressed_memory["fact_items"]
    assert fact_items
    assert all(item["provenance_id"] for item in fact_items)
    assert response.provenance_index is None


def test_include_provenance_true_includes_index():
    response = DomainMemoryCompressor().compress(
        MemoryCompressRequest(
            tool_name="admixture",
            step_name="audit",
            raw_output=RAW,
            memory_mode="compact",
            include_provenance=True,
        )
    )

    assert response.provenance_index
    for item in response.compressed_memory["fact_items"]:
        assert item["provenance_id"] in response.provenance_index

