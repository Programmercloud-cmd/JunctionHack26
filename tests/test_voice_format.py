"""Spoken presentation preserves claims/qualifiers and never changes evidence."""
import pytest

from app.schemas import Answer, Evidence, GateResult, ModelEvidence, Proposal, Usage
from app.voice_format import prepare_spoken_answer

OPAQUE_ID = "2XQY000000000000000001"


def answer(text, **overrides):
    values = dict(status="answered", answer=text,
        evidence=[Evidence(page=2,bbox=[.1,.2,.8,.9],label="Windows",observation="Source window labels")],
        model_evidence=[ModelEvidence(element_id=OPAQUE_ID,label="Window W1",observation="Source record")],
        highlight_ids=[OPAQUE_ID], missing_information=[],next_action="",proposal=None,
        inspected_pages=[2],gate=GateResult(decision="sufficient"),inspection_passes=1,usage=Usage())
    values.update(overrides)
    return Answer(**values)


def test_window_answer_natural_and_written_immutable():
    original = answer(f"There are 2 windows on the north wall, each approximately 1.2 m wide (bbox: [0.1, 0.2, 0.8, 0.9]; GlobalId: {OPAQUE_ID}; citation 1). Their height is not established.",missing_information=["Window height"],next_action="Check the section drawing.")
    before = original.model_dump()
    speech = prepare_spoken_answer(original,"How many windows are shown?")
    assert speech == "There are 2 windows on the north wall, each approximately 1.2 m wide. Their height is not established. Missing or unresolved: Window height. Next step: Check the section drawing."
    assert original.model_dump() == before


@pytest.mark.parametrize("text", [
    "The widths are [1.2, 1.4, 1.6] m, not verified.",
    "Window option [1] is 1.2 m wide; its height is unknown.",
    "The window schedule references 2 windows, but heights are unknown.",
    "Step 1 is to inspect the drawing; step 2 is to measure.",
    "Only page 2 region 7 was inspected; no height dimension was visible.",
    "Only page 2 was inspected. The windows are on the north wall.",
    "The width is .5 m and the range is 1..2 m, not a verified dimension.",
    ".5 m wide, approximately; height unknown.",
    "Object ID unknown.",
    "The object ID is unknown; the height is also unknown.",
    "The bbox is uncertain and coordinates are not available.",
])
def test_substantive_values_scope_steps_and_unknown_metadata_are_preserved(text):
    assert prepare_spoken_answer(answer(text), "Describe the windows.") == text


@pytest.mark.parametrize("label", ["bbox", "bounding box", "coordinates", "normalized coordinates"])
def test_nested_metadata_keeps_all_uncertainty(label):
    text = f"The window may be present ({label}: [0.1, 0.2, 0.8, 0.9]; (not confirmed); height unknown)."
    result = prepare_spoken_answer(answer(text),"Describe the window.")
    assert "0.1" not in result
    assert "may be present" in result and "not confirmed" in result and "height unknown" in result


def test_coordinate_subject_and_location_relation_are_preserved():
    result = prepare_spoken_answer(answer("Coordinates [0.1, 0.2] are approximate and do not establish the window width."),"Describe the windows.")
    assert result == "Coordinates are approximate and do not establish the window width."
    relation = prepare_spoken_answer(answer("The window at coordinates [0.1, 0.2] is approximately 1.2 m wide."),"Describe the window.")
    assert relation == "The window at the indicated location is approximately 1.2 m wide."


def test_named_numeric_coordinates_and_opaque_values_removed():
    value = answer(f"Window W-01 is shown (coordinates: {{\"x\": 0.1, \"y\": 0.2}}; GlobalId: {OPAQUE_ID}; STEP: #42). The window's height is unknown.")
    result = prepare_spoken_answer(value,"Describe the windows.")
    assert "W-01" in result and "height is unknown" in result
    assert "0.1" not in result and OPAQUE_ID not in result and "#42" not in result


@pytest.mark.parametrize("mark", ["W1", "W-01", "W_01"])
def test_human_window_labels_survive_even_when_called_ids(mark):
    value = answer(f"Window {mark} (object ID: {mark}) is 1.2 m wide.",highlight_ids=[mark])
    result = prepare_spoken_answer(value,"What is the window width?")
    assert result.count(mark) == 2 and "1.2 m" in result


def test_metadata_only_has_nonempty_fallback_and_all_qualifiers():
    value = answer(f"bbox: [0.1,0.2,0.8,0.9]; GlobalId: {OPAQUE_ID}; STEP: #42; [citation 1]",status="unclear",missing_information=["Window count", "Window height"],next_action="Upload a clearer source.")
    result = prepare_spoken_answer(value,"Describe the windows.")
    assert "Technical details are available in the written answer." in result
    assert result.startswith("The answer remains unclear from the inspected source.")
    assert "Missing or unresolved: Window count; Window height." in result
    assert result.endswith("Next step: Upload a clearer source.")


@pytest.mark.parametrize("status", ["insufficient", "unclear"])
def test_missing_qualifiers_are_never_substring_deduplicated(status):
    value = answer("The height is approximately 2 m in a display assumption, not a verified dimension.",status=status,missing_information=["height", "verified height", "height"],next_action="Check the original section.")
    result = prepare_spoken_answer(value,"What is the height?")
    assert "approximately 2 m" in result and "not a verified dimension" in result
    assert "Missing or unresolved: height; verified height; height." in result
    assert "Next step: Check the original section." in result


def test_missing_and_next_step_metadata_values_removed_without_losing_meaning():
    value = answer("The width is unknown.",missing_information=["Height at bbox [0.1,0.2,0.8,0.9], not verified"],next_action="Inspect bbox [0.1,0.2,0.8,0.9]; confirm the height.")
    result = prepare_spoken_answer(value,"What is the width?")
    assert "0.1" not in result
    assert "Missing or unresolved: Height at the indicated region, not verified." in result
    assert "Next step: Inspect the indicated region; confirm the height." in result


@pytest.mark.parametrize("question,keep_coords,keep_ids,keep_refs", [
    ("What are the coordinates of the window?",True,False,False),
    ("Include coordinates and IDs.",True,True,False),
    ("Read citations aloud.",False,False,True),
    ("What is the width without coordinates?",False,False,False),
    ("Read coordinates and IDs, but don't include coordinates.",False,True,False),
    ("Read coordinates and IDs, but not coordinates.",False,True,False),
    ("Show me the window width; don't tell me the coordinates.",False,False,False),
    ("What is the width of the window with object ID abc123?",False,False,False),
    ("No need for coordinates or IDs. Describe the window.",False,False,False),
    ("Describe the window without coordinates and give IDs.",False,True,False),
])
def test_explicit_requests_only_keep_requested_categories(question,keep_coords,keep_ids,keep_refs):
    value = answer(f"Window W1 is 1.2 m wide (bbox: [0.1,0.2,0.8,0.9]; GlobalId: {OPAQUE_ID}; [citation 1]).")
    result = prepare_spoken_answer(value,question)
    assert ("0.1" in result) == keep_coords
    assert (OPAQUE_ID in result) == keep_ids
    assert ("citation 1" in result) == keep_refs
    assert "Window W1 is 1.2 m wide" in result


def test_explicit_details_preserves_metadata_even_after_negative_question():
    text = f"Window W1 is approximately 1.2 m wide (bbox: [0.1,0.2,0.8,0.9]; GlobalId: {OPAQUE_ID}; STEP: #42; [citation 1])."
    result = prepare_spoken_answer(answer(text),"Describe the window without coordinates or IDs.",include_technical_details=True)
    assert "0.1" in result and OPAQUE_ID in result and "#42" in result and "citation 1" in result


def test_citation_links_preserve_url_when_requested():
    value = answer("See [the source](https://example.test/page/2) for the unverified window height.")
    assert "https://" not in prepare_spoken_answer(value,"Describe the window.")
    assert "https://example.test/page/2" in prepare_spoken_answer(value,"Read citations.")
    assert "https://example.test/page/2" in prepare_spoken_answer(value,"Describe the window.",include_technical_details=True)


def test_page_region_parenthetical_reference_removed_but_qualifier_kept():
    value = answer("The window width is approximately 1.2 m (page 2, region 7; height unknown).")
    result = prepare_spoken_answer(value,"Describe the window.")
    assert "region 7" not in result and "height unknown" in result and "approximately 1.2 m" in result


def test_main_proposal_qualifier_kept_separate_proposal_not_spoken():
    value = answer("As a proposal only, a 1.2 m window could fit; the source does not establish this dimension.",proposal=Proposal(text="Unsaid separate proposal",basis="explicit_assumption"))
    result = prepare_spoken_answer(value,"Describe the window.")
    assert "As a proposal only" in result and "source does not establish" in result
    assert "Unsaid" not in result


def test_bullets_remove_markup_but_keep_measurement_punctuation():
    value = answer("- **Window W1:** approximately .5 m wide.\n- Window W2: range 1..2 m; height unknown.")
    result = prepare_spoken_answer(value,"Describe the windows.")
    assert result == "Window W1: approximately .5 m wide. Window W2: range 1..2 m; height unknown."


@pytest.mark.parametrize("text", ["", " ", "...", "bbox: [0.1,0.2,0.8,0.9]"])
def test_valid_answer_always_yields_nonempty_speech(text):
    assert prepare_spoken_answer(answer(text),"Describe the windows.").strip()


@pytest.mark.parametrize("text, expected", [
    ("The estimate uses coordinates [0.1,0.2] and lacks a scale.","The estimate uses coordinates and lacks a scale."),
    ("Object ID abc123 is not confirmed by the source.","Object ID is not confirmed by the source."),
    ("Coordinates [0.1,0.2] and the window height remain uncertain.","Coordinates and the window height remain uncertain."),
    (f"Only {OPAQUE_ID} is visible; its height is unknown.","Only the referenced object is visible; its height is unknown."),
    (f"The width is unknown. Object ID: {OPAQUE_ID}. Citation: page 1.","The width is unknown."),
])
def test_metadata_prose_keeps_grammatical_nouns_and_qualifiers(text, expected):
    assert prepare_spoken_answer(answer(text),"Describe the windows.") == expected


@pytest.mark.parametrize("text, expected", [
    ("Reference: 1 does not establish the window height.","Reference does not establish the window height."),
    ("Evidence: 1 is insufficient to determine width.","Evidence is insufficient to determine width."),
    ("STEP: #42 does not contain a height.","STEP does not contain a height."),
    (f'Windows W1 and W2 are shown. Object IDs: ["{OPAQUE_ID}", "1abcdefghijklmnopqrstu"]. Widths are approximately 1.2 m and 1.4 m.',"Windows W1 and W2 are shown. Widths are approximately 1.2 m and 1.4 m."),
    ("Windows W1 and W2 are shown (Citations: [1, 2]; height unknown).","Windows W1 and W2 are shown (height unknown)."),
    ("Windows W1 and W2 are shown (References: [1, 2]).","Windows W1 and W2 are shown."),
])
def test_reference_nouns_and_explicit_metadata_collections(text, expected):
    assert prepare_spoken_answer(answer(text),"Describe the windows.") == expected
