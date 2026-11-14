"""Deterministic intent fixtures. No fixture result is a live inference claim."""
from copy import deepcopy

from fastapi.testclient import TestClient
import pytest

from app.chat_actions import ChatActionRequest, ChatIntent, WireChatIntent, interpret
from app.main import create_app
from app.scene import Scene
from app.schemas import Usage
from test_backend import png
from test_ifc_generate import description, floor
from test_ifc_import import fixture_model, encode


class IntentFixture:
    def __init__(self):
        self.actions = [{"type": "help"}]
        self.calls = []
        self.closed = 0
        self.error = None
        self.usage = Usage(input_tokens=5, output_tokens=3)

    def interpret_chat_actions(self, message, catalog):
        self.calls.append((message, deepcopy(catalog)))
        if self.error:
            raise self.error
        return {"status": "ready", "actions": self.actions}

    def close(self):
        self.closed += 1


@pytest.fixture
def chat_client(tmp_path):
    provider = IntentFixture()
    app = create_app(provider_factory=lambda: provider, storage_root=tmp_path)
    with TestClient(app) as client:
        yield client, app.state.documents, provider


def saved_drawing(store, *, scene=True):
    doc = store.add(png(), "Fixture assembly drawing.png")
    candidate = doc.snapshot()
    candidate.description = description(floor(label="Assembly floor", rooms=[], boundaries=[], persistent_id="floor-1"))
    candidate.interpretation_status = "complete"
    candidate.reasoning = None
    if scene:
        source = {"kind": "image", "page": 1, "bbox": [.1, .2, .4, .5]}
        elements = []
        for identifier, name, renderable in [("window-1", "Window one", True), ("window-2", "Window two", True), ("window-u", "Unresolved window", False)]:
            elements.append({"id": identifier, "kind": "window", "name": name, "storey_id": "floor-1", "source": source,
                "geometry_origin": "inferred", "representation": "reconstructed" if renderable else "unresolved",
                "geometry": {"type": "box", "center": [0, 0, 1], "size": [1, .1, 1]} if renderable else None})
        candidate.scene = Scene(document_id=doc.id, source_kind="image", units="relative", elements=elements,
            catalog_complete=False, derived=True, floors=[{"id": "floor-1", "label": "Assembly floor", "source": source}])
        candidate.geometry_status = "available"
    return store.commit(candidate, doc.revision_id, status="available" if scene else "source_available")


def payload(doc=None, message="Show all modeled windows.", **workspace):
    return {"message": message, "request_id": "fixture-request", "document_id": doc.id if doc else None,
        "revision_id": doc.revision_id if doc else None,
        "workspace": {"geometry_revision_id": doc.geometry_revision_id if doc and doc.scene else None,
                      "navigation_epoch": 7, **workspace}}


def post(client, provider, body, actions):
    provider.actions = actions
    return client.post("/api/chat/actions", json=body)


def test_selection_keeps_unresolved_separate_and_never_mutates_bundle(chat_client):
    client, store, provider = chat_client
    doc = saved_drawing(store)
    before = store.get(doc.id).snapshot()
    response = post(client, provider, payload(doc), [
        {"type": "show_model"}, {"type": "select", "selector": {"kind": "window"}}])
    assert response.status_code == 200
    result = response.json()
    assert result["actions"][1]["ids"] == ["window-1", "window-2"]
    assert result["actions"][1]["unresolved_ids"] == ["window-u"]
    assert result["navigation_epoch"] == 7 and result["usage"]["input_tokens"] == 5
    assert result["usage"]["latency_ms"] >= 0
    assert len(provider.calls) == 1 and provider.closed == 1
    assert all("source" not in row for row in provider.calls[0][1]["objects"])
    assert store.get(doc.id).revision_id == before.revision_id
    assert store.get(doc.id).scene == before.scene
    assert store.conversation(doc.id) == []
    assert client.app.state.jobs.for_building(doc.id) == []


def test_focused_source_and_question_use_captured_old_geometry_revision(chat_client):
    client, store, provider = chat_client
    old = saved_drawing(store)
    candidate = old.snapshot()
    candidate.geometry_status = "stale"
    newer = store.commit(candidate, old.revision_id, status="source_available")
    body = payload(newer, "What does this window show?", geometry_revision_id=old.revision_id,
                   focused_id="window-1", selected_ids=["window-1"], tour={"ids": ["window-1", "window-2"], "index": 0, "running": False})
    response = post(client, provider, body, [{"type": "show_source", "selector": {"target": "focused"}}])
    assert response.status_code == 200
    action = response.json()["actions"][0]
    assert action["source_revision_id"] == old.revision_id
    assert action["source"]["bbox"] == [.1, .2, .4, .5]
    context = provider.calls[-1][1]
    assert context["current_message"] == body["message"]
    assert context["captured_focus"] == {"object_id": "window-1", "source_revision_id": old.revision_id, "source_kind": "image"}
    response = post(client, provider, body, [{"type": "question", "question": "Invented factual paraphrase", "selector": {"target": "focused"}}])
    action = response.json()["actions"][0]
    assert action["question"] == body["message"]
    assert action["revision_id"] == old.revision_id
    assert action["navigation_reference"]["object_id"] == "window-1"
    assert "Invented" not in response.text


@pytest.mark.parametrize("workspace", [
    {"focused_id": "foreign"}, {"selected_ids": ["foreign"]}, {"floor_id": "foreign"},
    {"tour": {"ids": ["foreign"], "index": 0}},
])
def test_foreign_snapshot_rejected_before_provider(chat_client, workspace):
    client, store, provider = chat_client
    response = post(client, provider, payload(saved_drawing(store), **workspace), [{"type": "help"}])
    assert response.status_code == 409 and provider.calls == []


def test_foreign_action_and_geometryless_tour_are_rejected(chat_client):
    client, store, provider = chat_client
    doc = saved_drawing(store)
    response = post(client, provider, payload(doc), [{"type": "select", "selector": {"ids": ["foreign"]}}])
    assert response.status_code == 422
    response = post(client, provider, payload(doc, tour={"ids": ["window-u"], "index": 0}), [{"type": "tour", "command": "next"}])
    assert response.status_code == 422


def test_duplicate_labels_clarify_without_executing_earlier_actions(chat_client):
    client, store, provider = chat_client
    doc = saved_drawing(store)
    candidate = doc.snapshot()
    candidate.scene.elements[1].name = candidate.scene.elements[0].name
    doc = store.commit(candidate, doc.revision_id, status="available")
    response = post(client, provider, payload(doc), [{"type": "show_model"},
        {"type": "select", "selector": {"target": "named", "label": "Window one"}}])
    result = response.json()
    assert result["status"] == "clarification" and result["actions"] == []
    assert len(result["clarification"]["suggestions"]) == 2


def test_source_only_deferred_selection_requires_explicit_model_request(chat_client):
    client, store, provider = chat_client
    doc = saved_drawing(store, scene=False)
    actions = [{"type": "show_model"}, {"type": "select", "selector": {"kind": "window"}}, {"type": "tour", "command": "start"}]
    result = post(client, provider, payload(doc), actions).json()
    assert result["status"] == "ready"
    assert result["actions"][1]["deferred"] and result["actions"][1]["ids"] == []
    assert client.app.state.jobs.for_building(doc.id) == []
    result = post(client, provider, payload(doc), actions[1:2]).json()
    assert result["status"] == "clarification"


def test_stale_persistent_operations_and_source_membership(chat_client):
    client, store, provider = chat_client
    old = saved_drawing(store, scene=False)
    newer = store.commit(old.snapshot(), old.revision_id, status="source_available")
    for action in [{"type": "reconstruct", "mode": "refine"}, {"type": "show_model"}, {"type": "attach_sources"}]:
        response = post(client, provider, payload(old), [action])
        assert response.status_code == 409
    response = post(client, provider, payload(newer), [{"type": "show_source", "page": 2}])
    assert response.status_code == 422
    response = post(client, provider, payload(newer), [{"type": "show_source", "page": 1}])
    assert response.json()["actions"][0]["source"]["bbox"] is None


def test_refinement_preserves_user_number_unit_reason_without_publishing(chat_client):
    client, store, provider = chat_client
    doc = saved_drawing(store, scene=False)
    edit = {"property": "floor_height", "scope": {"floor_id": "Assembly floor"}, "value": 3, "unit": "m"}
    result = post(client, provider, payload(doc, "Set Assembly floor height to 3 metres."), [{"type": "refine", "edits": [edit]}]).json()
    assert result["status"] == "ready"
    action = result["actions"][0]
    assert action["base_revision_id"] == doc.revision_id
    assert action["edits"][0]["scope"]["floor_id"] == "floor-1"
    assert action["edits"][0]["reason"] == "Provided by user in chat: Set Assembly floor height to 3 metres."
    assert store.get(doc.id).user_values == []
    assert store.get(doc.id).revision_id == doc.revision_id
    for message in ["How tall is this?", "Set height to 4 m.", "Set height to 3."]:
        result = post(client, provider, payload(doc, message), [{"type": "refine", "edits": [edit]}]).json()
        assert result["status"] == "clarification" and not result["actions"]


@pytest.mark.parametrize("message,value,expected", [
    ("Set Assembly floor height to three metres.", 3, "ready"),
    ("Set Assembly floor height to three point five metres.", 3.5, "ready"),
    ("There are 3 rooms; set ceiling height to 2.6 m.", 3, "clarification"),
    ("Set Assembly floor height to 2.6 m.", 2.6, "ready"),
])
def test_supplied_dimension_matches_adjacent_quantity_with_spelled_numbers(chat_client, message, value, expected):
    client, store, provider = chat_client
    doc = saved_drawing(store, scene=False)
    result = post(client, provider, payload(doc, message), [{"type": "refine", "edits": [
        {"property": "floor_height", "scope": {"floor_id": "floor-1"}, "value": value, "unit": "m"}]}]).json()
    assert result["status"] == expected
    assert store.get(doc.id).user_values == []


def test_calibration_requires_user_endpoints_and_retains_original_scope_region(chat_client):
    client, store, provider = chat_client
    doc = saved_drawing(store, scene=False)
    edit = {"property": "calibration", "scope": {"floor_id": "floor-1"},
        "value": {"length": 3, "segment": [[.1, .1], [.5, .1]]}, "unit": "m"}
    result = post(client, provider, payload(doc, "Set calibration to 3 m."), [{"type": "refine", "edits": [edit]}]).json()
    assert result["status"] == "clarification" and "endpoints" in result["message"]
    message = "Set calibration to 3 m between (0.1, 0.1) and (0.5, 0.1)."
    result = post(client, provider, payload(doc, message), [{"type": "refine", "edits": [edit]}]).json()
    assert result["status"] == "ready"
    edit["source"] = {"page": 1, "bbox": [.1, .1, .5, .2]}
    result = post(client, provider, payload(doc, message), [{"type": "refine", "edits": [edit]}]).json()
    assert result["status"] == "clarification" and not result["actions"]
    edit["source"] = {"page": 1, "bbox": [0, 0, 1, 1]}
    result = post(client, provider, payload(doc, message), [{"type": "refine", "edits": [edit]}]).json()
    assert result["status"] == "ready" and result["actions"][0]["edits"][0]["source"]["bbox"] == [0, 0, 1, 1]
    assert store.get(doc.id).description.floors[0].calibration is None


def test_comparison_opacity_uses_existing_control_bounds(chat_client):
    client, store, provider = chat_client
    doc = saved_drawing(store)
    result = post(client, provider, payload(doc), [{"type": "set_comparison", "enabled": True, "opacity": 40}]).json()
    assert result["actions"][0]["opacity"] == 40
    assert post(client, provider, payload(doc), [{"type": "set_comparison", "enabled": True, "opacity": 0}]).status_code == 502


def test_correction_text_is_user_message_not_invented_claim(chat_client):
    client, store, provider = chat_client
    doc = saved_drawing(store, scene=False)
    message = "Please recheck the Assembly floor boundary."
    result = post(client, provider, payload(doc, message), [{"type": "refine", "edits": [
        {"property": "interpretation_correction", "scope": {"floor_id": "floor-1"}, "value": "Invented specific correction"}]}]).json()
    assert result["actions"][0]["edits"][0]["value"] == message
    assert store.get(doc.id).user_values == []


def test_native_geometryless_record_uses_original_record_not_blueprint(chat_client):
    client, store, provider = chat_client
    model, _, window, _ = fixture_model()
    doc = store.add(encode(model), "native-fixture.ifc")
    response = post(client, provider, payload(doc, focused_id=window.GlobalId), [{"type": "show_source"}])
    assert response.status_code == 200
    source = response.json()["actions"][0]["source"]
    assert source["kind"] == "ifc" and source["global_id"] == window.GlobalId and source["page"] is None
    result = post(client, provider, payload(doc), [{"type": "select", "selector": {"kind": "window"}}]).json()
    assert result["actions"][0]["ids"] == [] and result["actions"][0]["unresolved_ids"] == [window.GlobalId]
    assert post(client, provider, payload(doc), [{"type": "show_source", "page": 1}]).status_code == 422


def test_schema_errors_and_provider_failures_are_safe_and_close_provider(chat_client):
    client, store, provider = chat_client
    doc = saved_drawing(store)
    response = post(client, provider, payload(doc), [{"type": "set_theme", "theme": "dark", "code": "never execute"}])
    assert response.status_code == 502 and "code" not in response.json()["detail"]
    provider.error = RuntimeError("PRIVATE_PROVIDER_PAYLOAD_SENTINEL")
    response = client.post("/api/chat/actions", json=payload(doc))
    assert response.status_code == 502 and "SENTINEL" not in response.text
    assert provider.closed == 2 and store.get(doc.id).revision_id == doc.revision_id


@pytest.mark.parametrize("workspace", [
    {"cutaway": 101}, {"exploded": 1.2}, {"camera": {"position": [0, 0, 0], "target": [0, 0, 0], "up": [0, 0, 1]}},
    {"tour": {"ids": [], "index": 0}},
])
def test_invalid_snapshot_shape_never_calls_provider(chat_client, workspace):
    client, _, provider = chat_client
    assert client.post("/api/chat/actions", json=payload(**workspace)).status_code == 422
    assert not provider.calls


@pytest.mark.parametrize("method", ["_generate", "_parse"])
def test_reuses_selected_provider_transport_with_text_only_navigation_document(method):
    calls = []
    class Transport:
        pass
    provider = Transport()
    def generate(document, question, instruction, schema, **kwargs):
        calls.append((document, question, instruction, kwargs))
        return schema.model_validate({"actions": [{"type": "help"}]})
    setattr(provider, method, generate)
    request = ChatActionRequest.model_validate(payload(message="Help"))
    result = interpret(provider, request, {"authority": "Navigation only", "objects": []})
    assert isinstance(result, ChatIntent) and len(calls) == 1
    document, question, instruction, kwargs = calls[0]
    assert document.pages == [] and document.scene is None and document.description is None
    assert question == "Help" and kwargs["include_qa_context"] is False
    assert kwargs["extra_data"]["authority"] == "Navigation only"


def test_wire_action_uses_one_type_enum_and_strict_canonical_conversion():
    from pydantic import ValidationError
    schema = WireChatIntent.model_json_schema()
    items = schema["properties"]["actions"]["items"]
    assert "$ref" in items and "anyOf" not in items and "oneOf" not in items
    types = schema["$defs"]["WireAction"]["properties"]["type"]["enum"]
    assert {"show_source", "show_model", "select", "question", "refine"} <= set(types)
    result = WireChatIntent.model_validate({"actions": [
        {"type": "show_source", "selector": {"target": "focused"}, "mode": None, "edits": None}]}).canonical()
    assert result.actions[0].type == "show_source" and result.actions[0].selector.target == "focused"
    # Flattening grammar must not allow a known but unrelated field through.
    with pytest.raises(ValidationError):
        WireChatIntent.model_validate({"actions": [{"type": "show_source", "mode": "model"}]}).canonical()
    with pytest.raises(ValidationError):
        WireChatIntent.model_validate({"actions": [{"type": "refine"}]}).canonical()
