import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.providers.gemini import GeminiProvider, ProviderError, create_provider, settings
from app.schemas import GateResult


def test_default_is_gemini(monkeypatch):
    monkeypatch.delenv("AI_PROVIDER", raising=False)
    assert settings()["name"] == "gemini"
    assert settings()["gate_kind"] == "gemini_decisions"


def test_health_and_factory_use_selected_gemini(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "gemini")
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
    with pytest.raises(ProviderError, match="AI_PROVIDER"):
        settings("unsupported")


def test_missing_gemini_key_has_no_fallback(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "gemini")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-not-a-secret")
    with pytest.raises(ProviderError, match="GEMINI_API_KEY"):
        create_provider()


def test_health_and_factory_use_selected_openai_without_gemini_key(tmp_path, monkeypatch):
    from app.providers.openai import OpenAIProvider
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-openai-secret")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_RENDER_MODEL", "fixture-render")
    monkeypatch.setenv("OPENAI_DECISION_MODEL", "fixture-review")
    with TestClient(create_app(storage_root=tmp_path)) as client:
        data = client.get("/api/health").json()
    assert data["provider"] == "openai" and data["provider_ready"] is True
    assert data["provider_label"] == "OpenAI" and data["credential_env"] == "OPENAI_API_KEY"
    assert data["model"] == data["advanced_model"] == "gpt-6.1-sol"
    assert data["basic_model"] == data["router_model"] == data["ui_model"] == "gpt-6-luna"
    assert data["render_model"] == "fixture-render" and data["decision_model"] == "fixture-review"
    assert data["gate_kind"] == "structured_model_decision"
    assert "fixture-openai-secret" not in str(data)
    provider = create_provider()
    try:
        assert isinstance(provider, OpenAIProvider)
        assert provider.client.max_retries == 0
    finally:
        provider.close()


def test_missing_openai_key_does_not_use_available_gemini_key(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "fixture-available-gemini")
    with pytest.raises(ProviderError, match="OPENAI_API_KEY"):
        create_provider()


def test_invalid_provider_has_safe_health_error(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "unsupported")
    with TestClient(create_app(storage_root=tmp_path)) as client:
        response = client.get("/api/health")
    assert response.status_code == 503
    assert "AI_PROVIDER" in response.json()["detail"]


def test_null_confidence_is_not_fabricated():
    assert GateResult(decision="sufficient").confidence is None
    assert GateResult(decision="sufficient", confidence=.8).confidence == .8
    with pytest.raises(ValueError):
        GateResult(decision="sufficient", confidence=2)
