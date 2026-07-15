from __future__ import annotations

import hashlib
import json
import math
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, field_validator, model_serializer

from app.insilicopop.clinical.validation import DIRECT_IDENTIFIER_RULES


BYOK_SCHEMA_VERSION = "0.31"
BYOK_POLICY_VERSION = "v0.31-research-curation-1"


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
    estimated_cost_ceiling_usd: float = Field(default=1.0, ge=0, le=10_000)
    max_concurrent_calls: int = Field(default=1, ge=1, le=8)
    max_retries: int = Field(default=1, ge=0, le=2)


class BYOKSessionConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: str = Field(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    provider: ProviderType = ProviderType.MOCK
    model: str = Field(default="mock", min_length=1, max_length=160)
    base_url: str | None = Field(default=None, max_length=500)
    api_key: SecretStr = Field(default_factory=lambda: SecretStr(""))
    role_models: dict[ModelRole, str] = Field(default_factory=dict)
    budget: BYOKBudget = Field(default_factory=BYOKBudget)
    input_cost_per_million_usd: float = Field(default=0.0, ge=0, le=100_000)
    output_cost_per_million_usd: float = Field(default=0.0, ge=0, le=100_000)

    @model_serializer(mode="wrap")
    def serialize_without_secret(self, handler):
        data = handler(self)
        data.pop("api_key", None)
        return data

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlparse(value)
        local_http = parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        if parsed.scheme != "https" and not local_http:
            raise ValueError("BYOK base_url must use HTTPS, except for an explicit localhost endpoint.")
        if not parsed.netloc or parsed.username or parsed.password:
            raise ValueError("BYOK base_url must be an absolute endpoint without embedded credentials.")
        return value.rstrip("/")


class EvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str | None = Field(default=None, max_length=160)
    claim_id: str | None = Field(default=None, max_length=160)
    content: dict[str, Any] | str
    provenance_references: list[str] = Field(default_factory=list, max_length=50)


class BoundedLLMRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    role: ModelRole
    task: str = Field(min_length=1, max_length=500)
    compact_context: dict[str, Any] = Field(default_factory=dict)
    evidence: list[EvidenceItem] = Field(default_factory=list, max_length=200)
    schema_version: str = Field(default=BYOK_SCHEMA_VERSION, min_length=1, max_length=40)
    policy_version: str = Field(default=BYOK_POLICY_VERSION, min_length=1, max_length=80)


class BoundedStructuredResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["success", "refusal"]
    records: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    warnings: list[str] = Field(default_factory=list, max_length=50)


class BYOKUsageRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str
    model: str
    role: str
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0
    latency_ms: int = 0
    cache_hit: bool = False
    retry_count: int = 0
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
    ]


class BYOKExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: str
    response: BoundedStructuredResponse | None = None
    usage: BYOKUsageRecord
    message: str


class BYOKPublicStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["0.31"] = BYOK_SCHEMA_VERSION
    configured: bool
    provider: str
    model: str
    key_present_in_memory: bool
    base_url_configured: bool
    budget: BYOKBudget
    request_count: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    estimated_cost_usd: float
    remaining_calls: int
    remaining_total_tokens: int
    remaining_estimated_cost_usd: float
    active_calls: int
    external_call_made: bool
    usage: list[BYOKUsageRecord]


Transport = Callable[[str, dict[str, str], bytes | None, int, str], bytes]


@dataclass
class _Session:
    provider: ProviderType
    model: str
    base_url: str | None
    api_key: str | None = field(repr=False)
    role_models: dict[ModelRole, str]
    budget: BYOKBudget
    input_cost: float
    output_cost: float
    request_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost: float = 0.0
    active_calls: int = 0
    external_call_made: bool = False
    usage: list[BYOKUsageRecord] = field(default_factory=list)
    cache: dict[str, BoundedStructuredResponse] = field(default_factory=dict)


class _TransientProviderError(RuntimeError):
    def __init__(self, retries: int) -> None:
        super().__init__("bounded provider request failed")
        self.retries = retries


class BYOKRuntime:
    """Session-memory-only provider configuration and bounded structured calls."""

    def __init__(self, transport: Transport | None = None) -> None:
        self._sessions: dict[str, _Session] = {}
        self._transport = transport or _urllib_transport
        self._lock = threading.RLock()

    def configure(self, config: BYOKSessionConfiguration) -> BYOKPublicStatus:
        if config.provider == ProviderType.OPENAI_COMPATIBLE:
            if not config.api_key.get_secret_value():
                raise ValueError("An API key is required for an OpenAI-compatible BYOK session.")
            if not config.base_url:
                raise ValueError("A base URL is required for an OpenAI-compatible BYOK session.")
        secret = config.api_key.get_secret_value() or None
        with self._lock:
            self._sessions[config.session_id] = _Session(
                provider=config.provider,
                model=config.model,
                base_url=config.base_url,
                api_key=secret,
                role_models=dict(config.role_models),
                budget=config.budget,
                input_cost=config.input_cost_per_million_usd,
                output_cost=config.output_cost_per_million_usd,
            )
        return self.status(config.session_id)

    def status(self, session_id: str) -> BYOKPublicStatus:
        with self._lock:
            session = self._require_session(session_id)
            return _public_status(session)

    def public_provenance(self, session_id: str) -> dict[str, Any]:
        return self.status(session_id).model_dump()

    def forget(self, session_id: str) -> bool:
        with self._lock:
            session = self._sessions.pop(session_id, None)
            if session is None:
                return False
            session.api_key = None
            session.cache.clear()
            session.usage.clear()
            return True

    def test_connection(self, session_id: str) -> dict[str, Any]:
        with self._lock:
            session = self._require_session(session_id)
            if session.provider == ProviderType.MOCK:
                return {"status": "success", "provider": "mock", "model": session.model, "external_call_made": False}
            url, headers = _models_request(session)
            session.external_call_made = True
        try:
            self._transport(url, headers, None, 15, "GET")
            return {"status": "success", "provider": session.provider.value, "model": session.model, "external_call_made": True}
        except Exception:
            return {
                "status": "connection_test_failed",
                "provider": session.provider.value,
                "model": session.model,
                "external_call_made": True,
                "message": "Connection test failed. Check the endpoint, model, key, and network availability.",
            }

    def execute(self, session_id: str, request: BoundedLLMRequest) -> BYOKExecutionResult:
        request = request.model_copy(update={"evidence": deduplicate_evidence(request.evidence)})
        policy_match = _find_direct_identifier(request.model_dump(mode="json"))
        with self._lock:
            session = self._require_session(session_id)
            model = session.role_models.get(request.role, session.model)
            if policy_match:
                return self._record_terminal(session, model, request.role, "policy_blocked", "Request was blocked by direct-identifier controls.")
            cache_key = request_cache_key(session.provider.value, model, request)
            cached = session.cache.get(cache_key)
            if cached is not None:
                usage = BYOKUsageRecord(provider=session.provider.value, model=model, role=request.role.value, cache_hit=True, status="success")
                session.usage.append(usage)
                return BYOKExecutionResult(status="success", response=cached, usage=usage, message="Structured response served from session-memory cache.")
            input_tokens = estimate_tokens(request.model_dump(mode="json"))
            stop_status = _budget_stop_status(session, input_tokens)
            if stop_status:
                return self._record_terminal(session, model, request.role, stop_status, "Configured BYOK budget prevented the call.", input_tokens=input_tokens)
            if session.active_calls >= session.budget.max_concurrent_calls:
                return self._record_terminal(session, model, request.role, "budget_exhausted", "Configured concurrency limit is in use.", input_tokens=input_tokens)
            session.active_calls += 1
            session.request_count += 1
        started = time.monotonic()
        retries = 0
        try:
            if session.provider == ProviderType.MOCK:
                response = BoundedStructuredResponse(status="success", records=[], warnings=["mock_provider_no_external_call"])
                raw_output_tokens = estimate_tokens(response.model_dump(mode="json"))
            else:
                response, raw_output_tokens, retries = self._execute_external(session, model, request)
            latency = int((time.monotonic() - started) * 1000)
            cost = _estimated_cost(session, input_tokens, raw_output_tokens)
            usage_status = "refusal" if response.status == "refusal" else "success"
            usage = BYOKUsageRecord(
                provider=session.provider.value,
                model=model,
                role=request.role.value,
                input_tokens=input_tokens,
                output_tokens=raw_output_tokens,
                estimated_cost_usd=cost,
                latency_ms=latency,
                cache_hit=False,
                retry_count=retries,
                status=usage_status,
            )
            with self._lock:
                session.input_tokens += input_tokens
                session.output_tokens += raw_output_tokens
                session.estimated_cost = round(session.estimated_cost + cost, 8)
                session.usage.append(usage)
                if response.status == "success":
                    session.cache[cache_key] = response
            return BYOKExecutionResult(status=usage_status, response=response, usage=usage, message="Bounded structured response validated.")
        except _TransientProviderError as exc:
            retries = exc.retries
            usage = BYOKUsageRecord(
                provider=session.provider.value,
                model=model,
                role=request.role.value,
                input_tokens=input_tokens,
                latency_ms=int((time.monotonic() - started) * 1000),
                retry_count=retries,
                status="provider_unavailable",
            )
            with self._lock:
                session.input_tokens += input_tokens
                session.usage.append(usage)
            return BYOKExecutionResult(status="provider_unavailable", usage=usage, message="Provider request failed without exposing provider or credential details.")
        finally:
            with self._lock:
                session.active_calls = max(0, session.active_calls - 1)

    def _execute_external(
        self, session: _Session, model: str, request: BoundedLLMRequest
    ) -> tuple[BoundedStructuredResponse, int, int]:
        remaining_output_tokens = max(1, session.budget.max_output_tokens - session.output_tokens)
        payload = _provider_payload(model, request, remaining_output_tokens)
        url, headers = _chat_request(session)
        retries = 0
        while True:
            try:
                session.external_call_made = True
                raw = self._transport(url, headers, json.dumps(payload, sort_keys=True).encode("utf-8"), 30, "POST")
                content, output_tokens = _extract_structured_content(raw)
                return BoundedStructuredResponse.model_validate(content), output_tokens, retries
            except (ValidationError, ValueError, json.JSONDecodeError) as exc:
                if retries >= min(1, session.budget.max_retries):
                    raise _TransientProviderError(retries) from exc
            except (urllib.error.URLError, TimeoutError, OSError, _TransientProviderError) as exc:
                if retries >= session.budget.max_retries:
                    raise _TransientProviderError(retries) from exc
            retries += 1

    def _record_terminal(
        self,
        session: _Session,
        model: str,
        role: ModelRole,
        status: str,
        message: str,
        *,
        input_tokens: int = 0,
    ) -> BYOKExecutionResult:
        usage = BYOKUsageRecord(
            provider=session.provider.value,
            model=model,
            role=role.value,
            input_tokens=input_tokens,
            status=status,  # type: ignore[arg-type]
        )
        session.usage.append(usage)
        return BYOKExecutionResult(status=status, usage=usage, message=message)

    def _require_session(self, session_id: str) -> _Session:
        try:
            return self._sessions[session_id]
        except KeyError as exc:
            raise KeyError("No active in-memory BYOK session is configured.") from exc


def build_compact_case_context(case: dict[str, Any], required_fields: list[str]) -> dict[str, Any]:
    """Select only explicitly required dotted paths from a case without mutation."""

    compact: dict[str, Any] = {}
    for path in sorted(set(required_fields)):
        value: Any = case
        for part in path.split("."):
            if not isinstance(value, dict) or part not in value:
                value = None
                break
            value = value[part]
        if value is not None:
            target = compact
            parts = path.split(".")
            for part in parts[:-1]:
                target = target.setdefault(part, {})
            target[parts[-1]] = value
    return compact


def deduplicate_evidence(items: list[EvidenceItem]) -> list[EvidenceItem]:
    """Remove exact stable-ID/content duplicates while retaining same-ID conflicts."""

    seen: set[tuple[str, str]] = set()
    deduplicated: list[EvidenceItem] = []
    for item in items:
        stable_id = item.source_id or item.claim_id or "unidentified"
        digest = hashlib.sha256(_normalized_json(item.content).encode("utf-8")).hexdigest()
        key = (stable_id, digest)
        if key not in seen:
            seen.add(key)
            deduplicated.append(item)
    return deduplicated


def request_cache_key(provider: str, model: str, request: BoundedLLMRequest) -> str:
    evidence_digest = hashlib.sha256(
        _normalized_json([item.model_dump(mode="json") for item in request.evidence]).encode("utf-8")
    ).hexdigest()
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


def _public_status(session: _Session) -> BYOKPublicStatus:
    total = session.input_tokens + session.output_tokens
    return BYOKPublicStatus(
        configured=True,
        provider=session.provider.value,
        model=session.model,
        key_present_in_memory=bool(session.api_key),
        base_url_configured=bool(session.base_url),
        budget=session.budget,
        request_count=session.request_count,
        input_tokens=session.input_tokens,
        output_tokens=session.output_tokens,
        total_tokens=total,
        estimated_cost_usd=round(session.estimated_cost, 8),
        remaining_calls=max(0, session.budget.max_calls - session.request_count),
        remaining_total_tokens=max(0, session.budget.max_total_tokens - total),
        remaining_estimated_cost_usd=max(0.0, round(session.budget.estimated_cost_ceiling_usd - session.estimated_cost, 8)),
        active_calls=session.active_calls,
        external_call_made=session.external_call_made,
        usage=list(session.usage),
    )


def _budget_stop_status(session: _Session, input_tokens: int) -> str | None:
    budget = session.budget
    if session.request_count >= budget.max_calls:
        return "call_limit_reached"
    if session.input_tokens + input_tokens > budget.max_input_tokens:
        return "token_limit_reached"
    if session.output_tokens >= budget.max_output_tokens:
        return "token_limit_reached"
    remaining_output_tokens = max(0, budget.max_output_tokens - session.output_tokens)
    projected_total = session.input_tokens + session.output_tokens + input_tokens + remaining_output_tokens
    if projected_total > budget.max_total_tokens:
        return "token_limit_reached"
    projected_cost = session.estimated_cost + _estimated_cost(session, input_tokens, remaining_output_tokens)
    if projected_cost > budget.estimated_cost_ceiling_usd:
        return "cost_limit_reached"
    return None


def _estimated_cost(session: _Session, input_tokens: int, output_tokens: int) -> float:
    return round((input_tokens * session.input_cost + output_tokens * session.output_cost) / 1_000_000, 8)


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


def _extract_structured_content(raw: bytes) -> tuple[Any, int]:
    payload = json.loads(raw.decode("utf-8"))
    usage = payload.get("usage", {}) if isinstance(payload, dict) else {}
    output_tokens = int(usage.get("completion_tokens") or 0)
    if isinstance(payload, dict) and isinstance(payload.get("choices"), list) and payload["choices"]:
        choice = payload["choices"][0]
        content = choice.get("message", {}).get("content") if isinstance(choice, dict) else None
        if isinstance(content, str):
            parsed = json.loads(content)
            return parsed, output_tokens or estimate_tokens(parsed)
    if isinstance(payload, dict) and "status" in payload:
        return payload, output_tokens or estimate_tokens(payload)
    raise ValueError("unsupported structured response")


def _chat_request(session: _Session) -> tuple[str, dict[str, str]]:
    base = (session.base_url or "").rstrip("/")
    url = base if base.endswith("/chat/completions") else f"{base}/chat/completions" if base.endswith("/v1") else f"{base}/v1/chat/completions"
    return url, {"Authorization": f"Bearer {session.api_key}", "Content-Type": "application/json"}


def _models_request(session: _Session) -> tuple[str, dict[str, str]]:
    base = (session.base_url or "").rstrip("/")
    url = f"{base}/models" if base.endswith("/v1") else f"{base}/v1/models"
    return url, {"Authorization": f"Bearer {session.api_key}", "Accept": "application/json"}


def _find_direct_identifier(value: Any) -> str | None:
    if isinstance(value, dict):
        for item in value.values():
            match = _find_direct_identifier(item)
            if match:
                return match
    elif isinstance(value, list):
        for item in value:
            match = _find_direct_identifier(item)
            if match:
                return match
    elif isinstance(value, str):
        for code, pattern in DIRECT_IDENTIFIER_RULES:
            if pattern.search(value):
                return code
    return None


def _normalized_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _urllib_transport(url: str, headers: dict[str, str], body: bytes | None, timeout: int, method: str) -> bytes:
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:  # nosec - explicit session-scoped BYOK endpoint
        return response.read()


byok_runtime = BYOKRuntime()
