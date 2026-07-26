from __future__ import annotations

import hashlib
import http.client
import ipaddress
import json
import math
import re
import secrets
import socket
import ssl
import threading
import time
import urllib.error
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any, Callable, Literal
from urllib.parse import SplitResult, urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, field_validator, model_serializer

from app.insilicopop.clinical.validation import contains_direct_identifier


BYOK_SCHEMA_VERSION = "0.31.1"
BYOK_POLICY_VERSION = "v0.31.1-research-curation-security-1"
COMPACT_CONTEXT_SCHEMA_VERSION = "0.31.1"
DEFAULT_COMPACT_FIELD_LIMIT = 4_000
DEFAULT_COMPACT_TOTAL_LIMIT = 16_000
MAX_PROVIDER_RESPONSE_BYTES = 2_000_000
MAX_REPORTED_TOKENS = 10_000_000
MAX_USAGE_HISTORY = 128
ZERO_COST = Decimal("0")
_OMITTED = object()
METADATA_HOSTNAMES = {
    "169.254.169.254",
    "metadata.google.internal",
    "metadata.azure.internal",
    "instance-data.ec2.internal",
}
TRANSIENT_HTTP_STATUSES = {408, 429, 500, 502, 503, 504}


class ProviderType(str, Enum):
    MOCK = "mock"
    OPENAI_COMPATIBLE = "openai_compatible"


class ModelRole(str, Enum):
    EXTRACTION = "extraction"
    CLASSIFICATION = "classification"
    SYNTHESIS = "synthesis"
    CRITICISM = "criticism"


class BYOKBudget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_calls: int = Field(default=4, ge=0, le=50)
    max_input_tokens: int = Field(default=12000, ge=0, le=1_000_000)
    max_output_tokens: int = Field(default=2000, ge=0, le=100_000)
    max_total_tokens: int = Field(default=14000, ge=0, le=1_100_000)
    estimated_cost_ceiling_usd: Decimal = Field(default=Decimal("1.0"), ge=0, le=10_000)
    max_concurrent_calls: int = Field(default=1, ge=1, le=8)
    max_retries: int = Field(default=1, ge=0, le=2)
    max_connection_tests: int = Field(default=2, ge=0, le=10)
    max_concurrent_connection_tests: int = Field(default=1, ge=1, le=4)


class BYOKSessionConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    # Accepted for v0.31 request compatibility, but never trusted or used as the
    # capability. BYOKRuntime always generates the effective session identifier.
    session_id: str | None = Field(default=None, min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    provider: ProviderType = ProviderType.MOCK
    model: str = Field(default="mock", min_length=1, max_length=160)
    base_url: str | None = Field(default=None, max_length=500)
    api_key: SecretStr = Field(default_factory=lambda: SecretStr(""))
    role_models: dict[ModelRole, str] = Field(default_factory=dict)
    budget: BYOKBudget = Field(default_factory=BYOKBudget)
    input_cost_per_million_usd: Decimal = Field(default=ZERO_COST, ge=0, le=100_000)
    output_cost_per_million_usd: Decimal = Field(default=ZERO_COST, ge=0, le=100_000)
    connection_test_cost_usd: Decimal = Field(default=ZERO_COST, ge=0, le=100)

    @model_serializer(mode="wrap")
    def serialize_without_secret(self, handler):
        data = handler(self)
        data.pop("api_key", None)
        return data

    @field_validator("base_url")
    @classmethod
    def validate_base_url_syntax(cls, value: str | None) -> str | None:
        if value is None:
            return None
        _parse_endpoint(value)
        return value.rstrip("/")

    @field_validator("role_models")
    @classmethod
    def validate_role_models(cls, value: dict[ModelRole, str]) -> dict[ModelRole, str]:
        for model in value.values():
            if not model or len(model) > 160:
                raise ValueError("Role model names must contain between 1 and 160 characters.")
        return value


class EvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str | None = Field(default=None, max_length=160)
    claim_id: str | None = Field(default=None, max_length=160)
    content: dict[str, Any] | str
    provenance_references: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("content")
    @classmethod
    def bound_content(cls, value: dict[str, Any] | str) -> dict[str, Any] | str:
        if len(_normalized_json(value)) > DEFAULT_COMPACT_TOTAL_LIMIT:
            raise ValueError("Evidence content exceeds the bounded serialized size.")
        return value


class BoundedLLMRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    role: ModelRole
    task: str = Field(min_length=1, max_length=500)
    compact_context: dict[str, Any] = Field(default_factory=dict)
    evidence: list[EvidenceItem] = Field(default_factory=list, max_length=200)
    max_output_tokens: int = Field(default=512, ge=1, le=100_000)
    schema_version: str = Field(default=BYOK_SCHEMA_VERSION, min_length=1, max_length=40)
    policy_version: str = Field(default=BYOK_POLICY_VERSION, min_length=1, max_length=80)

    @field_validator("compact_context")
    @classmethod
    def bound_compact_context(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(_normalized_json(value)) > DEFAULT_COMPACT_TOTAL_LIMIT + 4_000:
            raise ValueError("Compact context exceeds the bounded serialized size.")
        return value


class BoundedStructuredResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["success", "refusal"]
    records: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    warnings: list[str] = Field(default_factory=list, max_length=50)


class BYOKAttemptRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    attempt_number: int
    call_type: Literal["mock_workflow", "scientific_workflow", "connection_test"]
    status: str
    transient: bool = False
    http_status: int | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    reported_input_tokens: int | None = None
    reported_output_tokens: int | None = None
    estimated_cost_usd: Decimal = ZERO_COST
    latency_ms: int = 0


class BYOKUsageRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str
    model: str
    role: str
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: Decimal = ZERO_COST
    latency_ms: int = 0
    cache_hit: bool = False
    retry_count: int = 0
    attempt_count: int = 0
    attempt_history: list[BYOKAttemptRecord] = Field(default_factory=list)
    status: Literal[
        "success",
        "failure",
        "refusal",
        "budget_exhausted",
        "call_limit_reached",
        "token_limit_reached",
        "cost_limit_reached",
        "provider_unavailable",
        "policy_blocked",
        "session_invalidated",
        "output_policy_blocked",
    ]


class BYOKExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: str
    response: BoundedStructuredResponse | None = None
    usage: BYOKUsageRecord
    message: str


class BYOKPublicStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["0.31.1"] = BYOK_SCHEMA_VERSION
    policy_version: str = BYOK_POLICY_VERSION
    configured: bool
    provider: str
    model: str
    resolved_role_models: dict[str, str]
    key_present_in_memory: bool
    base_url_configured: bool
    budget: BYOKBudget
    request_count: int
    logical_request_count: int
    provider_attempt_count: int
    workflow_provider_attempt_count: int
    connection_test_attempt_count: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    estimated_cost_usd: Decimal
    remaining_calls: int
    remaining_total_tokens: int
    remaining_estimated_cost_usd: Decimal
    active_calls: int
    reserved_calls: int
    reserved_input_tokens: int
    reserved_output_tokens: int
    reserved_estimated_cost_usd: Decimal
    external_call_made: bool
    external_workflow_call_made: bool
    cache_hit_count: int
    success_count: int
    failure_count: int
    refusal_count: int
    cancellation_count: int
    retry_count: int
    connection_test_request_count: int
    connection_test_success_count: int
    connection_test_failure_count: int
    remaining_connection_tests: int
    active_connection_tests: int
    reserved_connection_tests: int
    usage: list[BYOKUsageRecord]


class BYOKSessionStatus(BYOKPublicStatus):
    session_id: str
    idle_expires_in_seconds: int
    absolute_expires_in_seconds: int


Transport = Callable[[str, dict[str, str], bytes | None, int, str], bytes]
Resolver = Callable[[str, int], list[str]]


@dataclass
class _Reservation:
    input_tokens: int
    output_tokens: int
    estimated_cost: Decimal


@dataclass
class _ExecutionLease:
    session_id: str
    generation: int
    lease_id: str
    workflow: bool
    cancelled: bool = False


@dataclass
class _Session:
    provider: ProviderType
    model: str
    base_url: str | None
    api_key: str | None = field(repr=False)
    role_models: dict[ModelRole, str]
    budget: BYOKBudget
    input_cost: Decimal
    output_cost: Decimal
    connection_test_cost: Decimal
    created_at: float
    last_accessed_at: float
    generation: int = field(default_factory=lambda: secrets.randbits(64))
    valid: bool = True
    logical_request_count: int = 0
    provider_attempt_count: int = 0
    workflow_provider_attempt_count: int = 0
    connection_test_attempt_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost: Decimal = ZERO_COST
    active_calls: int = 0
    reserved_calls: int = 0
    reserved_input_tokens: int = 0
    reserved_output_tokens: int = 0
    reserved_cost: Decimal = ZERO_COST
    connection_test_request_count: int = 0
    connection_test_success_count: int = 0
    connection_test_failure_count: int = 0
    active_connection_tests: int = 0
    reserved_connection_tests: int = 0
    reserved_connection_cost: Decimal = ZERO_COST
    cache_hit_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    refusal_count: int = 0
    cancellation_count: int = 0
    retry_count: int = 0
    external_call_made: bool = False
    external_workflow_call_made: bool = False
    usage: list[BYOKUsageRecord] = field(default_factory=list)
    cache: dict[str, BoundedStructuredResponse] = field(default_factory=dict)
    leases: dict[str, _ExecutionLease] = field(default_factory=dict)


class _ProviderHTTPError(OSError):
    def __init__(self, status: int, *, redirect: bool = False) -> None:
        super().__init__("Provider returned a non-success response.")
        self.status = status
        self.redirect = redirect


class _UnsafeDestinationError(ValueError):
    pass


class _AttemptBudgetError(RuntimeError):
    def __init__(self, status: str) -> None:
        super().__init__("Configured BYOK budget prevented the provider attempt.")
        self.status = status


class _SessionInvalidatedError(RuntimeError):
    pass


class BYOKRuntime:
    """Session-memory-only provider configuration and bounded structured calls."""

    def __init__(
        self,
        transport: Transport | None = None,
        *,
        resolver: Resolver | None = None,
        allow_development_localhost: bool = False,
        idle_ttl_seconds: int = 30 * 60,
        absolute_ttl_seconds: int = 8 * 60 * 60,
        max_sessions: int = 64,
        time_source: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if idle_ttl_seconds < 1 or absolute_ttl_seconds < 1 or max_sessions < 1:
            raise ValueError("BYOK session bounds must be positive.")
        self._sessions: dict[str, _Session] = {}
        self._resolver = resolver or _default_resolver
        self._allow_development_localhost = allow_development_localhost
        self._custom_transport = transport
        self._idle_ttl_seconds = idle_ttl_seconds
        self._absolute_ttl_seconds = absolute_ttl_seconds
        self._max_sessions = max_sessions
        self._time = time_source
        self._sleep = sleeper
        self._lock = threading.RLock()

    def configure(self, config: BYOKSessionConfiguration) -> BYOKSessionStatus:
        if config.provider == ProviderType.OPENAI_COMPATIBLE:
            if not config.api_key.get_secret_value():
                raise ValueError("An API key is required for an OpenAI-compatible BYOK session.")
            if not config.base_url:
                raise ValueError("A base URL is required for an OpenAI-compatible BYOK session.")
            _validate_static_destination(config.base_url, self._allow_development_localhost)
        now = self._time()
        session_id = secrets.token_urlsafe(32)
        secret = config.api_key.get_secret_value() or None if config.provider == ProviderType.OPENAI_COMPATIBLE else None
        with self._lock:
            self._evict_expired_locked(now)
            self._make_capacity_locked()
            self._sessions[session_id] = _Session(
                provider=config.provider,
                model=config.model,
                base_url=config.base_url,
                api_key=secret,
                role_models=dict(config.role_models),
                budget=config.budget,
                input_cost=config.input_cost_per_million_usd,
                output_cost=config.output_cost_per_million_usd,
                connection_test_cost=config.connection_test_cost_usd,
                created_at=now,
                last_accessed_at=now,
            )
            return self._session_status_locked(session_id, self._sessions[session_id], now)

    def status(self, session_id: str) -> BYOKSessionStatus:
        with self._lock:
            session = self._require_session_locked(session_id)
            return self._session_status_locked(session_id, session, self._time())

    def public_provenance(self, session_id: str) -> dict[str, Any]:
        with self._lock:
            session = self._require_session_locked(session_id)
            return _public_status(session).model_dump()

    def forget(self, session_id: str) -> bool:
        with self._lock:
            self._evict_expired_locked(self._time())
            session = self._sessions.get(session_id)
            if session is None:
                return False
            self._invalidate_session_locked(session_id, session)
            return True

    def test_connection(self, session_id: str) -> dict[str, Any]:
        with self._lock:
            session = self._require_session_locked(session_id)
            session.connection_test_request_count += 1
            provider = session.provider.value
            model = session.model
            if session.provider == ProviderType.MOCK:
                return {
                    "status": "success",
                    "provider": "mock",
                    "model": session.model,
                    "call_type": "connection_test",
                    "external_call_made": False,
                }
            lease = self._acquire_lease_locked(session_id, session, workflow=False)
            try:
                self._reserve_connection_test_locked(session_id, session, lease)
            except _AttemptBudgetError:
                self._release_lease_locked(session, lease)
                return {
                    "status": "connection_test_limit_reached",
                    "provider": provider,
                    "model": model,
                    "call_type": "connection_test",
                    "external_call_made": False,
                    "message": "Configured connection-test allowance prevented the attempt.",
                }
        transport_attempted = False
        try:
            with self._lock:
                url, headers = self._authorized_request_locked(session_id, session, lease, connection_test=True)
            validate_provider_destination(url, self._resolver, self._allow_development_localhost)
            transport_attempted = True
            self._invoke_transport(
                url,
                headers,
                None,
                15,
                "GET",
                authorizer=lambda: self._assert_lease_current(session_id, session, lease),
            )
            with self._lock:
                self._assert_lease_current_locked(session_id, session, lease)
                self._settle_connection_test_locked(session, success=True)
            return {
                "status": "success",
                "provider": provider,
                "model": model,
                "call_type": "connection_test",
                "external_call_made": True,
            }
        except _SessionInvalidatedError:
            with self._lock:
                self._release_connection_test_locked(session)
            return {
                "status": "session_invalidated",
                "provider": provider,
                "model": model,
                "call_type": "connection_test",
                "external_call_made": False,
                "message": "The in-memory BYOK session is no longer active.",
            }
        except Exception:
            with self._lock:
                if self._lease_is_current_locked(session_id, session, lease) and transport_attempted:
                    self._settle_connection_test_locked(session, success=False)
                else:
                    self._release_connection_test_locked(session)
            return {
                "status": "connection_test_failed",
                "provider": provider,
                "model": model,
                "call_type": "connection_test",
                "external_call_made": transport_attempted,
                "message": "Connection test failed. Check the endpoint, model, key, and network availability.",
            }
        finally:
            with self._lock:
                self._release_lease_locked(session, lease)

    def execute(self, session_id: str, request: BoundedLLMRequest) -> BYOKExecutionResult:
        request = request.model_copy(update={"evidence": deduplicate_evidence(request.evidence)})
        policy_match = contains_direct_identifier(request.model_dump(mode="json"))
        with self._lock:
            session = self._require_session_locked(session_id)
            session.logical_request_count += 1
            model = session.role_models.get(request.role, session.model)
            if policy_match:
                return self._record_terminal(session, model, request.role, "policy_blocked", "Request was blocked by direct-identifier controls.")
            cache_key = request_cache_key(session.provider.value, model, request)
            cached = session.cache.get(cache_key)
            if cached is not None:
                usage = BYOKUsageRecord(provider=session.provider.value, model=model, role=request.role.value, cache_hit=True, status="success")
                session.cache_hit_count += 1
                session.success_count += 1
                self._append_usage_locked(session, usage)
                return BYOKExecutionResult(status="success", response=cached, usage=usage, message="Structured response served from session-memory cache.")
            if session.active_calls >= session.budget.max_concurrent_calls:
                return self._record_terminal(session, model, request.role, "budget_exhausted", "Configured concurrency limit is in use.")
            session.active_calls += 1
            lease = self._acquire_lease_locked(session_id, session, workflow=True)
        started = time.monotonic()
        try:
            if session.provider == ProviderType.MOCK:
                return self._execute_mock(session_id, session, lease, model, request, cache_key, started)
            return self._execute_external(session_id, session, lease, model, request, cache_key, started)
        finally:
            with self._lock:
                self._release_lease_locked(session, lease)

    def _execute_mock(
        self,
        session_id: str,
        session: _Session,
        lease: _ExecutionLease,
        model: str,
        request: BoundedLLMRequest,
        cache_key: str,
        started: float,
    ) -> BYOKExecutionResult:
        input_tokens = estimate_tokens(request.model_dump(mode="json"))
        try:
            reservation = self._reserve_attempt(session_id, session, lease, input_tokens, request.max_output_tokens)
        except _AttemptBudgetError as exc:
            return self._terminal_from_attempts(
                session_id,
                session,
                lease,
                model,
                request.role,
                exc.status,
                [],
                started,
                "Configured BYOK budget prevented the call.",
            )
        except _SessionInvalidatedError:
            return self._invalidated_result(session, model, request.role)
        response = BoundedStructuredResponse(status="success", records=[], warnings=["mock_provider_no_external_call"])
        output_tokens = estimate_tokens(response.model_dump(mode="json"))
        if output_tokens > reservation.output_tokens:
            attempt = self._settle_attempt(
                session_id,
                session,
                lease,
                reservation,
                reservation.input_tokens,
                reservation.output_tokens,
                "mock_usage_exceeded_reservation",
                "mock_workflow",
                0,
                reported_output_tokens=output_tokens,
            )
            return self._terminal_from_attempts(
                session_id,
                session,
                lease,
                model,
                request.role,
                "provider_unavailable",
                [attempt],
                started,
                "Mock response exceeded the reserved hard limit.",
            )
        attempt = self._settle_attempt(session_id, session, lease, reservation, reservation.input_tokens, output_tokens, "mock_success", "mock_workflow", 0)
        usage = _usage_from_attempts(session, model, request.role, "success", [attempt], started)
        with self._lock:
            self._assert_lease_current_locked(session_id, session, lease)
            session.success_count += 1
            self._append_usage_locked(session, usage, session_id=session_id, lease=lease)
            self._store_cache_locked(session_id, session, lease, cache_key, response)
        return BYOKExecutionResult(status="success", response=response, usage=usage, message="Bounded mock response validated.")

    def _execute_external(
        self,
        session_id: str,
        session: _Session,
        lease: _ExecutionLease,
        model: str,
        request: BoundedLLMRequest,
        cache_key: str,
        started: float,
    ) -> BYOKExecutionResult:
        input_tokens = estimate_tokens(request.model_dump(mode="json"))
        attempts: list[BYOKAttemptRecord] = []
        malformed_repair_used = False
        while True:
            try:
                with self._lock:
                    self._assert_lease_current_locked(session_id, session, lease)
                    url, headers = self._authorized_request_locked(session_id, session, lease, connection_test=False)
                validate_provider_destination(url, self._resolver, self._allow_development_localhost)
                reservation = self._reserve_attempt(session_id, session, lease, input_tokens, request.max_output_tokens)
                if attempts:
                    with self._lock:
                        self._assert_lease_current_locked(session_id, session, lease)
                        session.retry_count += 1
            except _AttemptBudgetError as exc:
                return self._terminal_from_attempts(session_id, session, lease, model, request.role, exc.status, attempts, started, "Configured BYOK budget prevented the provider attempt.")
            except _SessionInvalidatedError:
                return self._invalidated_result(session, model, request.role, attempts, started)
            except (OSError, ValueError):
                return self._terminal_from_attempts(session_id, session, lease, model, request.role, "provider_unavailable", attempts, started, "Provider destination validation failed safely.")
            attempt_started = time.monotonic()
            try:
                payload = _provider_payload(model, request, reservation.output_tokens)
                with self._lock:
                    self._assert_lease_current_locked(session_id, session, lease)
                    session.external_call_made = True
                    session.external_workflow_call_made = True
                raw = self._invoke_transport(
                    url,
                    headers,
                    json.dumps(payload, sort_keys=True).encode("utf-8"),
                    30,
                    "POST",
                    authorizer=lambda: self._assert_lease_current(session_id, session, lease),
                )
                with self._lock:
                    self._assert_lease_current_locked(session_id, session, lease)
                content, reported_input, reported_output = _extract_structured_content(raw)
                actual_input = reported_input if reported_input is not None else input_tokens
                actual_output = reported_output if reported_output is not None else estimate_tokens(content)
                if actual_input > reservation.input_tokens or actual_output > reservation.output_tokens:
                    attempt = self._settle_attempt(
                        session_id,
                        session,
                        lease,
                        reservation,
                        min(actual_input, reservation.input_tokens),
                        min(actual_output, reservation.output_tokens),
                        "provider_usage_exceeded_reservation",
                        "scientific_workflow",
                        int((time.monotonic() - attempt_started) * 1000),
                        reported_input_tokens=reported_input,
                        reported_output_tokens=reported_output,
                    )
                    attempts.append(attempt)
                    return self._terminal_from_attempts(session_id, session, lease, model, request.role, "provider_unavailable", attempts, started, "Provider usage exceeded the reserved hard limit; response was rejected.")
                response = BoundedStructuredResponse.model_validate(content)
                if _provider_output_policy_violation(response, request):
                    attempt = self._settle_attempt(
                        session_id,
                        session,
                        lease,
                        reservation,
                        actual_input,
                        actual_output,
                        "output_policy_blocked",
                        "scientific_workflow",
                        int((time.monotonic() - attempt_started) * 1000),
                        reported_input_tokens=reported_input,
                        reported_output_tokens=reported_output,
                    )
                    attempts.append(attempt)
                    return self._terminal_from_attempts(
                        session_id,
                        session,
                        lease,
                        model,
                        request.role,
                        "output_policy_blocked",
                        attempts,
                        started,
                        "Provider output was rejected by bounded privacy, clinical-policy, or provenance controls.",
                    )
                attempt = self._settle_attempt(
                    session_id,
                    session,
                    lease,
                    reservation,
                    actual_input,
                    actual_output,
                    "refusal" if response.status == "refusal" else "success",
                    "scientific_workflow",
                    int((time.monotonic() - attempt_started) * 1000),
                    reported_input_tokens=reported_input,
                    reported_output_tokens=reported_output,
                )
                attempts.append(attempt)
                status = "refusal" if response.status == "refusal" else "success"
                usage = _usage_from_attempts(session, model, request.role, status, attempts, started)
                with self._lock:
                    self._assert_lease_current_locked(session_id, session, lease)
                    if status == "success":
                        session.success_count += 1
                    else:
                        session.refusal_count += 1
                    self._append_usage_locked(session, usage, session_id=session_id, lease=lease)
                    if response.status == "success":
                        self._store_cache_locked(session_id, session, lease, cache_key, response)
                return BYOKExecutionResult(status=status, response=response, usage=usage, message="Bounded structured response validated.")
            except _SessionInvalidatedError:
                with self._lock:
                    self._release_reservation_locked(session, reservation)
                return self._invalidated_result(session, model, request.role, attempts, started)
            except (ValidationError, ValueError, json.JSONDecodeError):
                with self._lock:
                    if not self._lease_is_current_locked(session_id, session, lease):
                        self._release_reservation_locked(session, reservation)
                        return self._invalidated_result(session, model, request.role, attempts, started)
                attempt = self._settle_attempt(session_id, session, lease, reservation, reservation.input_tokens, 0, "malformed_response", "scientific_workflow", int((time.monotonic() - attempt_started) * 1000))
                attempts.append(attempt)
                if malformed_repair_used or len(attempts) > session.budget.max_retries:
                    return self._terminal_from_attempts(session_id, session, lease, model, request.role, "provider_unavailable", attempts, started, "Provider response failed bounded structured validation.")
                malformed_repair_used = True
            except Exception as exc:
                with self._lock:
                    if not self._lease_is_current_locked(session_id, session, lease):
                        self._release_reservation_locked(session, reservation)
                        return self._invalidated_result(session, model, request.role, attempts, started)
                status_code, transient = _classify_provider_failure(exc)
                attempt = self._settle_attempt(
                    session_id,
                    session,
                    lease,
                    reservation,
                    reservation.input_tokens,
                    0,
                    "transient_failure" if transient else "permanent_failure",
                    "scientific_workflow",
                    int((time.monotonic() - attempt_started) * 1000),
                    http_status=status_code,
                    transient=transient,
                )
                attempts.append(attempt)
                if not transient or len(attempts) > session.budget.max_retries:
                    return self._terminal_from_attempts(session_id, session, lease, model, request.role, "provider_unavailable", attempts, started, "Provider request failed without exposing provider or credential details.")
            except BaseException:
                with self._lock:
                    if self._lease_is_current_locked(session_id, session, lease):
                        self._settle_attempt(
                            session_id,
                            session,
                            lease,
                            reservation,
                            reservation.input_tokens,
                            0,
                            "cancelled",
                            "scientific_workflow",
                            int((time.monotonic() - attempt_started) * 1000),
                        )
                        session.cancellation_count += 1
                    else:
                        self._release_reservation_locked(session, reservation)
                raise
            with self._lock:
                if not self._lease_is_current_locked(session_id, session, lease):
                    return self._invalidated_result(session, model, request.role, attempts, started)
            self._sleep(min(0.2, 0.05 * (2 ** max(0, len(attempts) - 1))))
            with self._lock:
                if not self._lease_is_current_locked(session_id, session, lease):
                    return self._invalidated_result(session, model, request.role, attempts, started)

    def _reserve_attempt(
        self,
        session_id: str,
        session: _Session,
        lease: _ExecutionLease,
        input_tokens: int,
        desired_output_tokens: int,
    ) -> _Reservation:
        with self._lock:
            self._assert_lease_current_locked(session_id, session, lease)
            budget = session.budget
            committed_and_reserved_calls = session.provider_attempt_count + session.reserved_calls
            if committed_and_reserved_calls >= budget.max_calls:
                raise _AttemptBudgetError("call_limit_reached")
            available_output = budget.max_output_tokens - session.output_tokens - session.reserved_output_tokens
            output_tokens = min(desired_output_tokens, available_output)
            if output_tokens < 1:
                raise _AttemptBudgetError("token_limit_reached")
            if session.input_tokens + session.reserved_input_tokens + input_tokens > budget.max_input_tokens:
                raise _AttemptBudgetError("token_limit_reached")
            projected_total = (
                session.input_tokens
                + session.output_tokens
                + session.reserved_input_tokens
                + session.reserved_output_tokens
                + input_tokens
                + output_tokens
            )
            if projected_total > budget.max_total_tokens:
                raise _AttemptBudgetError("token_limit_reached")
            cost = _estimated_cost(session, input_tokens, output_tokens)
            if _projected_estimated_cost(session, cost) > budget.estimated_cost_ceiling_usd:
                raise _AttemptBudgetError("cost_limit_reached")
            session.reserved_calls += 1
            session.reserved_input_tokens += input_tokens
            session.reserved_output_tokens += output_tokens
            session.reserved_cost += cost
            return _Reservation(input_tokens=input_tokens, output_tokens=output_tokens, estimated_cost=cost)

    def _settle_attempt(
        self,
        session_id: str,
        session: _Session,
        lease: _ExecutionLease,
        reservation: _Reservation,
        input_tokens: int,
        output_tokens: int,
        status: str,
        call_type: Literal["mock_workflow", "scientific_workflow", "connection_test"],
        latency_ms: int,
        *,
        http_status: int | None = None,
        transient: bool = False,
        reported_input_tokens: int | None = None,
        reported_output_tokens: int | None = None,
    ) -> BYOKAttemptRecord:
        committed_input = min(max(0, input_tokens), reservation.input_tokens)
        committed_output = min(max(0, output_tokens), reservation.output_tokens)
        committed_cost = _estimated_cost(session, committed_input, committed_output)
        with self._lock:
            self._assert_lease_current_locked(session_id, session, lease)
            self._release_reservation_locked(session, reservation)
            session.provider_attempt_count += 1
            if call_type == "scientific_workflow":
                session.workflow_provider_attempt_count += 1
            session.input_tokens += committed_input
            session.output_tokens += committed_output
            session.estimated_cost += committed_cost
            attempt_number = session.provider_attempt_count
        return BYOKAttemptRecord(
            attempt_number=attempt_number,
            call_type=call_type,
            status=status,
            transient=transient,
            http_status=http_status,
            input_tokens=committed_input,
            output_tokens=committed_output,
            reported_input_tokens=reported_input_tokens,
            reported_output_tokens=reported_output_tokens,
            estimated_cost_usd=committed_cost,
            latency_ms=latency_ms,
        )

    def _terminal_from_attempts(
        self,
        session_id: str,
        session: _Session,
        lease: _ExecutionLease,
        model: str,
        role: ModelRole,
        status: str,
        attempts: list[BYOKAttemptRecord],
        started: float,
        message: str,
    ) -> BYOKExecutionResult:
        usage = _usage_from_attempts(session, model, role, status, attempts, started)
        with self._lock:
            if not self._lease_is_current_locked(session_id, session, lease):
                return self._invalidated_result(session, model, role, attempts, started)
            self._record_outcome_locked(session, status)
            self._append_usage_locked(session, usage, session_id=session_id, lease=lease)
        return BYOKExecutionResult(status=status, usage=usage, message=message)

    def _record_terminal(self, session: _Session, model: str, role: ModelRole, status: str, message: str) -> BYOKExecutionResult:
        usage = BYOKUsageRecord(provider=session.provider.value, model=model, role=role.value, status=status)  # type: ignore[arg-type]
        with self._lock:
            self._record_outcome_locked(session, status)
            self._append_usage_locked(session, usage)
        return BYOKExecutionResult(status=status, usage=usage, message=message)

    def _invalidated_result(
        self,
        session: _Session,
        model: str,
        role: ModelRole,
        attempts: list[BYOKAttemptRecord] | None = None,
        started: float | None = None,
    ) -> BYOKExecutionResult:
        attempt_items = attempts or []
        usage = _usage_from_attempts(session, model, role, "session_invalidated", attempt_items, started or time.monotonic())
        return BYOKExecutionResult(
            status="session_invalidated",
            usage=usage,
            message="The in-memory BYOK session was invalidated before the operation could be accepted.",
        )

    def _append_usage_locked(
        self,
        session: _Session,
        usage: BYOKUsageRecord,
        *,
        session_id: str | None = None,
        lease: _ExecutionLease | None = None,
    ) -> None:
        if session_id is not None and lease is not None:
            self._assert_lease_current_locked(session_id, session, lease)
        session.usage.append(usage)
        if len(session.usage) > MAX_USAGE_HISTORY:
            del session.usage[: len(session.usage) - MAX_USAGE_HISTORY]

    def _store_cache_locked(
        self,
        session_id: str,
        session: _Session,
        lease: _ExecutionLease,
        cache_key: str,
        response: BoundedStructuredResponse,
    ) -> None:
        self._assert_lease_current_locked(session_id, session, lease)
        session.cache[cache_key] = response

    def _record_outcome_locked(self, session: _Session, status: str) -> None:
        if status == "success":
            session.success_count += 1
        elif status == "refusal":
            session.refusal_count += 1
        elif status not in {"session_invalidated"}:
            session.failure_count += 1

    def _release_reservation_locked(self, session: _Session, reservation: _Reservation) -> None:
        session.reserved_calls = max(0, session.reserved_calls - 1)
        session.reserved_input_tokens = max(0, session.reserved_input_tokens - reservation.input_tokens)
        session.reserved_output_tokens = max(0, session.reserved_output_tokens - reservation.output_tokens)
        session.reserved_cost = max(ZERO_COST, session.reserved_cost - reservation.estimated_cost)

    def _acquire_lease_locked(self, session_id: str, session: _Session, *, workflow: bool) -> _ExecutionLease:
        if not self._session_is_current_locked(session_id, session):
            raise _SessionInvalidatedError("Session is not current.")
        lease = _ExecutionLease(
            session_id=session_id,
            generation=session.generation,
            lease_id=secrets.token_urlsafe(18),
            workflow=workflow,
        )
        session.leases[lease.lease_id] = lease
        return lease

    def _release_lease_locked(self, session: _Session, lease: _ExecutionLease) -> None:
        session.leases.pop(lease.lease_id, None)
        if lease.workflow:
            session.active_calls = max(0, session.active_calls - 1)

    def _lease_is_current_locked(self, session_id: str, session: _Session, lease: _ExecutionLease) -> bool:
        self._evict_expired_locked(self._time())
        return bool(
            session.valid
            and not lease.cancelled
            and session.generation == lease.generation
            and session.leases.get(lease.lease_id) is lease
            and self._sessions.get(session_id) is session
        )

    def _assert_lease_current_locked(self, session_id: str, session: _Session, lease: _ExecutionLease) -> None:
        if not self._lease_is_current_locked(session_id, session, lease):
            raise _SessionInvalidatedError("Session execution lease is no longer current.")

    def _assert_lease_current(self, session_id: str, session: _Session, lease: _ExecutionLease) -> None:
        with self._lock:
            self._assert_lease_current_locked(session_id, session, lease)

    def _authorized_request_locked(
        self,
        session_id: str,
        session: _Session,
        lease: _ExecutionLease,
        *,
        connection_test: bool,
    ) -> tuple[str, dict[str, str]]:
        self._assert_lease_current_locked(session_id, session, lease)
        if not session.api_key:
            raise _SessionInvalidatedError("Session key material is unavailable.")
        return _models_request(session) if connection_test else _chat_request(session)

    def _reserve_connection_test_locked(self, session_id: str, session: _Session, lease: _ExecutionLease) -> None:
        self._assert_lease_current_locked(session_id, session, lease)
        budget = session.budget
        if session.connection_test_attempt_count + session.reserved_connection_tests >= budget.max_connection_tests:
            raise _AttemptBudgetError("connection_test_limit_reached")
        if session.active_connection_tests >= budget.max_concurrent_connection_tests:
            raise _AttemptBudgetError("connection_test_limit_reached")
        projected_cost = _projected_estimated_cost(session, session.connection_test_cost)
        if projected_cost > budget.estimated_cost_ceiling_usd:
            raise _AttemptBudgetError("cost_limit_reached")
        session.reserved_connection_tests += 1
        session.active_connection_tests += 1
        session.reserved_connection_cost += session.connection_test_cost

    def _release_connection_test_locked(self, session: _Session) -> None:
        session.reserved_connection_tests = max(0, session.reserved_connection_tests - 1)
        session.active_connection_tests = max(0, session.active_connection_tests - 1)
        session.reserved_connection_cost = max(ZERO_COST, session.reserved_connection_cost - session.connection_test_cost)

    def _settle_connection_test_locked(self, session: _Session, *, success: bool) -> None:
        self._release_connection_test_locked(session)
        session.connection_test_attempt_count += 1
        session.external_call_made = True
        session.estimated_cost += session.connection_test_cost
        if success:
            session.connection_test_success_count += 1
        else:
            session.connection_test_failure_count += 1

    def _invalidate_session_locked(self, session_id: str, session: _Session) -> None:
        if not session.valid:
            return
        session.valid = False
        session.generation += 1
        for lease in session.leases.values():
            lease.cancelled = True
        if self._sessions.get(session_id) is session:
            self._sessions.pop(session_id, None)
        _clear_session(session)

    def _require_session_locked(self, session_id: str) -> _Session:
        now = self._time()
        self._evict_expired_locked(now)
        try:
            session = self._sessions[session_id]
        except KeyError as exc:
            raise KeyError("No active in-memory BYOK session is configured.") from exc
        session.last_accessed_at = now
        return session

    def _session_is_current_locked(self, session_id: str, session: _Session) -> bool:
        return session.valid and self._sessions.get(session_id) is session

    def _evict_expired_locked(self, now: float) -> None:
        expired = [
            session_id
            for session_id, session in self._sessions.items()
            if now - session.last_accessed_at >= self._idle_ttl_seconds or now - session.created_at >= self._absolute_ttl_seconds
        ]
        for session_id in expired:
            session = self._sessions.get(session_id)
            if session is not None:
                self._invalidate_session_locked(session_id, session)

    def _make_capacity_locked(self) -> None:
        if len(self._sessions) < self._max_sessions:
            return
        candidates = [(session.last_accessed_at, session_id) for session_id, session in self._sessions.items() if session.active_calls == 0]
        if not candidates:
            raise ValueError("The bounded BYOK session capacity is currently in use.")
        _, session_id = min(candidates)
        session = self._sessions[session_id]
        self._invalidate_session_locked(session_id, session)

    def _session_status_locked(self, session_id: str, session: _Session, now: float) -> BYOKSessionStatus:
        public = _public_status(session).model_dump()
        return BYOKSessionStatus(
            **public,
            session_id=session_id,
            idle_expires_in_seconds=max(0, math.ceil(self._idle_ttl_seconds - (now - session.last_accessed_at))),
            absolute_expires_in_seconds=max(0, math.ceil(self._absolute_ttl_seconds - (now - session.created_at))),
        )

    def _invoke_transport(
        self,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout: int,
        method: str,
        *,
        authorizer: Callable[[], None],
    ) -> bytes:
        if self._custom_transport is not None:
            authorizer()
            return self._custom_transport(url, headers, body, timeout, method)
        return _pinned_transport(
            url,
            headers,
            body,
            timeout,
            method,
            resolver=self._resolver,
            allow_development_localhost=self._allow_development_localhost,
            authorizer=authorizer,
        )


def build_compact_case_context(
    case: dict[str, Any],
    required_fields: list[str],
    *,
    per_field_limit: int = DEFAULT_COMPACT_FIELD_LIMIT,
    total_limit: int = DEFAULT_COMPACT_TOTAL_LIMIT,
) -> dict[str, Any]:
    """Select bounded required dotted paths with deterministic truncation metadata."""

    if per_field_limit < 1 or total_limit < per_field_limit:
        raise ValueError("Compact-context limits must be positive and total must cover one field.")
    compact: dict[str, Any] = {}
    truncated: list[dict[str, Any]] = []
    omitted: list[dict[str, Any]] = []
    for path in sorted(set(required_fields)):
        value: Any = case
        for part in path.split("."):
            if not isinstance(value, dict) or part not in value:
                value = None
                break
            value = value[part]
        if value is None:
            continue
        bounded, notes = _bound_value(value, path, per_field_limit)
        omitted.extend(notes)
        if bounded is _OMITTED:
            continue
        candidate = json.loads(json.dumps(compact))
        _set_dotted_path(candidate, path, bounded)
        if len(_normalized_json(candidate)) > total_limit:
            omitted.append({"path": path, "reason": "total_limit", "original_length": len(_normalized_json(value))})
            continue
        compact = candidate
    if truncated or omitted:
        compact["__compact_context_metadata__"] = {
            "schema_version": COMPACT_CONTEXT_SCHEMA_VERSION,
            "per_field_limit": per_field_limit,
            "total_limit": total_limit,
            "truncated_paths": truncated,
            "omitted_paths": omitted,
        }
    return compact


def deduplicate_evidence(items: list[EvidenceItem]) -> list[EvidenceItem]:
    """Merge exact stable-ID/content duplicates while preserving all provenance."""

    positions: dict[tuple[str, str, str | None], int] = {}
    deduplicated: list[EvidenceItem] = []
    for item in items:
        stable_id = item.source_id or item.claim_id or "unidentified"
        digest = hashlib.sha256(_normalized_json(item.content).encode("utf-8")).hexdigest()
        key = (stable_id, digest, item.claim_id)
        if key not in positions:
            positions[key] = len(deduplicated)
            deduplicated.append(item)
            continue
        index = positions[key]
        existing = deduplicated[index]
        merged = list(dict.fromkeys([*existing.provenance_references, *item.provenance_references]))
        if len(merged) > 50:
            # Preserve all source provenance by retaining another bounded item
            # rather than creating an invalid or lossy merged record.
            deduplicated.append(item)
            continue
        deduplicated[index] = existing.model_copy(update={"provenance_references": merged})
    return deduplicated


def request_cache_key(provider: str, model: str, request: BoundedLLMRequest) -> str:
    evidence_digest = hashlib.sha256(_normalized_json([item.model_dump(mode="json") for item in request.evidence]).encode("utf-8")).hexdigest()
    payload = {
        "provider": provider,
        "model": model,
        "request": request.model_dump(mode="json", exclude={"evidence"}),
        "schema_version": request.schema_version,
        "policy_version": request.policy_version,
        "evidence_digest": evidence_digest,
    }
    return hashlib.sha256(_normalized_json(payload).encode("utf-8")).hexdigest()


def estimate_tokens(value: Any) -> int:
    return max(1, math.ceil(len(_normalized_json(value).encode("utf-8")) / 4))


def validate_provider_destination(url: str, resolver: Resolver, allow_development_localhost: bool = False) -> tuple[SplitResult, list[str]]:
    parsed = _parse_endpoint(url)
    hostname = _normalized_hostname(parsed.hostname)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    local_requested = _is_localhost_name(hostname)
    if parsed.scheme != "https" and not (allow_development_localhost and parsed.scheme == "http" and local_requested):
        raise _UnsafeDestinationError("Remote BYOK endpoints require HTTPS.")
    if _is_metadata_hostname(hostname) or _is_internal_hostname(hostname):
        raise _UnsafeDestinationError("The provider destination is not a public network endpoint.")
    try:
        addresses = sorted(set(resolver(hostname, port)))
    except Exception as exc:
        raise _UnsafeDestinationError("The provider destination could not be safely resolved.") from exc
    if not addresses:
        raise _UnsafeDestinationError("The provider destination could not be safely resolved.")
    normalized_addresses: list[str] = []
    for raw_address in addresses:
        try:
            address = ipaddress.ip_address(raw_address.split("%", 1)[0])
        except ValueError as exc:
            raise _UnsafeDestinationError("The provider destination returned an invalid address.") from exc
        if allow_development_localhost and local_requested and address.is_loopback:
            normalized_addresses.append(str(address))
            continue
        if not _is_public_address(address):
            raise _UnsafeDestinationError("The provider destination resolved to a non-public address.")
        normalized_addresses.append(str(address))
    return parsed, normalized_addresses


def _public_status(session: _Session) -> BYOKPublicStatus:
    total = session.input_tokens + session.output_tokens
    resolved_roles = {role.value: session.role_models.get(role, session.model) for role in ModelRole}
    return BYOKPublicStatus(
        configured=True,
        provider=session.provider.value,
        model=session.model,
        resolved_role_models=resolved_roles,
        key_present_in_memory=bool(session.api_key),
        base_url_configured=bool(session.base_url),
        budget=session.budget,
        request_count=session.logical_request_count,
        logical_request_count=session.logical_request_count,
        provider_attempt_count=session.provider_attempt_count,
        workflow_provider_attempt_count=session.workflow_provider_attempt_count,
        connection_test_attempt_count=session.connection_test_attempt_count,
        input_tokens=session.input_tokens,
        output_tokens=session.output_tokens,
        total_tokens=total,
        estimated_cost_usd=session.estimated_cost,
        remaining_calls=max(0, session.budget.max_calls - session.provider_attempt_count - session.reserved_calls),
        remaining_total_tokens=max(0, session.budget.max_total_tokens - total - session.reserved_input_tokens - session.reserved_output_tokens),
        remaining_estimated_cost_usd=max(
            ZERO_COST,
            session.budget.estimated_cost_ceiling_usd
            - session.estimated_cost
            - session.reserved_cost
            - session.reserved_connection_cost,
        ),
        active_calls=session.active_calls,
        reserved_calls=session.reserved_calls,
        reserved_input_tokens=session.reserved_input_tokens,
        reserved_output_tokens=session.reserved_output_tokens,
        reserved_estimated_cost_usd=session.reserved_cost + session.reserved_connection_cost,
        external_call_made=session.external_call_made,
        external_workflow_call_made=session.external_workflow_call_made,
        cache_hit_count=session.cache_hit_count,
        success_count=session.success_count,
        failure_count=session.failure_count,
        refusal_count=session.refusal_count,
        cancellation_count=session.cancellation_count,
        retry_count=session.retry_count,
        connection_test_request_count=session.connection_test_request_count,
        connection_test_success_count=session.connection_test_success_count,
        connection_test_failure_count=session.connection_test_failure_count,
        remaining_connection_tests=max(
            0,
            session.budget.max_connection_tests
            - session.connection_test_attempt_count
            - session.reserved_connection_tests,
        ),
        active_connection_tests=session.active_connection_tests,
        reserved_connection_tests=session.reserved_connection_tests,
        usage=list(session.usage),
    )


def _usage_from_attempts(
    session: _Session,
    model: str,
    role: ModelRole,
    status: str,
    attempts: list[BYOKAttemptRecord],
    started: float,
) -> BYOKUsageRecord:
    return BYOKUsageRecord(
        provider=session.provider.value,
        model=model,
        role=role.value,
        input_tokens=sum(item.input_tokens for item in attempts),
        output_tokens=sum(item.output_tokens for item in attempts),
        estimated_cost_usd=sum((item.estimated_cost_usd for item in attempts), ZERO_COST),
        latency_ms=int((time.monotonic() - started) * 1000),
        retry_count=max(0, len(attempts) - 1),
        attempt_count=len(attempts),
        attempt_history=attempts,
        status=status,  # type: ignore[arg-type]
    )


def _estimated_cost(session: _Session, input_tokens: int, output_tokens: int) -> Decimal:
    return (
        Decimal(input_tokens) * session.input_cost
        + Decimal(output_tokens) * session.output_cost
    ) / Decimal(1_000_000)


def _projected_estimated_cost(session: _Session, requested_cost: Decimal) -> Decimal:
    """Authoritative shared ceiling projection for every external operation."""

    return session.estimated_cost + session.reserved_cost + session.reserved_connection_cost + requested_cost


def _provider_payload(model: str, request: BoundedLLMRequest, max_output_tokens: int) -> dict[str, Any]:
    system = (
        "Research-curation assistance only. Return only JSON with status ('success' or 'refusal'), "
        "records (maximum 100 objects), and warnings (maximum 50 strings). Do not diagnose, recommend treatment, "
        "make a final ACMG classification, infer identity or family relationships, or add unsupported facts."
    )
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": _normalized_json(request.model_dump(mode="json"))},
        ],
        "temperature": 0,
        "max_tokens": max_output_tokens,
        "response_format": {"type": "json_object"},
    }


def _extract_structured_content(raw: bytes) -> tuple[Any, int | None, int | None]:
    if len(raw) > MAX_PROVIDER_RESPONSE_BYTES:
        raise ValueError("Provider response exceeded the bounded response size.")
    payload = json.loads(raw.decode("utf-8"))
    usage = payload.get("usage") if isinstance(payload, dict) else None
    if usage is not None and not isinstance(usage, dict):
        raise ValueError("Provider usage was invalid.")
    input_tokens = _strict_token_count(usage.get("prompt_tokens"), "prompt_tokens") if usage is not None else None
    output_tokens = _strict_token_count(usage.get("completion_tokens"), "completion_tokens") if usage is not None else None
    if isinstance(payload, dict) and isinstance(payload.get("choices"), list) and payload["choices"]:
        choice = payload["choices"][0]
        content = choice.get("message", {}).get("content") if isinstance(choice, dict) else None
        if isinstance(content, str):
            parsed = json.loads(content)
            return parsed, input_tokens, output_tokens
    if isinstance(payload, dict) and "status" in payload:
        return payload, input_tokens, output_tokens
    raise ValueError("Unsupported structured response.")


def _strict_token_count(value: Any, field_name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"Provider {field_name} usage was invalid.")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and re.fullmatch(r"0|[1-9]\d*", value):
        parsed = int(value)
    else:
        raise ValueError(f"Provider {field_name} usage was invalid.")
    if parsed < 0 or parsed > MAX_REPORTED_TOKENS:
        raise ValueError(f"Provider {field_name} usage was outside bounded limits.")
    return parsed


def _provider_output_policy_violation(response: BoundedStructuredResponse, request: BoundedLLMRequest) -> bool:
    payload = response.model_dump(mode="json")
    if contains_direct_identifier(payload):
        return True
    allowed_provenance = {
        value
        for item in request.evidence
        for value in [item.source_id, item.claim_id, *item.provenance_references]
        if value
    }
    forbidden_keys = {
        "diagnosis",
        "treatment",
        "treatment_instruction",
        "treatment_recommendation",
        "final_diagnosis",
        "final_classification",
        "final_acmg_classification",
        "pathogenicity_conclusion",
        "human_approved",
        "approved_by_human",
        "reviewer_approved",
        "human_decision",
    }
    provenance_keys = {
        "source_id",
        "source_ids",
        "claim_id",
        "claim_ids",
        "provenance_source_id",
        "provenance_source_ids",
        "provenance_reference",
        "provenance_references",
        "provenance",
        "sources",
    }

    def strings(value: Any) -> list[str]:
        if isinstance(value, str):
            return [value]
        if isinstance(value, dict):
            return [item for child in value.values() for item in strings(child)]
        if isinstance(value, list):
            return [item for child in value for item in strings(child)]
        return []

    def visit(value: Any) -> bool:
        if isinstance(value, dict):
            for key, item in value.items():
                separated = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(key).strip())
                normalized = re.sub(r"[_\-\s]+", "_", separated).lower()
                if normalized in forbidden_keys and item not in (None, False, "", [], {}):
                    return True
                if normalized in {"classification", "acmg_classification", "pathogenicity"} and str(item).lower() not in {"", "unknown", "unresolved", "not_assessed"}:
                    return True
                if normalized in provenance_keys:
                    if any(candidate not in allowed_provenance for candidate in strings(item)):
                        return True
                if visit(item):
                    return True
        elif isinstance(value, list):
            return any(visit(item) for item in value)
        return False

    if visit(payload):
        return True
    return any(_provider_output_string_policy_violation(text) for text in strings(payload))


def _provider_output_string_policy_violation(value: str) -> bool:
    """Reject autonomous clinical authority while allowing attributed research claims."""

    normalized = re.sub(r"\s+", " ", value.strip().lower())
    if not normalized:
        return False

    if re.search(
        r"\b(?:literature|publication|study|source|clinvar|database)\b.*\b(?:discusses?|reports?|describes?|assertion|retrieved|states?)\b",
        normalized,
    ):
        return False

    forbidden_patterns = (
        r"\b(?:confirmed\s+|final\s+)?diagnosis\s*[:=]",
        r"\b(?:is|was)\s+diagnosed\s+with\b",
        r"\bdiagnosed\s+with\b",
        r"\btreatment\s*[:=]\s*(?:start|begin|use|give|administer|prescribe|take|initiate|commence)\b",
        r"\b(?:start|begin|administer|prescribe|take|initiate|commence)\s+(?:drug|medication|therapy|treatment)\b",
        r"\b(?:recommend|recommended|should receive|should start)\b.*\b(?:drug|medication|therapy|treatment)\b",
        r"\bclinical\s+sign[- ]?out\b",
        r"\b(?:the\s+)?variant\s+(?:is|was)\s+(?:likely\s+)?(?:pathogenic|benign)\b",
        r"\bfinal\s+(?:assessment|classification|pathogenicity)\s*[:=]\s*(?:likely\s+)?(?:pathogenic|benign)\b",
        r"\bacmg\s+classification\s+(?:is|was|:)\s*(?:likely\s+)?(?:pathogenic|benign)\b",
        r"\b(?:classified|classify)\s+as\s+(?:likely\s+)?(?:pathogenic|benign)\b",
        r"\brecurrence\s+risk\b.*\b(?:is|equals?|calculated|estimated)\b",
        r"\bpenetrance\b.*\b(?:is|equals?|calculated|estimated)\b",
        r"\b(?:clinician|reviewer|human|expert)\s+(?:has\s+)?approved\b",
        r"\bapproved\s+by\s+(?:a\s+)?(?:clinician|reviewer|human|expert)\b",
        r"\b(?:deterministically|automatically)\s+(?:confirmed|proven|established|approved)\b",
    )
    if any(re.search(pattern, normalized) for pattern in forbidden_patterns):
        return True
    if re.search(r"\bacmg\s+criteri(?:on|a)\b.*\b(?:approved|confirmed|met|satisfied)\b", normalized):
        return "proposed_not_approved" not in normalized and "proposed not approved" not in normalized
    return False


def _chat_request(session: _Session) -> tuple[str, dict[str, str]]:
    base = (session.base_url or "").rstrip("/")
    url = base if base.endswith("/chat/completions") else f"{base}/chat/completions" if base.endswith("/v1") else f"{base}/v1/chat/completions"
    return url, {"Authorization": f"Bearer {session.api_key}", "Content-Type": "application/json"}


def _models_request(session: _Session) -> tuple[str, dict[str, str]]:
    base = (session.base_url or "").rstrip("/")
    url = f"{base}/models" if base.endswith("/v1") else f"{base}/v1/models"
    return url, {"Authorization": f"Bearer {session.api_key}", "Accept": "application/json"}


def _classify_provider_failure(exc: Exception) -> tuple[int | None, bool]:
    if isinstance(exc, _ProviderHTTPError):
        return exc.status, exc.status in TRANSIENT_HTTP_STATUSES and not exc.redirect
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code, exc.code in TRANSIENT_HTTP_STATUSES
    if isinstance(exc, (TimeoutError, ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
        return None, True
    if isinstance(exc, urllib.error.URLError):
        return None, not isinstance(exc.reason, (ValueError, ssl.SSLError))
    if isinstance(exc, OSError):
        return None, True
    return None, False


def _validate_static_destination(url: str, allow_development_localhost: bool) -> None:
    parsed = _parse_endpoint(url)
    hostname = _normalized_hostname(parsed.hostname)
    local = _is_localhost_name(hostname)
    if parsed.scheme != "https" and not (allow_development_localhost and parsed.scheme == "http" and local):
        raise _UnsafeDestinationError("Remote BYOK endpoints require HTTPS.")
    if _is_metadata_hostname(hostname) or _is_internal_hostname(hostname):
        raise _UnsafeDestinationError("The provider destination is not allowed.")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return
    if allow_development_localhost and local and address.is_loopback:
        return
    if not _is_public_address(address):
        raise _UnsafeDestinationError("The provider destination is not a public address.")


def _parse_endpoint(url: str) -> SplitResult:
    try:
        parsed = urlsplit(url)
        _ = parsed.port
    except (TypeError, ValueError) as exc:
        raise ValueError("BYOK base_url is malformed.") from exc
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("BYOK base_url must use an approved HTTP scheme.")
    if not parsed.netloc or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("BYOK base_url must be absolute and must not contain embedded credentials.")
    if parsed.fragment:
        raise ValueError("BYOK base_url must not contain a fragment.")
    if parsed.query:
        raise ValueError("BYOK base_url must not contain a query string.")
    return parsed


def _normalized_hostname(hostname: str | None) -> str:
    if not hostname:
        raise _UnsafeDestinationError("Provider hostname is required.")
    try:
        return hostname.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise _UnsafeDestinationError("Provider hostname is invalid.") from exc


def _is_metadata_hostname(hostname: str) -> bool:
    return hostname in METADATA_HOSTNAMES or hostname.endswith(".metadata.google.internal")


def _is_internal_hostname(hostname: str) -> bool:
    if _is_localhost_name(hostname):
        return False
    return "." not in hostname or hostname.endswith((".local", ".internal", ".localhost"))


def _is_localhost_name(hostname: str) -> bool:
    if hostname == "localhost" or hostname.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def _is_public_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return bool(
        address.is_global
        and not address.is_loopback
        and not address.is_private
        and not address.is_link_local
        and not address.is_multicast
        and not address.is_unspecified
        and not address.is_reserved
    )


def _default_resolver(hostname: str, port: int) -> list[str]:
    results = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    return sorted({item[4][0] for item in results})


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, hostname: str, port: int, connect_ip: str, timeout: int, authorizer: Callable[[], None] | None = None) -> None:
        super().__init__(hostname, port=port, timeout=timeout, context=ssl.create_default_context())
        self._connect_ip = connect_ip
        self._authorizer = authorizer or (lambda: None)

    def connect(self) -> None:
        self._authorizer()
        raw = socket.create_connection((self._connect_ip, self.port), self.timeout, self.source_address)
        self.sock = self._context.wrap_socket(raw, server_hostname=self.host)


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, hostname: str, port: int, connect_ip: str, timeout: int, authorizer: Callable[[], None] | None = None) -> None:
        super().__init__(hostname, port=port, timeout=timeout)
        self._connect_ip = connect_ip
        self._authorizer = authorizer or (lambda: None)

    def connect(self) -> None:
        self._authorizer()
        self.sock = socket.create_connection((self._connect_ip, self.port), self.timeout, self.source_address)


def _pinned_transport(
    url: str,
    headers: dict[str, str],
    body: bytes | None,
    timeout: int,
    method: str,
    *,
    resolver: Resolver,
    allow_development_localhost: bool,
    authorizer: Callable[[], None] | None = None,
) -> bytes:
    parsed, addresses = validate_provider_destination(url, resolver, allow_development_localhost)
    hostname = _normalized_hostname(parsed.hostname)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    connection: http.client.HTTPConnection
    if parsed.scheme == "https":
        connection = _PinnedHTTPSConnection(hostname, port, addresses[0], timeout, authorizer)
    else:
        connection = _PinnedHTTPConnection(hostname, port, addresses[0], timeout, authorizer)
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    try:
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        if 300 <= response.status < 400:
            raise _ProviderHTTPError(response.status, redirect=True)
        if response.status < 200 or response.status >= 300:
            raise _ProviderHTTPError(response.status)
        payload = response.read(MAX_PROVIDER_RESPONSE_BYTES + 1)
        if len(payload) > MAX_PROVIDER_RESPONSE_BYTES:
            raise ValueError("Provider response exceeded the bounded response size.")
        return payload
    finally:
        connection.close()


def _bound_value(value: Any, path: str, limit: int) -> tuple[Any, list[dict[str, Any]]]:
    notes: list[dict[str, Any]] = []
    if isinstance(value, str):
        if len(value) <= limit:
            return value, notes
        notes.append(
            {
                "path": path,
                "reason": "semantic_safety_per_field_limit",
                "original_length": len(value),
                "retained_length": 0,
            }
        )
        return _OMITTED, notes
    if isinstance(value, dict):
        bounded: dict[str, Any] = {}
        for key in sorted(value):
            bounded_item, child_notes = _bound_value(value[key], f"{path}.{key}", limit)
            if bounded_item is not _OMITTED:
                bounded[key] = bounded_item
            notes.extend(child_notes)
        return bounded, notes
    if isinstance(value, list):
        bounded_list = []
        for index, item in enumerate(value):
            bounded_item, child_notes = _bound_value(item, f"{path}.{index}", limit)
            if bounded_item is not _OMITTED:
                bounded_list.append(bounded_item)
            notes.extend(child_notes)
        return bounded_list, notes
    return value, notes


def _set_dotted_path(target: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    cursor = target
    for part in parts[:-1]:
        cursor = cursor.setdefault(part, {})
    cursor[parts[-1]] = value


def _clear_session(session: _Session) -> None:
    session.api_key = None
    session.cache.clear()
    session.usage.clear()
    session.reserved_calls = 0
    session.reserved_input_tokens = 0
    session.reserved_output_tokens = 0
    session.reserved_cost = ZERO_COST
    session.reserved_connection_tests = 0
    session.reserved_connection_cost = ZERO_COST
    session.active_connection_tests = 0
    session.active_calls = 0
    session.base_url = None
    session.role_models.clear()
    session.input_cost = ZERO_COST
    session.output_cost = ZERO_COST
    session.connection_test_cost = ZERO_COST
    session.leases.clear()


def _normalized_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


byok_runtime = BYOKRuntime()
