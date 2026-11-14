"""Content-free failure telemetry through the existing SDK and job observer."""
from copy import deepcopy
import json
from types import SimpleNamespace

from google.genai import errors as genai_errors
from google.genai import _interactions as decision_errors
import httpx2
import pytest
from pydantic import ValidationError

from app.jobs import JobRunner
from app.provider import ProviderError, _record_exception
from test_gemini_schema import CROP, intercept, sdk_document


CANARY = "PRIVATE_DIAGNOSTIC_CANARY"


def transport(provider, handler):
    provider.client._api_client._httpx_client.close()
    provider.client._api_client._httpx_client = httpx2.Client(transport=httpx2.MockTransport(handler))


def observe(provider):
    saved = []
    runner = SimpleNamespace(jobs={"fixture": {"phase": "answering"}},
        _update=lambda identity, **values: saved.append(deepcopy(values)))
    JobRunner._bind_provider(runner, "fixture", provider)
    return saved


@pytest.mark.parametrize("mode", ["generation", "decisions"])
def test_timeout_preserves_exception_observer_and_no_retry(sdk_document, mode):
    provider, document = sdk_document
    saved = observe(provider)
    private_request = httpx2.Request("POST", f"https://example.invalid/{CANARY}",
        headers={"Authorization": CANARY}, content=CANARY)
    error = httpx2.ReadTimeout(CANARY, request=private_request)
    requests = []

    def failure(request):
        requests.append(request)
        raise error

    transport(provider, failure)
    expected = httpx2.ReadTimeout if mode == "generation" else decision_errors.APITimeoutError
    with pytest.raises(expected) as caught:
        if mode == "generation": provider.choose_crop(document, "Fixture")
        else: provider.gate(document, "Fixture")
    if mode == "generation": assert caught.value is error
    assert len(requests) == 1
    assert requests[0].extensions["timeout"] == dict(connect=45, read=45, write=45, pool=45)
    call = provider.provider_calls[-1]
    assert call["exception_type"] == expected.__name__ and call["http_status"] is None
    assert call["outcome"] == "provider_error" and call["timeout_ms"] == 45000
    assert call["stage"] == "answering" and call["elapsed_ms"] >= 0
    assert call["prompt_tokens"] is None and call["candidate_tokens"] is None
    assert call["finish_reason"] is None and provider.last_response_text is None
    assert saved[-1]["provider_calls"] == provider.provider_calls
    assert CANARY not in json.dumps(saved)


@pytest.mark.parametrize("status,label", [(400, "ClientError"), (429, "ClientError"), (503, "ServerError")])
@pytest.mark.parametrize("mode", ["generation", "decisions"])
def test_sdk_http_status_is_safe_and_success_clears_failure_fields(sdk_document, status, label, mode):
    provider, document = sdk_document
    saved = observe(provider)
    requests = []

    def failure(request):
        requests.append(request)
        return httpx2.Response(status, json={"error": {"code": status,
            "message": CANARY, "status": CANARY, "details": [{CANARY: CANARY}]}},
            headers={"x-private": CANARY})

    transport(provider, failure)
    expected = genai_errors.APIError if mode == "generation" else decision_errors.APIStatusError
    with pytest.raises(expected):
        if mode == "generation": provider.choose_crop(document, "Fixture")
        else: provider.gate(document, "Fixture")
    assert len(requests) == 1
    failed = deepcopy(provider.provider_calls[-1])
    if mode == "decisions": label = {400: "BadRequestError", 429: "RateLimitError", 503: "InternalServerError"}[status]
    assert failed["exception_type"] == label and failed["http_status"] == status
    assert failed["outcome"] == "provider_error" and CANARY not in json.dumps(saved)
    provider.client._api_client._httpx_client.close()
    intercept(provider, CROP)
    provider.choose_crop(document, "Fixture")
    success = provider.provider_calls[-1]
    assert success["outcome"] == "validated_response"
    assert success["exception_type"] is None and success["http_status"] is None
    assert failed["call_id"] != success["call_id"]
    assert provider.provider_calls[-2] == failed
    assert saved[-1]["provider_calls"] == provider.provider_calls


@pytest.mark.parametrize("body,outcome", [("not json", "response_json_rejected"),
    (json.dumps({"page": "invalid", "bbox": [0, 0, 1, 1], "reason": CANARY}), "response_schema_rejected")])
def test_local_response_validation_retains_outcome_without_upstream_error_status(sdk_document, body, outcome):
    provider, document = sdk_document
    saved = observe(provider)
    transport(provider, lambda request: httpx2.Response(200, json={"candidates": [
        {"finishReason": "STOP", "content": {"parts": [{"text": body}]}}]}))
    with pytest.raises(ValidationError): provider.choose_crop(document, "Fixture")
    call = provider.provider_calls[-1]
    assert call["outcome"] == outcome and call["exception_type"] == "ValidationError"
    assert call["http_status"] is None and CANARY not in json.dumps(saved)


def test_output_limit_is_local_error_not_upstream_http_failure(sdk_document):
    provider, document = sdk_document
    intercept(provider, CROP, finish_reason="MAX_TOKENS")
    with pytest.raises(ProviderError) as caught: provider.choose_crop(document, "Fixture")
    assert caught.value.category == "provider_output_limit"
    call = provider.provider_calls[-1]
    assert call["outcome"] == "output_limit" and call["exception_type"] == "ProviderError"
    assert call["http_status"] is None


def test_unknown_dynamic_class_and_exception_attributes_never_escape(sdk_document):
    provider, document = sdk_document
    saved = observe(provider)
    error = type(CANARY, (Exception,), {"code": 401, "status": 403})(CANARY)

    def failure(request): raise error

    transport(provider, failure)
    with pytest.raises(type(error)) as caught: provider.choose_crop(document, "Fixture")
    assert caught.value is error
    call = provider.provider_calls[-1]
    assert call["exception_type"] == "UnexpectedError" and call["http_status"] is None
    assert CANARY not in json.dumps(saved)


def test_decisions_wrapper_is_reraised_unchanged(sdk_document, monkeypatch):
    provider, document = sdk_document
    error = decision_errors.APITimeoutError(request=httpx2.Request("POST", f"https://example.invalid/{CANARY}"))

    def failure(**kwargs): raise error

    monkeypatch.setattr(provider.client.decisions, "create", failure)
    with pytest.raises(decision_errors.APITimeoutError) as caught: provider.gate(document, "Fixture")
    assert caught.value is error
    assert provider.provider_calls[-1]["exception_type"] == "APITimeoutError"


@pytest.mark.parametrize("status", [True, "429", 99, 600, None])
def test_only_numeric_http_status_metadata_is_retained(status):
    error = genai_errors.APIError(400, {"message": CANARY})
    error.code = status
    record = {}
    _record_exception(record, error)
    assert record == {"exception_type": "APIError", "http_status": None}


def test_http_status_exception_reads_response_status_without_response_content():
    request = httpx2.Request("GET", f"https://example.invalid/{CANARY}")
    response = httpx2.Response(502, content=CANARY, request=request)
    record = {}
    _record_exception(record, httpx2.HTTPStatusError(CANARY, request=request, response=response))
    assert record == {"exception_type": "HTTPStatusError", "http_status": 502}


def test_json_decode_error_records_no_doc_or_position():
    record = {}
    _record_exception(record, json.JSONDecodeError(CANARY, CANARY, 0))
    assert record == {"exception_type": "JSONDecodeError", "http_status": None}
