from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
import json

from fastapi.testclient import TestClient
from PIL import Image
import pypdfium2 as pdfium
import pytest

from app.documents import DocumentStore, MAX_UPLOAD
from app.main import create_app
from app.provider import GeminiProvider, views
from app.schemas import CropRequest, DraftAnswer, GateResult, Usage


def png():
    buffer = BytesIO()
    Image.new("RGB", (100, 80), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def pdf(pages=1):
    document = pdfium.PdfDocument.new()
    for _ in range(pages):
        page = document.new_page(200, 100)
        page.close()
    buffer = BytesIO()
    document.save(buffer)
    document.close()
    return buffer.getvalue()


def evidence(page=1, bbox=None):
    return {"page": page, "bbox": bbox or [0, 0, 1, 1], "label": "Plan", "observation": "No windows shown"}


class FakeProvider:
    def __init__(self, decisions=("sufficient",), draft=None):
        self.decisions = iter(decisions)
        self.calls = []
        self.usage = Usage(input_tokens=20, output_tokens=10)
        self.draft = draft or DraftAnswer(status="answered", answer="0 windows", evidence=[evidence()])

    def gate(self, document, question, crop=None):
        self.calls.append(("gate", crop))
        return GateResult(decision=next(self.decisions), confidence=.9)

    def choose_crop(self, document, question):
        self.calls.append(("crop", None))
        return CropRequest(page=1, bbox=[0, 0, .5, .5], reason="Inspect symbols")

    def answer(self, document, question, gate, crop=None):
        self.calls.append(("answer", crop))
        return self.draft.model_copy(deep=True)

    def close(self):
        pass


@pytest.fixture
def app_client(tmp_path):
    fake = FakeProvider()
    with TestClient(create_app(provider_factory=lambda: fake, storage_root=tmp_path)) as client:
        yield client, fake


def upload(client, content=None, name="plan.png"):
    response = client.post("/api/documents", files={"file": (name, content or png())})
    assert response.status_code == 200, response.text
    return response.json()


def ask(client, document):
    return client.post("/api/ask", json={"document_id": document["document_id"], "question": "How many windows?"})


def test_upload_and_answer_with_zero_count_citation(app_client):
    client, fake = app_client
    document = upload(client)
    preview = client.get(document["pages"][0]["image_url"])
    assert preview.status_code == 200
    assert preview.headers["content-type"] == "image/png"
    response = ask(client, document)
    assert response.status_code == 200
    assert response.json()["status"] == "answered"
    assert response.json()["inspected_pages"] == [1]
    assert response.json()["evidence"][0]["bbox"] == [0, 0, 1, 1]
    assert [name for name, _ in fake.calls] == ["gate", "answer"]


def test_pdf_all_pages_and_page_two_evidence(app_client):
    client, fake = app_client
    document = upload(client, pdf(2), "plan.pdf")
    assert len(document["pages"]) == 2
    fake.draft = DraftAnswer(status="answered", answer="0 windows on page two", evidence=[evidence(page=2)])
    response = ask(client, document)
    assert response.status_code == 200
    assert response.json()["inspected_pages"] == [1, 2]
    assert response.json()["evidence"][0]["page"] == 2


def test_oversized_pdf_rejected_not_truncated(app_client):
    client, _ = app_client
    response = client.post("/api/documents", files={"file": ("six.pdf", pdf(6))})
    assert response.status_code == 413


@pytest.mark.parametrize("content,name,status", [(b"not a picture", "plan.jpg", 400), (b"", "empty.png", 400),
                                                  (b"x" * (MAX_UPLOAD + 1), "large.png", 413)])
def test_invalid_uploads(app_client, content, name, status):
    client, _ = app_client
    assert client.post("/api/documents", files={"file": (name, content)}).status_code == status


def test_pixel_limit_precedes_decode(app_client, monkeypatch):
    import app.documents
    client, _ = app_client
    monkeypatch.setattr(app.documents, "MAX_PIXELS", 100)
    assert client.post("/api/documents", files={"file": ("plan.png", png())}).status_code == 413


def test_exif_orientation_normalized(app_client):
    client, _ = app_client
    image = Image.new("RGB", (100, 80), "white")
    exif = Image.Exif()
    exif[274] = 6
    buffer = BytesIO()
    image.save(buffer, format="JPEG", exif=exif)
    document = upload(client, buffer.getvalue(), "rotated.jpg")
    assert (document["pages"][0]["width"], document["pages"][0]["height"]) == (80, 100)


def test_insufficient_cannot_turn_into_answer(app_client):
    client, fake = app_client
    fake.decisions = iter(["insufficient"])
    response = ask(client, upload(client))
    assert response.status_code == 502


def test_insufficient_scoped_explanation(app_client):
    client, fake = app_client
    fake.decisions = iter(["insufficient"])
    fake.draft = DraftAnswer(status="insufficient", answer="Height is absent from this plan.",
                            missing_information=["Ceiling height"], next_action="Upload a section drawing.")
    response = ask(client, upload(client))
    assert response.status_code == 200
    assert response.json()["status"] == "insufficient"
    assert response.json()["missing_information"] == ["Ceiling height"]


def test_unclear_gets_one_real_crop_and_stays_unclear(app_client):
    client, fake = app_client
    fake.decisions = iter(["unclear", "unclear"])
    fake.draft = DraftAnswer(status="unclear", answer="The symbol remains ambiguous.")
    response = ask(client, upload(client))
    assert response.status_code == 200
    assert response.json()["inspection_passes"] == 2
    assert response.json()["status"] == "unclear"
    assert [name for name, _ in fake.calls] == ["gate", "crop", "gate", "answer"]
    assert fake.calls[2][1].bbox == [0, 0, .5, .5]


def test_sufficient_may_downgrade(app_client):
    client, fake = app_client
    fake.draft = DraftAnswer(status="insufficient", answer="A scale is missing.")
    response = ask(client, upload(client))
    assert response.status_code == 200
    assert response.json()["status"] == "insufficient"


def test_malformed_evidence_and_missing_citations_not_accepted(app_client):
    client, fake = app_client
    fake.draft.evidence = []
    assert ask(client, upload(client)).status_code == 502
    fake.decisions = iter(["sufficient"])
    fake.draft = DraftAnswer(status="answered", answer="1", evidence=[evidence(page=2)])
    response = ask(client, upload(client))
    assert response.status_code == 502
    assert "uninspected page" in response.json()["detail"]


def test_unclear_can_resolve_after_one_crop(app_client):
    client, fake = app_client
    fake.decisions = iter(["unclear", "sufficient"])
    response = ask(client, upload(client))
    assert response.status_code == 200
    assert response.json()["status"] == "answered"
    assert response.json()["inspection_passes"] == 2
    assert [name for name, _ in fake.calls] == ["gate", "crop", "gate", "answer"]


def test_whole_page_repeat_does_not_count_as_new_inspection(app_client):
    client, fake = app_client
    fake.decisions = iter(["unclear"])
    fake.choose_crop = lambda *args: CropRequest(page=1, bbox=[0, 0, 1, 1], reason="Whole page")
    fake.draft = DraftAnswer(status="unclear", answer="The question remains ambiguous.")
    response = ask(client, upload(client))
    assert response.status_code == 200
    assert response.json()["status"] == "unclear"
    assert response.json()["inspection_passes"] == 1
    assert [name for name, _ in fake.calls] == ["gate", "answer"]


@pytest.mark.parametrize("bbox", [[0, 0, 2, 1], [0, 0, 0, 1], [0, 1, 1, 0], [0, 0, float('nan'), 1]])
def test_evidence_bounds(bbox):
    with pytest.raises(ValueError):
        DraftAnswer(status="answered", answer="1", evidence=[evidence(bbox=bbox)])


def test_calculation_computed_from_cited_operands(app_client):
    client, fake = app_client
    fake.draft = DraftAnswer(status="answered", answer="Area is {result} m².", evidence=[evidence()],
                            calculation={"operation": "product", "operands": [{"value": 3, "evidence_index": 0},
                                         {"value": 4, "evidence_index": 0}], "unit": "m²"})
    response = ask(client, upload(client))
    assert response.status_code == 200
    assert response.json()["answer"] == "Area is 12 m²."


def test_provider_failure_is_operational_and_sanitized(app_client):
    client, fake = app_client
    def fail(*args, **kwargs):
        raise RuntimeError("secret-provider-body-do-not-expose")
    fake.gate = fail
    response = ask(client, upload(client))
    assert response.status_code == 502
    assert "secret-provider" not in response.text
    assert "status" not in response.json()


def test_missing_credentials_and_health(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with TestClient(create_app(storage_root=tmp_path)) as client:
        assert client.get("/api/health").json()["provider_ready"] is False
        response = ask(client, upload(client))
        assert response.status_code == 503
        assert "GEMINI_API_KEY" in response.json()["detail"]


def test_question_validation_and_missing_document(app_client):
    client, _ = app_client
    assert client.post("/api/ask", json={"document_id": "missing", "question": " "}).status_code == 422
    assert client.post("/api/ask", json={"document_id": "missing", "question": "How many?"}).status_code == 404


def test_real_sdk_serializes_gate_crop_and_answer(tmp_path, monkeypatch):
    """Use actual SDK serialization and parsing, intercepting only HTTP transport."""
    import httpx2
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real")
    requests = []
    draft = DraftAnswer(status="answered", answer="0 windows", evidence=[evidence()])
    def handler(request):
        body = json.loads(request.content)
        requests.append((str(request.url), body))
        if str(request.url).endswith("/decisions"):
            assert set(body["questions"]) == {"sufficiency"}
            assert any(block["type"] == "image" and block["data"] for block in body["input"])
            return httpx2.Response(200, json={"answers": {"sufficiency": {"type": "choice", "choice": "sufficient",
                                  "confidence": .8, "probabilities": {"sufficient": .8, "insufficient": .1, "unclear": .1}}},
                                  "usage": {"total_input_tokens": 10, "total_output_tokens": 0}})
        assert body["generationConfig"]["responseMimeType"] == "application/json"
        schema = body["generationConfig"].get("responseSchema") or body["generationConfig"].get("responseJsonSchema")
        assert schema
        output = {"page": 1, "bbox": [0, 0, .5, .5], "reason": "Look closer"} if len(requests) == 2 else draft.model_dump()
        return httpx2.Response(200, json={"candidates": [{"content": {"parts": [{"text": json.dumps(output)}], "role": "model"},
                                                     "finishReason": "STOP"}],
                                       "usageMetadata": {"promptTokenCount": 20, "candidatesTokenCount": 5}})
    provider = GeminiProvider()
    provider.client._api_client._httpx_client.close()
    provider.client._api_client._httpx_client = httpx2.Client(transport=httpx2.MockTransport(handler))
    store = DocumentStore(tmp_path)
    try:
        document = store.add(png(), "plan.png")
        gate = provider.gate(document, "How many windows?")
        crop = provider.choose_crop(document, "How many windows?")
        result = provider.answer(document, "How many windows?", gate, crop)
        assert result.answer == "0 windows"
        assert len(requests) == 3
        assert provider.usage.input_tokens == 50
        assert len(views(document, crop)) == 2
    finally:
        provider.close()
        store.close()
