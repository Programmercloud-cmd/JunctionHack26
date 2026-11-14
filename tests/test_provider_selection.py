import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.provider import ProviderError, create_provider, settings
from app.schemas import GateResult


def test_default_is_gemini(monkeypatch):
    monkeypatch.delenv("AI_PROVIDER", raising=False)
    assert settings()["name"] == "gemini"
    assert settings()["gate_kind"] == "gemini_decisions"


def test_openai_health_is_explicit(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-not-a-secret")
    monkeypatch.setenv("OPENAI_MODEL", "fixture-model")
    with TestClient(create_app(storage_root=tmp_path)) as client:
        data = client.get("/api/health").json()
    assert data["provider"] == "openai"
    assert data["provider_label"] == "OpenAI"
    assert data["model"] == data["decision_model"] == "fixture-model"
    assert data["gate_kind"] == "structured_classification"
    assert data["provider_ready"] is True
    assert "fixture-not-a-secret" not in str(data)


def test_unknown_provider_fails_explicitly(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "typo")
    with pytest.raises(ProviderError, match="Unknown AI_PROVIDER"):
        create_provider()
    with TestClient(create_app(storage_root=tmp_path)) as client:
        assert client.get("/api/health").status_code == 503


@pytest.mark.parametrize("selected,missing,other", [("openai", "OPENAI_API_KEY", "GEMINI_API_KEY"),
                                                  ("gemini", "GEMINI_API_KEY", "OPENAI_API_KEY")])
def test_no_automatic_fallback(selected, missing, other, monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", selected)
    monkeypatch.delenv(missing, raising=False)
    monkeypatch.setenv(other, "fixture-not-a-secret")
    with pytest.raises(ProviderError, match=missing):
        create_provider()


def test_null_confidence_is_not_fabricated():
    assert GateResult(decision="sufficient").confidence is None
    assert GateResult(decision="sufficient", confidence=.8).confidence == .8
    with pytest.raises(ValueError):
        GateResult(decision="sufficient", confidence=2)
