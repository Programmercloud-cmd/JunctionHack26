import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.providers.gemini import GeminiProvider, ProviderError, create_provider, settings
from app.schemas import GateResult


def test_default_is_gemini(monkeypatch):
    monkeypatch.delenv("AI_PROVIDER", raising=False)
    assert settings()["name"] == "gemini"
    assert settings()["gate_kind"] == "gemini_decisions"


def test_health_and_factory_use_gemini_with_legacy_provider_env(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("GEMINI_API_KEY", "fixture-not-a-secret")
    monkeypatch.setenv("GEMINI_MODEL", "fixture-answer-model")
    monkeypatch.setenv("GEMINI_INTERPRETATION_MODEL", "fixture-interpretation-model")
    monkeypatch.setenv("GEMINI_CLARIFICATION_MODEL", "fixture-clarification-model")
    monkeypatch.setenv("GEMINI_RECONSTRUCTION_MODEL", "fixture-reconstruction-model")
    monkeypatch.setenv("GEMINI_DECISION_MODEL", "fixture-decision-model")
    with TestClient(create_app(storage_root=tmp_path)) as client:
        data = client.get("/api/health").json()
    assert data["provider"] == "gemini"
    assert data["provider_label"] == "Gemini"
    assert data["credential_env"] == "GEMINI_API_KEY"
    assert data["model"] == "fixture-answer-model"
    assert data["interpretation_model"] == "fixture-interpretation-model"
    assert data["clarification_model"] == "fixture-clarification-model"
    assert data["reconstruction_model"] == "fixture-reconstruction-model"
    assert data["decision_model"] == "fixture-decision-model"
    assert data["gate_kind"] == "gemini_decisions"
    assert data["provider_ready"] is True
    assert "fixture-not-a-secret" not in str(data)
    provider = create_provider()
    try:
        assert isinstance(provider, GeminiProvider)
        assert provider.model == "fixture-answer-model"
        assert provider.interpretation_model == "fixture-interpretation-model"
        assert provider.clarification_model == "fixture-clarification-model"
    finally:
        provider.close()


def test_explicit_unsupported_provider_is_rejected():
    with pytest.raises(ProviderError, match="Gemini is the supported AI provider"):
        settings("openai")


def test_missing_gemini_key_has_no_fallback(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-not-a-secret")
    with pytest.raises(ProviderError, match="GEMINI_API_KEY"):
        create_provider()


def test_null_confidence_is_not_fabricated():
    assert GateResult(decision="sufficient").confidence is None
    assert GateResult(decision="sufficient", confidence=.8).confidence == .8
    with pytest.raises(ValueError):
        GateResult(decision="sufficient", confidence=2)
