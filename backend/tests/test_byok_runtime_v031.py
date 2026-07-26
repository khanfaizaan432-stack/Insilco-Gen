from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.insilicopop.agent.state import AgentState
from app.insilicopop.llm.byok_runtime import (
    BYOKBudget,
    BYOKRuntime,
    BYOKSessionConfiguration,
    BoundedLLMRequest,
    EvidenceItem,
    build_compact_case_context,
    deduplicate_evidence,
    request_cache_key,
)


SESSION = "session-1234567890"
SECRET = "synthetic-credential-never-persist-this-value"


def _config(**updates):
    values = {"session_id": SESSION, "provider": "mock", "model": "mock"}
    values.update(updates)
    return BYOKSessionConfiguration(**values)


def _request(**updates):
    values = {"role": "extraction", "task": "Extract bounded supplied facts", "compact_context": {"case_id": "CASE-1"}}
    values.update(updates)
    return BoundedLLMRequest(**values)


def _configure(runtime, **updates):
    return runtime.configure(_config(**updates)).session_id


def test_mock_is_default_and_configuration_never_serializes_secret():
    config = _config(api_key=SECRET)
    assert "api_key" not in config.model_dump()
    assert SECRET not in config.model_dump_json()
    runtime = BYOKRuntime()
    status = runtime.configure(config)
    serialized = status.model_dump_json()
    assert status.provider == "mock"
    assert status.external_call_made is False
    assert SECRET not in serialized
    assert "api_key" not in serialized


def test_agent_state_rejects_arbitrary_credential_bearing_byok_dictionary():
    with pytest.raises(ValidationError):
        AgentState(run_id="state-secret-test", byok_runtime={"api_key": SECRET, "provider": "mock", "model": "mock"})


def test_no_external_call_without_explicit_external_provider_configuration():
    calls = []
    runtime = BYOKRuntime(transport=lambda *args: calls.append(args) or b"{}")
    session_id = _configure(runtime)
    result = runtime.execute(session_id, _request())
    assert result.status == "success"
    assert calls == []
    assert runtime.status(session_id).external_call_made is False
    with pytest.raises(KeyError):
        runtime.execute("not-configured-session", _request())


def test_forget_removes_key_cache_usage_and_session():
    runtime = BYOKRuntime()
    session_id = _configure(runtime, api_key=SECRET)
    runtime.execute(session_id, _request())
    assert runtime.forget(session_id) is True
    assert runtime.forget(session_id) is False
    with pytest.raises(KeyError):
        runtime.status(session_id)


def test_failed_connection_is_generic_and_does_not_expose_key():
    def fail(*_args):
        raise OSError(f"transport accidentally included {SECRET}")

    runtime = BYOKRuntime(transport=fail, resolver=lambda _host, _port: ["8.8.8.8"])
    session_id = _configure(runtime, provider="openai_compatible", model="bounded-model", base_url="https://provider.invalid/v1", api_key=SECRET)
    result = runtime.test_connection(session_id)
    assert result["status"] == "connection_test_failed"
    assert SECRET not in json.dumps(result)
    assert result["provider"] == "openai_compatible"
    assert result["model"] == "bounded-model"


def test_compact_context_excludes_unrelated_fields_and_preserves_required_provenance():
    case = {"case": {"id": "C1", "phenotype": "bounded"}, "trace": ["do not send"], "provenance": {"source_ids": ["SRC-1"]}}
    compact = build_compact_case_context(case, ["case.id", "provenance.source_ids"])
    assert compact == {"case": {"id": "C1"}, "provenance": {"source_ids": ["SRC-1"]}}
    assert "trace" not in compact
    assert "phenotype" not in json.dumps(compact)


def test_evidence_dedup_removes_exact_duplicate_but_preserves_conflict():
    items = [
        EvidenceItem(source_id="SRC-1", content={"assertion": "supports"}),
        EvidenceItem(source_id="SRC-1", content={"assertion": "supports"}),
        EvidenceItem(source_id="SRC-1", content={"assertion": "conflicts"}),
    ]
    deduplicated = deduplicate_evidence(items)
    assert len(deduplicated) == 2
    assert [item.content["assertion"] for item in deduplicated] == ["supports", "conflicts"]


def test_cache_is_session_memory_only_and_policy_or_evidence_change_invalidates():
    runtime = BYOKRuntime()
    session_id = _configure(runtime)
    first = runtime.execute(session_id, _request(evidence=[EvidenceItem(source_id="S1", content="one")]))
    cached = runtime.execute(session_id, _request(evidence=[EvidenceItem(source_id="S1", content="one")]))
    changed = runtime.execute(session_id, _request(evidence=[EvidenceItem(source_id="S1", content="two")]))
    policy_changed = runtime.execute(session_id, _request(policy_version="changed", evidence=[EvidenceItem(source_id="S1", content="one")]))
    assert first.usage.cache_hit is False
    assert cached.usage.cache_hit is True
    assert changed.usage.cache_hit is False
    assert policy_changed.usage.cache_hit is False
    assert request_cache_key("mock", "mock", _request(policy_version="a")) != request_cache_key("mock", "mock", _request(policy_version="b"))


@pytest.mark.parametrize(
    ("budget", "expected"),
    [
        (BYOKBudget(max_calls=0), "call_limit_reached"),
        (BYOKBudget(max_input_tokens=1), "token_limit_reached"),
        (BYOKBudget(max_total_tokens=1), "token_limit_reached"),
        (BYOKBudget(max_output_tokens=100, max_total_tokens=10000, estimated_cost_ceiling_usd=0), "cost_limit_reached"),
    ],
)
def test_budgets_stop_safely_before_execution(budget, expected):
    calls = []
    runtime = BYOKRuntime(transport=lambda *args: calls.append(args) or b"{}")
    session_id = _configure(runtime, budget=budget, input_cost_per_million_usd=1, output_cost_per_million_usd=1)
    result = runtime.execute(session_id, _request())
    assert result.status == expected
    assert calls == []


def test_direct_identifiers_are_policy_blocked_before_transport_and_not_cached():
    calls = []
    runtime = BYOKRuntime(transport=lambda *args: calls.append(args) or b"{}")
    session_id = _configure(runtime)
    result = runtime.execute(session_id, _request(compact_context={"note": "person@example.org"}))
    assert result.status == "policy_blocked"
    assert result.usage.retry_count == 0
    assert calls == []


def test_structured_output_validation_retry_is_bounded_and_usage_is_deterministic():
    calls = []

    def transport(_url, _headers, _body, _timeout, _method):
        calls.append(1)
        return b'{"choices":[{"message":{"content":"not-json"}}]}'

    runtime = BYOKRuntime(transport=transport, resolver=lambda _host, _port: ["8.8.8.8"], sleeper=lambda _seconds: None)
    session_id = _configure(runtime, provider="openai_compatible", model="bounded-model", base_url="https://provider.invalid/v1", api_key=SECRET, budget=BYOKBudget(max_retries=1))
    result = runtime.execute(session_id, _request())
    assert result.status == "provider_unavailable"
    assert len(calls) == 2
    assert result.response is None
    assert result.usage.retry_count == 1
    assert result.usage.provider == "openai_compatible"
    assert result.usage.model == "bounded-model"


def test_provider_refusal_is_validated_and_never_retried():
    calls = []

    def transport(_url, _headers, _body, _timeout, _method):
        calls.append(1)
        return b'{"choices":[{"message":{"content":"{\\"status\\":\\"refusal\\",\\"records\\":[],\\"warnings\\":[\\"policy refusal\\"]}"}}],"usage":{"completion_tokens":8}}'

    runtime = BYOKRuntime(transport=transport, resolver=lambda _host, _port: ["8.8.8.8"])
    session_id = _configure(runtime, provider="openai_compatible", model="bounded-model", base_url="https://provider.invalid/v1", api_key=SECRET, budget=BYOKBudget(max_retries=2))
    result = runtime.execute(session_id, _request())
    assert result.status == "refusal"
    assert result.usage.retry_count == 0
    assert len(calls) == 1
    assert SECRET not in result.model_dump_json()
