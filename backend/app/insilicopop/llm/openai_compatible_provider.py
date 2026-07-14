from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Callable

from pydantic import ValidationError

from app.insilicopop.llm.base import LLMProviderError
from app.insilicopop.llm.config import LLMConfig
from app.insilicopop.llm.prompt_builder import build_orchestration_prompt
from app.insilicopop.llm.schemas import LLMActionProposal


HttpPost = Callable[[str, dict[str, str], bytes, int], bytes]


class OpenAICompatibleProvider:
    def __init__(self, config: LLMConfig, http_post: HttpPost | None = None) -> None:
        self.provider_name = "openai_compatible"
        self.config = config
        self.external_call_made = False
        self.last_prompt: dict[str, Any] | None = None
        self._http_post = http_post or _urllib_post

    def propose_actions(self, *, compact_memory: dict[str, Any], audit_summary: dict[str, Any], query: str | None) -> list[LLMActionProposal]:
        self.last_prompt = build_orchestration_prompt(compact_memory=compact_memory, audit_summary=audit_summary, query=query)
        payload = {
            "model": self.config.openai_compatible_model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Return only JSON matching {\"actions\":[{\"action_type\":str,\"rationale\":str,"
                        "\"required_inputs\":[],\"expected_outputs\":[],\"claim_intent\":null,\"confidence\":0.0}]}. "
                        "Do not ask to execute tools; propose planning actions only."
                    ),
                },
                {"role": "user", "content": json.dumps(self.last_prompt, sort_keys=True)},
            ],
            "temperature": 0,
        }
        url = _chat_completions_url(self.config.openai_compatible_base_url or "")
        headers = {
            "Authorization": f"Bearer {self.config.openai_compatible_api_key}",
            "Content-Type": "application/json",
        }
        try:
            self.external_call_made = True
            raw = self._http_post(url, headers, json.dumps(payload).encode("utf-8"), self.config.timeout_seconds)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise LLMProviderError(
                "external_llm_request_failed",
                f"OpenAI-compatible provider request failed: {exc}",
                severity="warning",
                recommended_fix="Check base URL, API key, model, and network settings, or use llm_provider=mock.",
            ) from exc
        return _parse_provider_response(raw)


def _urllib_post(url: str, headers: dict[str, str], body: bytes, timeout_seconds: int) -> bytes:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:  # nosec - user-supplied BYOK endpoint, opt-in only
        return response.read()


def _chat_completions_url(base_url: str) -> str:
    stripped = base_url.rstrip("/")
    if stripped.endswith("/chat/completions"):
        return stripped
    if stripped.endswith("/v1"):
        return f"{stripped}/chat/completions"
    return f"{stripped}/v1/chat/completions"


def _parse_provider_response(raw: bytes) -> list[LLMActionProposal]:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LLMProviderError(
            "invalid_llm_json",
            "OpenAI-compatible provider returned invalid JSON.",
            severity="warning",
            recommended_fix="Configure the provider to return JSON-only structured action proposals.",
        ) from exc
    content = _extract_content(payload)
    try:
        actions_payload = json.loads(content) if isinstance(content, str) else content
    except json.JSONDecodeError as exc:
        raise LLMProviderError(
            "invalid_llm_action_json",
            "OpenAI-compatible provider message content was not valid action JSON.",
            severity="warning",
            recommended_fix="Configure the provider prompt/model to return only JSON action proposals.",
        ) from exc
    if isinstance(actions_payload, list):
        actions = actions_payload
    elif isinstance(actions_payload, dict) and isinstance(actions_payload.get("actions"), list):
        actions = actions_payload["actions"]
    elif isinstance(actions_payload, dict):
        actions = [actions_payload]
    else:
        raise LLMProviderError(
            "invalid_llm_action_shape",
            "OpenAI-compatible provider returned an unsupported action payload shape.",
            severity="warning",
            recommended_fix="Return a JSON object with an 'actions' list.",
            details={"type": type(actions_payload).__name__},
        )
    try:
        return [LLMActionProposal(**action) for action in actions]
    except (TypeError, ValidationError) as exc:
        raise LLMProviderError(
            "invalid_llm_action_schema",
            "OpenAI-compatible provider action proposal failed schema validation.",
            severity="warning",
            recommended_fix="Return action_type, rationale, required_inputs, expected_outputs, claim_intent, and confidence fields.",
        ) from exc


def _extract_content(payload: Any) -> Any:
    if isinstance(payload, dict) and isinstance(payload.get("choices"), list) and payload["choices"]:
        message = payload["choices"][0].get("message", {}) if isinstance(payload["choices"][0], dict) else {}
        if isinstance(message, dict) and "content" in message:
            return message["content"]
    if isinstance(payload, dict) and ("actions" in payload or "action_type" in payload):
        return payload
    raise LLMProviderError(
        "invalid_llm_response_shape",
        "OpenAI-compatible provider response did not contain choices[0].message.content or direct action JSON.",
        severity="warning",
        recommended_fix="Use a chat-completions compatible endpoint or return direct action JSON.",
    )
