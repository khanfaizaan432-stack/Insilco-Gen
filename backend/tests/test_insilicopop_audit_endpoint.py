from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_insilicopop_audit_metadata_only():
    response = client.post(
        "/insilicopop/audit",
        files={"metadata_file": ("metadata.csv", b"sample_id,population\nS1,Iyer\nS2,North Indian\n", "text/csv")},
    )

    assert response.status_code == 200
    body = response.json()
    assert "reliability_score" in body
    assert "risk_flags" in body
    assert "compressed_memory" in body
    assert "next_analysis_plan" in body


def test_insilicopop_audit_multiple_files():
    response = client.post(
        "/insilicopop/audit",
        files={
            "metadata_file": ("metadata.csv", b"sample_id,population\nS1,Iyer\nS2,Iyer\n", "text/csv"),
            "pca_file": ("pca.csv", b"sample_id,pc1_variance,outlier\nS1,12.3,false\n", "text/csv"),
            "admixture_file": ("admix.csv", b"K,cv_error\n2,0.6\n3,0.5\n", "text/csv"),
            "fst_file": ("fst.csv", b"pop1,pop2,fst\nIyer,North Indian,0.04\n", "text/csv"),
            "roh_file": ("roh.csv", b"sample_id,population,total_roh_mb\nS1,Iyer,80\n", "text/csv"),
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["compressed_memory"]["tools"]["pca"]
    assert body["compressed_memory"]["tools"]["admixture"]
    assert body["compressed_memory"]["tools"]["fst"]
    assert body["compressed_memory"]["tools"]["roh"]

