from app.insilicopop.memory.compressor import DomainMemoryCompressor
from app.schemas.memory import MemoryCompressRequest


def compress(tool_name, summary):
    return DomainMemoryCompressor().compress(
        MemoryCompressRequest(tool_name=tool_name, step_name="audit", raw_output={"summary": summary, "rows": []})
    ).compressed_memory


def test_pca_memory_has_required_fields():
    memory = compress("pca", {"parsed_pc_columns": ["PC1"], "variance_explained_summary": {"pc1": 12}, "ld_pruning_documented": "unknown", "relatedness_removal_documented": "unknown", "warnings": ["Missing LD pruning"]})

    assert memory["summary"]
    assert memory["retained_metrics"]["parsed_pc_columns"] == ["PC1"]
    assert memory["warnings"]
    assert memory["downstream_dependencies"]


def test_admixture_memory_has_best_k_and_warning():
    memory = compress("admixture", {"k_values_tested": [2, 3], "best_k_by_cv": 3, "cv_error_by_k": {2: 0.6, 3: 0.5}, "seed_count_by_k": {}, "narrow_k_sweep_warning": "K sweep too narrow"})

    assert memory["retained_metrics"]["best_k_by_cv"] == 3
    assert memory["warnings"]


def test_fst_memory_has_highest_pair_from_matrix_summary():
    memory = compress("fst", {"highest_fst_pairs": [{"pop1": "A", "pop2": "B", "fst": 0.2}], "lowest_fst_pairs": [], "populations_seen": ["A", "B"], "matrix_shape": [2, 2]})

    assert memory["retained_metrics"]["highest_fst_pairs"][0]["fst"] == 0.2


def test_roh_memory_has_high_roh_flags():
    memory = compress("roh", {"high_roh_samples": [{"sample_id": "S1"}], "high_roh_populations": ["A"], "roh_summary_by_population": {"A": 150}, "endogamy_interpretation_warnings": ["caveat"]})

    assert memory["retained_metrics"]["high_roh_populations"] == ["A"]
    assert memory["warnings"]


def test_selection_memory_has_correction_caveat():
    memory = compress("selection_scan", {"top_candidate_regions": ["chr1:1-2"], "statistic_used": "iHS", "multiple_testing_status": "not_documented", "overclaim_warnings": ["caveat"]})

    assert memory["retained_metrics"]["top_candidate_regions"]
    assert any("correction" in warning.lower() for warning in memory["warnings"])

