from __future__ import annotations

import json
import logging
import threading
import urllib.error
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import app.insilicopop.llm.byok_runtime as byok_runtime_module
from app.main import app
from app.insilicopop.agent.loop import AgentLoop
from app.insilicopop.agent.workbench import WorkbenchRunStore
from app.insilicopop.clinical import build_clinical_case_intake
from app.insilicopop.clinical.validation import detect_direct_identifiers, sanitized_clinical_free_text
from app.insilicopop.llm.byok_runtime import (
    BYOKBudget,
    BYOKRuntime,
    BYOKSessionConfiguration,
    BoundedLLMRequest,
    EvidenceItem,
    MAX_USAGE_HISTORY,
    build_compact_case_context,
    deduplicate_evidence,
)


SECRET = "TEST_SECRET_MUST_NOT_APPEAR"
PUBLIC_IP = "8.8.8.8"
client = TestClient(app)


def _resolver(addresses: list[str]):
    return lambda _host, _port: addresses


def _external_config(**updates) -> BYOKSessionConfiguration:
    values = {
        "provider": "openai_compatible",
        "model": "bounded-model",
        "base_url": "https://provider.example/v1",
        "api_key": SECRET,
        "budget": BYOKBudget(max_calls=4, max_output_tokens=200, max_total_tokens=10_000, max_concurrent_calls=2),
    }
    values.update(updates)
    return BYOKSessionConfiguration(**values)


def _request(**updates) -> BoundedLLMRequest:
    values = {
        "role": "extraction",
        "task": "Bounded synthetic security test",
        "compact_context": {"case_id": "CASE-SYNTHETIC"},
        "max_output_tokens": 50,
    }
    values.update(updates)
    return BoundedLLMRequest(**values)


def _success(output_tokens: int = 10) -> bytes:
    content = json.dumps({"status": "success", "records": [], "warnings": []})
    return json.dumps({"choices": [{"message": {"content": content}}], "usage": {"completion_tokens": output_tokens}}).encode()


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1/v1",
        "https://[::1]/v1",
        "https://10.0.0.1/v1",
        "https://172.16.0.1/v1",
        "https://192.168.1.1/v1",
        "https://169.254.169.254/v1",
        "https://[fe80::1]/v1",
        "https://[fd00::1]/v1",
        "https://metadata.google.internal/v1",
        "http://localhost:8000/v1",
        "http://provider.example/v1",
    ],
)
def test_ssrf_literal_internal_metadata_and_http_destinations_are_rejected(url):
    runtime = BYOKRuntime(resolver=_resolver([PUBLIC_IP]))
    with pytest.raises(ValueError):
        runtime.configure(_external_config(base_url=url))


@pytest.mark.parametrize("url", ["file:///tmp/key", "ftp://provider.example/v1", "https://user:password@provider.example/v1", "https://provider.example:bad/v1"])
def test_unsupported_malformed_or_credential_bearing_urls_are_rejected(url):
    with pytest.raises((ValidationError, ValueError)):
        _external_config(base_url=url)


def test_public_https_destination_is_accepted_with_fake_resolution_and_transport():
    calls = []
    runtime = BYOKRuntime(transport=lambda *args: calls.append(args) or b"{}", resolver=_resolver([PUBLIC_IP]))
    status = runtime.configure(_external_config())
    result = runtime.test_connection(status.session_id)
    assert result["status"] == "success"
    assert result["call_type"] == "connection_test"
    assert len(calls) == 1


@pytest.mark.parametrize("addresses", [["10.0.0.5"], ["2001:db8::1"], [PUBLIC_IP, "192.168.1.4"], ["fe80::1"]])
def test_dns_resolution_to_any_non_public_address_is_rejected(addresses):
    calls = []
    runtime = BYOKRuntime(transport=lambda *args: calls.append(args) or b"{}", resolver=_resolver(addresses))
    status = runtime.configure(_external_config())
    result = runtime.test_connection(status.session_id)
    assert result["status"] == "connection_test_failed"
    assert result["external_call_made"] is False
    assert calls == []


def test_redirect_is_not_followed_or_retried():
    calls = []

    def redirect(url, *_args):
        calls.append(url)
        raise urllib.error.HTTPError(url, 302, "redirect", {"Location": "http://127.0.0.1/internal"}, None)

    runtime = BYOKRuntime(transport=redirect, resolver=_resolver([PUBLIC_IP]), sleeper=lambda _seconds: None)
    status = runtime.configure(_external_config(budget=BYOKBudget(max_calls=3, max_output_tokens=100, max_total_tokens=10_000, max_retries=2)))
    result = runtime.execute(status.session_id, _request())
    assert result.status == "provider_unavailable"
    assert len(calls) == 1
    assert result.usage.attempt_history[0].http_status == 302
    assert result.usage.attempt_history[0].transient is False


def test_development_localhost_requires_explicit_runtime_flag():
    config = _external_config(base_url="http://localhost:8000/v1")
    with pytest.raises(ValueError):
        BYOKRuntime().configure(config)
    runtime = BYOKRuntime(transport=lambda *_args: b"{}", resolver=_resolver(["127.0.0.1"]), allow_development_localhost=True)
    status = runtime.configure(config)
    assert runtime.test_connection(status.session_id)["status"] == "success"


@pytest.mark.parametrize(
    "payload",
    [
        SECRET,
        [{"api_key": SECRET}],
        {"provider": "openai_compatible", "api_key": SECRET, "budget": {"max_calls": "invalid"}},
        {"provider": "openai_compatible", "api_key": SECRET, "role_models": {"extraction": ""}},
    ],
)
def test_configure_validation_never_echoes_secret_or_logs_body(payload, caplog):
    caplog.set_level(logging.DEBUG)
    response = client.post("/insilicopop/byok/session", json=payload)
    assert response.status_code == 400
    assert SECRET not in response.text
    assert SECRET not in caplog.text


def test_malformed_json_never_echoes_secret():
    response = client.post(
        "/insilicopop/byok/session",
        content='{"api_key":"' + SECRET + '",',
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 400
    assert SECRET not in response.text


def test_valid_configuration_still_returns_server_generated_capability():
    requested = "caller-selected-session-123456"
    response = client.post("/insilicopop/byok/session", json={"session_id": requested, "provider": "mock", "model": "mock"})
    assert response.status_code == 200
    assert response.json()["session_id"] != requested
    assert len(response.json()["session_id"]) >= 40
    client.delete(f"/insilicopop/byok/session/{response.json()['session_id']}")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Patient name: Priya Sharma", "patient_name"),
        ("UHID: AB123456", "medical_record_number"),
        ("MRN: ZX-998877", "medical_record_number"),
        ("Hospital registration no: HOSP-778899", "medical_record_number"),
        ("Phone: +91 98765 43210", "phone_number"),
        ("Email: person@example.org", "email_address"),
        ("Aadhaar: 1234 5678 9012", "aadhaar_number"),
        ("Insurance ID: INS-998877", "insurance_member_number"),
        ("Passport: A1234567", "passport_number"),
        ("Patient address:\nFlat 2B\nMG Road\nBengaluru 560001", "street_address"),
    ],
)
def test_field_aware_identifier_positive_cases(value, expected):
    assert expected in detect_direct_identifiers(value, "global_intake_context.language_context.original_text")


@pytest.mark.parametrize(
    ("value", "path"),
    [
        ("chr1:123456789 A>G", "candidate_variants.coordinate"),
        ("chr1:123456789-123456999", "candidate_variants.interval"),
        ("NC_000001.11:123456789:A:G", "variant.spdi"),
        ("NM_000059.4:c.7790G>A", "variant.hgvs"),
        ("PMID: 123456789", "evidence.pmid"),
        ("2026-07-15", "laboratory.report_date"),
        ("NM_000059.4", "laboratory.transcript_exact"),
        ("sha256:abcdef0123456789abcdef0123456789", "reference_digest"),
        ("MODEL-123456789", "byok.model"),
        ("SAMPLE-123456789", "sample_id"),
    ],
)
def test_scientific_and_pseudonymous_values_are_not_phone_identifiers(value, path):
    assert detect_direct_identifiers(value, path) == []


def _clinical_case(global_text: str | None = None) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "0.27",
        "pseudonymous_case_id": "CASE-V0311",
        "intended_use": "clinical_genetics_research_curation",
        "redaction_declared": True,
        "reviewer_status": "pending",
        "human_review_required": True,
    }
    if global_text is not None:
        payload["global_intake_context"] = {"language_context": {"original_text": global_text}}
    return payload


def test_detected_identifier_is_removed_from_state_report_reproducibility_and_workbench(tmp_path: Path):
    sensitive = "Patient name: Priya Sharma"
    run = AgentLoop(generated_root=tmp_path).run(query="bounded intake", uploads={}, clinical_case_intake=_clinical_case(sensitive))
    serialized = json.dumps(run)
    assert sensitive not in serialized
    assert "patient_name" in serialized
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert sensitive not in path.read_text(encoding="utf-8", errors="ignore")
    detail = WorkbenchRunStore(tmp_path).run_detail(run["run_id"])
    assert sensitive not in detail.model_dump_json()


def test_identifier_in_structured_id_is_replaced_with_schema_safe_nonsecret_id():
    payload = _clinical_case()
    payload["candidate_variants"] = [
        {
            "candidate_id": "MRN:AB123456",
            "submitted_representation": "NM_000059.4:c.7790G>A",
        }
    ]
    result = build_clinical_case_intake(payload)
    assert result.intake_completeness == "blocked"
    assert result.candidate_variant_ids[0].startswith("REDACTED-ID-")
    assert "MRN:AB123456" not in result.model_dump_json()


def test_schema_invalid_intake_does_not_echo_identifier_or_invalid_intended_use():
    sensitive = "Patient name: Priya Sharma"
    result = build_clinical_case_intake(
        {
            "schema_version": "0.27",
            "pseudonymous_case_id": sensitive,
            "intended_use": SECRET,
            "redaction_declared": True,
        }
    )
    assert result.intake_completeness == "invalid"
    assert result.pseudonymous_case_id == "invalid_case_id"
    assert result.intended_use == "invalid"
    assert sensitive not in result.model_dump_json()
    assert SECRET not in result.model_dump_json()


@pytest.mark.parametrize(
    "blocked_text",
    ["Patient name: Priya Sharma", "UHID: AB123456", "Patient address:\nFlat 2B\nMG Road\nBengaluru 560001"],
)
def test_detected_identifier_is_blocked_before_byok_transport(blocked_text):
    calls = []
    runtime = BYOKRuntime(transport=lambda *args: calls.append(args) or _success(), resolver=_resolver([PUBLIC_IP]))
    session_id = runtime.configure(_external_config()).session_id
    result = runtime.execute(session_id, _request(compact_context={"note": blocked_text}))
    assert result.status == "policy_blocked"
    assert calls == []


@pytest.mark.parametrize(
    ("budget", "output_cost"),
    [
        (BYOKBudget(max_calls=1, max_output_tokens=100, max_total_tokens=10_000, max_concurrent_calls=2), 0),
        (BYOKBudget(max_calls=2, max_output_tokens=50, max_total_tokens=10_000, max_concurrent_calls=2), 0),
        (BYOKBudget(max_calls=2, max_output_tokens=100, max_total_tokens=10_000, estimated_cost_ceiling_usd=5, max_concurrent_calls=2), 100_000),
    ],
)
def test_atomic_reservations_allow_only_one_simultaneous_request_when_one_fits(budget, output_cost):
    entered = threading.Event()
    release = threading.Event()

    def transport(*_args):
        entered.set()
        assert release.wait(5)
        return _success(10)

    runtime = BYOKRuntime(transport=transport, resolver=_resolver([PUBLIC_IP]))
    status = runtime.configure(_external_config(budget=budget, output_cost_per_million_usd=output_cost))
    results = []
    thread = threading.Thread(target=lambda: results.append(runtime.execute(status.session_id, _request()).status))
    thread.start()
    assert entered.wait(5)
    results.append(runtime.execute(status.session_id, _request()).status)
    release.set()
    thread.join(5)
    assert sorted(results) in (["call_limit_reached", "success"], ["cost_limit_reached", "success"], ["success", "token_limit_reached"])
    final = runtime.status(status.session_id)
    assert final.reserved_calls == 0
    assert final.output_tokens <= budget.max_output_tokens
    assert final.estimated_cost_usd <= budget.estimated_cost_ceiling_usd


def test_transient_retry_consumes_attempt_budget_and_permanent_error_does_not_retry():
    transient_calls = []

    def transient_then_success(url, *_args):
        transient_calls.append(1)
        if len(transient_calls) == 1:
            raise urllib.error.HTTPError(url, 429, "rate limited", {}, None)
        return _success(7)

    runtime = BYOKRuntime(transport=transient_then_success, resolver=_resolver([PUBLIC_IP]), sleeper=lambda _seconds: None)
    session_id = runtime.configure(_external_config(budget=BYOKBudget(max_calls=2, max_output_tokens=100, max_total_tokens=10_000, max_retries=1))).session_id
    result = runtime.execute(session_id, _request())
    assert result.status == "success"
    assert result.usage.attempt_count == 2
    assert runtime.status(session_id).provider_attempt_count == 2

    permanent_calls = []

    def unauthorized(url, *_args):
        permanent_calls.append(1)
        raise urllib.error.HTTPError(url, 401, "unauthorized", {}, None)

    runtime = BYOKRuntime(transport=unauthorized, resolver=_resolver([PUBLIC_IP]), sleeper=lambda _seconds: None)
    session_id = runtime.configure(_external_config(budget=BYOKBudget(max_calls=3, max_output_tokens=100, max_total_tokens=10_000, max_retries=2))).session_id
    result = runtime.execute(session_id, _request())
    assert result.status == "provider_unavailable"
    assert len(permanent_calls) == 1
    assert result.usage.attempt_history[0].http_status == 401


def test_exhausted_retry_and_usage_over_reservation_are_bounded():
    runtime = BYOKRuntime(
        transport=lambda url, *_args: (_ for _ in ()).throw(urllib.error.HTTPError(url, 503, "unavailable", {}, None)),
        resolver=_resolver([PUBLIC_IP]),
        sleeper=lambda _seconds: None,
    )
    session_id = runtime.configure(_external_config(budget=BYOKBudget(max_calls=2, max_output_tokens=100, max_total_tokens=10_000, max_retries=1))).session_id
    result = runtime.execute(session_id, _request())
    assert result.usage.attempt_count == 2
    assert result.status == "provider_unavailable"
    assert runtime.status(session_id).reserved_calls == 0

    runtime = BYOKRuntime(transport=lambda *_args: _success(100), resolver=_resolver([PUBLIC_IP]))
    session_id = runtime.configure(_external_config(budget=BYOKBudget(max_calls=1, max_output_tokens=10, max_total_tokens=10_000))).session_id
    result = runtime.execute(session_id, _request(max_output_tokens=10))
    assert result.status == "provider_unavailable"
    assert result.usage.attempt_history[0].reported_output_tokens == 100
    assert runtime.status(session_id).output_tokens <= 10


def test_session_expiry_capacity_and_forget_are_bounded():
    now = [100.0]
    runtime = BYOKRuntime(time_source=lambda: now[0], idle_ttl_seconds=10, absolute_ttl_seconds=100, max_sessions=1)
    first = runtime.configure(BYOKSessionConfiguration(provider="mock", model="mock"))
    second = runtime.configure(BYOKSessionConfiguration(provider="mock", model="mock"))
    with pytest.raises(KeyError):
        runtime.status(first.session_id)
    assert runtime.status(second.session_id).configured is True
    assert runtime.forget(second.session_id) is True
    with pytest.raises(KeyError):
        runtime.status(second.session_id)

    third = runtime.configure(BYOKSessionConfiguration(provider="mock", model="mock"))
    now[0] += 11
    with pytest.raises(KeyError):
        runtime.status(third.session_id)


def test_compact_context_is_deterministic_bounded_and_records_truncation_and_omission():
    case = {"case": {"a": "a" * 50, "b": "b" * 50, "id": "CASE-1"}}
    first = build_compact_case_context(case, ["case.b", "case.id", "case.a"], per_field_limit=20, total_limit=80)
    second = build_compact_case_context(case, ["case.a", "case.id", "case.b"], per_field_limit=20, total_limit=80)
    assert first == second
    metadata = first["__compact_context_metadata__"]
    assert metadata["truncated_paths"] == []
    assert metadata["omitted_paths"]
    assert all(item.get("retained_length", 0) == 0 for item in metadata["omitted_paths"] if item["reason"].startswith("semantic_safety"))
    assert len(json.dumps(first, sort_keys=True)) < 2_000


def test_evidence_dedup_merges_provenance_and_preserves_conflicts():
    items = [
        EvidenceItem(source_id="S1", claim_id="C1", content={"assertion": "supports"}, provenance_references=["P1", "P2"]),
        EvidenceItem(source_id="S1", claim_id="C1", content={"assertion": "supports"}, provenance_references=["P2", "P3"]),
        EvidenceItem(source_id="S1", claim_id="C1", content={"assertion": "conflicts"}, provenance_references=["P4"]),
    ]
    result = deduplicate_evidence(items)
    assert len(result) == 2
    assert result[0].provenance_references == ["P1", "P2", "P3"]
    assert result[1].content == {"assertion": "conflicts"}


def test_runtime_lock_has_conditional_pointer_role_mapping_and_call_types(tmp_path: Path):
    runtime = BYOKRuntime()
    status = runtime.configure(BYOKSessionConfiguration(provider="mock", model="default-model", role_models={"extraction": "extract-model"}))
    public = runtime.public_provenance(status.session_id)
    run = AgentLoop(generated_root=tmp_path).run(query="bounded dry run", uploads={}, byok_runtime=public)
    repro = Path(run["reproducibility_bundle"]["path"])
    lock = json.loads((repro / "runtime_lock.json").read_text(encoding="utf-8"))
    provenance = json.loads((repro / "provenance_index.json").read_text(encoding="utf-8"))
    assert lock["byok_schema_version"] == "0.31.1"
    assert lock["byok_policy_version"]
    assert lock["byok_resolved_role_models"]["extraction"] == "extract-model"
    assert lock["byok_connection_test_attempt_count"] == 0
    assert lock["byok_workflow_provider_attempt_count"] == 0
    assert "global_intake_context" not in provenance


def test_artifact_redaction_preserves_usage_tokens_but_removes_credentials(tmp_path: Path):
    run_dir = tmp_path / "RUN-1" / "reproducibility"
    run_dir.mkdir(parents=True)
    path = run_dir / "guardrail_decisions.json"
    path.write_text(json.dumps({"input_tokens": 12, "output_tokens": 8, "total_tokens": 20, "access_token": SECRET}), encoding="utf-8")
    content = WorkbenchRunStore(tmp_path).read_artifact("RUN-1", "reproducibility/guardrail_decisions.json").content
    assert content["input_tokens"] == 12
    assert content["output_tokens"] == 8
    assert content["total_tokens"] == 20
    assert content["access_token"] == "[REDACTED]"
    assert SECRET not in json.dumps(content)


def test_forget_during_first_attempt_prevents_retry_and_discards_late_result():
    entered = threading.Event()
    release = threading.Event()
    calls: list[str] = []

    def transport(url, headers, *_args):
        calls.append(headers["Authorization"])
        entered.set()
        assert release.wait(5)
        raise urllib.error.HTTPError(url, 503, "synthetic transient", {}, None)

    runtime = BYOKRuntime(transport=transport, resolver=_resolver([PUBLIC_IP]), sleeper=lambda _seconds: None)
    session_id = runtime.configure(_external_config()).session_id
    results = []
    thread = threading.Thread(target=lambda: results.append(runtime.execute(session_id, _request())))
    thread.start()
    assert entered.wait(5)
    assert runtime.forget(session_id) is True
    release.set()
    thread.join(5)

    assert len(calls) == 1
    assert results[0].status == "session_invalidated"
    assert results[0].response is None
    with pytest.raises(KeyError):
        runtime.status(session_id)


def test_forget_during_backoff_prevents_retry():
    backoff = threading.Event()
    release = threading.Event()
    calls = []

    def transport(url, *_args):
        calls.append(url)
        raise urllib.error.HTTPError(url, 429, "synthetic rate limit", {}, None)

    def sleeper(_seconds):
        backoff.set()
        assert release.wait(5)

    runtime = BYOKRuntime(transport=transport, resolver=_resolver([PUBLIC_IP]), sleeper=sleeper)
    session_id = runtime.configure(_external_config()).session_id
    results = []
    thread = threading.Thread(target=lambda: results.append(runtime.execute(session_id, _request())))
    thread.start()
    assert backoff.wait(5)
    runtime.forget(session_id)
    release.set()
    thread.join(5)
    assert len(calls) == 1
    assert results[0].status == "session_invalidated"


def test_expiry_during_attempt_discards_success_and_cache():
    now = [100.0]
    entered = threading.Event()
    release = threading.Event()
    calls = []

    def transport(*_args):
        calls.append(1)
        entered.set()
        assert release.wait(5)
        return _success(5)

    runtime = BYOKRuntime(
        transport=transport,
        resolver=_resolver([PUBLIC_IP]),
        time_source=lambda: now[0],
        idle_ttl_seconds=5,
        absolute_ttl_seconds=20,
    )
    session_id = runtime.configure(_external_config()).session_id
    results = []
    thread = threading.Thread(target=lambda: results.append(runtime.execute(session_id, _request())))
    thread.start()
    assert entered.wait(5)
    now[0] += 6
    release.set()
    thread.join(5)
    assert results[0].status == "session_invalidated"
    assert results[0].response is None
    with pytest.raises(KeyError):
        runtime.status(session_id)


def test_connection_tests_have_separate_zero_and_concurrent_limits():
    calls = []
    zero_runtime = BYOKRuntime(transport=lambda *args: calls.append(args) or b"{}", resolver=_resolver([PUBLIC_IP]))
    zero_id = zero_runtime.configure(
        _external_config(
            budget=BYOKBudget(
                max_calls=0,
                max_input_tokens=0,
                max_output_tokens=0,
                max_total_tokens=0,
                estimated_cost_ceiling_usd=0,
                max_connection_tests=0,
            )
        )
    ).session_id
    assert zero_runtime.test_connection(zero_id)["status"] == "connection_test_limit_reached"
    assert calls == []

    entered = threading.Event()
    release = threading.Event()
    concurrent_calls = []

    def transport(*_args):
        concurrent_calls.append(1)
        entered.set()
        assert release.wait(5)
        return b"{}"

    runtime = BYOKRuntime(transport=transport, resolver=_resolver([PUBLIC_IP]))
    session_id = runtime.configure(
        _external_config(budget=BYOKBudget(max_connection_tests=2, max_concurrent_connection_tests=1))
    ).session_id
    results = []
    thread = threading.Thread(target=lambda: results.append(runtime.test_connection(session_id)["status"]))
    thread.start()
    assert entered.wait(5)
    results.append(runtime.test_connection(session_id)["status"])
    release.set()
    thread.join(5)
    assert sorted(results) == ["connection_test_limit_reached", "success"]
    status = runtime.status(session_id)
    assert status.connection_test_request_count == 2
    assert status.connection_test_attempt_count == 1
    assert status.connection_test_success_count == 1
    assert status.provider_attempt_count == 0


def test_forget_discards_late_connection_test():
    entered = threading.Event()
    release = threading.Event()

    def transport(*_args):
        entered.set()
        assert release.wait(5)
        return b"{}"

    runtime = BYOKRuntime(transport=transport, resolver=_resolver([PUBLIC_IP]))
    session_id = runtime.configure(_external_config()).session_id
    results = []
    thread = threading.Thread(target=lambda: results.append(runtime.test_connection(session_id)))
    thread.start()
    assert entered.wait(5)
    runtime.forget(session_id)
    release.set()
    thread.join(5)
    assert results[0]["status"] == "session_invalidated"


def test_capacity_eviction_invalidates_active_connection_lease_and_old_capability():
    entered = threading.Event()
    release = threading.Event()

    def transport(*_args):
        entered.set()
        assert release.wait(5)
        return b"{}"

    runtime = BYOKRuntime(transport=transport, resolver=_resolver([PUBLIC_IP]), max_sessions=1)
    old_id = runtime.configure(_external_config()).session_id
    results = []
    thread = threading.Thread(target=lambda: results.append(runtime.test_connection(old_id)))
    thread.start()
    assert entered.wait(5)
    replacement = runtime.configure(BYOKSessionConfiguration(provider="mock", model="mock"))
    release.set()
    thread.join(5)
    assert results[0]["status"] == "session_invalidated"
    with pytest.raises(KeyError):
        runtime.status(old_id)
    assert runtime.status(replacement.session_id).provider == "mock"


def _success_with_usage(prompt_tokens, completion_tokens, records=None) -> bytes:
    content = json.dumps({"status": "success", "records": records or [], "warnings": []})
    return json.dumps(
        {
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
        }
    ).encode()


@pytest.mark.parametrize("invalid", [True, 1.5, "1.5", -1, "NaN"])
def test_provider_token_usage_is_strictly_validated(invalid):
    runtime = BYOKRuntime(
        transport=lambda *_args: _success_with_usage(10, invalid),
        resolver=_resolver([PUBLIC_IP]),
    )
    session_id = runtime.configure(
        _external_config(budget=BYOKBudget(max_calls=1, max_retries=0, max_total_tokens=10_000))
    ).session_id
    result = runtime.execute(session_id, _request())
    assert result.status == "provider_unavailable"
    assert result.response is None


def test_prompt_and_completion_usage_and_decimal_cost_are_reconciled_exactly():
    runtime = BYOKRuntime(
        transport=lambda *_args: _success_with_usage(12, 7),
        resolver=_resolver([PUBLIC_IP]),
    )
    session_id = runtime.configure(
        _external_config(
            input_cost_per_million_usd=Decimal("0.1"),
            output_cost_per_million_usd=Decimal("0.2"),
            budget=BYOKBudget(max_calls=1, max_input_tokens=100, max_output_tokens=100, max_total_tokens=200),
        )
    ).session_id
    result = runtime.execute(session_id, _request())
    assert result.status == "success"
    status = runtime.status(session_id)
    assert status.input_tokens == 12
    assert status.output_tokens == 7
    assert status.estimated_cost_usd == Decimal("0.0000026")


def test_usage_history_is_bounded_but_aggregate_cache_hits_are_exact():
    runtime = BYOKRuntime(transport=lambda *_args: _success_with_usage(10, 5), resolver=_resolver([PUBLIC_IP]))
    session_id = runtime.configure(_external_config(budget=BYOKBudget(max_calls=1, max_total_tokens=10_000))).session_id
    assert runtime.execute(session_id, _request()).status == "success"
    for _ in range(MAX_USAGE_HISTORY + 200):
        assert runtime.execute(session_id, _request()).usage.cache_hit is True
    status = runtime.status(session_id)
    assert len(status.usage) == MAX_USAGE_HISTORY
    assert status.cache_hit_count == MAX_USAGE_HISTORY + 200
    assert status.logical_request_count == MAX_USAGE_HISTORY + 201
    assert status.provider_attempt_count == 1


@pytest.mark.parametrize(
    "records",
    [
        [{"note": "Patient email: synthetic.patient@example.org"}],
        [{"note": "Phone: +91 98765 43210"}],
        [{"treatment": "Recommend treatment immediately"}],
        [{"diagnosis": "Final diagnosis: synthetic disorder"}],
        [{"human_approved": True}],
        [{"classification": "pathogenic"}],
    ],
)
def test_policy_invalid_provider_output_is_rejected_and_not_cached(records):
    calls = []
    runtime = BYOKRuntime(
        transport=lambda *_args: calls.append(1) or _success_with_usage(10, 5, records),
        resolver=_resolver([PUBLIC_IP]),
    )
    session_id = runtime.configure(_external_config(budget=BYOKBudget(max_calls=2, max_total_tokens=10_000))).session_id
    first = runtime.execute(session_id, _request())
    second = runtime.execute(session_id, _request())
    assert first.status == second.status == "output_policy_blocked"
    assert first.response is second.response is None
    assert len(calls) == 2


def test_provider_output_provenance_must_reference_supplied_evidence():
    request = _request(evidence=[EvidenceItem(source_id="SRC-1", claim_id="CLAIM-1", content={"fact": "supplied"})])
    allowed_runtime = BYOKRuntime(
        transport=lambda *_args: _success_with_usage(10, 5, [{"source_id": "SRC-1", "claim_id": "CLAIM-1"}]),
        resolver=_resolver([PUBLIC_IP]),
    )
    allowed_id = allowed_runtime.configure(_external_config()).session_id
    assert allowed_runtime.execute(allowed_id, request).status == "success"

    fabricated_runtime = BYOKRuntime(
        transport=lambda *_args: _success_with_usage(10, 5, [{"source_id": "FABRICATED-SOURCE"}]),
        resolver=_resolver([PUBLIC_IP]),
    )
    fabricated_id = fabricated_runtime.configure(_external_config()).session_id
    assert fabricated_runtime.execute(fabricated_id, request).status == "output_policy_blocked"


@pytest.mark.parametrize(
    "value",
    [
        "Patient name: Priya Sharma",
        "Email: synthetic.patient@example.org",
        "Phone: +91 98765 43210",
        "Aadhaar: 1234 5678 9012",
    ],
)
def test_query_identifier_free_text_is_sanitized(value):
    assert sanitized_clinical_free_text(value, "query") == "[REDACTED_DIRECT_IDENTIFIER]"


def test_query_identifier_is_absent_from_agent_response_and_generated_surfaces(tmp_path: Path):
    sensitive = "Patient name: Priya Sharma; Email: synthetic.patient@example.org"
    run = AgentLoop(generated_root=tmp_path).run(
        query=sensitive,
        uploads={},
        clinical_case_intake=_clinical_case(),
    )
    serialized = json.dumps(run)
    assert sensitive not in serialized
    assert "synthetic.patient@example.org" not in serialized
    assert run["final_state"]["query"] == "[REDACTED_DIRECT_IDENTIFIER]"
    assert any(item["category"] == "direct_identifier" for item in run["clinical_case_intake"]["policy_blocks"])
    for path in tmp_path.rglob("*"):
        if path.is_file():
            content = path.read_text(encoding="utf-8", errors="ignore")
            assert sensitive not in content
            assert "synthetic.patient@example.org" not in content


@pytest.mark.parametrize(
    "value",
    [
        "NM_000059.4:c.68_69delAG",
        "NC_000001.11:123456789:A:G",
        "HP:0001250",
        "PMID:12345678",
        "doi:10.1000/182",
        "chr1:123456789 A>G",
    ],
)
def test_scientific_query_text_is_preserved(value):
    assert sanitized_clinical_free_text(value, "query") == value


def test_compact_context_omits_corrections_negations_and_long_scientific_strings_whole():
    values = {
        "negated": "Seizures were suspected but are NOT present",
        "corrected": "Family affected; correction: family NOT affected",
        "translated": "Translated clinical wording " * 20,
        "hgvs": "NM_000059.4:c." + "1" * 100 + "del",
        "relationship": "Reported relationship wording " * 20,
        "laboratory": "Exact laboratory wording " * 20,
    }
    compact = build_compact_case_context({"case": values}, [f"case.{key}" for key in values], per_field_limit=30, total_limit=500)
    serialized = json.dumps(compact)
    assert "Family affected;" not in serialized
    assert "Seizures were suspected" not in serialized
    assert "NM_000059.4:c." not in serialized
    omitted = compact["__compact_context_metadata__"]["omitted_paths"]
    assert {item["path"] for item in omitted} == {f"case.{key}" for key in values}


def test_phone_shaped_assay_identifier_is_preserved_but_patient_phone_is_blocked():
    assay_path = "global_intake_context.laboratory_contexts.0.assay_or_sequencing_method_exact"
    assert detect_direct_identifiers("1234-5678-9012", assay_path) == []
    assert "phone_number" in detect_direct_identifiers("Patient phone: +91 98765 43210", assay_path)
    assert "phone_number" in detect_direct_identifiers(
        "Patient contact phone: +91 98765 43210",
        "global_intake_context.language_context.original_text",
    )


def test_explicit_phone_in_provider_assay_field_is_rejected_and_not_cached():
    calls = []
    records = [{"assay_or_sequencing_method_exact": "Patient phone: +91 98765 43210"}]
    runtime = BYOKRuntime(
        transport=lambda *_args: calls.append(1) or _success_with_usage(10, 5, records),
        resolver=_resolver([PUBLIC_IP]),
    )
    session_id = runtime.configure(_external_config(budget=BYOKBudget(max_calls=2, max_total_tokens=10_000))).session_id
    assert runtime.execute(session_id, _request()).status == "output_policy_blocked"
    assert runtime.execute(session_id, _request()).status == "output_policy_blocked"
    assert len(calls) == 2


@pytest.mark.parametrize(
    "text",
    [
        "Diagnosis: Marfan syndrome",
        "Treatment: start drug X",
        "The variant is pathogenic",
        "Final assessment: pathogenic",
        "ACMG classification is pathogenic",
        "The clinician approved this conclusion",
        "Recurrence risk is 25 percent",
        "Penetrance is 80 percent",
        "Candidate note: Diagnosis: Marfan syndrome",
        "For expert review, Treatment: start drug X",
    ],
)
def test_provider_authority_text_is_rejected_inside_nested_generic_fields(text):
    runtime = BYOKRuntime(
        transport=lambda *_args: _success_with_usage(10, 5, [{"nested": {"note": text}}]),
        resolver=_resolver([PUBLIC_IP]),
    )
    session_id = runtime.configure(_external_config()).session_id
    result = runtime.execute(session_id, _request())
    assert result.status == "output_policy_blocked"
    assert result.response is None


@pytest.mark.parametrize(
    "text",
    [
        "The literature discusses treatment X for expert review",
        "A pathogenic ClinVar assertion was retrieved from source Y",
        "Candidate ACMG criterion proposed_not_approved",
        "Clinical significance remains unresolved",
    ],
)
def test_provider_research_attribution_and_candidate_wording_remain_allowed(text):
    runtime = BYOKRuntime(
        transport=lambda *_args: _success_with_usage(10, 5, [{"nested": {"note": text}}]),
        resolver=_resolver([PUBLIC_IP]),
    )
    session_id = runtime.configure(_external_config()).session_id
    assert runtime.execute(session_id, _request()).status == "success"


def test_connection_reservation_blocks_workflow_that_would_exceed_shared_cost_ceiling():
    entered = threading.Event()
    release = threading.Event()
    methods = []

    def transport(_url, _headers, _body, _timeout, method):
        methods.append(method)
        if method == "GET":
            entered.set()
            assert release.wait(5)
            return b"{}"
        return _success_with_usage(1, 10)

    runtime = BYOKRuntime(transport=transport, resolver=_resolver([PUBLIC_IP]))
    session_id = runtime.configure(
        _external_config(
            output_cost_per_million_usd=Decimal("100000"),
            connection_test_cost_usd=Decimal("3.5"),
            budget=BYOKBudget(
                max_calls=1,
                max_input_tokens=1000,
                max_output_tokens=10,
                max_total_tokens=1010,
                estimated_cost_ceiling_usd=Decimal("4"),
                max_connection_tests=1,
            ),
        )
    ).session_id
    connection_results = []
    thread = threading.Thread(target=lambda: connection_results.append(runtime.test_connection(session_id)))
    thread.start()
    assert entered.wait(5)
    workflow = runtime.execute(session_id, _request(max_output_tokens=10))
    release.set()
    thread.join(5)
    assert workflow.status == "cost_limit_reached"
    assert methods == ["GET"]
    assert connection_results[0]["status"] == "success"
    assert runtime.status(session_id).estimated_cost_usd == Decimal("3.5")


def test_workflow_reservation_blocks_connection_that_would_exceed_shared_cost_ceiling():
    entered = threading.Event()
    release = threading.Event()
    methods = []

    def transport(_url, _headers, _body, _timeout, method):
        methods.append(method)
        if method == "POST":
            entered.set()
            assert release.wait(5)
            return _success_with_usage(1, 10)
        return b"{}"

    runtime = BYOKRuntime(transport=transport, resolver=_resolver([PUBLIC_IP]))
    session_id = runtime.configure(
        _external_config(
            output_cost_per_million_usd=Decimal("100000"),
            connection_test_cost_usd=Decimal("3.5"),
            budget=BYOKBudget(
                max_calls=1,
                max_input_tokens=1000,
                max_output_tokens=10,
                max_total_tokens=1010,
                estimated_cost_ceiling_usd=Decimal("4"),
                max_connection_tests=1,
            ),
        )
    ).session_id
    workflow_results = []
    thread = threading.Thread(target=lambda: workflow_results.append(runtime.execute(session_id, _request(max_output_tokens=10))))
    thread.start()
    assert entered.wait(5)
    connection = runtime.test_connection(session_id)
    release.set()
    thread.join(5)
    assert connection["status"] == "connection_test_limit_reached"
    assert methods == ["POST"]
    assert workflow_results[0].status == "success"
    assert runtime.status(session_id).estimated_cost_usd == Decimal("1")


def test_forget_during_output_policy_prevents_stale_settlement_and_terminal_mutation(monkeypatch):
    entered = threading.Event()
    release = threading.Event()

    def delayed_policy(*_args):
        entered.set()
        assert release.wait(5)
        return True

    runtime = BYOKRuntime(
        transport=lambda *_args: _success_with_usage(10, 5, [{"note": "bounded"}]),
        resolver=_resolver([PUBLIC_IP]),
    )
    session_id = runtime.configure(_external_config()).session_id
    detached = runtime._sessions[session_id]
    monkeypatch.setattr(byok_runtime_module, "_provider_output_policy_violation", delayed_policy)
    results = []
    thread = threading.Thread(target=lambda: results.append(runtime.execute(session_id, _request())))
    thread.start()
    assert entered.wait(5)
    assert runtime.forget(session_id) is True
    cleared_state = (
        detached.provider_attempt_count,
        detached.input_tokens,
        detached.output_tokens,
        detached.estimated_cost,
        detached.failure_count,
        len(detached.usage),
        len(detached.cache),
    )
    release.set()
    thread.join(5)
    assert results[0].status == "session_invalidated"
    assert results[0].response is None
    assert (
        detached.provider_attempt_count,
        detached.input_tokens,
        detached.output_tokens,
        detached.estimated_cost,
        detached.failure_count,
        len(detached.usage),
        len(detached.cache),
    ) == cleared_state


def test_camel_case_artifact_credentials_are_redacted_without_over_redacting_science(tmp_path: Path):
    run_dir = tmp_path / "RUN-CAMEL" / "reproducibility"
    run_dir.mkdir(parents=True)
    path = run_dir / "guardrail_decisions.json"
    path.write_text(
        json.dumps(
            {
                "apiKey": SECRET,
                "clientSecret": SECRET,
                "accessToken": SECRET,
                "authorizationHeader": SECRET,
                "privateKey": SECRET,
                "variant_key": "BRCA1:NM_000059.4",
            }
        ),
        encoding="utf-8",
    )
    content = WorkbenchRunStore(tmp_path).read_artifact("RUN-CAMEL", "reproducibility/guardrail_decisions.json").content
    for key in ("apiKey", "clientSecret", "accessToken", "authorizationHeader", "privateKey"):
        assert content[key] == "[REDACTED]"
    assert content["variant_key"] == "BRCA1:NM_000059.4"
