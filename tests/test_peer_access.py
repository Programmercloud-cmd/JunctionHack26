"""Peer-review access switches without weakening pinned examples or source guards."""
import json
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import create_app
from app.public_access import PublicAccess, hash_access_code
from test_backend import png
from test_public_access import PUBLIC, PRIVATE, REVISION, NEW_REVISION, SOURCE, Store, request
from test_public_access_integration import prepared


@pytest.fixture(scope='module')
def verifier():
    return hash_access_code('test-only-peer-code')


def configured_access(tmp_path, verifier, **extra):
    manifest=tmp_path/'peer-examples.json'
    manifest.write_text(json.dumps([{'building_id':PUBLIC,'revision_id':REVISION}]))
    env={'BLUEPRINT_PUBLIC_DEMO':'1','BLUEPRINT_PUBLIC_EXAMPLES_FILE':str(manifest),
         'BLUEPRINT_DEMO_ACCESS_CODE_HASH':verifier,'BLUEPRINT_DEMO_SESSION_SECRET':'peer-test-secret',**extra}
    return PublicAccess.from_environment(env)


@pytest.mark.parametrize('flag,required',[('1',True),('0',False)])
def test_static_peer_mode_is_explicit_and_keeps_public_pins(tmp_path,verifier,flag,required):
    access=configured_access(tmp_path,verifier,BLUEPRINT_DEMO_REQUIRE_ACCESS_CODE=flag)
    assert access.enabled and access._requires_code() is required
    assert access.status(request())=={'public_demo':True,'access_code_required':required,
        'can_work':not required,'shared_workspace':not required}
    assert access.document(Store(),request(),PUBLIC).revision_id==REVISION
    with pytest.raises(HTTPException):access.document(Store(),request(),PUBLIC,NEW_REVISION)
    if not required:
        access.require_editor(request('/api/chat','POST'))
        assert access.document(Store(),request(),PRIVATE).revision_id==NEW_REVISION
        with pytest.raises(HTTPException) as denied:access.require_editable(request(),PUBLIC)
        assert denied.value.status_code==409


@pytest.mark.parametrize('flag',['','yes','true','2'])
def test_invalid_static_flag_is_rejected(tmp_path,verifier,flag):
    with pytest.raises(RuntimeError,match='BLUEPRINT_DEMO_REQUIRE_ACCESS_CODE'):
        configured_access(tmp_path,verifier,BLUEPRINT_DEMO_REQUIRE_ACCESS_CODE=flag)


def test_runtime_mode_changes_without_restarting_or_minting_open_sessions(tmp_path,verifier):
    mode=tmp_path/'access-mode';mode.write_text('code\n')
    access=configured_access(tmp_path,verifier,BLUEPRINT_DEMO_ACCESS_MODE_FILE=str(mode))
    req=request()
    assert access.status(req)['access_code_required'] and not access.is_editor(req)
    mode.write_text('open\n')
    assert not access.status(req)['access_code_required'] and access.is_editor(req)
    unlock=access.unlock(request('/api/access/unlock','POST'),'')
    assert 'set-cookie' not in unlock.headers
    assert json.loads(unlock.body)==access.status(req)
    locked=access.lock(request('/api/access/lock','POST'))
    assert json.loads(locked.body)==access.status(req)
    assert 'Max-Age=0' in locked.headers['set-cookie']
    mode.write_text('code\n')
    assert access.status(req)['access_code_required'] and not access.is_editor(req)
    with pytest.raises(HTTPException) as denied:access.require_editor(req)
    assert denied.value.status_code==401


@pytest.mark.parametrize('content',[None,b'',b'unknown\n',b'false\n',b'\xff'])
def test_configured_missing_or_invalid_mode_fails_closed_even_with_static_open(tmp_path,verifier,content):
    mode=tmp_path/'access-mode'
    if content is not None:mode.write_bytes(content)
    access=configured_access(tmp_path,verifier,BLUEPRINT_DEMO_REQUIRE_ACCESS_CODE='0',
                             BLUEPRINT_DEMO_ACCESS_MODE_FILE=str(mode))
    assert access._requires_code() and not access.is_editor(request())
    mode.write_text('open\n')
    assert access.is_editor(request())
    mode.unlink()
    assert not access.is_editor(request())


def test_unreadable_runtime_mode_fails_closed(tmp_path,verifier,monkeypatch):
    mode=tmp_path/'access-mode';mode.write_text('open\n')
    access=configured_access(tmp_path,verifier,BLUEPRINT_DEMO_REQUIRE_ACCESS_CODE='0',
                             BLUEPRINT_DEMO_ACCESS_MODE_FILE=str(mode))
    read=Path.read_text
    def denied(path,*args,**kwargs):
        if path==mode:raise PermissionError('private fixture path')
        return read(path,*args,**kwargs)
    monkeypatch.setattr(Path,'read_text',denied)
    assert access._requires_code() and not access.is_editor(request())


@pytest.mark.parametrize('origin,site',[('https://other.example',None),(None,'cross-site'),(None,'same-site')])
def test_open_mode_preserves_same_origin_and_protected_sources(tmp_path,verifier,origin,site):
    access=configured_access(tmp_path,verifier,BLUEPRINT_DEMO_REQUIRE_ACCESS_CODE='0')
    with pytest.raises(HTTPException) as denied:
        access.authorize_http(request('/api/chat','POST',origin=origin,site=site))
    assert denied.value.status_code==403
    access.validate_store(Store())
    with pytest.raises(HTTPException) as denied:access.require_uploadable(request(),[b'curated source'])
    assert denied.value.status_code==409 and SOURCE in access.protected_source_ids
    access.require_uploadable(request(),[b'different peer source'])


def test_one_live_app_transitions_code_open_code_with_same_cookie_free_client(prepared,tmp_path,monkeypatch):
    root,document,private=prepared
    mode=tmp_path/'access-mode';mode.write_text('code\n')
    monkeypatch.setenv('BLUEPRINT_DEMO_ACCESS_MODE_FILE',str(mode))
    calls=[]
    def forbidden():calls.append(True);raise AssertionError('Access checks must not infer')
    with TestClient(create_app(storage_root=root,provider_factory=forbidden),base_url='https://demo.test') as client:
        assert not client.cookies
        assert client.post('/api/projects',json={'name':'Peer fixture'}).status_code==401
        assert client.get('/api/buildings/'+private.id).status_code==404
        mode.write_text('open\n')
        status=client.get('/api/access');assert status.headers['cache-control']=='no-store'
        assert status.json()=={'public_demo':True,'access_code_required':False,'can_work':True,'shared_workspace':True}
        assert client.post('/api/projects',json={'name':'Peer fixture'}).status_code==201
        assert client.get('/api/buildings/'+private.id).status_code==200
        assert client.post('/api/access/unlock',json={'code':''}).status_code==200
        assert not client.cookies
        assert client.post('/api/access/lock').json()['can_work'] is True
        assert not client.cookies
        listing=client.get('/api/buildings').json()['buildings']
        example=next(row for row in listing if row['building_id']==document.id)
        assert example['read_only_model'] and example['pinned_revision_id']==document.revision_id
        assert client.post(f'/api/buildings/{document.id}/render',json={'base_revision_id':document.revision_id}).status_code==409
        assert client.post('/api/documents',files={'file':('renamed.png',png())}).status_code==409
        assert client.post('/api/projects',json={'name':'Cross-origin fixture'},headers={'Origin':'https://other.example'}).status_code==403
        mode.write_text('code\n')
        assert client.get('/api/access').json()['access_code_required'] is True
        assert client.get('/api/buildings/'+private.id).status_code==404
        assert client.post('/api/projects',json={'name':'No longer open'}).status_code==401
        assert not calls
