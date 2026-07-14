from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_insilicopop_memory_compress_returns_structured_memory():
    response = client.post(
        "/insilicopop/memory/compress",
        json={
            "tool_name": "selection_scan",
            "step_name": "selection_audit",
            "raw_output": [{"region": "chr2", "statistic": "iHS", "score": 4.2}],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert "compressed_memory" in body
    assert "retained_facts" in body
    assert "risk_flags" in body
