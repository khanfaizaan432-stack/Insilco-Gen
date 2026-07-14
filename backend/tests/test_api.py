from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health_endpoint():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_analyze_endpoint_returns_reports():
    response = client.post(
        "/analyze",
        files={
            "sequences": ("sequences.fasta", b">s1\nATGC\n>s2\nTTAA\n", "text/plain"),
            "labels": (
                "labels.csv",
                b"sample_id,label\ns1,resistant\ns2,susceptible\n",
                "text/csv",
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data_health_report"]["passed"] is True
    assert "workflow_pack: Dry-Biotics" in body["workflow_yaml"]
