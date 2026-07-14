from __future__ import annotations

import json

import pytest

from app.insilicopop.agent.loop import AgentLoop
from app.insilicopop.llm.base import LLMProviderError
from app.insilicopop.llm.config import LLMConfig
from app.insilicopop.llm.openai_compatible_provider import OpenAICompatibleProvider
from app.insilicopop.llm.schemas import LLMActionProposal


def _config() -> LLMConfig:
    return LLMConfig(
        provider="openai_compatible",
        external_llm_enabled=True,
        openai_compatible_base_url="http://llm.invalid/v1",
        openai_compatible_api_key="test-key",
        openai_compatible_model="test-model",
    )


def test_openai_compatible_provider_parses_structured_actions_without_real_network():
    captured = {}

    def fake_post(url, headers, body, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["payload"] = json.loads(body.decode("utf-8"))
        content = {
            "actions": [
                {
                    "action_type": "run_admixture",
                    "rationale": "Current ADMIXTURE K sweep is too narrow.",
                    "required_inputs": ["LD-pruned genotype data"],
                    "expected_outputs": ["Q matrix", "CV errors"],
                    "claim_intent": None,
                    "confidence": 0.82,
                }
            ]
        }
        return json.dumps({"choices": [{"message": {"content": json.dumps(content)}}]}).encode("utf-8")

    provider = OpenAICompatibleProvider(_config(), http_post=fake_post)
    proposals = provider.propose_actions(compact_memory={"facts": ["narrow K"]}, audit_summary={"risk_flags": []}, query="admixture")

    assert proposals[0].action_type == "run_admixture"
    assert provider.external_call_made is True
    assert captured["url"] == "http://llm.invalid/v1/chat/completions"
    prompt = json.loads(captured["payload"]["messages"][1]["content"])
    assert prompt["raw_files_included"] is False
    assert prompt["redaction_policy"]["raw_genomic_files_included"] is False


def test_openai_compatible_invalid_json_raises_controlled_provider_error():
    provider = OpenAICompatibleProvider(_config(), http_post=lambda url, headers, body, timeout: b"not-json")

    with pytest.raises(LLMProviderError) as exc:
        provider.propose_actions(compact_memory={}, audit_summary={}, query=None)

    failure = exc.value.failure_reason()
    assert failure["failure_type"] == "invalid_llm_json"
    assert failure["recommended_fix"]


def test_agent_loop_records_invalid_provider_json_as_controlled_failure(monkeypatch):
    class BadProvider:
        provider_name = "openai_compatible"
        external_call_made = True

        def propose_actions(self, *, compact_memory, audit_summary, query):
            raise LLMProviderError("invalid_llm_json", "Provider returned invalid JSON.")

    monkeypatch.setattr("app.insilicopop.agent.loop.build_llm_provider", lambda provider_name: BadProvider())

    result = AgentLoop().run(query="selection is proven", uploads={}, llm_provider="openai_compatible")

    assert result["llm_provider"] == "openai_compatible"
    assert result["external_llm_called"] is True
    assert result["external_tools_executed"] is False
    assert any(failure["failure_type"] == "invalid_llm_json" for failure in result["failure_reasons"])


def test_agent_loop_reports_external_provider_metadata_with_fake_provider(monkeypatch):
    class FakeProvider:
        provider_name = "openai_compatible"
        external_call_made = True

        def propose_actions(self, *, compact_memory, audit_summary, query):
            return [
                LLMActionProposal(
                    action_type="interpret_selection",
                    rationale="User asks for selection interpretation.",
                    required_inputs=["selection scan table"],
                    expected_outputs=["cautious interpretation"],
                    claim_intent="selection is proven",
                    confidence=0.75,
                )
            ]

    monkeypatch.setattr("app.insilicopop.agent.loop.build_llm_provider", lambda provider_name: FakeProvider())

    result = AgentLoop().run(query="selection is proven", uploads={}, llm_provider="openai_compatible")

    assert result["llm_provider"] == "openai_compatible"
    assert result["external_llm_called"] is True
    assert result["external_tools_executed"] is False
    assert result["validated_actions"]
