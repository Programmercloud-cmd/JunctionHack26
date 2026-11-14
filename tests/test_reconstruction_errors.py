"""Diagnostic categories survive while source text, credentials and SDK bodies do not."""
import json
import re

from fastapi.testclient import TestClient
from google.genai.errors import APIError
import httpx2
from pydantic import ValidationError
import pytest

from app.documents import DocumentError
from app.main import create_app
from app.providers.gemini import GeminiProvider, ProviderError
from app.reconstruction_errors import LOGGER, reconstruction_error
from test_backend import png
from test_ifc_generate import description


CANARY = "PRIVATE_SOURCE_SECRET_do_not_log_8f6f22"


def events(caplog):
    return [json.loads(record.getMessage()) for record in caplog.records if record.name == LOGGER.name]


def assert_safe(caplog, detail):
    assert CANARY not in detail and CANARY not in caplog.text
    for record in caplog.records:
        if record.name == LOGGER.name:
            assert record.exc_info is None and record.exc_text is None
            event = json.loads(record.getMessage())
            assert re.fullmatch(r"[0-9a-f]{32}", event["diagnostic_id"])
            assert not ({"message", "input", "ctx", "url", "body", "traceback"} & event.keys())


class FakeProvider:
    def __init__(self, error=None, output=None):
        self.error, self.output, self.calls = error, output, 0

    def reconstruct(self, document):
        self.calls += 1
        if self.error:
            raise self.error
        return self.output if self.output is not None else description()

    def review_reconstruction(self,*args,**kwargs):
        from app.review_schema import ReconstructionReview
        return ReconstructionReview(candidate_supported=True,summary="Deterministic diagnostic fixture review")

    def close(self):
        pass


def run_http_failure(tmp_path, provider, caplog):
    app = create_app(provider_factory=lambda:provider, storage_root=tmp_path)
    with TestClient(app) as client:
        # This fixture isolates one explicit generation job. Upload now starts an
        # independent extraction job, covered by test_sourcefirst_jobs instead.
        upload = app.state.documents.add(png(),CANARY+".png").public()
        path = f"/api/documents/{upload['document_id']}/scene"
        response = client.post(path,json={})
        assert response.status_code == 502
        assert isinstance(response.json()["detail"],str)
        assert client.get(path).status_code == 404
        assert client.get(f"/api/documents/{upload['document_id']}/model.ifc").status_code == 404
        document = app.state.documents.get(upload["document_id"])
        assert document.scene is None and document.ifc_bytes is None
    assert len(events(caplog)) == 1
    event = events(caplog)[0]
    detail = response.json()["detail"]
    assert event["diagnostic_id"] in detail and event["category"] in detail and event["phase"] in detail
    assert_safe(caplog,detail)
    return event


@pytest.mark.parametrize("code,category",[(400,"provider_request"),(401,"provider_auth"),(403,"provider_auth"),
    (408,"provider_timeout"),(429,"provider_quota"),(503,"provider_request"),(504,"provider_timeout")])
def test_real_sdk_api_error_has_only_allowlisted_status_and_safe_http_detail(tmp_path,caplog,code,category):
    error = APIError(code,{"error":{"message":CANARY,"status":CANARY,"details":[{"request":CANARY}]}})
    event = run_http_failure(tmp_path,FakeProvider(error=error),caplog)
    assert event["phase"] == "provider" and event["category"] == category
    assert event["http_status"] == code and event["error_type"] == "APIError"


def test_real_httpx2_timeout_does_not_leak_url_headers_or_message(tmp_path,caplog):
    request=httpx2.Request("POST",f"https://example.invalid/{CANARY}",headers={"Authorization":CANARY})
    event=run_http_failure(tmp_path,FakeProvider(error=httpx2.ReadTimeout(CANARY,request=request)),caplog)
    assert event["category"] == "provider_timeout" and event["error_type"] == "TimeoutError"


def test_validation_context_input_and_unknown_location_are_redacted(tmp_path,caplog):
    error=ValidationError.from_exception_data(CANARY,[{
        "type":"value_error","loc":("floors",0,"boundaries",CANARY,"source"),
        "input":{"private":CANARY},"ctx":{"error":ValueError(CANARY)},
    }])
    event=run_http_failure(tmp_path,FakeProvider(error=error),caplog)
    assert event["category"] == "response_schema"
    assert event["validation"] == [{"type":"value_error","location":["floors",0,"boundaries","field","source"]}]


def test_invalid_returned_description_has_distinct_validation_phase(tmp_path,caplog):
    event=run_http_failure(tmp_path,FakeProvider(output={"floors":CANARY,"limitations":[],CANARY:CANARY}),caplog)
    assert event["phase"] == "description" and event["category"] == "response_schema"
    assert {item["type"] for item in event["validation"]} == {"list_type","extra_forbidden"}
    assert any(item["location"] == ["field"] for item in event["validation"])


@pytest.mark.parametrize("phase",["generation","artifact"])
def test_unexpected_post_provider_failure_is_categorized_and_keeps_cache_atomic(tmp_path,caplog,monkeypatch,phase):
    def fail(*args,**kwargs):
        raise RuntimeError(CANARY)
    if phase == "generation":
        monkeypatch.setattr("app.jobs.generate_ifc",fail)
    else:
        monkeypatch.setattr("app.jobs.generate_ifc",lambda *args:b"synthetic artifact")
        monkeypatch.setattr("app.jobs.load_artifact",fail)
    event=run_http_failure(tmp_path,FakeProvider(),caplog)
    assert event["phase"] == phase and event["category"] == {"generation":"generation_failure","artifact":"artifact_failure"}[phase]


@pytest.mark.parametrize("phase",["generation","artifact"])
def test_local_validation_and_timeout_do_not_blame_provider(phase,caplog):
    error=ValidationError.from_exception_data(CANARY,[{"type":"missing","loc":(CANARY,),"input":CANARY}])
    expected={"generation":"generation_failure","artifact":"artifact_failure"}[phase]
    for cause in (error,TimeoutError(CANARY)):
        result=reconstruction_error(cause,phase)
        assert result.category==expected and events(caplog)[-1]["category"]==expected
        assert_safe(caplog,result.message)


@pytest.mark.parametrize("output",["{ malformed "+CANARY,json.dumps({"floors":CANARY,"limitations":[]})])
def test_actual_gemini_sdk_output_parsing_keeps_safe_json_vs_schema_categories(tmp_path,caplog,monkeypatch,output):
    monkeypatch.setenv("GEMINI_API_KEY","offline-only")
    provider=GeminiProvider()
    provider.client._api_client._httpx_client.close()
    def handler(request):
        return httpx2.Response(200,json={"candidates":[{"content":{"parts":[{"text":output}],"role":"model"},"finishReason":"STOP"}]})
    provider.client._api_client._httpx_client=httpx2.Client(transport=httpx2.MockTransport(handler))
    event=run_http_failure(tmp_path,provider,caplog)
    assert event["phase"] == "provider"
    assert event["category"] == ("response_json" if output.startswith("{ malformed") else "response_schema")


@pytest.mark.parametrize("error",[
    ProviderError("Gemini reached its output token limit before completing the response. No result was accepted; try again."),
    DocumentError("Generated IFC exceeds the existing 25 MiB limit; nothing was truncated.",413),
])
def test_known_application_errors_keep_exact_message_type_and_status(error,caplog):
    original_message, original_status = error.message, error.status
    result=reconstruction_error(error,"generation")
    assert result is error and result.message==original_message and result.status==original_status
    event=events(caplog)[0]
    assert "message" not in event and event["http_status"]==original_status
    assert event["error_type"] in {"ProviderError","DocumentError"}


def test_unknown_exception_class_phase_and_http_status_are_not_logged_verbatim(caplog):
    private_type=type(CANARY,(Exception,),{})
    error=reconstruction_error(private_type(CANARY),CANARY)
    event=events(caplog)[0]
    assert event["phase"]=="unknown" and event["error_type"]=="UnexpectedError"
    assert_safe(caplog,error.message)
    caplog.clear()
    error=reconstruction_error(APIError(123456,{"message":CANARY}),"provider")
    assert "http_status" not in events(caplog)[0]
    assert_safe(caplog,error.message)


def test_logging_failure_cannot_replace_reconstruction_failure(monkeypatch):
    def fail(*args,**kwargs):
        raise RuntimeError(CANARY)
    monkeypatch.setattr(LOGGER,"warning",fail)
    error=reconstruction_error(RuntimeError(CANARY),"generation")
    assert error.category=="generation_failure" and CANARY not in error.message


def test_success_and_cached_model_remain_unchanged_without_failure_events(tmp_path,caplog):
    provider=FakeProvider()
    app=create_app(provider_factory=lambda:provider,storage_root=tmp_path)
    with TestClient(app) as client:
        upload=app.state.documents.add(png(),"fixture.png").public()
        path=f"/api/documents/{upload['document_id']}/scene"
        first=client.post(path,json={})
        assert first.status_code==200
        assert client.post(path,json={}).json()==first.json()
        assert client.get(f"/api/documents/{upload['document_id']}/model.ifc").status_code==200
        assert provider.calls==1
    assert events(caplog)==[]
