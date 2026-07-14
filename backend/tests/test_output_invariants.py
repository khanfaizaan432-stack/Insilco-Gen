from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def audit_response():
    return client.post(
        "/insilicopop/audit",
        data={"query": "selection is proven in this cohort"},
        files={
            "metadata_file": ("metadata.csv", b"sample_id,population\nS1,North Indian\nS2,Iyer\n", "text/csv"),
            "pca_file": ("pca.csv", b"sample_id,PC1,PC2,pc1_variance\nS1,0.1,0.2,12.3\n", "text/csv"),
            "admixture_file": ("admix.csv", b"K,cv_error\n2,0.6\n3,0.5\n", "text/csv"),
            "selection_file": ("selection.csv", b"chromosome,start,end,statistic,score\n1,10,20,iHS,4.2\n", "text/csv"),
        },
    ).json()


def test_score_below_100_implies_penalties_non_empty():
    body = audit_response()

    assert body["reliability_score"] < 100
    assert body["audit_report"]["reliability"]["penalties"]


def test_risk_flags_imply_recommended_steps_non_empty():
    body = audit_response()

    assert body["risk_flags"]
    assert body["next_analysis_plan"]["recommended_steps"]


def test_parsed_inputs_imply_memory_tools_non_empty():
    body = audit_response()

    for tool in ["pca", "admixture", "selection_scan"]:
        item = body["compressed_memory"]["tools"][tool]["compressed_memory"]
        assert item["summary"]
        assert item["retained_metrics"] is not None
        assert item["assumptions"]
        assert item["downstream_dependencies"]


def test_selection_overclaim_populates_blocked_steps():
    body = audit_response()

    assert body["next_analysis_plan"]["blocked_steps"]
    assert any("selection" in step["blocked_step"].lower() for step in body["next_analysis_plan"]["blocked_steps"])

