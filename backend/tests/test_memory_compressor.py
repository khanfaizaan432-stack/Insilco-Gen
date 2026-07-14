from app.insilicopop.memory.compressor import DomainMemoryCompressor
from app.schemas.memory import MemoryCompressRequest


def compress(tool_name, raw_output):
    return DomainMemoryCompressor().compress(
        MemoryCompressRequest(tool_name=tool_name, step_name="test", raw_output=raw_output)
    )


def test_compresses_pca_and_preserves_variance_and_ld_warning():
    response = compress("pca", [{"sample_id": "S1", "pc1_variance": 12.3}])

    assert "pc1_variance" in response.compressed_memory["facts"]["variance_explained"]
    assert any("LD pruning" in risk for risk in response.risk_flags)


def test_compresses_admixture_and_preserves_k_cv_info():
    response = compress("admixture", [{"K": 2, "cv_error": 0.6}, {"K": 3, "cv_error": 0.5}])

    assert response.compressed_memory["facts"]["k_values_tested"] == [2, 3]
    assert response.compressed_memory["facts"]["best_k"] == 3


def test_compresses_fst_and_preserves_highest_pair():
    response = compress("fst", [{"pop1": "A", "pop2": "B", "fst": 0.1}, {"pop1": "A", "pop2": "C", "fst": 0.2}])

    assert response.compressed_memory["facts"]["highest_fst_pairs"][0]["pop2"] == "C"


def test_compresses_selection_and_preserves_candidates_and_correction_caveat():
    response = compress("selection_scan", [{"region": "chr1", "statistic": "iHS", "score": 3.1}])

    assert response.compressed_memory["facts"]["top_candidate_regions"] == ["chr1"]
    assert any("correction" in risk for risk in response.risk_flags)

