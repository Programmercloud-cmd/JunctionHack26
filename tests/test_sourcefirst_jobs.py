"""Integrated source-first jobs, using injected providers and immutable source fixtures."""
from io import BytesIO
from threading import Event
from PIL import Image
from fastapi.testclient import TestClient
import pytest
from app.bundles import BuildingStore
from app.jobs import JobRunner
from app.main import create_app
from app.provider import ProviderError
from app.schemas import Usage, AskRequest, DraftAnswer, QuestionIntent, Clarification
from app.review_schema import ReconstructionReview, DescriptionPatch
from app.user_inputs import RefinementRequest, prepare_inputs, assumptions
from app.revisions import apply_enrichment
from test_backend import png, evidence
from test_ifc_generate import description, floor, boundary, opening, region
from test_reviewed_qa import ReviewedFixture


def other_png():
    output=BytesIO();Image.new('RGB',(120,90),'gray').save(output,format='PNG');return output.getvalue()


class SourceProvider:
    def __init__(self,pause=False):
        self.usage=Usage();self.extracts=[];self.enrichments=0;self.reviews=0
        self.pause=pause;self.entered=Event();self.release=Event()
    def extract_interpretation(self,document,*,include_geometry=False):
        assert not include_geometry and document.scene is None
        assert all(p.number==p.source_page for p in document.pages)
        self.extracts.append(document.id);self.entered.set()
        if self.pause:assert self.release.wait(10)
        return description(floor(label=document.filename,boundaries=[boundary()],openings=[opening()]))
    def reconstruct(self,*args):pytest.fail('Source-first path must not re-extract complete geometry')
    def enrich_geometry(self,document):self.enrichments+=1;return DescriptionPatch(base_revision_id=document.revision_id)
    def review_reconstruction(self,*args,**kwargs):
        self.reviews+=1;return ReconstructionReview(candidate_supported=True,summary='Fixture source review')
    def close(self):pass


def finish(runner,jobs):
    for job in jobs:runner.futures[job['id']].result(10)


def test_automatic_extraction_and_incremental_reupload_cache(tmp_path):
    provider=SourceProvider();app=create_app(storage_root=tmp_path,provider_factory=lambda:provider)
    with TestClient(app) as client:
        first=client.post('/api/documents',files={'file':('first.png',png())}).json()
        finish(app.state.jobs,first['extraction_jobs'])
        saved=app.state.documents.get(first['building_id'])
        assert saved.description and saved.scene is None and saved.reasoning['objects']
        assert provider.reviews==provider.enrichments==0 and len(provider.extracts)==1
        duplicate=client.post('/api/documents',files={'file':('renamed.png',png())}).json()
        assert not duplicate['is_new_upload'] and duplicate['extraction_jobs']==[]
        old_revision=saved.revision_id
        appended=client.post(f"/api/buildings/{saved.id}/sources",files=[('files',('second.png',other_png()))]).json()
        finish(app.state.jobs,appended['extraction_jobs'])
        latest=app.state.documents.get(saved.id)
        assert len(provider.extracts)==2 and len(latest.pages)==2
        assert latest.pages[0].number==1 and latest.pages[1].number==2
        assert client.get(f'/api/buildings/{saved.id}/revisions/{old_revision}/pages/1').status_code==200
        assert client.get(f'/api/buildings/{saved.id}/revisions/{old_revision}/pages/2').status_code==404
    reopened=create_app(storage_root=tmp_path,provider_factory=lambda:pytest.fail('Reopen must not infer'))
    with TestClient(reopened) as client:
        assert client.get('/api/buildings').json()['buildings'][0]['interpretation_status']=='complete'
        result=client.post('/api/documents',files={'file':('same.png',png())}).json()
        assert result['extraction_jobs']==[]


def test_geometry_failure_keeps_successful_interpretation_and_truthful_diagnostic(tmp_path,monkeypatch):
    store=BuildingStore(tmp_path);document=store.add(png(),'plan.png');provider=SourceProvider();runner=JobRunner(store,lambda:provider)
    try:
        finish(runner,runner.extract(document.id))
        saved=store.get(document.id);revision=saved.revision_id
        def fail(candidate):raise RuntimeError('unsafe provider/token-looking value must not escape')
        monkeypatch.setattr(runner,'_geometry',fail)
        job=runner.reconstruct(document.id,revision);finish(runner,[job])
        result=runner.get(job['id'])
        assert result['status']=='failed' and result['error_stage']=='ifc_generation'
        assert 'no usable model has been generated' in result['message'] and not result['has_previous_model']
        assert 'unsafe' not in str(result) and 'token-looking' not in str(result)
        assert store.get(document.id).revision_id==revision and store.get(document.id).description
        assert len(provider.extracts)==1
    finally:runner.close();store.close()


def test_explicit_geometry_uses_saved_interpretation(tmp_path):
    store=BuildingStore(tmp_path);document=store.add(png(),'plan.png');provider=SourceProvider();runner=JobRunner(store,lambda:provider)
    try:
        finish(runner,runner.extract(document.id))
        job=runner.reconstruct(document.id);finish(runner,[job])
        assert runner.get(job['id'])['status']=='complete'
        assert store.get(document.id).scene and len(provider.extracts)==1 and provider.enrichments==0
        assert provider.reviews==1 and store.get(document.id).geometry_status=='available'
    finally:runner.close();store.close()


def test_failed_extraction_requires_explicit_retry(tmp_path):
    store=BuildingStore(tmp_path);document=store.add(png(),'plan.png');provider=SourceProvider();calls=[]
    def unavailable():calls.append(True);raise ProviderError('Provider unavailable',503)
    runner=JobRunner(store,unavailable)
    try:
        jobs=runner.extract(document.id);finish(runner,jobs)
        assert runner.get(jobs[0]['id'])['status']=='failed'
        assert runner.extract(document.id)==[] and len(calls)==1
        runner.provider_factory=lambda:provider
        finish(runner,runner.extract(document.id,retry=True))
        assert store.get(document.id).description and len(provider.extracts)==1
    finally:runner.close();store.close()


def test_source_cache_reused_across_different_building_without_provider(tmp_path):
    store=BuildingStore(tmp_path);a=store.add(png(),'a.png');provider=SourceProvider();runner=JobRunner(store,lambda:provider)
    try:
        finish(runner,runner.extract(a.id))
        b=store.add_many([(other_png(),'b.png'),(png(),'copy.png')])
        copied=next(s['source_id'] for s in b.sources if s['source_id']==a.id)
        runner.provider_factory=lambda:pytest.fail('Cached source does not need credentials')
        finish(runner,runner.extract(b.id,[copied]))
        assert len(provider.extracts)==1 and copied in store.get(b.id).source_interpretations
        assert store.get(a.id).description.floors[0].persistent_id!=store.get(b.id).description.floors[0].persistent_id
    finally:runner.close();store.close()


def test_source_only_assumption_batch_persists_user_provenance_and_no_xy_calibration(tmp_path):
    store=BuildingStore(tmp_path);document=store.add(png(),'plan.png');provider=SourceProvider();runner=JobRunner(store,lambda:provider)
    try:
        finish(runner,runner.extract(document.id));document=store.get(document.id);floor_id=document.description.floors[0].persistent_id
        request=RefinementRequest(base_revision_id=document.revision_id,edits=[{'property':'floor_height','scope':{'floor_id':floor_id},'value':3,'unit':'m'}])
        job=runner.refine_inputs(document.id,request);finish(runner,[job]);saved=store.get(document.id)
        assert runner.get(job['id'])['status']=='complete' and saved.scene is None
        assert saved.user_values[0]['provenance']=='user_provided' and saved.user_values[0]['value']==3
        assert saved.description.floors[0].calibration is None and saved.description.floors[0].height is None
        assert any(r['provenance']=='user_provided' for r in assumptions(saved)['rows'])
        with pytest.raises(Exception,match='revision changed'):runner.refine_inputs(document.id,request)
    finally:runner.close();store.close()


def test_refinement_failure_retains_submissions_and_prior_model(tmp_path,monkeypatch):
    store=BuildingStore(tmp_path);document=store.add(png(),'plan.png');provider=SourceProvider();runner=JobRunner(store,lambda:provider)
    try:
        finish(runner,runner.extract(document.id));finish(runner,[runner.reconstruct(document.id)]);document=store.get(document.id)
        def fail(candidate):raise RuntimeError('fixture failure')
        monkeypatch.setattr(runner,'_geometry',fail)
        request=RefinementRequest(base_revision_id=document.revision_id,edits=[{'property':'floor_height','scope':{'floor_id':document.description.floors[0].persistent_id},'value':3,'unit':'m'}])
        job=runner.refine_inputs(document.id,request);finish(runner,[job]);result=runner.get(job['id'])
        assert result['status']=='failed' and result['submitted_values'][0]['provenance']=='user_provided'
        assert store.get(document.id).revision_id==document.revision_id and result['has_previous_model']
    finally:runner.close();store.close()


def test_conversation_clarification_and_followup_are_saved_without_scene(tmp_path):
    store=BuildingStore(tmp_path);document=store.add(png(),'plan.png')
    class QA(ReviewedFixture):
        def resolve_intent(self,document,question):
            if not document.conversation_context['messages']:
                return QuestionIntent(action='clarify',clarification=Clarification(message='Which floor?',suggestions=['Upper','Both']))
            assert document.conversation_context['clarification_response']=='Upper'
            return QuestionIntent(action='answer',resolved_question='How many doors on the upper floor?')
        def close(self):pass
    provider=QA(DraftAnswer(status='answered',answer='Two depicted doors.',evidence=[evidence()]))
    runner=JobRunner(store,lambda:provider)
    try:
        first=runner.question(AskRequest(document_id=document.id,question='How many doors?'));finish(runner,[first])
        result=runner.get(first['id']);assert result['answer']['status']=='clarification'
        second=runner.question(AskRequest(document_id=document.id,question='Upper',reply_to=result['assistant_message_id'],clarification_response='Upper'));finish(runner,[second])
        messages=store.conversation(document.id)
        assert [m['role'] for m in messages]==['user','assistant','user','assistant']
        assert messages[-1]['answer']['status']=='answered' and messages[-1]['revision_id']==document.revision_id
        assert store.get(document.id).scene is None
    finally:runner.close();store.close()


def test_enrichment_does_not_invent_user_provenance(tmp_path):
    store=BuildingStore(tmp_path);document=store.add(png(),'plan.png');provider=SourceProvider();runner=JobRunner(store,lambda:provider)
    try:
        finish(runner,runner.extract(document.id));document=store.get(document.id);f=document.description.floors[0]
        replacement=f.model_dump();replacement['calibration']={'length_m':3,'segment':[[.1,.1],[.8,.1]],'source':region(),'note':'Invented user input','provenance':'user_provided'}
        patch=DescriptionPatch(base_revision_id=document.revision_id,operations=[{'action':'replace','collection':'floors','target_id':f.persistent_id,'record':replacement,'evidence':region(),'reason':'Fixture'}])
        with pytest.raises(Exception,match='cannot invent'):apply_enrichment(document,patch)
    finally:runner.close();store.close()


def test_observed_calibration_conflict_retains_source_and_submitted_value(tmp_path):
    from app.building import Calibration
    store=BuildingStore(tmp_path);document=store.add(png(),'plan.png');provider=SourceProvider();runner=JobRunner(store,lambda:provider)
    try:
        finish(runner,runner.extract(document.id));document=store.get(document.id)
        candidate=store.prepare(document);floor=candidate.description.floors[0]
        floor.calibration=Calibration(length_m=8,segment=[[.1,.1],[.9,.1]],source=region(),note='Observed dimension')
        document=store.commit(candidate,document.revision_id,status='fixture')
        request=RefinementRequest(base_revision_id=document.revision_id,edits=[{'property':'calibration','scope':{'floor_id':floor.persistent_id},
            'value':{'length':5,'segment':[[.1,.1],[.9,.1]]},'unit':'m'}])
        job=runner.refine_inputs(document.id,request);finish(runner,[job]);result=runner.get(job['id'])
        assert result['status']=='needs_attention' and result['conflicts'][0]['observed_calibration']['length_m']==8
        assert result['submitted_values'][0]['value']['length']==5
        assert store.get(document.id).description.floors[0].calibration.length_m==8
        equivalent=RefinementRequest(base_revision_id=document.revision_id,edits=[{'property':'calibration','scope':{'floor_id':floor.persistent_id},
            'value':{'length':4000,'segment':[[.1,.1],[.5,.1]]},'unit':'mm'}])
        assert prepare_inputs(document,equivalent)[3]==[]
    finally:runner.close();store.close()


def test_section_height_observation_is_checked_without_floor_height(tmp_path):
    from app.building import SourceObservation
    store=BuildingStore(tmp_path);document=store.add(png(),'plan.png');provider=SourceProvider();runner=JobRunner(store,lambda:provider)
    try:
        finish(runner,runner.extract(document.id));document=store.get(document.id)
        document.description.observations.append(SourceObservation(label='Section height',category='storey_height',value=4,unit='m',source=region()))
        floor=document.description.floors[0];assert floor.height is None
        request=RefinementRequest(base_revision_id=document.revision_id,edits=[{'property':'floor_height','scope':{'floor_id':floor.persistent_id},'value':3,'unit':'m'}])
        conflicts=prepare_inputs(document,request)[3]
        assert conflicts and conflicts[0]['observed_value']==4
        assert 'scope' in conflicts[0]['message']
    finally:runner.close();store.close()


@pytest.mark.parametrize('supported',[True,False])
def test_numeric_geometry_refinement_reviews_originals_before_publication(tmp_path,supported):
    class NumericReview(SourceProvider):
        def review_reconstruction(self,document,description,scene,**kwargs):
            self.reviews+=1
            if document.user_values:
                assert document.pages[0].path.exists() and kwargs['previous_scene']
                assert document.user_values[0]['provenance']=='user_provided'
                assert document.description.floors[0].height is None
                assert kwargs['change_context']['requested_inputs']
                assert kwargs['previous_user_values']==[]
                return ReconstructionReview(candidate_supported=supported,summary='Fixture original-source conflict check',candidate_assessment={
                    'delta_support':'supported' if supported else 'unsupported','source_conflicts':[],
                    'new_regressions':[],'pre_existing_issue_ids':[],'unresolved':[],'issue_resolutions':[]})
            return ReconstructionReview(candidate_supported=True,summary='Fixture first model')
    store=BuildingStore(tmp_path);document=store.add(png(),'plan.png');provider=NumericReview();runner=JobRunner(store,lambda:provider)
    try:
        finish(runner,runner.extract(document.id));finish(runner,[runner.reconstruct(document.id)])
        before=store.get(document.id)
        request=RefinementRequest(base_revision_id=before.revision_id,edits=[{'property':'floor_height','scope':{'floor_id':before.description.floors[0].persistent_id},'value':3,'unit':'m'}])
        job=runner.refine_inputs(document.id,request);finish(runner,[job]);result=runner.get(job['id'])
        assert provider.reviews==2 and provider.enrichments==0 and len(provider.extracts)==1
        assert result['status']==('complete' if supported else 'needs_attention')
        assert result['submitted_values'][0]['value']==3
        assert (store.get(document.id).revision_id!=before.revision_id)==supported
    finally:runner.close();store.close()
