"""Scene/API provenance tests; no model inference or reconstruction service required."""
from io import BytesIO
import json

from fastapi.testclient import TestClient
import ifcopenshell
from PIL import Image
import pytest

from app.documents import Document, Page
from app.highlights import validated_highlights, whole_model_count_kind
from app.main import create_app
from app.scene import Assumption, Geometry, Property, Scene, SceneElement, SourceRef
from app.schemas import DraftAnswer, GateResult, Usage
from app.service import ask, validate_draft
from app.provider import ProviderError
from app.source_context import source_context


def model_bytes():
    model = ifcopenshell.file(schema="IFC4")
    unit = model.create_entity("IfcSIUnit", UnitType="LENGTHUNIT", Name="METRE")
    units = model.create_entity("IfcUnitAssignment", Units=(unit,))
    model.create_entity("IfcProject", GlobalId=ifcopenshell.guid.new(), UnitsInContext=units)
    model.create_entity("IfcWall", GlobalId=ifcopenshell.guid.new(), Name="Wall A")
    model.create_entity("IfcWallStandardCase", GlobalId=ifcopenshell.guid.new(), Name="Wall B")
    return model.to_string().encode()


class Provider:
    # This legacy fixture tests pre-review behavior; reviewed QA has dedicated fixtures.
    legacy_fixture_without_review = True
    def __init__(self, decision="sufficient", draft=None):
        self.decision = decision
        self.draft = draft
        self.calls = []
        self.usage = Usage()

    def gate(self, document, question, crop=None):
        self.calls.append("gate")
        return GateResult(decision=self.decision, confidence=None)

    def answer(self, document, question, gate, crop=None):
        self.calls.append("answer")
        assert self.draft is not None, "Deterministic count unexpectedly asked a model to generate the answer"
        return self.draft.model_copy(deep=True)

    def choose_crop(self, *args):
        raise AssertionError("Native IFC must not request image crops")

    def close(self):
        pass


@pytest.fixture
def client(tmp_path):
    provider = Provider()
    with TestClient(create_app(provider_factory=lambda: provider, storage_root=tmp_path)) as client:
        yield client, provider


def upload_ifc(client):
    result = client.post("/api/documents", files={"file": ("model.ifc", model_bytes(), "application/octet-stream")})
    assert result.status_code == 200, result.text
    return result.json()


def question(client, document, text):
    return client.post("/api/ask", json={"document_id": document["document_id"], "question": text})


def test_ifc_upload_scene_api_reuses_scene_without_inference(client):
    http, provider = client
    document = upload_ifc(http)
    assert document["kind"] == "ifc" and document["pages"] == []
    scene = http.get(document["scene_url"])
    assert scene.status_code == 200
    assert scene.json()["catalog_complete"] is True
    assert scene.json()["units"] == "m"
    assert len(scene.json()["elements"]) == 2
    assert all(element["geometry"] is None for element in scene.json()["elements"])
    assert http.post(document["scene_url"], json={"page": 1}).json() == scene.json()
    assert provider.calls == []
    assert http.get(f"/api/documents/{document['document_id']}/pages/1").status_code == 404


def test_supported_count_uses_gate_then_catalog_including_geometryless_elements(client):
    http, provider = client
    document = upload_ifc(http)
    result = question(http, document, "How many walls are in this model?")
    assert result.status_code == 200, result.text
    answer = result.json()
    assert answer["status"] == "answered" and answer["answer"].startswith("2 walls")
    assert len(answer["model_evidence"]) == len(answer["highlight_ids"]) == 2
    assert set(answer["highlight_ids"]) == {ref["element_id"] for ref in answer["model_evidence"]}
    assert answer["inspected_pages"] == []
    assert provider.calls == ["gate"]


def test_zero_count_uses_complete_catalog_evidence_without_fake_ids(client):
    http, provider = client
    result = question(http, upload_ifc(http), "How many windows are there in the uploaded IFC model?")
    assert result.status_code == 200, result.text
    answer = result.json()
    assert answer["answer"].startswith("0 windows")
    assert answer["highlight_ids"] == []
    assert answer["model_evidence"][0]["element_id"] is None
    assert provider.calls == ["gate"]


@pytest.mark.parametrize("decision", ["insufficient", "unclear"])
def test_negative_gate_never_bypassed_for_ifc_count(client, decision):
    http, provider = client
    provider.decision = decision
    provider.draft = DraftAnswer(status=decision, answer="The requested scope is unresolved.")
    result = question(http, upload_ifc(http), "How many walls are in this model?")
    assert result.status_code == 200
    assert result.json()["status"] == decision
    assert result.json()["highlight_ids"] == []
    assert provider.calls == ["gate", "answer"]


@pytest.mark.parametrize("text", ["How many fire doors are in this model?", "How many walls are on the first floor?",
                                 "How many windows and doors are in this model?", "How many external walls are in this model?"])
def test_qualified_questions_are_not_simplified_to_whole_model_counts(client, text):
    http, provider = client
    provider.draft = DraftAnswer(status="insufficient", answer="The requested qualifier is not established by this record view.")
    result = question(http, upload_ifc(http), text)
    assert result.status_code == 200
    assert result.json()["status"] == "insufficient"
    assert provider.calls == ["gate", "answer"]


@pytest.mark.parametrize("text,kind", [("How many doors are in this IFC model?", "door"),
                                     ("How many rooms does this model have?", "room"),
                                     ("How many spaces are there in the model?", "room")])
def test_count_recognizer_explicit_supported_forms(text, kind):
    assert whole_model_count_kind(text) == kind


def ifc_document(complete=True):
    element = SceneElement(id="wall-a", kind="wall", name="Wall A", ifc_type="IfcWall",
                            source=SourceRef(kind="ifc", global_id="wall-a", step_id=10),
                            properties=[Property(name="Name", value="Wall A")])
    scene = Scene(document_id="ifc-doc", source_kind="ifc", units="m", elements=[element], catalog_complete=complete)
    return Document("ifc-doc", "model.ifc", [], kind="ifc", scene=scene)


def test_unknown_and_unbacked_highlights_dropped_but_valid_answer_retained():
    document = ifc_document()
    draft = DraftAnswer(status="answered", answer="Wall A", model_evidence=[{
        "element_id": "wall-a", "label": "Wall", "observation": "Name is Wall A", "property_name": "Name"}],
        highlight_ids=["unknown", "wall-a", "wall-a"])
    validate_draft(draft, document, GateResult(decision="sufficient"))
    assert draft.highlight_ids == ["wall-a"]
    assert draft.answer == "Wall A"
    draft.model_evidence[0].element_id = None
    draft.model_evidence[0].property_name = None
    assert validated_highlights(draft, document) == []


@pytest.mark.parametrize("reference", [
    {"element_id": "invented-id", "label": "Wall", "observation": "Unknown"},
    {"element_id": "wall-a", "label": "Wall", "observation": "Unknown property", "property_name": "AssumedHeight"},
])
def test_unknown_ifc_evidence_rejected(reference):
    with pytest.raises(ProviderError):
        validate_draft(DraftAnswer(status="answered", answer="unsupported", model_evidence=[reference]),
                       ifc_document(), GateResult(decision="sufficient"))


def test_incomplete_catalog_cannot_support_zero_count_reference():
    draft = DraftAnswer(status="answered", answer="0 windows", model_evidence=[{
        "element_id": None, "label": "Catalog", "observation": "No windows"}])
    with pytest.raises(ProviderError, match="Catalog-only evidence"):
        validate_draft(draft, ifc_document(complete=False), GateResult(decision="sufficient"), server_catalog_count=True)


def test_provider_cannot_claim_height_with_null_id_catalog_evidence(client):
    http, provider = client
    provider.draft = DraftAnswer(status="answered", answer="The ceiling height is 3 metres.", model_evidence=[{
        "element_id": None, "label": "Complete IFC catalog", "observation": "Assumed height"}])
    result = question(http, upload_ifc(http), "What is the ceiling height?")
    assert result.status_code == 502
    assert "Catalog-only evidence" in result.json()["detail"]
    assert "3 metres" not in result.text
    assert provider.calls == ["gate", "answer"]


def test_long_source_names_do_not_break_deterministic_counts():
    document = ifc_document()
    document.scene.elements[0].name = "A" * 500
    result = ask(document, "How many walls are in this model?", Provider())
    assert result.status == "answered"
    assert result.answer.startswith("1 walls")
    assert len(result.model_evidence[0].label) <= 200
    assert result.highlight_ids == ["wall-a"]


def test_existing_but_uninspected_ifc_property_is_not_valid_evidence():
    document = ifc_document()
    document.scene.elements[0].properties = [Property(name=f"Property{i}", value=i) for i in range(13)]
    context = json.loads(source_context(document))
    # Retrieval is explicit, not an arbitrary property-count cap.
    document.question_context=context
    record=next(r for r in context["objects"] if r["id"]=="wall-a")
    assert len(record["values"])==13
    record["values"].pop("Property12")
    draft = DraftAnswer(status="answered", answer="12", model_evidence=[{
        "element_id": "wall-a", "label": "Property", "observation": "Value 12", "property_name": "Property12"}])
    with pytest.raises(ProviderError):
        validate_draft(draft, document, GateResult(decision="sufficient"))
    draft.model_evidence[0].property_name = "Property11"
    validate_draft(draft, document, GateResult(decision="sufficient"))


def image_document(tmp_path, *, duplicate=False, name="Kitchen"):
    path = tmp_path / "source.png"
    Image.new("RGB", (100, 100), "white").save(path)
    element = SceneElement(id="room-a", kind="room", name=name,
                            source=SourceRef(kind="image", page=1, bbox=[.1, .1, .4, .4]),
                            geometry_origin="inferred", geometry=Geometry(type="box", center=[0, 0, .15], size=[.3, .3, .3]),
                            assumptions=[Assumption(property="height", value="invented-height-marker", reason="Unknown actual height")],
                            properties=[Property(name="InventedProperty", value="not-source")])
    elements = [element]
    if duplicate:
        elements.append(element.model_copy(update={"id": "room-b"}))
    scene = Scene(document_id="drawing", source_kind="image", source_page=1, units="relative", elements=elements, catalog_complete=False)
    return Document("drawing", "plan.png", [Page(1, 100, 100, path)], scene=scene)


def image_answer(*, bbox=None, label="Kitchen room", page=1):
    return DraftAnswer(status="answered", answer="This is the kitchen.", evidence=[{
        "page": page, "bbox": bbox or [.1, .1, .4, .4], "label": label, "observation": "Visible source annotation"}],
        highlight_ids=["room-a", "invented"])


def test_image_unique_region_match_and_ambiguous_overlap(tmp_path):
    assert validated_highlights(image_answer(), image_document(tmp_path)) == ["room-a"]
    assert validated_highlights(image_answer(), image_document(tmp_path, duplicate=True)) == []


def test_room_kind_token_cannot_override_conflicting_room_name(tmp_path):
    draft = image_answer(label="Kitchen room")
    document = image_document(tmp_path, name="Bedroom")
    assert validated_highlights(draft, document) == []
    assert draft.evidence[0].bbox == document.scene.elements[0].source.bbox


@pytest.mark.parametrize("name", ["", "   ", "---"])
def test_blank_room_name_cannot_match_arbitrary_evidence(tmp_path, name):
    assert validated_highlights(image_answer(label="Kitchen room"), image_document(tmp_path, name=name)) == []


def test_room_name_match_normalizes_case_and_punctuation(tmp_path):
    assert validated_highlights(image_answer(label="KITCHEN room"), image_document(tmp_path, name="Kitchen!")) == ["room-a"]


@pytest.mark.parametrize("bbox,label,page", [([0, 0, 1, 1], "Kitchen room", 1),
                                          ([.6, .6, .9, .9], "Kitchen room", 1),
                                          ([.1, .1, .4, .4], "Dimension annotation", 1),
                                          ([.1, .1, .4, .4], "Kitchen room", 2)])
def test_unreliable_image_mapping_retains_only_source_evidence(tmp_path, bbox, label, page):
    draft = image_answer(bbox=bbox, label=label, page=page)
    assert validated_highlights(draft, image_document(tmp_path)) == []
    assert draft.evidence and draft.answer == "This is the kitchen."


def test_image_assumptions_and_geometry_never_enter_source_context(tmp_path):
    context = json.loads(source_context(image_document(tmp_path)))
    assert context["objects"][0]["id"] == "room-a"
    assert "invented-height-marker" not in json.dumps(context)
    assert "InventedProperty" not in json.dumps(context)
    assert all("geometry" not in item for item in context["objects"])


def test_scene_absence_and_nonexistent_document(client):
    http, _ = client
    assert http.get("/api/documents/missing/scene").status_code == 404
    buffer = BytesIO()
    Image.new("RGB", (20, 20), "white").save(buffer, format="PNG")
    uploaded = http.post("/api/documents", files={"file": ("plan.png", buffer.getvalue())}).json()
    assert http.get(f"/api/documents/{uploaded['document_id']}/scene").status_code == 404


def test_exact_source_name_disambiguates_shared_region_but_not_duplicate_names(tmp_path):
    document=image_document(tmp_path)
    room=document.scene.elements[0]
    edge=room.model_copy(deep=True,update={"id":"edge-a","kind":"open_edge","name":"Open terrace edge"})
    document.scene.elements.append(edge)
    draft=image_answer();draft.highlight_ids=[room.id,edge.id]
    assert validated_highlights(draft,document)==[room.id]
    edge.name=room.name
    assert validated_highlights(draft,document)==[]
    edge.name="Open terrace edge"
    draft.evidence[0].label="Bedroom";draft.evidence[0].observation="Source room region"
    assert validated_highlights(draft,document)==[]


@pytest.mark.parametrize("kind",["room","outdoor"])
def test_unique_named_space_label_citation_maps_requested_space(tmp_path,kind):
    document=image_document(tmp_path);document.scene.elements[0].kind=kind
    draft=image_answer(bbox=[.2,.2,.24,.24])
    assert validated_highlights(draft,document)==["room-a"]


@pytest.mark.parametrize("failure",["outside","other_page","other_floor","duplicate","unrequested","wall","window","furniture","unresolved"])
def test_tight_label_mapping_preserves_source_and_semantic_ambiguity(tmp_path,failure):
    document=image_document(tmp_path);item=document.scene.elements[0]
    draft=image_answer(bbox=[.2,.2,.24,.24])
    if failure=="outside":draft.evidence[0].bbox=[.5,.5,.54,.54]
    elif failure=="other_page":draft.evidence[0].page=2
    elif failure=="other_floor":
        item.source.bbox=[.6,.6,.9,.9]
        document.scene.elements.append(item.model_copy(deep=True,update={"id":"other-floor"}))
        document.scene.elements[-1].source.bbox=[.1,.1,.4,.4]
    elif failure=="duplicate":
        # Include a same-name non-space record not requested by the model.
        document.scene.elements.append(item.model_copy(deep=True,update={"id":"edge","kind":"open_edge"}))
    elif failure=="unrequested":draft.highlight_ids=[]
    elif failure=="unresolved":item.representation="unresolved"
    else:item.kind=failure
    assert validated_highlights(draft,document)==[]
    assert draft.evidence and draft.answer
