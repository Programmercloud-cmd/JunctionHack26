"""Offline SDK contracts for reviewed recovery; no fixture is live inference."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.provider import ProviderError, gemini_wire_schema
from app.review_schema import DescriptionPatch, ReconstructionReview, AdditionalTargetRequest
from test_backend import png
from test_gemini_schema import sdk_document, intercept as gemini_intercept
from test_ifc_generate import description, region
from test_openai_provider import (provider as openai_provider, document as source_document,
                                 intercept as openai_intercept, response)


def test_floor_metadata_instructions_apply_to_reconstruction_not_qa():
    from app.provider import (FLOOR_METADATA_INSTRUCTIONS,GEOMETRY_ENRICHMENT_INSTRUCTIONS,
                              RECONSTRUCTION_PATCH_INSTRUCTIONS,ANSWER_INSTRUCTIONS,GATE_INSTRUCTIONS)
    assert FLOOR_METADATA_INSTRUCTIONS in GEOMETRY_ENRICHMENT_INSTRUCTIONS
    assert FLOOR_METADATA_INSTRUCTIONS in RECONSTRUCTION_PATCH_INSTRUCTIONS
    assert FLOOR_METADATA_INSTRUCTIONS not in ANSWER_INSTRUCTIONS
    assert FLOOR_METADATA_INSTRUCTIONS not in GATE_INSTRUCTIONS


@pytest.fixture(params=['gemini', 'openai'])
def sdk(request, sdk_document, openai_provider, source_document, monkeypatch):
    monkeypatch.setattr('app.review_render.overlay_views',lambda *args:[('Actual IFC overlay',png())])
    monkeypatch.setattr('app.review_render.issue_crops',lambda *args:[('Original issue crop',png())])
    if request.param == 'gemini':
        provider, document = sdk_document
    else:
        provider, document = openai_provider, source_document
    document.description=description()
    document.revision_id="fixture-revision"
    document.user_values=[{'id':'current-height','property':'floor_height','value':3,'provenance':'user_provided'}]
    scene=SimpleNamespace(elements=[])
    return request.param, provider, document, scene


def intercept(kind,provider,output):
    if kind=='gemini':return gemini_intercept(provider,output)
    calls=[]
    def handler(request):
        import httpx2
        calls.append(json.loads(request.content))
        return httpx2.Response(200,json=response(output))
    openai_intercept(provider,handler)
    return calls


def payload(kind,request):
    if kind=='gemini':
        texts=[p['text'] for p in request['contents'][0]['parts'] if 'text' in p]
    else:
        texts=[p['text'] for p in request['input'][0]['content'] if p['type']=='input_text']
    return next(json.loads(t) for t in texts if t.startswith('{') and '"description"' in t and '"base_revision_id"' in t)


def instruction(kind,request):
    return request['systemInstruction']['parts'][0]['text'] if kind=='gemini' else request['instructions']


def images(kind,request):
    if kind=='gemini':return sum('inlineData' in p for p in request['contents'][0]['parts'])
    return sum(p['type']=='input_image' for p in request['input'][0]['content'])


def review():
    return ReconstructionReview(candidate_supported=False,summary='Known gap',issues=[{
        'id':'opening-gap','object_ids':['door-1'],'source':region(), 'category':'extraction',
        'discrepancy':'Source opening is unresolved','evidence':'Original depicts opening',
        'proposed_action':'Inspect source host','actionable':True}])


def assessment():
    return {'delta_support':'supported','source_conflicts':[],'new_regressions':[],
            'pre_existing_issue_ids':['opening-gap'],'unresolved_delta':[],'issue_resolutions':[]}


def test_patch_feedback_and_exact_grants_reach_both_adapters_without_mutating_review(sdk):
    kind,provider,document,scene=sdk
    existing=review();before=existing.model_dump()
    feedback={'base_revision_id':document.revision_id,'code':'target_not_authorized','target_id':'wall-1'}
    grants=[{'base_revision_id':document.revision_id,'request_id':'request-1','issue_id':'opening-gap','target_id':'wall-1'}]
    calls=intercept(kind,provider,{'base_revision_id':document.revision_id,'operations':[]})
    provider.patch_reconstruction(document,document.description,scene,existing,validation_feedback=feedback,authorizations=grants)
    data=payload(kind,calls[0])
    assert data['validation_feedback']==feedback and data['authorizations']==grants
    assert data['issue_target_scopes'][0]['explicit_target_ids']==['door-1']
    assert data['issue_target_scopes'][0]['target_scope']=='listed_existing_ids_only'
    assert 'existing_issue_target_scopes' not in data
    assert existing.model_dump()==before
    text=instruction(kind,calls[0])
    assert 'floor_metadata_updates' in text and 'SAME response' in text and 'request is not authorization' in text
    assert images(kind,calls[0])==3 # original, actual IFC, original issue crop
    calls=intercept(kind,provider,{'base_revision_id':document.revision_id,'operations':[]})
    provider.patch_reconstruction(document,document.description,scene,existing)
    assert 'validation_feedback' not in payload(kind,calls[0])
    assert 'authorizations' not in payload(kind,calls[0])


@pytest.mark.parametrize('decision',['approved','denied','unclear'])
def test_additional_target_review_keeps_originals_scope_and_existing_review_budget(sdk,decision):
    kind,provider,document,scene=sdk
    target=AdditionalTargetRequest(request_id='request-1',base_revision_id=document.revision_id,
        issue_id='opening-gap',target_id='wall-1',floor_id='floor-1',collection='boundaries',
        evidence=region(),reason='Inspect the depicted host, not nearest geometry')
    result={'base_revision_id':document.revision_id,'decisions':[{'request_id':'request-1',
        'issue_id':'opening-gap','target_id':'wall-1','decision':decision,'evidence':region(),
        'reason':'Fixture original-source inspection outcome'}]}
    calls=intercept(kind,provider,result)
    current_review=review();before=current_review.model_dump()
    answer=provider.review_target_requests(document,document.description,scene,current_review,[target])
    assert answer.decisions[0].decision==decision
    assert current_review.model_dump()==before # No provider result itself mutates authority.
    data=payload(kind,calls[0])
    assert data['additional_target_requests']==[target.model_dump(mode='json')]
    assert data['base_revision_id']==document.revision_id and 'actual_geometry_inventory' in data
    assert data['user_values']==document.user_values
    assert data['existing_issue_target_scopes'][0]['currently_authorized_target_ids']==['door-1']
    assert 'target_scope' not in data['existing_issue_target_scopes'][0]
    assert 'issue_target_scopes' not in data
    assert target.target_id not in data['existing_issue_target_scopes'][0]['currently_authorized_target_ids']
    assert images(kind,calls[0])==3
    text=instruction(kind,calls[0])
    assert 'exactly one decision' in text and 'unrequested target' in text and 'not acceptance' in text
    assert 'not an eligibility ceiling' in text
    assert 'Absence from the old authorized list is not itself a reason to deny' in text
    assert 'explicitly requested host wall' in text and 'ORIGINAL evidence establishes why' in text
    assert 'never grants automatic authority' in text
    call=provider.provider_calls[-1]
    assert call['schema']=='AuthorizationReview'
    assert call['timeout_ms']==120000 and call['max_output_tokens']==16384
    assert call['model']==(provider.reconstruction_model if kind=='gemini' else provider.model)


def test_delta_review_keeps_old_values_findings_both_ifcs_and_false_decision(sdk):
    kind,provider,document,scene=sdk
    previous_values=[{'id':'old-height','value':2.6,'provenance':'user_provided'}]
    context={'base_revision_id':'previous','requested_input_ids':['current-height'],
             'actual_geometry_delta':{'xy_changed_ids':[],'z_changed_ids':['wall-1']}}
    result={'candidate_supported':False,'summary':'Review remains uncertain','issues':review().model_dump()['issues'],
            'candidate_assessment':{**assessment(),'delta_support':'unclear','unresolved_delta':['Unclear source conflict']}}
    calls=intercept(kind,provider,result)
    answer=provider.review_reconstruction(document,document.description,scene,previous_description=document.description,
        previous_scene=scene,previous_review=review(),change_context=context,previous_user_values=previous_values)
    assert answer.candidate_supported is False and answer.candidate_assessment.delta_support=='unclear'
    assert answer.candidate_assessment.unresolved_delta==['Unclear source conflict']
    data=payload(kind,calls[0])
    assert data['previous_user_values']==previous_values and data['user_values']==document.user_values
    assert data['change_context']==context and data['previous_review']['issues'][0]['id']=='opening-gap'
    assert images(kind,calls[0])==4 # source, candidate IFC, prior IFC, original issue crop
    text=instruction(kind,calls[0])
    assert 'Unchanged XY alone does not prove support' in text
    assert 'unrelated omissions already existed' in text and 'candidate_assessment' in text
    assert 'issue_resolutions' in text and 'cannot resolve an unrelated missing opening' in text
    assert 'never unresolved_delta merely because they remain unfixed' in text
    assert answer.candidate_assessment.issue_resolutions==[]
    assert provider.provider_calls[-1]['max_output_tokens']==16384


@pytest.mark.parametrize('missing',[True,False])
def test_candidate_context_requires_nonnull_assessment(sdk,missing):
    kind,provider,document,scene=sdk
    output={'candidate_supported':True,'summary':'Incomplete review','issues':[]}
    if not missing:output['candidate_assessment']=None
    intercept(kind,provider,output)
    with pytest.raises((ValidationError,ProviderError)):
        provider.review_reconstruction(document,document.description,scene,change_context={'requested_input_ids':['x']})


@pytest.mark.parametrize('defect',['missing_delta','null_delta','legacy_field'])
def test_fresh_candidate_rejects_ambiguous_legacy_or_missing_delta_field(sdk,defect):
    kind,provider,document,scene=sdk
    details=assessment()
    if defect=='missing_delta':details.pop('unresolved_delta')
    elif defect=='null_delta':details['unresolved_delta']=None
    else:details['unresolved']=['opening-gap']
    intercept(kind,provider,{'candidate_supported':True,'summary':'Fixture','issues':[],
                             'candidate_assessment':details})
    with pytest.raises((ValidationError,ProviderError)):
        provider.review_reconstruction(document,document.description,scene,change_context={'requested_input_ids':['height']})


def test_fresh_wire_requires_delta_field_and_omits_legacy_field(sdk):
    kind,provider,document,scene=sdk
    calls=intercept(kind,provider,{'candidate_supported':True,'summary':'Fixture','issues':review().model_dump()['issues'],
                                  'candidate_assessment':assessment()})
    result=provider.review_reconstruction(document,document.description,scene,change_context={'requested_input_ids':['height']})
    wire=(calls[0]['generationConfig']['responseJsonSchema'] if kind=='gemini' else calls[0]['text']['format']['schema'])
    reference=wire['properties']['candidate_assessment']['$ref'].split('/')[-1]
    details=wire['$defs'][reference]
    assert 'unresolved_delta' in details['required']
    assert details['properties']['unresolved_delta']['type']=='array'
    assert 'unresolved' not in details['properties']
    assert result.candidate_assessment.unresolved_delta==[]
    assert result.candidate_assessment.pre_existing_issue_ids==['opening-gap']
    assert result.issues[0].id=='opening-gap'
    assert 'unresolved' not in result.candidate_assessment.model_dump()


def test_canonical_old_assessment_stays_readable_without_implying_delta_support():
    legacy={'candidate_supported':False,'summary':'Legacy uncertainty','issues':[],
            'candidate_assessment':{k:v for k,v in assessment().items() if k!='unresolved_delta'}}
    legacy['candidate_assessment']['unresolved']=['opening-gap']
    result=ReconstructionReview.model_validate(legacy)
    assert result.candidate_assessment.unresolved_delta is None
    assert result.candidate_assessment.unresolved==['opening-gap']
    assert result.candidate_supported is False


def test_initial_review_legacy_response_remains_compatible(sdk):
    kind,provider,document,scene=sdk
    calls=intercept(kind,provider,{'candidate_supported':True,'summary':'Initial preview','issues':[]})
    result=provider.review_reconstruction(document,document.description,scene)
    assert result.candidate_assessment is None
    assert 'change_context' not in payload(kind,calls[0])
    assert 'previous_user_values' not in payload(kind,calls[0])


def metadata_patch(document,changes):
    document.revision_id=document.revision_id or "fixture-revision"
    return {'base_revision_id':document.revision_id,'operations':[], 'floor_metadata_updates':[{
        'floor_id':'floor-1','changes':changes,'evidence':region(),'reason':'Correct supported metadata','issue_ids':[]}]}


def test_gemini_metadata_wire_decodes_explicit_fields_and_keeps_canonical_types(sdk_document):
    provider,document=sdk_document
    changes=[{'field':'source','value':region(bbox=[.1,.1,.9,.9])},{'field':'order','value':None}]
    output=metadata_patch(document,json.dumps(changes))
    canonical=DescriptionPatch.model_json_schema();before=deepcopy(canonical)
    calls=gemini_intercept(provider,output)
    result=provider._generate(document,'Fixture','Fixture',DescriptionPatch)
    decoded=result.floor_metadata_updates[0].changes
    assert decoded[0].value.bbox==[.1,.1,.9,.9] and decoded[1].value is None
    assert [c.field for c in decoded]==['source','order']
    wire=calls[0]['generationConfig']['responseJsonSchema']
    assert wire['$defs']['FloorMetadataUpdate']['properties']['changes']['type']=='string'
    assert canonical==before and canonical['$defs']['FloorMetadataUpdate']['properties']['changes']['type']=='array'
    assert provider.last_structured_output==output # diagnostic retains original wire response


@pytest.mark.parametrize('changes',[json.dumps([{'field':'rooms','value':[]}]),json.dumps([{'field':'label','value':None}]),'{}','not json'])
def test_invalid_gemini_metadata_payload_never_repairs_or_discards_fields(sdk_document,changes):
    provider,document=sdk_document
    output=metadata_patch(document,changes)
    gemini_intercept(provider,output)
    with pytest.raises((ValidationError,ProviderError,json.JSONDecodeError)):
        provider._generate(document,'Fixture','Fixture',DescriptionPatch)
    assert provider.last_structured_output==output


def test_openai_metadata_remains_typed(source_document,openai_provider):
    output=metadata_patch(source_document,[{'field':'label','value':'Original label'}])
    calls=intercept('openai',openai_provider,output)
    result=openai_provider._parse(source_document,'Fixture','Fixture',DescriptionPatch)
    assert result.floor_metadata_updates[0].changes[0].value=='Original label'
    wire=calls[0]['text']['format']['schema']
    assert wire['$defs']['FloorMetadataUpdate']['properties']['changes']['type']=='array'
