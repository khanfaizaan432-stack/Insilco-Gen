from __future__ import annotations

import pytest

from app.insilicopop.llm.config import load_llm_config
from app.insilicopop.llm.mock_provider import MockLLMProvider
from app.insilicopop.llm.provider_factory import build_llm_provider


def test_provider_factory_selects_mock_by_default(monkeypatch):
    monkeypatch.delenv("INSILICOPOP_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("INSILICOPOP_EXTERNAL_LLM", raising=False)

    provider = build_llm_provider()

    assert isinstance(provider, MockLLMProvider)
    assert provider.provider_name == "mock"
    assert provider.external_call_made is False


def test_default_config_does_not_enable_external_llm(monkeypatch):
    monkeypatch.delenv("INSILICOPOP_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("INSILICOPOP_EXTERNAL_LLM", raising=False)

    config = load_llm_config()

    assert config.provider == "mock"
    assert config.external_llm_enabled is False


def test_provider_factory_rejects_unknown_provider_cleanly():
    with pytest.raises(ValueError, match="Unknown LLM provider"):
        build_llm_provider("mystery_provider")


def test_openai_compatible_requires_explicit_external_enablement(monkeypatch):
    monkeypatch.setenv("INSILICOPOP_EXTERNAL_LLM", "false")

    with pytest.raises(ValueError, match="INSILICOPOP_EXTERNAL_LLM=true"):
        build_llm_provider("openai_compatible")


def test_openai_compatible_missing_api_key_fails_cleanly(monkeypatch):
    monkeypatch.setenv("INSILICOPOP_EXTERNAL_LLM", "true")
    monkeypatch.delenv("INSILICOPOP_OPENAI_COMPATIBLE_API_KEY", raising=False)
    monkeypatch.setenv("INSILICOPOP_OPENAI_COMPATIBLE_BASE_URL", "http://example.invalid")
    monkeypatch.setenv("INSILICOPOP_OPENAI_COMPATIBLE_MODEL", "test-model")

    with pytest.raises(ValueError, match="API_KEY"):
        build_llm_provider("openai_compatible")

