"""Public demo enforcement through real HTTP routes; fixture inference is explicit."""
import json
from threading import Event
import pytest
from fastapi.testclient import TestClient
from app.bundles import BuildingStore
from app.main import create_app
from app.public_access import hash_access_code
from app.schemas import DraftAnswer
from test_backend import png,evidence
from test_bundles_revisions import build
from test_ifc_generate import description
from test_reviewed_qa import ReviewedFixture


@pytest.fixture
def prepared(tmp_path,monkeypatch):
    store=BuildingStore(tmp_path/'store')
    doc=build(store,store.add(png(),'shared.png'),description())
    private=store.add(png()+b'private-fixture','private.png');store.close()
    manifest=tmp_path/'examples.json';manifest.write_text(json.dumps([{'building_id':doc.id,'revision_id':doc.revision_id,'title':'Fixture example'}]))
    monkeypatch.setenv('BLUEPRINT_PUBLIC_DEMO','1');monkeypatch.setenv('BLUEPRINT_PUBLIC_EXAMPLES_FILE',str(manifest))
    monkeypatch.setenv('BLUEPRINT_DEMO_ACCESS_CODE_HASH',hash_access_code('explicit-fixture-access-code'))
    monkeypatch.setenv('BLUEPRINT_DEMO_SESSION_SECRET','fixture-session-secret')
    return tmp_path/'store',doc,private


def unlock(client):
    assert client.post('/api/access/unlock',json={'code':'explicit-fixture-access-code'}).status_code==200


def test_anonymous_pinned_reads_hide_private_state_and_all_paid_paths(prepared):
    root,doc,private=prepared;calls=[]
    def forbidden():calls.append(True);raise AssertionError('No anonymous inference')
    with TestClient(create_app(storage_root=root,provider_factory=forbidden),base_url='https://demo.test')as client:
        assert client.get('/api/access').json()['can_work']is False
        listed=client.get('/api/buildings').json()['buildings'];assert [x['building_id']for x in listed]==[doc.id]
        assert listed[0]['read_only_model']and listed[0]['pinned_revision_id']==doc.revision_id
        store=client.app.state.documents
        candidate=store.prepare(store.get(doc.id));candidate.scene.elements=[]
        changed=store.commit(candidate,doc.revision_id,status='preview_reviewing')
        detail=client.get('/api/buildings/'+doc.id).json()
        assert detail['revision_id']==doc.revision_id and detail['jobs']==[]
        assert client.get('/api/documents/'+doc.id+'/scene').json()['elements']
        assert client.get('/api/documents/'+doc.id+'/model.ifc').status_code==200
        assert client.get(f'/api/buildings/{doc.id}/revisions/{doc.revision_id}/pages/1').status_code==200
        paths=[f'/api/buildings/{private.id}',f'/api/documents/{private.id}/pages/1',f'/api/documents/{private.id}/scene',
               f'/api/buildings/{doc.id}/conversation',f'/api/buildings/{doc.id}/sources/{doc.id}/original',
               f'/api/buildings/{doc.id}/revisions/{changed.revision_id}/pages/1','/api/jobs/unknown','/openapi.json','/api/future-route']
        for path in paths:assert client.get(path).status_code in {401,404},path
        for path in ['/api/documents','/api/questions','/api/ask','/api/chat/actions',f'/api/buildings/{doc.id}/sources',
                     f'/api/buildings/{doc.id}/extraction',f'/api/buildings/{doc.id}/reconstruction',f'/api/buildings/{doc.id}/refinements',
                     f'/api/documents/{doc.id}/scene','/api/jobs/unknown/stop','/api/future-route']:
            assert client.post(path,json={}).status_code==401,path
        assert not calls


def test_editor_cannot_mutate_examples_including_multipart_aliases(prepared):
    root,doc,private=prepared
    with TestClient(create_app(storage_root=root,provider_factory=lambda:None),base_url='https://demo.test')as client:
        unlock(client);store=client.app.state.documents;directory=store.directory(doc.id)
        hashes={str(p.relative_to(directory)):p.read_bytes()for p in directory.rglob('*')if p.is_file()}
        for suffix,body in [('extraction',{}),('reconstruction',{}),('refinements',{'base_revision_id':doc.revision_id,'edits':[{'property':'display_height','scope':{'floor_id':doc.scene.floors[0].id},'value':1.4,'unit':'relative'}]})]:
            assert client.post(f'/api/buildings/{doc.id}/{suffix}',json=body).status_code==409
        assert client.post(f'/api/documents/{doc.id}/scene',json={}).status_code==409
        assert client.post('/api/documents',files={'file':('alias.png',png())}).status_code==409
        assert client.post('/api/documents',files=[('files',('distinct.png',png()+b'new')),('files',('alias.png',png()))]).status_code==409
        assert client.post(f'/api/buildings/{doc.id}/sources',files={'file':('other.png',png()+b'new')}).status_code==409
        assert hashes=={str(p.relative_to(directory)):p.read_bytes()for p in directory.rglob('*')if p.is_file()}
        assert len(store.list())==2
        assert client.get('/api/buildings/'+private.id).status_code==200


def test_authenticated_example_qa_pins_inference_and_highlights_despite_current_change(prepared):
    root,doc,private=prepared;entered=Event();release=Event();room=next(e for e in doc.scene.elements if e.kind=='room');inspected=[]
    class Fixture(ReviewedFixture):
        def gate(self,document,*args,**kwargs):
            inspected.append(document.revision_id)
            return super().gate(document,*args,**kwargs)
        def review_answer(self,*args,**kwargs):
            entered.set();assert release.wait(10)
            return super().review_answer(*args,**kwargs)
        def close(self):pass
    provider=Fixture(DraftAnswer(status='answered',answer='Fixture room shown.',evidence=[evidence(bbox=room.source.bbox)|{'label':room.name,'observation':room.name}],highlight_ids=[room.id]))
    with TestClient(create_app(storage_root=root,provider_factory=lambda:provider),base_url='https://demo.test')as client:
        unlock(client);store=client.app.state.documents
        changed=store.prepare(store.get(doc.id));changed.scene.elements=[]
        latest=store.commit(changed,doc.revision_id,status='preview_reviewing')
        body={'document_id':doc.id,'revision_id':doc.revision_id,'question':'Which room?'}
        result=client.post('/api/questions',json=body);assert result.status_code==202,result.text
        job=result.json();assert entered.wait(10)
        release.set();client.app.state.jobs.futures[job['id']].result(10)
        answer=client.get('/api/jobs/'+job['id']).json()['answer']
        assert answer['answered_revision_id']==answer['display_revision_id']==doc.revision_id
        assert answer['highlight_ids']==[room.id]and inspected==[doc.revision_id]
        assert client.get('/api/buildings/'+doc.id+'/conversation').json()['messages']
        assert store.get(doc.id).revision_id==latest.revision_id
        assert client.post('/api/questions',json=body|{'revision_id':latest.revision_id}).status_code==404
        client.post('/api/access/lock')
        assert client.get('/api/buildings/'+doc.id+'/conversation').status_code==404
        assert client.get('/api/jobs/'+job['id']).status_code==404


def test_synchronous_question_uses_pinned_example(prepared):
    root,doc,private=prepared;seen=[]
    class Fixture(ReviewedFixture):
        def gate(self,document,*args,**kwargs):
            seen.append(document.revision_id);return super().gate(document,*args,**kwargs)
        def close(self):pass
    provider=Fixture(DraftAnswer(status='answered',answer='Fixture only',evidence=[evidence()]))
    with TestClient(create_app(storage_root=root,provider_factory=lambda:provider),base_url='https://demo.test')as client:
        unlock(client);store=client.app.state.documents
        changed=store.prepare(store.get(doc.id));store.commit(changed,doc.revision_id,status='preview_reviewing')
        result=client.post('/api/ask',json={'document_id':doc.id,'question':'Fixture question'})
        assert result.status_code==200,result.text
        assert result.json()['answered_revision_id']==result.json()['display_revision_id']==doc.revision_id
        assert seen==[doc.revision_id]


def test_pinned_question_cannot_reuse_job_id_from_another_revision(prepared):
    root,doc,private=prepared
    def forbidden():raise AssertionError('Conflicting idempotency must not infer')
    with TestClient(create_app(storage_root=root,provider_factory=forbidden),base_url='https://demo.test')as client:
        unlock(client);store=client.app.state.documents;runner=client.app.state.jobs
        newer=store.commit(store.prepare(store.get(doc.id)),doc.revision_id,status='preview_reviewing')
        identity=runner._new(newer,'question','same-request')
        runner._update(identity,status='complete',phase='complete')
        result=client.post('/api/questions',json={'document_id':doc.id,'revision_id':doc.revision_id,'request_id':'same-request','question':'Fixture question?'})
        assert result.status_code==409


def test_chat_actions_require_code_exact_example_revisions_and_readonly_outputs(prepared):
    from test_chat_actions import IntentFixture
    root,doc,private=prepared;provider=IntentFixture()
    with TestClient(create_app(storage_root=root,provider_factory=lambda:provider),base_url='https://demo.test')as client:
        body={'message':'Show the model','request_id':'fixture-intent','document_id':doc.id,'revision_id':doc.revision_id,
              'workspace':{'geometry_revision_id':doc.revision_id}}
        assert client.post('/api/chat/actions',json=body).status_code==401
        assert not provider.calls
        unlock(client);store=client.app.state.documents
        newer=store.commit(store.prepare(store.get(doc.id)),doc.revision_id,status='preview_reviewing')
        assert client.post('/api/chat/actions',json=body|{'workspace':{'geometry_revision_id':newer.revision_id}}).status_code==404
        assert not provider.calls
        provider.actions=[{'type':'question'}]
        result=client.post('/api/chat/actions',json=body)
        assert result.status_code==200,result.text
        assert result.json()['actions'][0]['revision_id']==doc.revision_id
        provider.actions=[{'type':'attach_sources'}]
        # CURRENT consistency can independently reject before the readonly check.
        assert client.post('/api/chat/actions',json=body).status_code==409


def test_chat_readonly_guard_runs_with_current_equal_to_manifest(prepared):
    from test_chat_actions import IntentFixture
    root,doc,private=prepared;provider=IntentFixture()
    with TestClient(create_app(storage_root=root,provider_factory=lambda:provider),base_url='https://demo.test')as client:
        unlock(client)
        body={'message':'Change this example','request_id':'readonly-fixture','document_id':doc.id,
              'revision_id':doc.revision_id,'workspace':{'geometry_revision_id':doc.revision_id}}
        for action in [{'type':'attach_sources'},{'type':'reconstruct','mode':'refine'},{'type':'retry_extraction'}]:
            provider.actions=[action]
            result=client.post('/api/chat/actions',json=body)
            assert result.status_code==409,result.text
            assert 'read-only'in result.json()['detail']
        assert len(provider.calls)==3
        assert client.app.state.documents.get(doc.id).revision_id==doc.revision_id
