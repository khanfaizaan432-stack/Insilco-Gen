from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_agent_run_endpoint_returns_actions_and_files():
    response = client.post(
        "/insilicopop/agent/run",
        data={"query": "selection is proven", "memory_budget_chars": "1500", "memory_mode": "compact"},
        files={
            "selection_file": ("selection.tsv", b"chr\tposition\tgene\tihs\tp_value\n1\t123\tLCT\t2.8\t0.001\n", "text/plain"),
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["planned_actions"]
    assert body["blocked_actions"]
    assert any(action["action_type"] == "block_interpretation" for action in body["blocked_actions"])
    assert body["generated_files"]["agent_state"]["created"] is True
    assert body["generated_files"]["final_report"]["created"] is True

