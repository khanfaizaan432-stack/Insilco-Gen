from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_agent_response_includes_command_previews_with_execution_disabled():
    response = client.post(
        "/insilicopop/agent/run",
        data={"query": "selection is proven", "memory_mode": "compact", "llm_provider": "mock"},
        files={"selection_file": ("selection.tsv", b"chr\tposition\tgene\tihs\tp_value\n1\t123\tLCT\t2.8\t0.001\n", "text/plain")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["command_previews"]
    assert body["llm_provider"] == "mock"
    assert body["external_llm_called"] is False
    assert body["external_tools_executed"] is False
    for preview in body["command_previews"]:
        assert preview["execution_enabled"] is False
        assert preview["tool"]
        assert preview["command"]
        assert preview["purpose"]
        assert "required_inputs" in preview
        assert "expected_outputs" in preview

