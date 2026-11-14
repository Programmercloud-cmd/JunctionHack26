"""Gemini wire compatibility never relaxes the application's response validation."""
from copy import deepcopy
import json

import httpx2
from pydantic import ValidationError
import pytest

from app.documents import DocumentError, DocumentStore
from app.provider import GeminiProvider, ProviderError, gemini_wire_schema
from app.reconstruction import reconstruct_scene
from app.building import BuildingDescription
from test_ifc_generate import description, floor, room, region
from app.schemas import CropRequest, DraftAnswer, GateResult
from test_backend import png


ROOM = room()
FLOOR = description(floor(rooms=[ROOM])).model_dump()
CROP = {"page": 1, "bbox": [0, 0, 1, 1], "reason": "Inspect plan"}
ANSWER = {"status": "answered", "answer": "One visible room", "evidence": [
    {"page": 1, "bbox": [0, 0, 1, 1], "label": "Plan", "observation": "One enclosed region"}]}


def test_schema_walk_preserves_data_property_names_and_other_constraints():
    bounded = {"type": "array", "minItems": 4, "maxItems": 4, "items": {"type": "number"}}
    data = {"type": "array", "maxItems": 9}
    original = {
        "type": "object", "additionalProperties": False, "required": ["maxItems"],
        "properties": {"maxItems": deepcopy(bounded), "choice": {"anyOf": [deepcopy(bounded), {"type": "null"}]}},
        "$defs": {"Box": deepcopy(bounded)}, "$ref": "#/$defs/Box",
        "enum": [data], "const": data, "default": data, "examples": [data],
    }
    before = deepcopy(original)
    expected = deepcopy(original)
    del expected["properties"]["maxItems"]["maxItems"]
    del expected["properties"]["choice"]["anyOf"][0]["maxItems"]
    del expected["$defs"]["Box"]["maxItems"]
    assert gemini_wire_schema(original) == expected
    assert original == before


@pytest.fixture
def sdk_document(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "offline-test-only")
    provider = GeminiProvider()
    provider.client._api_client._httpx_client.close()
    store = DocumentStore(tmp_path)
    try:
        yield provider, store.add(png(), "plan.png")
    finally:
        provider.close()
        store.close()


def intercept(provider, output, finish_reason="STOP"):
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx2.Response(200, json={"candidates": [{"content": {"role": "model", "parts": [
            {"text": json.dumps(output)}]}, "finishReason": finish_reason}],
            "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5}})

    provider.client._api_client._httpx_client = httpx2.Client(transport=httpx2.MockTransport(handler))
    return requests


def generate(provider, document, mode):
    if mode == "reconstruct":
        return provider.reconstruct(document, 1)
    if mode == "crop":
        return provider.choose_crop(document, "Inspect this plan")
    return provider.answer(document, "How many rooms?", GateResult(decision="sufficient"))


@pytest.mark.parametrize("mode,schema,output", [
    ("reconstruct", BuildingDescription, FLOOR), ("crop", CropRequest, CROP), ("answer", DraftAnswer, ANSWER),
])
def test_actual_sdk_serializes_only_relaxed_array_bounds(sdk_document, mode, schema, output):
    provider, document = sdk_document
    requests = intercept(provider, output)
    result = generate(provider, document, mode)
    assert isinstance(result, schema)
    original = schema.model_json_schema()
    if mode != "reconstruct":
        assert '"maxItems"' in json.dumps(original)
    wire = requests[0]["generationConfig"]["responseJsonSchema"]
    assert wire == gemini_wire_schema(original)
    assert '"maxItems"' not in json.dumps(wire)
    assert wire["additionalProperties"] is False
    if mode == "crop":
        assert wire["properties"]["bbox"]["minItems"] == 4
    if mode == "answer":
        assert wire["$defs"]["Evidence"]["properties"]["bbox"]["minItems"] == 4
        assert wire["properties"]["status"]["enum"] == ["answered", "insufficient", "unclear"]
    if mode == "reconstruct":
        assert wire["$defs"]["RoomDescription"]["properties"]["polygon"]["items"]["required"] == ["x", "y"]
        assert wire["$defs"]["PageRegion"]["properties"]["bbox"]["required"] == ["left", "top", "right", "bottom"]
    assert len(requests) == 1
    assert any("inlineData" in part for content in requests[0]["contents"] for part in content["parts"])


@pytest.mark.parametrize("mode,output", [
    ("reconstruct", {"floors": [floor(source=region(page=0))], "limitations": []}),
    ("reconstruct", FLOOR | {"invented_height": 3}),
    ("crop", CROP | {"bbox": [0, 0, 1, 1, 1]}),
    ("crop", CROP | {"bbox": [0, 0, 1]}),
    ("crop", CROP | {"bbox": [0, 0, 2, 1]}),
    ("answer", ANSWER | {"highlight_ids": ["id"] * 4001}),
    ("answer", ANSWER | {"evidence": ANSWER["evidence"] * 101}),
    ("answer", ANSWER | {"status": "confident"}),
])
def test_invalid_or_overlimit_sdk_outputs_still_fail_local_validation(sdk_document, mode, output):
    provider, document = sdk_document
    requests = intercept(provider, output)
    with pytest.raises(ValidationError):
        generate(provider, document, mode)
    assert len(requests) == 1


@pytest.mark.parametrize("polygon", [
    [[-.1, 0], [.9, 0], [.9, .9]],
    [[.1, .1], [.9, .9], [.1, .9], [.9, .1]],
    [[.1, .1, .2], [.9, .1], [.9, .9]],
])
def test_wire_relaxation_keeps_reconstruction_geometry_checks(sdk_document, polygon):
    provider, document = sdk_document
    intercept(provider, {"floors": [floor(rooms=[room(polygon=polygon)])], "limitations": []})
    scene = reconstruct_scene(document, 1, provider)
    broken = next(e for e in scene.elements if e.kind == "room")
    assert broken.geometry is None and broken.representation == "unresolved"
    assert broken.note and broken.source.page == 1


@pytest.mark.parametrize("mode,output", [("reconstruct", FLOOR), ("crop", CROP), ("answer", ANSWER)])
def test_token_limit_rejects_even_locally_valid_json(sdk_document, mode, output):
    provider, document = sdk_document
    intercept(provider, output, finish_reason="MAX_TOKENS")
    with pytest.raises(ProviderError, match="output token limit") as error:
        generate(provider, document, mode)
    assert error.value.status == 502
    assert "clearer" not in error.value.message and "insufficient" not in error.value.message
    assert document.scene is None


def test_reconstruction_budgets_are_scoped_and_qa_budgets_unchanged(sdk_document):
    provider, document = sdk_document
    requests = []
    endpoints = []
    outputs = iter([FLOOR, ANSWER, CROP])

    def handler(request):
        body = json.loads(request.content)
        endpoints.append(request.url.path)
        requests.append((body, request.extensions["timeout"]))
        if str(request.url).endswith("/decisions"):
            return httpx2.Response(200, json={"answers": {"sufficiency": {"type": "choice", "choice": "sufficient",
                "confidence": .8, "probabilities": {"sufficient": .8, "insufficient": .1, "unclear": .1}}}})
        return httpx2.Response(200, json={"candidates": [{"content": {"role": "model", "parts": [
            {"text": json.dumps(next(outputs))}]}, "finishReason": "STOP"}]})

    provider.client._api_client._httpx_client = httpx2.Client(transport=httpx2.MockTransport(handler))
    generate(provider, document, "reconstruct")
    generate(provider, document, "answer")
    generate(provider, document, "crop")
    provider.gate(document, "How many rooms?")
    assert len(requests) == 4
    assert provider.reconstruction_model == "gemini-3.1-pro-preview"
    assert endpoints[0].endswith(f"models/{provider.reconstruction_model}:generateContent")
    assert all(path.endswith(f"models/{provider.model}:generateContent") for path in endpoints[1:3])
    for index, (body, timeout) in enumerate(requests):
        assert timeout["read"] == (300 if index == 0 else 45)
        if index < 3:
            assert body["generationConfig"]["maxOutputTokens"] == (65536 if index == 0 else 8192)
            assert "httpOptions" not in body["generationConfig"]
            if index == 0:
                assert body["generationConfig"]["thinkingConfig"] == {"thinking_level": "HIGH"}
            else:
                assert "thinkingConfig" not in body["generationConfig"]
        else:
            assert "generationConfig" not in body and "thinkingConfig" not in body


def test_patch_record_wire_string_keeps_exact_local_types_strict():
    from app.review_schema import DescriptionPatch
    from app.provider import gemini_wire_schema
    from pydantic import ValidationError
    original=DescriptionPatch.model_json_schema()
    wire=gemini_wire_schema(original)
    assert len(original['$defs']['RecordPatch']['properties']['record']['anyOf'])==7
    record=wire['$defs']['RecordPatch']['properties']['record']['anyOf'][0]
    assert record['type']=='string' and 'properties' not in record
    assert 'Local validation' in record['description']
    import pytest
    with pytest.raises(ValidationError):
        DescriptionPatch.model_validate({'base_revision_id':'test','operations':[{'action':'add','collection':'rooms',
            'record':{'label':'Unsupported','execute_python':'forbidden'},'evidence':{'page':1,'bbox':[0,0,1,1]},'reason':'fixture'}]})


def test_patch_string_record_decodes_typed_data_and_retains_exact_diagnostic(sdk_document):
    from app.review_schema import DescriptionPatch
    provider,document=sdk_document
    record=room()
    encoded=json.dumps(record)
    output={'base_revision_id':'r1','operations':[{'action':'add','collection':'rooms','record':encoded,
        'evidence':{'page':1,'bbox':[0,0,1,1]},'reason':'fixture'}]}
    calls=intercept(provider,output)
    patch=provider._generate(document,'fixture','fixture',DescriptionPatch)
    assert patch.operations[0].record.label==record['label']
    assert provider.last_structured_output==output and isinstance(provider.last_structured_output['operations'][0]['record'],str)
    assert calls[0]['generationConfig']['responseJsonSchema']['$defs']['RecordPatch']['properties']['record']['anyOf'][0]['type']=='string'


@pytest.mark.parametrize('record',['{broken','[]','{}','null',json.dumps({**room(),'execute_python':'forbidden'})])
def test_invalid_patch_string_is_not_coerced_or_published(sdk_document,record):
    from app.review_schema import DescriptionPatch
    provider,document=sdk_document
    output={'base_revision_id':'r1','operations':[{'action':'add','collection':'rooms','record':record,
        'evidence':{'page':1,'bbox':[0,0,1,1]},'reason':'fixture'}]}
    intercept(provider,output)
    with pytest.raises((ValueError,ProviderError)):
        provider._generate(document,'fixture','fixture',DescriptionPatch)
    assert provider.last_structured_output==output
    assert document.scene is None and document.description is None


def test_missing_requests_do_not_retrace_valid_walls_or_request_reference_registration():
    from app.geometry_requirements import missing_geometry_requests
    from app.revisions import needs_geometry
    d=description(floor('Ground',order=0,order_basis='Ground source label'),floor('Upper',order=1,order_basis='Upper source label'))
    for i,f in enumerate(d.floors):f.persistent_id=str(i)
    requests=missing_geometry_requests(d)
    assert requests and needs_geometry(d)
    assert all(request['fields']==['registration'] for request in requests)
    assert all(request['target_id']=='1' for request in requests)


def test_gemini_omits_rejected_numeric_wire_bounds_but_keeps_canonical_bounds(sdk_document):
    provider,document=sdk_document
    requests=intercept(provider,FLOOR)
    provider.extract_interpretation(document)
    wire=requests[0]['generationConfig']['responseJsonSchema']
    boxes=wire['$defs']['PageRegion']['properties']['bbox']['properties']
    points=wire['$defs']['RoomDescription']['properties']['polygon']['items']['properties']
    assert set(boxes)=={'left','top','right','bottom'} and set(points)=={'x','y'}
    for value in [*boxes.values(),*points.values()]:
        assert 'minimum' not in value and 'maximum' not in value
    canonical=BuildingDescription.model_json_schema()
    canonical_boxes=canonical['$defs']['PageRegion']['properties']['bbox']['properties']
    canonical_points=canonical['$defs']['RoomDescription']['properties']['polygon']['items']['properties']
    for value in [*canonical_boxes.values(),*canonical_points.values()]:
        assert value['minimum']==0 and value['maximum']==1
    assert 'maximum' not in wire['$defs']['Calibration']['properties']['length_m']
    assert all('maximum' not in node for node in wire['$defs']['Measurement']['properties']['value']['anyOf'])


@pytest.mark.parametrize('bbox', [[.1,.1,4989473684210526,.9],{'left':.1,'top':.1,'right':4989473684210526,'bottom':.9}])
def test_missing_decimal_coordinate_still_rejects_without_rescaling(sdk_document,bbox):
    provider,document=sdk_document
    value=deepcopy(FLOOR);value['floors'][0]['source']['bbox']=bbox
    intercept(provider,value)
    with pytest.raises(ValidationError) as error:provider.extract_interpretation(document)
    assert ('floors',0,'source') in [entry['loc']for entry in error.value.errors()]
    assert provider.last_structured_output['floors'][0]['source']['bbox']==bbox


def test_numeric_bound_adaptation_only_visits_schema_nodes():
    literal={'type':'number','minimum':123,'maximum':456}
    numeric={'type':'number','minimum':0,'maximum':1,'exclusiveMinimum':-1}
    original={'type':'object','properties':{
        'minimum':deepcopy(numeric),'maximum':{'type':['integer','null'],'minimum':1,'maximum':7},
        'nested':{'anyOf':[deepcopy(numeric),{'type':'null'}]}},
        '$defs':{'Number':deepcopy(numeric)},
        'default':literal,'enum':[literal],'const':literal,'examples':[literal]}
    before=deepcopy(original);wire=gemini_wire_schema(original)
    assert original==before
    assert set(wire['properties'])=={'minimum','maximum','nested'}
    for node in [wire['properties']['minimum'],wire['properties']['maximum'],
                 wire['properties']['nested']['anyOf'][0],wire['$defs']['Number']]:
        assert 'minimum' not in node and 'maximum' not in node
    assert wire['properties']['minimum']['exclusiveMinimum']==-1
    assert wire['default']==literal and wire['enum']==[literal] and wire['const']==literal and wire['examples']==[literal]
