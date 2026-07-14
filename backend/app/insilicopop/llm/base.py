from __future__ import annotations

from typing import Any, Protocol

from app.insilicopop.llm.schemas import LLMActionProposal


class LLMProvider(Protocol):
    provider_name: str
    external_call_made: bool

    def propose_actions(self, *, compact_memory: dict[str, object], audit_summary: dict[str, object], query: str | None) -> list[LLMActionProposal]:
        ...


class LLMProviderError(RuntimeError):
    def __init__(
        self,
        failure_type: str,
        message: str,
        *,
        severity: str = "warning",
        recommended_fix: str = "Use mock provider or correct provider configuration/output.",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.failure_type = failure_type
        self.message = message
        self.severity = severity
        self.recommended_fix = recommended_fix
        self.details = details or {}

    def failure_reason(self) -> dict[str, Any]:
        return {
            "failure_type": self.failure_type,
            "severity": self.severity,
            "message": self.message,
            "triggered_by": ["llm_provider"],
            "recommended_fix": self.recommended_fix,
            "blocked_action_id": None,
            "details": self.details,
        }
