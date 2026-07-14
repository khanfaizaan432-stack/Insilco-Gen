from pathlib import Path

from fastapi.testclient import TestClient

from app.insilicopop.auditors.fst_auditor import FSTAuditor
from app.insilicopop.memory.compressor import DomainMemoryCompressor
from app.insilicopop.parsers.fst_parser import parse_fst
from app.main import app
from app.schemas.memory import MemoryCompressRequest


client = TestClient(app)


def test_risk_flags_have_provenance_and_sections_are_non_empty():
    response = client.post(
        "/insilicopop/audit",
        data={"query": "selection is proven in this cohort"},
        files={
            "metadata_file": ("indian_metadata.csv", b"sample_id,population\nS1,North Indian\nS2,Iyer\n", "text/csv"),
            "pca_file": ("pca_results.csv", b"sample_id,PC1,PC2,pc1_variance,is_outlier\nS1,0.1,0.2,12.3,true\n", "text/csv"),
            "admixture_file": ("admixture_cv_errors.csv", b"K,cv_error\n2,0.421\n3,0.398\n", "text/csv"),
            "fst_file": ("fst_matrix.csv", b"population,Iyer,North Indian\nIyer,0,0.05\nNorth Indian,0.05,0\n", "text/csv"),
            "roh_file": ("roh_summary.csv", b"sample_id,population,total_roh_length_mb\nS1,Iyer,150\n", "text/csv"),
            "selection_file": ("selection.csv", b"chromosome,start,end,statistic,score,gene\n1,10,20,iHS,4.2,GENE1\n", "text/csv"),
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["risk_flags"]
    assert all(flag["provenance"] for flag in body["risk_flags"])
    assert body["audit_report"]["metadata"]["sample_count"] == 2
    assert body["audit_report"]["pca"]["summary"]["parsed_pc_columns"]
    assert body["audit_report"]["admixture"]["summary"]["best_k_by_cv"] == 3
    assert body["audit_report"]["fst"]["summary"]["highest_fst_pairs"]
    assert body["audit_report"]["roh"]["summary"]["high_roh_samples"]
    assert body["audit_report"]["selection"]["summary"]["top_candidate_regions"]
    assert body["audit_report"]["overclaim"]["findings"]


def test_reliability_penalties_include_provenance_and_plan_has_blocks():
    response = client.post(
        "/insilicopop/audit",
        files={
            "metadata_file": ("metadata.csv", b"sample_id,population\nS1,North Indian\nS2,Iyer\n", "text/csv"),
            "pca_file": ("pca.csv", b"sample_id,PC1,PC2\nS1,0.1,0.2\n", "text/csv"),
        },
    )

    body = response.json()
    penalties = body["audit_report"]["reliability"]["penalties"]
    assert penalties
    assert all(penalty["provenance"] for penalty in penalties)
    assert body["next_analysis_plan"]["recommended_steps"]
    assert body["next_analysis_plan"]["blocked_steps"]


def test_fst_matrix_parser_top_pairs():
    table = parse_fst("population,A,B,C\nA,0,0.01,0.20\nB,0.01,0,0.04\nC,0.20,0.04,0\n")
    result = FSTAuditor().run(table)

    assert result["summary"]["highest_fst_pairs"][0]["fst"] == 0.20
    assert result["summary"]["highest_fst_pairs"][0]["pop2"] == "C"


def test_compressed_memory_non_empty_for_all_core_tools():
    compressor = DomainMemoryCompressor()
    payloads = {
        "pca": [{"sample_id": "S1", "pc1_variance": 11.2}],
        "admixture": [{"K": 2, "cv_error": 0.5}, {"K": 3, "cv_error": 0.4}],
        "fst": [{"pop1": "A", "pop2": "B", "fst": 0.2}],
        "roh": [{"sample_id": "S1", "population": "A", "total_roh_mb": 150}],
        "selection_scan": [{"region": "chr1:1-2", "statistic": "iHS", "score": 4.1}],
    }

    for tool, raw in payloads.items():
        response = compressor.compress(MemoryCompressRequest(tool_name=tool, step_name="audit", raw_output=raw))
        assert response.compressed_memory["summary"]
        assert response.compressed_memory["retained_metrics"] is not None


def test_generated_provenance_trace_exists():
    response = client.post(
        "/insilicopop/audit",
        files={"metadata_file": ("metadata.csv", b"sample_id,population\nS1,North Indian\n", "text/csv")},
    )

    trace_path = Path(response.json()["generated_files"]["provenance_trace"]["absolute_path"])
    assert trace_path.exists()
