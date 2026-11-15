"""Attributed arithmetic resolves exact permitted values without making them drawing facts."""
from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.documents import DocumentStore
from app.providers.gemini import ProviderError
from app.schemas import DraftAnswer, Operand
from app.service import ask_agent, validate_draft
from test_agent_chat import AgentFixture
from test_backend import png


@pytest.fixture
def measured_drawing(tmp_path):
    store = DocumentStore(tmp_path)
    drawing = store.add(png(), "rectangle.png")
    drawing.revision_id = "source-revision"
    drawing.question_context = {"evidence_scope": "sources_and_user", "user_values": [
        {"id": "width", "property": "annotation_measurement", "value": 10, "unit": "m", "provenance": "user_provided"},
        {"id": "height", "property": "annotation_measurement", "value": 10, "unit": "m", "provenance": "user_provided"}]}
    yield drawing
    store.close()


def area_draft():
    return DraftAnswer(status="answered", answer="The marked rectangle has an area of {result} m² based on your dimensions.",
        user_value_evidence=["width", "height"], calculation={"operation": "product", "unit": "m²", "operands": [
            {"value": 10, "unit": "m", "user_value_id": "width"},
            {"value": 10, "unit": "m", "user_value_id": "height"}]})


def test_user_area_resolves_exact_values_and_retains_distinct_provenance(measured_drawing):
    draft = area_draft()
    result = validate_draft(draft, measured_drawing, None)
    assert result["value"] == 100 and "100 m²" in draft.answer
    assert "user-provided" in result["method"]
    assert [operand["user_value_id"] for operand in result["operands"]] == ["width", "height"]
    assert all(operand["provenance"] == operand["source"]["provenance"] == "user_provided" for operand in result["operands"])
    assert all("evidence_index" not in operand for operand in result["operands"])
    assert draft.evidence == []


@pytest.mark.parametrize("reference", [{}, {"evidence_index": 0, "user_value_id": "width"}, {"evidence_index": -1}])
def test_operand_requires_one_valid_reference(reference):
    with pytest.raises(ValidationError):
        Operand(value=10, unit="m", **reference)


@pytest.mark.parametrize("mutation", ["unknown", "wrong_value", "wrong_unit", "unattributed", "source_only", "missing_permitted_value"])
def test_untrusted_user_operand_never_computes(measured_drawing, mutation):
    draft = area_draft()
    if mutation == "unknown":
        draft.calculation.operands[0].user_value_id = "invented"
    elif mutation == "wrong_value":
        draft.calculation.operands[0].value = 99
    elif mutation == "wrong_unit":
        draft.calculation.operands[0].unit = "cm"
    elif mutation == "unattributed":
        draft.user_value_evidence = ["height"]
    elif mutation == "source_only":
        measured_drawing.question_context["evidence_scope"] = "sources_only"
    else:
        measured_drawing.question_context["user_values"] = measured_drawing.question_context["user_values"][1:]
    with pytest.raises(ProviderError):
        validate_draft(draft, measured_drawing, None)
    assert "{result}" in draft.answer


def test_drawing_index_out_of_bounds_rejected(measured_drawing):
    draft = area_draft()
    draft.calculation.operands[0] = Operand(value=10, evidence_index=0, unit="m")
    with pytest.raises(ProviderError, match="source reference"):
        validate_draft(draft, measured_drawing, None)


@pytest.mark.parametrize("operation,unit,expected", [
    ("product", "m²", 100), ("product", "cm²", 1000000),
    ("sum", "m", 20), ("sum", "cm", 2000),
    ("difference", "m", 0), ("quotient", "ratio", 1)])
def test_mixed_length_units_normalize_arithmetic_and_preserve_entered_values(measured_drawing, operation, unit, expected):
    measured_drawing.question_context["user_values"][1].update(value=1000, unit="cm")
    draft = area_draft()
    draft.calculation.operation = operation
    draft.calculation.unit = unit
    draft.calculation.operands[1].value = 1000
    draft.calculation.operands[1].unit = "cm"
    draft.answer = "The attributed result is {result} " + unit
    result = validate_draft(draft, measured_drawing, None)
    assert result["value"] == pytest.approx(expected)
    assert result["operands"][1]["value"] == result["operands"][1]["source"]["value"] == 1000
    assert result["operands"][1]["unit"] == result["operands"][1]["source"]["unit"] == "cm"
    assert result["computation"]["operands"] == [{"value": 10, "unit": "m"}, {"value": 10, "unit": "m"}]


@pytest.mark.parametrize("operation,unit", [("product", "m"), ("product", "ratio"), ("sum", "m²"), ("quotient", "m²")])
def test_result_dimension_cannot_mislabel_attributed_arithmetic(measured_drawing, operation, unit):
    draft = area_draft()
    draft.calculation.operation = operation
    draft.calculation.unit = unit
    with pytest.raises(ProviderError, match="dimensions"):
        validate_draft(draft, measured_drawing, None)
    assert "{result}" in draft.answer


def test_length_times_dimensionless_drawing_ratio_preserves_linear_unit(measured_drawing):
    draft = area_draft()
    draft.evidence = [{"page": 1, "bbox": [0, 0, 1, 1], "label": "Traced ratio", "observation": "The trace spans twice the marked reference"}]
    # Assignment to a validated model intentionally uses its typed field.
    from app.schemas import Evidence
    draft.evidence = [Evidence.model_validate(row) for row in draft.evidence]
    draft.calculation.operands[1] = Operand(value=2, evidence_index=0)
    draft.calculation.unit = "m"
    draft.answer = "The attributed traced length is {result} m."
    result = validate_draft(draft, measured_drawing, None)
    assert result["value"] == 20
    assert result["computation"]["unit"] == "m"


def test_explicit_room_dimensions_can_compute_without_assuming_global_image_scale(measured_drawing):
    # Distinct pixel spans deliberately imply incompatible global calibrations;
    # this does not invalidate the user's explicit dimensions for this rectangle.
    marks = [{"id": identity, "kind": "measurement", "space": "source", "value": 10, "unit": "m",
              "revision_id": measured_drawing.revision_id, "page": 1, "floor_id": "ground",
              "points": points, "provenance": "user_provided"} for identity, points in [
                  ("width", [[.1, .1], [.7, .1]]), ("height", [[.1, .1], [.1, .4]])]]
    measured_drawing.conversation_context = {"evidence_scope": "sources_and_user", "user_annotations": marks}
    before = deepcopy(measured_drawing.user_values)
    provider = AgentFixture("technical_advanced", draft=area_draft())
    provider.model = provider.advanced_model
    answer = ask_agent(measured_drawing, "What is the area of this rectangular room using my marked dimensions?", provider)
    assert answer.status == "answered" and "100 m²" in answer.answer
    assert "Provided by user" in answer.answer
    assert len(answer.user_value_attributions) == 2
    assert answer.calculation_results[0]["value"] == 100
    assert measured_drawing.user_values == before
    assert answer.gate is None
