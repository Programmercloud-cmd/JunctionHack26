"""OpenAI's real Responses SDK against injected HTTP, without provider inference."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from time import monotonic

import httpx2
import openai
import pytest

from app.agent_chat import AgentRoute, ConversationResponse
from app.agent_render import RenderReview
from app.building import BuildingDescription
from app.documents import DocumentStore
from app.providers.gemini import ProviderError
from app.providers.openai import OpenAIProvider, openai_wire_schema
from app.review_schema import AnswerReview, DescriptionPatch
from app.schemas import AgentTechnicalResponse, CropRequest, DraftAnswer, GateResult
from test_backend import png
from test_ifc_generate import description, region, room


CANARY = "PRIVATE_OPENAI_FIXTURE_NOT_A_REAL_KEY"
CONFIG = {"api_key": CANARY, **{key: "gpt-6.1-sol" for key in (
    "model", "advanced_model", "interpretation_model", "reconstruction_model", "render_model")},
    **{key: "gpt-6-luna" for key in (
        "basic_model", "router_model", "ui_model", "clarification_model", "decision_model")}}
ANSWER = {"status": "answered", "answer": "One room is depicted.", "evidence": [{
    "page": 1, "bbox": [0, 0, 1, 1], "label": "Original", "observation": "Synthetic room"}]}


def response(output, *, status="completed", reason=None, refusal=False):
    text = output if isinstance(output, str) else json.dumps(output)
    content = [{"type": "refusal", "refusal": CANARY}] if refusal else [
        {"type": "output_text", "text": text, "annotations": []}]
    return {"id": "resp_fixture", "object": "response", "created_at": 0,
            "model": "fixture", "status": status,
            "incomplete_details": {"reason": reason} if reason else None,
            "output": [{"type": "reasoning", "id": "private_reasoning", "summary": [],
                        "content": [{"type": "reasoning_text", "text": CANARY}]},
                       {"type": "message", "id": "msg_fixture", "role": "assistant",
                        "status": "completed", "content": content}],
            "usage": {"input_tokens": 30, "output_tokens": 12, "total_tokens": 42,
                      "output_tokens_details": {"reasoning_tokens": 3}}}


class Harness:
    def __init__(self):
        self.calls = []
        self.outputs = []

        def handler(request):
            self.calls.append((json.loads(request.content), request.extensions["timeout"]))
            output = self.outputs.pop(0)
            if isinstance(output, Exception):
                raise output
            status, body = output if isinstance(output, tuple) else (200, response(output))
            return httpx2.Response(status, json=body)

        self.client = openai.OpenAI(api_key=CANARY, max_retries=0,
            http_client=httpx2.Client(transport=httpx2.MockTransport(handler)))
        self.provider = OpenAIProvider(config=CONFIG, client=self.client)


@pytest.fixture
def setup(tmp_path):
    harness = Harness()
    store = DocumentStore(tmp_path)
    document = store.add(png(), "source.png")
    document.revision_id = "r1"
    try:
        yield harness, document
    finally:
        harness.provider.close()
        store.close()


def content(body):
    return body["input"][0]["content"]


def text(body):
    return "\n".join(part.get("text", "") for part in content(body))


def test_strict_schema_keeps_nullable_types_and_typed_patch_records():
    original = DescriptionPatch.model_json_schema()
    before = deepcopy(original)
    wire = openai_wire_schema(original)
    assert original == before
    assert '"discriminator"' not in json.dumps(wire)
    assert '"oneOf"' not in json.dumps(wire)
    assert '"default"' not in json.dumps(wire)
    record = wire["$defs"]["RecordPatch"]["properties"]["record"]
    assert record["anyOf"][0] == {"$ref": "#/$defs/RoomDescription"}
    assert {"type": "null"} in record["anyOf"]
    assert wire["$defs"]["FloorMetadataUpdate"]["properties"]["changes"]["type"] == "array"
    assert wire["$defs"]["RoomDescription"]["required"] == list(wire["$defs"]["RoomDescription"]["properties"])
    assert wire["$defs"]["PageRegion"]["additionalProperties"] is False
    # Schema keyword handling must not rewrite a data property named default/const.
    custom = {"type": "object", "properties": {"default": {"type": "string", "default": "x"},
              "const": {"type": "integer", "const": 2}}, "enum": [{"default": "retain"}]}
    adapted = openai_wire_schema(custom)
    assert adapted["properties"]["default"] == {"type": "string"}
    assert adapted["properties"]["const"] == {"type": "integer", "enum": [2]}
    assert adapted["enum"] == [{"default": "retain"}]


def test_ref_siblings_are_inlined_without_losing_annotation_or_constraints():
    original = {
        "type": "object", "properties": {
            "evidence": {"$ref": "#/$defs/Region", "description": "Original inspected evidence"},
            "optional": {"anyOf": [{"$ref": "#/$defs/Region", "description": "Nullable evidence"}, {"type": "null"}]},
        },
        "$defs": {"Region": {"type": "object", "properties": {
            "page": {"type": "integer", "minimum": 1},
            "bbox": {"type": "array", "items": {"type": "number", "minimum": 0, "maximum": 1},
                     "minItems": 4, "maxItems": 4},
        }, "required": ["page", "bbox"], "additionalProperties": False}},
    }
    before = deepcopy(original)
    wire = openai_wire_schema(original)
    evidence = wire["properties"]["evidence"]
    assert "$ref" not in evidence and evidence["description"] == "Original inspected evidence"
    assert evidence["properties"] == wire["$defs"]["Region"]["properties"]
    assert evidence["properties"]["page"]["minimum"] == 1
    assert evidence["properties"]["bbox"]["maxItems"] == 4
    assert evidence["properties"]["bbox"]["items"]["maximum"] == 1
    assert wire["properties"]["optional"]["anyOf"][1] == {"type": "null"}
    assert wire["properties"]["optional"]["anyOf"][0]["description"] == "Nullable evidence"
    assert original == before

    def check(node):
        if isinstance(node, dict):
            if "$ref" in node:
                assert set(node) == {"$ref"}
            for value in node.values():
                check(value)
        elif isinstance(node, list):
            for value in node:
                check(value)
    for schema in (BuildingDescription, DescriptionPatch, RenderReview):
        check(openai_wire_schema(schema.model_json_schema()))


def test_router_and_conversation_are_explicit_normal_openai_models(setup):
    h, _ = setup
    h.outputs.extend([{"tool": "technical_basic"}, {"message": "Hello", "ui_request": "Look down"}])
    assert isinstance(h.provider.route_agent("Exact user's message", {"history": []}), AgentRoute)
    assert isinstance(h.provider.converse_agent("Hello and look down", {}), ConversationResponse)
    assert [call[0]["model"] for call in h.calls] == [CONFIG["router_model"], CONFIG["basic_model"]]
    assert all(body["store"] is False and body["text"]["format"]["strict"] for body, _ in h.calls)
    assert all(not any(p["type"] == "input_image" for p in content(body)) for body, _ in h.calls)
    assert '"question": "Exact user\'s message"' in text(h.calls[0][0])
    assert h.provider.last_response_text == json.dumps({"message": "Hello", "ui_request": "Look down"})
    assert CANARY not in h.provider.last_response_text
    assert h.provider.usage.input_tokens == 60 and h.provider.usage.output_tokens == 24
    assert h.provider.provider_calls[-1]["candidate_tokens"] == 9
    assert h.provider.provider_calls[-1]["thought_tokens"] == 3


def test_technical_worker_uses_originals_and_openai_budgets(setup, monkeypatch):
    h, document = setup
    monkeypatch.setenv("GEMINI_AGENT_ANSWER_TOKENS", "17")
    monkeypatch.setenv("OPENAI_AGENT_ANSWER_TOKENS", "9000")
    monkeypatch.setenv("OPENAI_AGENT_ANSWER_SECONDS", "61")
    monkeypatch.setenv("OPENAI_ADVANCED_REASONING_EFFORT", "high")
    h.outputs.append({"draft": ANSWER, "clarification": None, "ui_request": None})
    result = h.provider.answer_agent(document, "What is depicted?")
    assert isinstance(result, AgentTechnicalResponse) and result.draft.answer == ANSWER["answer"]
    body, timeout = h.calls[0]
    assert body["model"] == "gpt-6.1-sol" and body["max_output_tokens"] == 9000
    assert body["reasoning"] == {"effort": "high"} and timeout["read"] == 61
    images = [p for p in content(body) if p["type"] == "input_image"]
    assert len(images) == 1 and images[0]["image_url"].startswith("data:image/png;base64,")
    assert "Original source page 1" in text(body)


def test_ui_worker_still_returns_canonical_validated_navigation(setup):
    h, _ = setup
    h.outputs.append({"status": "ready", "actions": [{"type": "set_camera", "preset": "top"}]})
    result = h.provider.interact_agent("Look down", {"objects": [], "workspace": {}}, ui_request="Use top camera")
    assert result.canonical().actions[0].type == "set_camera"
    assert h.calls[0][0]["model"] == CONFIG["ui_model"]
    assert "Use top camera" in text(h.calls[0][0])


def test_decisions_use_normal_responses_model_with_original_crop_and_null_confidence(setup):
    h, document = setup
    h.outputs.extend([{"sufficiency": {"choice": "unclear", "confidence": None}},
                      {"support": {"choice": "supported", "confidence": None}}])
    crop = CropRequest(page=1, bbox=[.1, .1, .5, .5], reason="Inspect source")
    gate = h.provider.gate(document, "What is the height?", crop)
    assert gate == GateResult(decision="unclear")
    draft = DraftAnswer(status="unclear", answer="The drawing is ambiguous.")
    result = h.provider.review_answer(document, "Height?", draft, gate, crop, validation={"errors": []})
    assert result == AnswerReview(decision="supported")
    for body, _ in h.calls:
        assert body["model"] == CONFIG["decision_model"]
        assert len([p for p in content(body) if p["type"] == "input_image"]) == 2
        assert "Original source page 1" in text(body) and "Detail crop" in text(body)
        assert "decision_questions" in text(body)
    assert "The drawing is ambiguous" in text(h.calls[1][0])
    assert "validation" in text(h.calls[1][0])
    assert [r["schema"] for r in h.provider.provider_calls] == ["GateResult", "AnswerReview"]


def test_non_null_invented_decision_confidence_is_rejected(setup):
    h, document = setup
    h.outputs.append({"sufficiency": {"choice": "sufficient", "confidence": .99}})
    with pytest.raises(ProviderError, match="invalid structured response"):
        h.provider.gate(document, "Question")


def test_native_decision_catalog_is_preserved_without_image_invention(setup, monkeypatch):
    h, document = setup
    monkeypatch.setattr("app.reasoning.native_count_decision_context", lambda *_: {
        "catalog_complete": True, "records": [{"global_id": "original-native-id", "ifc_class": "IfcWindow"}]})
    document.pages = []
    h.outputs.append({"sufficiency": {"choice": "sufficient", "confidence": None}})
    assert h.provider.gate(document, "How many windows?").decision == "sufficient"
    body = h.calls[0][0]
    assert '"global_id":"original-native-id"' in text(body)
    assert '"catalog_complete":true' in text(body)
    assert not any(p["type"] == "input_image" for p in content(body))


def test_constructor_does_not_initialize_gemini_sdk(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Gemini client must not be constructed")
    monkeypatch.setattr("app.providers.gemini.genai.Client", forbidden)
    h = Harness()
    try:
        assert h.provider.client is h.client
    finally:
        h.provider.close()


def test_typed_patch_and_actual_ifc_overlay_use_same_sources(setup):
    h, document = setup
    output = {"base_revision_id": "r1", "operations": [{"action": "add", "collection": "rooms",
        "record": room(), "evidence": region(), "reason": "Source-supported fixture"}],
        "floor_metadata_updates": [{"floor_id": "floor", "changes": [{"field": "label", "value": "Level"}],
          "evidence": region(), "reason": "Printed floor label"}]}
    h.outputs.append(output)
    patch = h.provider._generate(document, "Correct this", "Inspect actual IFC overlays.", DescriptionPatch,
        include_qa_context=False, extra_views=[("ACTUAL REOPENED IFC", png())],
        extra_data={"base_revision_id": "r1", "user_values": [{"value": 3, "unit": "m"}]})
    assert patch.operations[0].record.label == "Room"
    assert patch.floor_metadata_updates[0].changes[0].value == "Level"
    body = h.calls[0][0]
    assert len([p for p in content(body) if p["type"] == "input_image"]) == 2
    assert "ACTUAL REOPENED IFC" in text(body) and '"user_values"' in text(body)
    assert "JSON-encoded STRING" not in body["instructions"]


def test_three_separate_clients_can_create_then_review_in_parallel(setup):
    h, document = setup
    reviewers = [Harness(), Harness()]
    h.outputs.append(description().model_dump(mode="json"))
    for reviewer in reviewers:
        reviewer.outputs.append({"candidate_supported": True, "satisfied": True, "summary": "Fixture only"})
    try:
        assert len({id(h.client), *(id(r.client) for r in reviewers)}) == 3
        candidate = h.provider.extract_interpretation(document, include_geometry=True)
        assert isinstance(candidate, BuildingDescription)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(r.provider._generate, document, "Review", "Inspect independently.", RenderReview,
                model=r.provider.reconstruction_model, extra_views=[("ACTUAL REOPENED IFC", png())],
                extra_data={"candidate_digest": "same-digest"}) for r in reviewers]
            assert all(f.result().satisfied for f in futures)
        assert [r.provider.provider_calls[0]["model"] for r in reviewers] == ["gpt-6.1-sol"] * 2
        assert all("same-digest" in text(r.calls[0][0]) for r in reviewers)
    finally:
        for reviewer in reviewers:
            reviewer.provider.close()


def test_deadline_is_clamped_and_expired_deadline_makes_no_request(setup):
    h, document = setup
    h.outputs.append({"page": 1, "bbox": [0, 0, 1, 1], "reason": "Inspect"})
    h.provider.request_deadline = monotonic() + 7
    h.provider.choose_crop(document, "Inspect")
    assert 0 < h.calls[0][1]["read"] <= 7
    h.provider.request_deadline = monotonic() - 1
    with pytest.raises(ProviderError, match="budget"):
        h.provider.choose_crop(document, "Inspect")
    assert len(h.calls) == 1


@pytest.mark.parametrize("status,label", [(400, "BadRequestError"), (401, "AuthenticationError"),
    (403, "PermissionDeniedError"), (404, "NotFoundError"), (429, "RateLimitError"), (503, "InternalServerError")])
def test_api_errors_are_safe_without_hidden_retries(setup, status, label):
    h, document = setup
    h.outputs.append((status, {"error": {"message": CANARY, "type": "invalid_request_error", "code": CANARY}}))
    with pytest.raises(ProviderError) as error:
        h.provider.choose_crop(document, "Inspect")
    assert CANARY not in str(error.value.message)
    assert len(h.calls) == 1
    call = h.provider.provider_calls[0]
    assert call["exception_type"] == label and call["http_status"] == status
    assert CANARY not in json.dumps(h.provider.provider_calls)


def test_transport_timeout_is_an_operational_failure_without_retry(setup):
    h, document = setup
    h.outputs.append(httpx2.ReadTimeout(CANARY))
    with pytest.raises(ProviderError) as error:
        h.provider.choose_crop(document, "Inspect")
    assert error.value.status == 504 and CANARY not in error.value.message
    assert len(h.calls) == 1 and h.provider.provider_calls[0]["outcome"] == "provider_timeout"


@pytest.mark.parametrize("status,reason", [("incomplete", "max_output_tokens"),
    ("incomplete", "content_filter"), ("failed", None)])
def test_incomplete_valid_json_is_never_accepted(setup, status, reason):
    h, document = setup
    h.outputs.append((200, response({"page": 1, "bbox": [0, 0, 1, 1], "reason": "Inspect"}, status=status, reason=reason)))
    with pytest.raises(ProviderError) as error:
        h.provider.choose_crop(document, "Inspect")
    assert h.provider.last_structured_output is None
    assert len(h.calls) == 1
    if reason == "max_output_tokens":
        assert error.value.category == "provider_output_limit"
        assert h.provider.provider_calls[0]["outcome"] == "output_limit"


def test_refusal_text_is_not_echoed_or_accepted(setup):
    h, document = setup
    h.outputs.append((200, response({}, refusal=True)))
    with pytest.raises(ProviderError, match="declined") as error:
        h.provider.choose_crop(document, "Inspect")
    assert CANARY not in error.value.message and h.provider.last_response_text is None


def test_invalid_json_is_safe_and_not_an_evidence_judgment(setup):
    h, document = setup
    h.outputs.append(CANARY)
    with pytest.raises(ProviderError, match="invalid structured response") as error:
        h.provider.choose_crop(document, "Inspect")
    assert CANARY not in error.value.message
    assert h.provider.provider_calls[0]["outcome"] == "response_json_rejected"


def test_draft_format_repairs_once_with_same_evidence_and_safe_hints(setup, monkeypatch):
    h, document = setup
    monkeypatch.setenv("OPENAI_DRAFT_SECONDS", "67")
    monkeypatch.setenv("GEMINI_DRAFT_SECONDS", "1")
    invalid = deepcopy(ANSWER)
    invalid["evidence"][0]["bbox"] = [0, 0, 2, 1]
    invalid[CANARY] = CANARY
    h.outputs.extend([invalid, ANSWER])
    result = h.provider.answer(document, "Count rooms", GateResult(decision="sufficient"))
    assert result.answer == ANSWER["answer"] and len(h.calls) == 2
    assert all(timeout["read"] == 67 for _, timeout in h.calls)
    assert CANARY not in h.calls[1][0]["instructions"]
    assert "validation issues" in h.calls[1][0]["instructions"]
    original_images = [p for p in content(h.calls[0][0]) if p["type"] == "input_image"]
    repaired_images = [p for p in content(h.calls[1][0]) if p["type"] == "input_image"]
    assert original_images == repaired_images
    h.outputs.extend([invalid, invalid])
    with pytest.raises(ProviderError, match="OpenAI returned an answer in an invalid format after one retry"):
        h.provider.answer(document, "Count rooms", None)
    assert len(h.calls) == 4


def test_missing_key_never_constructs_a_provider_or_falls_back():
    with pytest.raises(ProviderError, match="OPENAI_API_KEY"):
        OpenAIProvider(config=CONFIG | {"api_key": ""})
