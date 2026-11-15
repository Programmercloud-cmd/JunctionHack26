"""Direct evidence workers preserve original native records and user attribution."""
from copy import deepcopy

import pytest

from app.documents import DocumentStore
from app.reasoning import ensure_reasoning
from app.schemas import DraftAnswer
from app.service import ask_agent
from test_agent_chat import AgentFixture
from test_backend import png, evidence
from test_ifc_import import fixture_model, encode


@pytest.fixture
def drawing(tmp_path):
    store = DocumentStore(tmp_path)
    document = store.add(png(), "source.png")
    document.revision_id = "fixture-source-revision"
    yield document
    store.close()


def measurement(document):
    return {"id": "server-measurement", "document_id": document.id, "revision_id": document.revision_id,
            "kind": "measurement", "space": "source", "page": 1, "points": [[.1, .2], [.7, .2]],
            "value": 6, "unit": "m", "label": "User says 6 m", "floor_id": "fixture-floor", "provenance": "user_provided"}


def test_selected_unsaved_measurement_can_be_used_only_with_user_attribution(drawing):
    drawing.conversation_context = {"evidence_scope": "sources_and_user", "user_annotations": [measurement(drawing)]}
    provider = AgentFixture("technical_basic", draft=DraftAnswer(status="answered", answer="The user supplied a distance of 6 m.",
                                                                user_value_evidence=["server-measurement"]))
    provider.model = provider.basic_model
    result = ask_agent(drawing, "Use the distance I provided in the selected mark.", provider)
    assert result.status == "answered"
    assert result.user_value_attributions == [{"id": "server-measurement", "property": "annotation_measurement", "value": 6,
        "unit": "m", "scope": {"floor_id": "fixture-floor"}, "provenance": "user_provided",
        "label": "Provided by user; not observed in the original drawing."}]
    assert "Provided by user" in result.answer
    assert not drawing.user_values  # discussing a mark does not persist a source refinement


def test_source_only_worker_and_review_context_exclude_numeric_mark_values(drawing):
    drawing.conversation_context = {"evidence_scope": "sources_and_user", "user_annotations": [measurement(drawing)]}
    provider = AgentFixture("technical_basic")
    provider.model = provider.basic_model
    result = ask_agent(drawing, "What dimension is printed in the original drawing?", provider)
    seen = provider.seen[0][0]
    assert result.status == "answered" and not result.user_value_attributions
    assert not seen.question_context["user_values"]
    mark = seen.question_context["conversation_context"]["user_annotations"][0]
    assert mark["points"] == [[.1, .2], [.7, .2]]
    assert not {"value", "unit", "label"} & mark.keys()
    assert mark == seen.conversation_context["user_annotations"][0]


def test_source_only_answer_cannot_cite_user_mark_as_original_evidence(drawing):
    drawing.conversation_context = {"evidence_scope": "sources_only", "user_annotations": [measurement(drawing)]}
    provider = AgentFixture("technical_basic", draft=DraftAnswer(status="answered", answer="The original blueprint specifies 6 m.",
                                                                user_value_evidence=["server-measurement"]), reviews=("supported",))
    provider.model = provider.basic_model
    result = ask_agent(drawing, "What is shown in the drawing?", provider)
    assert result.status == "unclear" and "6 m" not in result.answer
    assert not result.user_value_attributions


def test_marked_native_record_is_inspected_in_full_even_when_text_retrieval_omits_it(tmp_path):
    model, wall, window, _ = fixture_model()
    store = DocumentStore(tmp_path)
    try:
        document = store.add(encode(model), "original.ifc")
        document.revision_id = "native-revision"
        original = next(row for row in ensure_reasoning(document)["objects"] if row["id"] == window.GlobalId)
        document.conversation_context = {"evidence_scope": "sources_only", "navigation_references": [{
            "object_id": window.GlobalId, "source_revision_id": document.revision_id}], "user_annotations": []}
        provider = AgentFixture("technical_advanced", draft=DraftAnswer(status="answered", answer="The marked record has a specified height.",
            model_evidence=[{"element_id": window.GlobalId, "property_name": "Dimensions.SpecifiedHeight", "label": "Original specified height", "observation": "Supplied IFC property"}]))
        provider.model = provider.advanced_model
        result = ask_agent(document, "Describe the material properties of this wall", provider)
        assert result.status == "answered"
        inspected = next(row for row in provider.seen[0][0].question_context["objects"] if row["id"] == window.GlobalId)
        assert inspected["values"] == original["values"]
        assert "Dimensions.SpecifiedHeight" in inspected["values"]
        assert result.model_evidence[0].element_id == window.GlobalId
    finally:
        store.close()


def test_whole_native_model_count_uses_complete_semantic_catalog_without_gate(tmp_path):
    model, wall, window, _ = fixture_model()
    store = DocumentStore(tmp_path)
    try:
        document = store.add(encode(model), "original.ifc")
        document.revision_id = "native-revision"
        provider = AgentFixture("technical_basic", draft=DraftAnswer(status="answered", answer="Incorrect fixture count of 200 windows.",
            model_evidence=[{"element_id": wall.GlobalId, "label": "Supplied record", "observation": "Fixture initial assertion"}]))
        provider.model = provider.basic_model
        result = ask_agent(document, "How many windows are in this IFC model?", provider)
        assert result.status == "answered" and result.answer.startswith("1 windows")
        assert result.calculation_results[0]["value"] == 1
        assert result.model_evidence[0].element_id == window.GlobalId
        assert result.gate is None
    finally:
        store.close()
