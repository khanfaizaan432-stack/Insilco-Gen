from __future__ import annotations

import os
from dataclasses import dataclass


TRUE_VALUES = {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class LLMConfig:
    provider: str = "mock"
    external_llm_enabled: bool = False
    openai_compatible_base_url: str | None = None
    openai_compatible_api_key: str | None = None
    openai_compatible_model: str | None = None
    timeout_seconds: int = 30


def load_llm_config(provider_override: str | None = None) -> LLMConfig:
    provider = (provider_override or os.getenv("INSILICOPOP_LLM_PROVIDER") or "mock").strip().lower()
    external = (os.getenv("INSILICOPOP_EXTERNAL_LLM") or "false").strip().lower() in TRUE_VALUES
    return LLMConfig(
        provider=provider,
        external_llm_enabled=external,
        openai_compatible_base_url=_clean(os.getenv("INSILICOPOP_OPENAI_COMPATIBLE_BASE_URL")),
        openai_compatible_api_key=_clean(os.getenv("INSILICOPOP_OPENAI_COMPATIBLE_API_KEY")),
        openai_compatible_model=_clean(os.getenv("INSILICOPOP_OPENAI_COMPATIBLE_MODEL")),
    )


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None
