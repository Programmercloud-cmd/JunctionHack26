"""Flat Building scopes retain legacy identity while new uploads share one group."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import json

from fastapi.testclient import TestClient
import pytest

from app.main import create_app
from test_agent_chat import AgentFixture
from test_backend import png
from test_ifc_import import fixture_model, encode
from test_public_access_integration import prepared, unlock
from test_voice import voice_app


def owner(client, name='Building'):
    result=client.post('/api/projects',json={'name':name})
    assert result.status_code==201,result.text
    return result.json()


def scopes(client, identity=None):
    rows=client.get('/api/buildings').json()['building_scopes']
    return [row for row in rows if identity is None or row['owner_project_id']==identity]


def base(project, scope='shared'):
    return f"/api/projects/{project['id']}/scopes/{scope}"


def upload(client, project, data, scope='shared'):
    return client.post(base(project,scope)+'/sources',files=[('files',(name,payload)) for name,payload in data])


@pytest.fixture
def setup(tmp_path):
    providers=[]
    def factory():
        provider=AgentFixture('technical_basic');providers.append(provider);return provider
    with TestClient(create_app(storage_root=tmp_path,provider_factory=factory)) as client:
        extraction=[]
        client.app.state.jobs.extract=lambda identity,source_ids,**kwargs: extraction.append((identity,list(source_ids))) or []
        yield client,providers,extraction


def test_new_building_batches_and_all_chats_share_one_context(setup):
    client,providers,extraction=setup;p=owner(client)
    empty=client.post(base(p)+'/chats',json={}).json()
    assert empty['building_id'] is empty['effective_building_id'] is None
    first=upload(client,p,[('a.png',png()),('b.png',png()+b'b')]);assert first.status_code==200,first.text
    doc=first.json();group=doc['document_id'];assert group!=hashlib.sha256(png()).hexdigest()
    assert doc['building_scope']['source_group_id']==group and len(doc['sources'])==2
    current=client.get(f"/api/projects/{p['id']}/chats/{empty['id']}").json()
    assert current['building_id'] is None and current['effective_building_id']==group
    second=client.post(base(p)+'/chats',json={'name':'Other chat'}).json()
    added=upload(client,p,[('c.png',png()+b'c')]);assert added.status_code==200,added.text
    doc=added.json();assert doc['document_id']==group and len(doc['sources'])==3
    assert len(scopes(client,p['id']))==1
    for session in [empty,second]:
        response=client.post('/api/chat',json={'project_id':p['id'],'session_id':session['id'],
            'document_id':group,'revision_id':doc['revision_id'],'message':'What is depicted?','request_id':session['id']})
        assert response.status_code==200,response.text
        assert len(providers[-1].seen[0][0].sources)==3
    stale=client.post('/api/chat',json={'project_id':p['id'],'session_id':empty['id'],'message':'Stale no-source page','request_id':'stale' })
    assert stale.status_code==409
    record=client.app.state.project_chats.get(p['id'],empty['id'])
    assert record['building_id'] is None and all(m['document_id']==group for m in record['messages'])
    assert [len(ids) for _,ids in extraction]==[2,1]
    # Duplicate upload is a no-op, without source extraction or model generation.
    count=len(extraction);again=upload(client,p,[('renamed.png',png())]).json()
    assert again['added_source_ids']==[] and again['revision_id']==doc['revision_id'] and len(extraction)==count


def test_duplicate_original_new_building_is_independent(setup):
    client,_,_=setup;a=owner(client,'A');b=owner(client,'B')
    da=upload(client,a,[('a.png',png()),('extra.png',png()+b'extra')]).json()
    from test_bundles_revisions import build
    from test_ifc_generate import description
    store=client.app.state.documents
    modeled=build(store,store.get(da['document_id']),description())
    store.append_conversation(modeled.id,{'role':'user','question':'Retain only in A'})
    chat=client.post(base(a)+'/chats',json={'name':'A history'}).json()
    before=deepcopy(client.app.state.project_chats.get(a['id'],chat['id']))
    db=upload(client,b,[('same.png',png())]).json()
    assert da['document_id']!=db['document_id']
    assert len(db['sources'])==1 and db['sources'][0]['source_id']==hashlib.sha256(png()).hexdigest()
    assert not client.app.state.documents.get(db['document_id']).scene
    assert store.conversation(db['document_id'])==[]
    assert client.get(base(b)+'/chats').json()['chats']==[]
    assert store.get(modeled.id).ifc_bytes==modeled.ifc_bytes
    assert client.app.state.project_chats.get(a['id'],chat['id'])==before
    upload(client,b,[('b-only.png',png()+b'b-only')])
    assert len(client.app.state.documents.get(da['document_id']).sources)==2
    assert len(client.app.state.documents.get(db['document_id']).sources)==2


def test_reserved_namespace_retry_adds_first_incoming_file_and_is_not_adopted(setup):
    client,_,_=setup;p=owner(client)
    store=client.app.state.documents;projects=client.app.state.projects
    identity=projects.shared_group_id(p['id'])
    store.add(png(),'retained.png',group_id=identity)
    assert projects.get(p['id'])['shared_drawing_building_id'] is None
    assert len(client.get('/api/buildings').json()['projects'])==1
    result=upload(client,p,[('first-retry.png',png()+b'first-retry'),('second-retry.png',png()+b'second-retry')])
    assert result.status_code==200,result.text
    assert result.json()['document_id']==identity and len(result.json()['sources'])==3
    assert projects.get(p['id'])['shared_drawing_building_id']==identity


def test_concurrent_first_uploads_join_one_namespace(setup):
    client,_,_=setup;p=owner(client)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(upload,client,p,[(f'{index}.png',png()+str(index).encode())]) for index in range(2)]
        results=[future.result(10) for future in futures]
    assert all(result.status_code==200 for result in results),[result.text for result in results]
    assert len({result.json()['document_id'] for result in results})==1
    group=client.app.state.documents.get(results[0].json()['document_id'])
    assert len(group.sources)==2 and len(scopes(client,p['id']))==1


def make_legacy(client):
    store=client.app.state.documents;projects=client.app.state.projects
    a=store.add(png(),'a.png');b=store.add(png()+b'b','b.png')
    p=owner(client,'Old project')
    client.put(f"/api/projects/{p['id']}/files/{a.id}")
    client.put(f"/api/projects/{p['id']}/files/{b.id}")
    chats=[client.post(f"/api/projects/{p['id']}/chats",json={'building_id':group}).json() for group in [a.id,b.id,None]]
    rows=projects._read();record=next(row for row in rows if row['id']==p['id']);record.pop('shared_drawing_building_id');record['retained_extra']={'unknown':'keep'};projects._write(rows)
    return p,a,b,chats


def test_legacy_groups_and_general_are_scoped_without_rebinding_and_crud_keeps_siblings(setup):
    client,_,_=setup;p,a,b,chats=make_legacy(client)
    before=[deepcopy(client.app.state.project_chats.get(p['id'],chat['id'])) for chat in chats]
    rows=scopes(client,p['id']);assert {row['scope_id'] for row in rows}=={a.id,b.id,'shared'}
    for scope,chat in zip([a.id,b.id,'shared'],chats):
        records=client.get(base(p,scope)+'/chats').json()['chats']
        assert [record['id'] for record in records]==[chat['id']]
    assert client.patch(base(p,a.id),json={'name':'Renamed A'}).status_code==200
    assert client.delete(base(p,a.id)).status_code==200
    remaining=scopes(client,p['id']);assert {row['scope_id'] for row in remaining}=={b.id,'shared'}
    assert client.post(base(p,a.id)+'/restore').json()['name']=='Renamed A'
    after=[client.app.state.project_chats.get(p['id'],chat['id']) for chat in chats]
    assert after==before
    assert client.app.state.projects.get(p['id'])['retained_extra']=={'unknown':'keep'}
    assert client.app.state.documents.get(a.id).source_bytes==png()
    # An explicit General upload establishes only that context; old groups stay exact.
    uploaded=upload(client,p,[('general.png',png()+b'general')]).json()
    general=client.get(f"/api/projects/{p['id']}/chats/{chats[2]['id']}").json()
    assert general['building_id'] is None and general['effective_building_id']==uploaded['document_id']
    assert client.get(f"/api/projects/{p['id']}/chats/{chats[0]['id']}").json()['effective_building_id']==a.id


def test_shared_legacy_group_append_rejected_including_deleted_owner(setup):
    client,_,_=setup;store=client.app.state.documents
    group=store.add(png(),'linked.png');a=owner(client,'A');b=owner(client,'B')
    for p in [a,b]:client.put(f"/api/projects/{p['id']}/files/{group.id}")
    client.delete('/api/projects/'+b['id'])
    dto=next(row for row in scopes(client,a['id']) if row['source_group_id']==group.id)
    assert not dto['upload_allowed'] and 'more than one' in dto['upload_reason']
    before=store.get(group.id).revision_id
    assert upload(client,a,[('new.png',png()+b'new')],scope=group.id).status_code==409
    assert client.post(f'/api/buildings/{group.id}/sources',files={'file':('new.png',png()+b'new')}).status_code==409
    assert client.post('/api/documents',files=[('files',('linked.png',png())),('files',('new.png',png()+b'new'))]).status_code==409
    assert store.get(group.id).revision_id==before


def test_native_ifc_stays_separate_and_mixed_batch_publishes_no_membership(setup):
    client,_,_=setup;p=owner(client);model,*_=fixture_model();data=encode(model)
    mixed=upload(client,p,[('native.ifc',data),('plan.png',png())]);assert mixed.status_code==422,mixed.text
    assert client.app.state.projects.get(p['id'])['building_ids']==[]
    native=upload(client,p,[('native.ifc',data)]);assert native.status_code==200,native.text
    dto=native.json()['building_scope'];assert dto['kind']=='native_ifc' and not dto['upload_allowed']
    assert upload(client,p,[('plan.png',png())]).status_code==409


def test_anonymous_scopes_do_not_reveal_private_general_chats(prepared):
    root,doc,_=prepared
    with TestClient(create_app(storage_root=root,provider_factory=lambda:None),base_url='https://demo.test') as client:
        p=client.get('/api/buildings').json()['projects'][0]
        unlock(client)
        client.post(f"/api/projects/{p['id']}/chats",json={'building_id':None})
        client.post('/api/access/lock')
        rows=client.get('/api/buildings').json()['building_scopes']
        assert len(rows)==1 and rows[0]['source_group_id']==doc.id
        assert client.post(base(p,doc.id)+'/sources',files={'file':('private.png',png()+b'private')}).status_code==401


def test_compat_removal_cannot_break_shared_pointer_and_deleted_scope_rejects_chat(setup):
    client,providers,_=setup;p=owner(client)
    doc=upload(client,p,[('plan.png',png())]).json();group=doc['document_id']
    chat=client.post(base(p)+'/chats',json={}).json()
    response=client.delete(f"/api/projects/{p['id']}/files/{group}")
    assert response.status_code==409 and 'Building entry' in response.json()['detail']
    project=client.app.state.projects.get(p['id'])
    assert project['shared_drawing_building_id']==group and group in project['building_ids']
    assert client.get(base(p)+'/chats').status_code==200
    client.delete(base(p));before=len(providers)
    response=client.post('/api/chat',json={'project_id':p['id'],'session_id':chat['id'],
        'document_id':group,'revision_id':doc['revision_id'],'message':'Stale removed Building','request_id':'removed'})
    assert response.status_code==409 and len(providers)==before
    assert client.post(base(p)+'/restore').status_code==200


def test_general_scope_metadata_survives_last_null_chat_removal_and_restart(setup):
    client,_,_=setup;p,a,b,chats=make_legacy(client)
    sibling_sessions=[deepcopy(client.app.state.project_chats.get(p['id'],c['id'])) for c in chats[:2]]
    assert client.patch(base(p),json={'name':'Retained General'}).status_code==200
    assert client.delete(base(p)).status_code==200
    assert client.delete(f"/api/projects/{p['id']}/chats/{chats[2]['id']}").status_code==200
    # Recreate the metadata adapters as a restart without touching the live job store.
    from app.projects import ProjectStore
    from app.project_chats import ProjectChats
    client.app.state.projects=ProjectStore(client.app.state.documents)
    client.app.state.project_chats=ProjectChats(client.app.state.documents,client.app.state.projects)
    assert {r['scope_id'] for r in scopes(client,p['id'])}=={a.id,b.id}
    restored=client.post(base(p)+'/restore')
    assert restored.status_code==200,restored.text
    assert restored.json()['name']=='Retained General' and restored.json()['source_group_id'] is None
    assert client.get(base(p)+'/chats').json()['chats']==[]
    assert [client.app.state.project_chats.get(p['id'],c['id']) for c in chats[:2]]==sibling_sessions
    assert set(client.app.state.projects.get(p['id'])['building_ids'])=={a.id,b.id}


def test_grouped_drawing_voice_vocabulary_and_transcription_remain_available(voice_app):
    client,app,identity,provider,_=voice_app
    original=app.state.documents.get(identity)
    grouped=app.state.documents.add_many([(original.source_bytes+b'second','second.png')],building_id=identity)
    assert len(grouped.sources)==2
    assert client.get(f'/api/documents/{identity}/voice-vocabulary').status_code==200
    with client.websocket_connect('/api/voice/transcribe') as ws:
        ws.send_json({'type':'start','document_id':identity,'custom_vocabulary':['User term']})
        assert ws.receive_json()=={'type':'ready'}
        ws.send_json({'type':'cancel'})
    assert provider.terms==['User term'] and provider.closed.wait(1)
