"""Reconstruction failures retain strict contracts and attributable diagnostics."""
from copy import deepcopy
import json

import httpx2
import pytest
from pydantic import ValidationError

from app.building import BoundaryDescription
from app.bundles import BuildingStore
from app.jobs import JobRunner
from app.provider import GeminiProvider,ProviderError,GEOMETRY_ENRICHMENT_INSTRUCTIONS,RECONSTRUCTION_PATCH_INSTRUCTIONS
from app.review_schema import DescriptionPatch,ReconstructionReview
from app.revisions import apply_patch
from app.schemas import Usage
from test_backend import png
from test_bundles_revisions import build
from test_gemini_schema import sdk_document,intercept
from test_ifc_generate import description,floor,boundary,opening,region


def test_line_record_source_does_not_relax_contextual_operation_evidence():
    line=region(bbox=[.058,.021,.912,.021])
    record=boundary(source=line,segment=[[.058,.021],[.912,.021]])
    assert BoundaryDescription.model_validate(record)
    payload={'base_revision_id':'fixture','operations':[{'action':'add','collection':'boundaries',
        'floor_id':'floor','record':record,'evidence':line,'reason':'Inspected boundary'}]}
    with pytest.raises(ValidationError) as error:DescriptionPatch.model_validate(payload)
    assert [e['loc'] for e in error.value.errors()]==[('operations',0,'evidence')]
    supported=deepcopy(payload);supported['operations'][0]['evidence']=region(bbox=[.05,.01,.92,.03])
    assert DescriptionPatch.model_validate(supported).operations[0].record.source.bbox==line['bbox']
    assert payload['operations'][0]['evidence']==line
    assert 'positive width AND height' in GEOMETRY_ENRICHMENT_INSTRUCTIONS
    assert 'positive width AND height' in RECONSTRUCTION_PATCH_INSTRUCTIONS


def test_current_truncated_review_cannot_retain_previous_patch_or_private_thoughts(sdk_document):
    provider,document=sdk_document
    patch={'base_revision_id':'fixture','operations':[]}
    intercept(provider,patch)
    provider._generate(document,'Fixture','Fixture',DescriptionPatch)
    old_id=provider.last_response_call_id
    partial='{"candidate_supported":'
    def handler(request):
        return httpx2.Response(200,json={'candidates':[{'finishReason':'MAX_TOKENS','content':{'parts':[
            {'text':'PRIVATE_THOUGHT_CANARY','thought':True},{'text':partial}]}}],
            'usageMetadata':{'promptTokenCount':100,'candidatesTokenCount':3,'thoughtsTokenCount':20}})
    provider.client._api_client._httpx_client.close()
    provider.client._api_client._httpx_client=httpx2.Client(transport=httpx2.MockTransport(handler))
    provider.diagnostic_stage=lambda:'checking_revision'
    with pytest.raises(ProviderError,match='output token limit') as error:
        provider._generate(document,'Fixture','Fixture',ReconstructionReview,max_tokens=16384,thinking_level='high')
    call=provider.provider_calls[-1]
    assert call['stage']=='checking_revision' and call['schema']=='ReconstructionReview'
    assert call['finish_reason']=='MAX_TOKENS' and call['outcome']=='output_limit'
    assert call['prompt_tokens']==100 and call['candidate_tokens']==3 and call['thought_tokens']==20
    assert call['max_output_tokens']==16384 and call['elapsed_ms']>=0
    assert provider.last_response_call_id!=old_id and provider.last_structured_output is None
    assert provider.last_response_text==partial
    assert 'PRIVATE_THOUGHT_CANARY' not in json.dumps(call) and error.value.category=='provider_output_limit'


def test_unavailable_response_clears_old_body_and_reports_unknown_usage(sdk_document):
    provider,document=sdk_document
    intercept(provider,{'page':1,'bbox':[0,0,1,1],'reason':'fixture'})
    provider.choose_crop(document,'fixture')
    def failure(request):raise httpx2.ReadTimeout('PRIVATE_REQUEST_CANARY')
    provider.client._api_client._httpx_client.close()
    provider.client._api_client._httpx_client=httpx2.Client(transport=httpx2.MockTransport(failure))
    with pytest.raises(httpx2.ReadTimeout):provider.choose_crop(document,'fixture')
    assert provider.last_response_call_id is None and provider.last_structured_output is None and provider.last_response_text is None
    call=provider.provider_calls[-1]
    assert call['outcome']=='provider_error' and call['prompt_tokens'] is None and call['candidate_tokens'] is None
    assert 'PRIVATE_REQUEST_CANARY' not in json.dumps(call)


def test_review_has_one_current_description_and_keeps_original_and_both_overlays(sdk_document,monkeypatch):
    provider,document=sdk_document
    document.description=description();document.question_context={'duplicate_qa_context':'DO_NOT_REPEAT_QA'}
    old=document.description.model_copy(deep=True);old.limitations=['Previous interpretation marker']
    # Capture request contract without needing geometric fixtures; overlay function is isolated here.
    from types import SimpleNamespace
    scene=SimpleNamespace(elements=[])
    monkeypatch.setattr('app.review_render.overlay_views',lambda *args:[('Actual overlay',png())])
    requests=intercept(provider,{'candidate_supported':True,'summary':'Fixture review','issues':[]})
    provider.review_reconstruction(document,document.description,scene,previous_description=old,previous_scene=scene)
    parts=requests[0]['contents'][0]['parts'];texts=[p['text']for p in parts if 'text'in p]
    assert 'DO_NOT_REPEAT_QA' not in ''.join(texts)
    data=[json.loads(t)for t in texts if t.startswith('{')]
    assert sum('description'in x for x in data)==1
    payload=next(x for x in data if 'description'in x)
    assert payload['description']==document.description.model_dump(mode='json')
    assert payload['previous_description']==old.model_dump(mode='json')
    assert any('source_catalog'in x for x in data)
    assert sum('inlineData'in p for p in parts)==3
    requests=intercept(provider,{'page':1,'bbox':[0,0,1,1],'reason':'fixture'})
    provider.choose_crop(document,'fixture')
    assert 'DO_NOT_REPEAT_QA' in json.dumps(requests)


def test_explicit_review_target_does_not_authorize_host_wall_edit(tmp_path):
    store=BuildingStore(tmp_path)
    try:
        current=build(store,store.add(png(),'fixture.png'),description(floor(openings=[opening()])))
        f=current.description.floors[0];wall=f.boundaries[0];door=f.openings[0]
        review=ReconstructionReview(candidate_supported=True,summary='Door finding',issues=[{
            'id':'opening','object_ids':[door.persistent_id],'source':region(),'category':'extraction',
            'discrepancy':'Fixture opening mismatch','evidence':'Original opening region',
            'proposed_action':'Correct opening','actionable':True}])
        replacement=wall.model_copy(deep=True);replacement.note='Unreviewed host alteration'
        patch=DescriptionPatch(base_revision_id=current.revision_id,operations=[{
            'action':'replace','collection':'boundaries','floor_id':f.persistent_id,'target_id':wall.persistent_id,
            'record':replacement,'evidence':region(),'reason':'Host wall edit','issue_ids':['opening']}])
        before=current.description.model_dump()
        from app.documents import DocumentError
        with pytest.raises(DocumentError,match='not identified'):apply_patch(current,patch,review)
        assert current.description.model_dump()==before
    finally:store.close()


def test_failed_revision_review_retains_private_candidate_without_publishing(tmp_path):
    store=BuildingStore(tmp_path)
    current=build(store,store.add(png(),'fixture.png'),description())
    class Provider:
        usage=Usage()
        def review_reconstruction(self,*args,**kwargs):
            raise ProviderError('Fixture output limit; no result accepted')
        def close(self):pass
    runner=JobRunner(store,Provider)
    try:
        original=current.revision_id;original_bytes=current.ifc_bytes
        job=runner.reconstruct(current.id,original)
        runner.futures[job['id']].result(10)
        result=runner.get(job['id'])
        assert result['status']=='failed' and result['error_stage']=='reviewing'
        assert result['config']['reconstruction_review_tokens']>0
        saved=store.get(current.id)
        assert saved.revision_id==original and saved.ifc_bytes==original_bytes
        entry=result['review_candidates'][0];assert entry['status']=='review_failed'
        folder=store.directory(current.id)/entry['candidate']
        assert (folder/'model.ifc').read_bytes()==original_bytes
        assert json.loads((folder/'audit.json').read_text())['status']=='review_failed'
        diagnostic=json.loads((store.directory(current.id)/'diagnostics'/(result['diagnostic_id']+'.json')).read_text())
        assert diagnostic['structured_output'] is None and not diagnostic['response_available']
        assert diagnostic['provider_call'] is None
    finally:runner.close();store.close()
    restarted=BuildingStore(tmp_path)
    try:
        assert restarted.get(current.id).revision_id==original
        assert restarted.saved_jobs(current.id)[0]['review_candidates'][0]['status']=='review_failed'
    finally:restarted.close()


def test_reconstruction_catalog_keeps_source_format_and_normalization_warnings(sdk_document):
    provider,document=sdk_document
    document.description=description()
    document.sources=[{"source_id":"a"*64,"filename":"assembly.svg","filenames":["assembly.svg"],
        "kind":"svg","media_type":"image/svg+xml","interpretation_status":"complete",
        "warnings":["External SVG image omitted"],"private_path":"DO_NOT_SEND_LOCAL_PATH"}]
    document.warnings=["Normalization could not render unsupported symbols"]
    document.question_context={"interpretation":"DUPLICATE_QA_CONTEXT"}
    # This test concerns the request; return the required valid patch revision.
    document.revision_id='fixture-revision'
    requests=intercept(provider,{"base_revision_id":document.revision_id,"operations":[]})
    provider.enrich_geometry(document)
    texts=[p['text'] for p in requests[0]['contents'][0]['parts'] if 'text'in p]
    catalog=next(json.loads(t) for t in texts if t.startswith('{') and 'source_catalog'in json.loads(t))
    assert catalog['source_catalog']['files'][0]['filename']=='assembly.svg'
    assert catalog['source_catalog']['files'][0]['kind']=='svg'
    assert catalog['source_catalog']['files'][0]['warnings']==['External SVG image omitted']
    assert catalog['warnings']==document.warnings
    assert catalog['source_catalog']['pages'][0]['width']==document.pages[0].width
    assert not catalog['coverage']['catalog_complete']
    assert 'DUPLICATE_QA_CONTEXT' not in ''.join(texts)
    assert 'DO_NOT_SEND_LOCAL_PATH' not in ''.join(texts)
