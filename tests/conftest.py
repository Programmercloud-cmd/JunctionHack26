import pytest


@pytest.fixture(autouse=True)
def deterministic_provider_selection(monkeypatch):
    """Local developer provider choice must not change test behavior."""
    monkeypatch.setenv("AI_PROVIDER", "gemini")
