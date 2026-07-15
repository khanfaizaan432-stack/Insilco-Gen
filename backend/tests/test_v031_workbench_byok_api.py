from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_workbench_has_optional_global_india_and_byok_controls_without_browser_storage():
    text = client.get("/insilicopop/workbench").text
    for expected in (
        "Global Care and Intake Context (optional)",
        "None / not supplied",
        "Global default",
        "India locale additions",
        "Exact original-language clinical wording",
        "Separate translated working text",
        "Provider Settings — session-memory BYOK (optional)",
        "Test connection",
        "Forget key",
        'type="password"',
        "activeByokSessionId",
    ):
        assert expected in text
    assert "localStorage" not in text
    assert "sessionStorage" not in text
    assert 'event.target.value !== "india"' in text


def test_byok_api_configure_status_test_and_forget_never_return_secret():
    secret = "synthetic-api-security-test-secret"
    session_id = "api-session-123456789"
    response = client.post(
        "/insilicopop/byok/session",
        json={"session_id": session_id, "provider": "mock", "model": "mock", "api_key": secret},
    )
    assert response.status_code == 200
    assert secret not in response.text
    assert "api_key" not in response.text
    assert response.json()["provider"] == "mock"
    assert client.post(f"/insilicopop/byok/session/{session_id}/test").json()["external_call_made"] is False
    status = client.get(f"/insilicopop/byok/session/{session_id}")
    assert status.status_code == 200
    assert secret not in status.text
    forgotten = client.delete(f"/insilicopop/byok/session/{session_id}")
    assert forgotten.json() == {"status": "forgotten", "forgotten": True}
    assert client.get(f"/insilicopop/byok/session/{session_id}").status_code == 404


def test_invalid_byok_configuration_does_not_echo_secret_in_validation_error():
    secret = "synthetic-invalid-request-must-not-echo"
    response = client.post(
        "/insilicopop/byok/session",
        json={
            "session_id": "invalid-session-123456",
            "provider": "openai_compatible",
            "model": "bounded-model",
            "base_url": "not-an-absolute-url",
            "api_key": secret,
            "budget": {"max_calls": "not-an-integer"},
        },
    )
    assert response.status_code == 400
    assert secret not in response.text
    assert "api_key" not in response.text


def test_nonsecret_byok_provenance_may_join_run_state_without_session_id_or_key(tmp_path, monkeypatch):
    from app.insilicopop.agent.loop import AgentLoop

    monkeypatch.setattr(AgentLoop, "__init__", lambda self, generated_root=None: setattr(self, "generated_root", tmp_path))
    session_id = "run-session-123456789"
    secret = "synthetic-run-never-persist"
    assert client.post("/insilicopop/byok/session", json={"session_id": session_id, "provider": "mock", "model": "mock", "api_key": secret}).status_code == 200
    response = client.post(
        "/insilicopop/agent/run",
        data={"query": "bounded dry-run", "llm_provider": "mock", "byok_session_id": session_id},
    )
    assert response.status_code == 200
    body = response.json()
    serialized = json.dumps(body)
    assert body["byok_runtime"]["provider"] == "mock"
    assert secret not in serialized
    assert session_id not in serialized
    for path in tmp_path.rglob("*"):
        if path.is_file():
            content = path.read_text(encoding="utf-8", errors="ignore")
            assert secret not in content
            assert session_id not in content
