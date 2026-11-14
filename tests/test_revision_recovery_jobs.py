"""Recovery state-machine regressions using explicit synthetic providers, never live claims."""
from copy import deepcopy
from pathlib import Path
import pytest
from app.bundles import BuildingStore
from app.jobs import JobRunner
from app.review_schema import ReconstructionReview,DescriptionPatch,AuthorizationReview
from app.schemas import Usage
from app.user_inputs import RefinementRequest
from test_backend import png
from test_bundles_revisions import build
from test_ifc_generate import description,floor,boundary,opening,region


def assessment(**changes):
    return dict(delta_support='supported',source_conflicts=[],new_regressions=[],pre_existing_issue_ids=[],unresolved=[],issue_resolutions=[])|changes


def finding(identity,id='floor'):
    return dict(id=id,object_ids=[identity],source=region(),category='extraction',discrepancy='Fixture source-region correction',evidence='Synthetic source context',proposed_action='Correct the named record',actionable=True)


@pytest.fixture
def saved(tmp_path):
    store=BuildingStore(tmp_path);source=store.add(png(),'fixture.png')
    current=build(store,source,description(floor(boundaries=[boundary()],openings=[opening()])))
    yield store,current
    store.close()


class MetadataRecovery:
    def __init__(self,mode='recover'):
        self.usage=Usage();self.calls=0;self.feedback=[];self.mode=mode;self.contexts=[]
    def close(self):pass
    def review_reconstruction(self,document,description,scene,**kwargs):
        f=description.floors[0]
        if kwargs.get('change_context'):
            self.contexts.append(kwargs['change_context'])
            return ReconstructionReview(candidate_supported=True,summary='Fixture metadata delta inspected',candidate_assessment=assessment(
                issue_resolutions=[{'issue_id':'floor','evidence':region(),'reason':'Fixture bbox change resolved the scoped issue'}]))
        return ReconstructionReview(candidate_supported=True,summary='Fixture initial issue',issues=[finding(f.persistent_id)])
    def patch_reconstruction(self,document,description,scene,review,**kwargs):
        self.calls+=1;self.feedback.append(deepcopy(kwargs.get('validation_feedback')))
        f=description.floors[0]
        if self.mode=='noop':return DescriptionPatch(base_revision_id=document.revision_id)
        if self.calls==1 or self.mode=='repeat':
            value=f.model_dump();value['boundaries']=[]
            return DescriptionPatch(base_revision_id=document.revision_id,operations=[dict(action='replace',collection='floors',target_id=f.persistent_id,
                record=value,evidence=region(),reason='Changed wording '+str(self.calls),issue_ids=['floor'])])
        return DescriptionPatch(base_revision_id=document.revision_id,floor_metadata_updates=[dict(floor_id=f.persistent_id,
            changes=[{'field':'source','value':region(bbox=[.001,0,1,1])}],evidence=region(),reason='Metadata only',issue_ids=['floor'])])


def run(store,current,provider):
    runner=JobRunner(store,lambda:provider)
    try:
        job=runner.reconstruct(current.id,current.revision_id);runner.futures[job['id']].result(20)
        return runner.get(job['id'])
    finally:runner.close()


def test_historical_nested_rejection_recovers_as_metadata_within_two_proposals(saved):
    store,current=saved;provider=MetadataRecovery();before=current.description.model_dump()
    job=run(store,current,provider);latest=store.get(current.id)
    assert provider.calls==2 and job['status']=='complete'
    assert provider.feedback[1]['code']=='nested_floor_edit'
    assert provider.feedback[1]['rejected_proposal']['operations'][0]['record']['boundaries']==[]
    assert latest.description.floors[0].source.bbox==[.001,0,1,1]
    for key in ['boundaries','rooms','openings','features','unresolved']:
        assert latest.description.floors[0].model_dump()[key]==before['floors'][0][key]
    assert job['attempts'][0]['accepted'] and job['issues']==[]
    assert current.description.model_dump()==before
    assert provider.contexts[0]['base_revision_id']==current.revision_id


@pytest.mark.parametrize('mode,expected_calls',[('repeat',2),('noop',1)])
def test_repeat_or_empty_stops_unresolved_without_publishing(saved,mode,expected_calls):
    store,current=saved;provider=MetadataRecovery(mode);job=run(store,current,provider)
    assert provider.calls==expected_calls and job['status']=='needs_attention'
    assert store.get(current.id).revision_id==current.revision_id
    assert 'operational' not in job['message']
    if mode=='repeat':assert job['recovery_events'][-1]['kind']=='stopped'
    else:assert job['recovery_events'][-1]['feedback']['code']=='no_material_change'


class ScopeRecovery:
    def __init__(self,decision='approved',invalid_after_grant=False):
        self.usage=Usage();self.calls=0;self.scope_calls=0;self.decision=decision;self.invalid_after_grant=invalid_after_grant
    def close(self):pass
    def review_reconstruction(self,document,description,scene,**kwargs):
        issue=finding(description.floors[0].openings[0].persistent_id,'opening')
        return ReconstructionReview(candidate_supported=True,summary='Fixture source inspection',issues=[issue],
            candidate_assessment=assessment() if kwargs.get('change_context') else None)
    def patch_reconstruction(self,document,description,scene,review,**kwargs):
        self.calls+=1;f=description.floors[0];wall=f.boundaries[0];record=wall.model_dump();record['note']='Supported fixture wall annotation'
        requests=[]
        if self.calls==2:
            assert kwargs['validation_feedback']['code']=='unauthorized_target'
            requests=[dict(request_id='requested-wall',base_revision_id=document.revision_id,issue_id='opening',target_id=wall.persistent_id,
                floor_id=f.persistent_id,collection='boundaries',evidence=region(),reason='This explicit host needs inspection')]
            if self.invalid_after_grant:record['persistent_id']='invented-replacement-identity'
        return DescriptionPatch(base_revision_id=document.revision_id,operations=[dict(action='replace',collection='boundaries',floor_id=f.persistent_id,
            target_id=wall.persistent_id,record=record,evidence=region(),reason='Source-linked host correction',issue_ids=['opening'])],additional_target_requests=requests)
    def review_target_requests(self,document,description,scene,review,requests,**kwargs):
        self.scope_calls+=1
        assert document.pages[0].path.exists() and scene.derived
        assert kwargs['validation_feedback']['code']=='unauthorized_target'
        return AuthorizationReview(base_revision_id=document.revision_id,decisions=[dict(request_id=r.request_id,issue_id=r.issue_id,target_id=r.target_id,
            decision=self.decision,evidence=region(),reason='Fixture original inspected')for r in requests])


@pytest.mark.parametrize('decision',['approved','denied','unclear'])
def test_feedback_requests_exact_source_reviewed_scope_without_extra_proposals(saved,decision):
    store,current=saved;provider=ScopeRecovery(decision);job=run(store,current,provider)
    assert provider.calls==2 and provider.scope_calls==1
    assert job['recovery_events'][0]['feedback']['code']=='unauthorized_target'
    decisions=[e for e in job['recovery_events']if e['kind']=='authorization'][0]['decisions']
    assert decisions[0]['decision']==decision
    assert (store.get(current.id).revision_id!=current.revision_id)==(decision=='approved')
    if decision=='approved':assert job['attempts'][0]['accepted']
    else:assert job['status']=='needs_attention'


def test_approved_scope_does_not_bypass_other_identity_validation(saved):
    store,current=saved;provider=ScopeRecovery(invalid_after_grant=True);job=run(store,current,provider)
    assert provider.scope_calls==1 and job['status']=='failed'
    assert store.get(current.id).revision_id==current.revision_id
    assert not job['attempts']


@pytest.mark.parametrize('candidate_assessment',[None,assessment(),assessment(delta_support='unclear'),assessment(source_conflicts=['Original source conflict'])])
def test_height_delta_acceptance_carries_prior_findings_and_requires_supported_assessment(saved,candidate_assessment):
    store,current=saved;old_issue=finding(current.description.floors[0].openings[0].persistent_id,'old-gap')
    baseline=store.commit(store.prepare(current),current.revision_id,status='reviewed_issues',review=ReconstructionReview(candidate_supported=True,summary='Existing incomplete fixture',issues=[old_issue]))
    class HeightReview:
        usage=Usage()
        def close(self):pass
        def review_reconstruction(self,document,description,scene,**kwargs):
            assert kwargs['change_context']['pure_height_change']
            assert not kwargs['change_context']['local_failures']
            assert kwargs['previous_user_values']==[] and kwargs['previous_review'].issues[0].id=='old-gap'
            return ReconstructionReview(candidate_supported=True,summary='Fixture requested delta only',candidate_assessment=candidate_assessment)
    runner=JobRunner(store,HeightReview)
    try:
        request=RefinementRequest(base_revision_id=baseline.revision_id,edits=[dict(property='display_height',scope={'floor_id':baseline.description.floors[0].persistent_id},value=1.4,unit='relative')])
        job=runner.refine_inputs(baseline.id,request);runner.futures[job['id']].result(20);result=runner.get(job['id'])
        accepted=candidate_assessment==assessment()
        assert (result['status']=='complete')==accepted
        assert (store.get(baseline.id).revision_id!=baseline.revision_id)==accepted
        assert any(issue['id']=='old-gap'for issue in result['issues'])
        assert result['submitted_values'][0]['provenance']=='user_provided'
    finally:runner.close()


def test_height_only_cannot_silently_resolve_existing_opening_omission(saved):
    store,current=saved;issue=finding(current.description.floors[0].openings[0].persistent_id)
    review=ReconstructionReview(candidate_supported=True,summary='Fixture unsupported resolution',candidate_assessment=assessment(
        issue_resolutions=[dict(issue_id='floor',evidence=region(),reason='Incorrectly claim a height fixed an opening')]))
    previous=ReconstructionReview(candidate_supported=True,summary='Fixture previous',issues=[issue])
    resolved,errors=JobRunner._resolved_findings(current,review,previous,{'pure_height_change':True,'object_changes':[{'id':issue['object_ids'][0]}]})
    assert not resolved and errors


def test_unattributed_job_issues_never_become_published_baseline_findings(saved):
    store,current=saved;runner=JobRunner(store,MetadataRecovery)
    try:
        runner.jobs['rejected-candidate']={'id':'rejected-candidate','building_id':current.id,'base_revision_id':current.revision_id,
            'revision_id':current.revision_id,'created_at':1,'status':'needs_attention',
            'issues':[finding('unknown-candidate-only-id')]}
        prior=runner._baseline_review(current)
        assert prior is None or not prior.issues
    finally:runner.close()


def test_private_candidate_findings_require_same_source_and_unchanged_target(saved):
    import json
    store,current=saved;runner=JobRunner(store,MetadataRecovery)
    folder=store.directory(current.id)/'diagnostics'/'candidate';folder.mkdir(parents=True)
    room=current.description.floors[0].rooms[0]
    try:
        (folder/'audit.json').write_text(json.dumps({'status':'reviewed','base_revision_id':current.revision_id}))
        (folder/'description.json').write_text(current.description.model_dump_json())
        (folder/'scene.json').write_text(current.scene.model_dump_json())
        (folder/'review.json').write_text(ReconstructionReview(candidate_supported=False,summary='Reported on rejected candidate',issues=[finding(room.persistent_id)]).model_dump_json())
        runner.jobs['candidate']={'id':'candidate','building_id':current.id,'base_revision_id':current.revision_id,'created_at':1,'status':'needs_attention',
            'review_candidates':[{'candidate':'diagnostics/candidate','revision_id':'e'*32}]}
        prior=runner._baseline_review(current)
        assert len(prior.issues)==1 and 'separate candidate' in prior.issues[0].uncertainty
        altered=current.description.model_dump();altered['floors'][0]['rooms'][0]['label']='Candidate-only source mutation'
        (folder/'description.json').write_text(json.dumps(altered))
        prior=runner._baseline_review(current)
        assert prior is None or not prior.issues
        (folder/'description.json').write_text(current.description.model_dump_json())
        scene=current.scene.model_dump();target=next(e for e in scene['elements']if e['id']==room.persistent_id)
        target['note']='Candidate-only changed target'
        (folder/'scene.json').write_text(json.dumps(scene))
        prior=runner._baseline_review(current)
        assert prior is None or not prior.issues
    finally:runner.close()


def test_region_only_candidate_findings_cannot_hide_changed_horizontal_geometry(saved):
    import json
    store,current=saved;runner=JobRunner(store,MetadataRecovery)
    folder=store.directory(current.id)/'diagnostics'/'region-candidate';folder.mkdir(parents=True)
    try:
        (folder/'audit.json').write_text(json.dumps({'status':'reviewed','base_revision_id':current.revision_id}))
        (folder/'description.json').write_text(current.description.model_dump_json())
        issue=finding(current.description.floors[0].persistent_id);issue['object_ids']=[]
        (folder/'review.json').write_text(ReconstructionReview(candidate_supported=False,summary='Candidate-only report',issues=[issue]).model_dump_json())
        runner.jobs['region-candidate']={'id':'region-candidate','building_id':current.id,'base_revision_id':current.revision_id,'created_at':1,'status':'needs_attention',
            'review_candidates':[{'candidate':'diagnostics/region-candidate','revision_id':'e'*32}]}
        scene=current.scene.model_dump();mesh=next(e['geometry']for e in scene['elements']if e.get('geometry')and e['geometry']['type']=='mesh')
        mesh['positions'][2]+=.3
        (folder/'scene.json').write_text(json.dumps(scene))
        assert len(runner._baseline_review(current).issues)==1  # Vertical-only source interpretation remains identical.
        mesh['positions'][0]+=.3
        (folder/'scene.json').write_text(json.dumps(scene))
        prior=runner._baseline_review(current)
        assert prior is None or not prior.issues
    finally:runner.close()
