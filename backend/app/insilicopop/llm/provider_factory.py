from __future__ import annotations

from app.insilicopop.llm.base import LLMProvider
from app.insilicopop.llm.config import LLMConfig, load_llm_config
from app.insilicopop.llm.mock_provider import MockLLMProvider
from app.insilicopop.llm.openai_compatible_provider import OpenAICompatibleProvider


SUPPORTED_PROVIDERS = {"mock", "openai_compatible"}
RESERVED_FUTURE_PROVIDERS = {"openai", "gemini", "anthropic", "claude", "grok", "local"}


def build_llm_provider(provider_name: str | None = None, *, config: LLMConfig | None = None) -> LLMProvider:
    cfg = config or load_llm_config(provider_name)
    provider = (provider_name or cfg.provider or "mock").strip().lower()
    if provider == "mock":
        return MockLLMProvider()
    if provider in RESERVED_FUTURE_PROVIDERS:
        raise ValueError(f"LLM provider '{provider}' is reserved but not implemented yet. Use 'mock' or 'openai_compatible'.")
    if provider not in SUPPORTED_PROVIDERS:
        raise ValueError(f"Unknown LLM provider '{provider}'. Supported providers: {', '.join(sorted(SUPPORTED_PROVIDERS))}.")
    if not cfg.external_llm_enabled:
        raise ValueError("External LLM providers require INSILICOPOP_EXTERNAL_LLM=true.")
    if provider == "openai_compatible":
        if not cfg.openai_compatible_api_key:
            raise ValueError("OpenAI-compatible provider requires INSILICOPOP_OPENAI_COMPATIBLE_API_KEY.")
        if not cfg.openai_compatible_base_url:
            raise ValueError("OpenAI-compatible provider requires INSILICOPOP_OPENAI_COMPATIBLE_BASE_URL.")
        if not cfg.openai_compatible_model:
            raise ValueError("OpenAI-compatible provider requires INSILICOPOP_OPENAI_COMPATIBLE_MODEL.")
        return OpenAICompatibleProvider(cfg)
    raise ValueError(f"Unsupported LLM provider '{provider}'.")
