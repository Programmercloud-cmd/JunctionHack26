"""Offline tests exercise the actual OpenAI SDK request serializer and parser."""
from io import BytesIO
import json

import httpx2
from openai import OpenAI
from PIL import Image
import pytest

from app.documents import DocumentStore
from app.openai_provider import OpenAIProvider
from app.provider import ProviderError
from app.schemas import GateResult


def response(output=None, *, status="completed", refusal=None):
    content = []
    if output is not None:
        content = [{"type": "output_text", "text": json.dumps(output), "annotations": []}]
    if refusal is not None:
        content = [{"type": "refusal", "refusal": refusal}]
    return {
        "id": "resp_test", "object": "response", "created_at": 0, "status": status,
        "model": "gpt-6.1-sol", "error": None,
        "incomplete_details": {"reason": "max_output_tokens"} if status == "incomplete" else None,
        "output": [{"id": "msg_test", "type": "message", "role": "assistant", "status": "completed",
                    "content": content}] if content else [],
        "parallel_tool_calls": True, "tools": [], "tool_choice": "auto",
        "usage": {"input_tokens": 20, "output_tokens": 10, "total_tokens": 30,
                  "input_tokens_details": {"cached_tokens": 0}, "output_tokens_details": {"reasoning_tokens": 0}},
    }


@pytest.fixture
def document(tmp_path):
    store = DocumentStore(tmp_path)
    buffer = BytesIO()
    Image.new("RGB", (200, 100), "white").save(buffer, format="PNG")
    yield store.add(buffer.getvalue(), "plan.png")
    store.close()


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "offline-test-key")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-6.1-sol")
    instance = OpenAIProvider()
    yield instance
    instance.close()


def intercept(provider, handler):
    provider.client.close()
    provider.client = OpenAI(api_key="offline-test-key", max_retries=0, timeout=45,
                             http_client=httpx2.Client(transport=httpx2.MockTransport(handler)))


def test_actual_sdk_all_stages_and_source_images(provider, document):
    calls = []
    answer = {"status": "answered", "answer": "No windows are shown.",
              "evidence": [{"page": 1, "bbox": [0, 0, 1, 1], "label": "Whole plan", "observation": "No window symbols"}],
              "missing_information": [], "next_action": "", "proposal": None, "calculation": None}
    def handler(request):
        payload = json.loads(request.content)
        calls.append(payload)
        assert str(request.url) == "https://api.openai.com/v1/responses"
        assert payload["model"] == "gpt-6.1-sol"
        assert payload["store"] is False
        assert "temperature" not in payload
        assert payload["text"]["format"]["type"] == "json_schema"
        assert payload["text"]["format"]["strict"] is True
        content = payload["input"][0]["content"]
        images = [block for block in content if block["type"] == "input_image"]
        assert len(images) == (2 if len(calls) == 3 else 1)
        assert all(block["image_url"].startswith("data:image/png;base64,") for block in images)
        if len(calls) == 1:
            assert set(payload["text"]["format"]["schema"]["properties"]) == {"decision"}
            result = {"decision": "sufficient"}
        elif len(calls) == 2:
            result = {"page": 1, "bbox": [0, 0, .5, .5], "reason": "Inspect room label"}
        else:
            assert "default" not in payload["text"]["format"]["schema"]["properties"]["next_action"]
            result = answer
        return httpx2.Response(200, json=response(result))
    intercept(provider, handler)
    gate = provider.gate(document, "How many windows?")
    assert gate.confidence is None
    crop = provider.choose_crop(document, "How many windows?")
    draft = provider.answer(document, "How many windows?", gate, crop)
    assert draft.answer == answer["answer"]
    assert provider.usage.input_tokens == 60
    assert provider.usage.output_tokens == 30
    assert len(calls) == 3


@pytest.mark.parametrize("decision", ["insufficient", "unclear"])
def test_gate_labels_and_no_invented_confidence(provider, document, decision):
    intercept(provider, lambda request: httpx2.Response(200, json=response({"decision": decision})))
    gate = provider.gate(document, "What is the ceiling height?")
    assert gate.decision == decision
    assert gate.confidence is None


@pytest.mark.parametrize("body", [response(refusal="private refusal detail"),
                                 response(status="incomplete"), response(),
                                 response({"decision": "made-up-label"}),
                                 response({"decision": "sufficient", "confidence": .99})])
def test_refusal_incomplete_missing_or_invalid_output_is_operational(provider, document, body):
    intercept(provider, lambda request: httpx2.Response(200, json=body))
    with pytest.raises(ProviderError) as error:
        provider.gate(document, "How many windows?")
    assert error.value.status == 502
    assert "private refusal detail" not in error.value.message
    assert "No evidence conclusion" in error.value.message or "no evidence conclusion" in error.value.message


def test_api_failure_sanitized_and_not_retried(provider, document):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx2.Response(429, json={"error": {"message": "sensitive quota body", "type": "rate_limit_error", "code": "rate_limit"}})
    intercept(provider, handler)
    with pytest.raises(ProviderError) as error:
        provider.gate(document, "How many windows?")
    assert len(calls) == 1
    assert error.value.status == 502
    assert "sensitive" not in error.value.message


def test_missing_key_fails_before_network(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ProviderError) as error:
        OpenAIProvider()
    assert error.value.status == 503
    assert "OPENAI_API_KEY" in error.value.message
