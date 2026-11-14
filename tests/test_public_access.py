"""Public access boundary without live credentials/providers or dataset fixtures."""
import hashlib
import json
from http.cookies import SimpleCookie
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request
from app.public_access import PublicAccess,COOKIE_NAME,hash_access_code

PUBLIC='a'*64
PRIVATE='b'*64
REVISION='c'*32
NEW_REVISION='d'*32
SOURCE=hashlib.sha256(b'curated source').hexdigest()


def request(path='/',method='GET',cookie=None,origin=None,site=None):
    headers=[(b'host',b'demo.example')]
    if cookie:headers.append((b'cookie',cookie.encode()))
    if origin:headers.append((b'origin',origin.encode()))
    if site:headers.append((b'sec-fetch-site',site.encode()))
    return Request({'type':'http','scheme':'https','server':('demo.example',443),'client':('127.0.0.1',1),
        'method':method,'path':path,'raw_path':path.encode(),'query_string':b'','headers':headers})


class Store:
    def __init__(self):self.calls=[]
    def _doc(self,identity,revision):
        return SimpleNamespace(id=identity,revision_id=revision,sources=[{'source_id':SOURCE}],
            public=lambda:{'building_id':identity,'revision_id':revision,'sources':[{'source_id':SOURCE}]})
    def revision(self,identity,revision):
        self.calls.append(('revision',identity,revision));return self._doc(identity,revision)
    def get(self,identity):self.calls.append(('current',identity));return self._doc(identity,NEW_REVISION)


@pytest.fixture(scope='module')
def verifier():return hash_access_code('test-only-shared-code')


@pytest.fixture
def access(verifier):return PublicAccess(True,{PUBLIC:REVISION},{PUBLIC:'Curated example'},verifier,'test-only-signing-secret')


def editor_cookie(access):
    response=access.unlock(request('/api/access/unlock','POST'),'test-only-shared-code')
    jar=SimpleCookie();jar.load(response.headers['set-cookie'])
    return f'{COOKIE_NAME}={jar[COOKIE_NAME].value}'


def test_configuration_defaults_local_and_public_fails_closed(tmp_path,verifier):
    assert not PublicAccess.from_environment({}).enabled
    with pytest.raises(RuntimeError):PublicAccess.from_environment({'BLUEPRINT_PUBLIC_DEMO':'yes'})
    env={'BLUEPRINT_PUBLIC_DEMO':'1'}
    with pytest.raises(RuntimeError):PublicAccess.from_environment(env)
    env['BLUEPRINT_DEMO_ACCESS_CODE_HASH']=verifier
    with pytest.raises(RuntimeError):PublicAccess.from_environment(env)
    env['BLUEPRINT_DEMO_SESSION_SECRET']='private-secret'
    with pytest.raises(RuntimeError):PublicAccess.from_environment(env)
    manifest=tmp_path/'examples.json';manifest.write_text(json.dumps({'examples':[{'building_id':PUBLIC,'revision_id':REVISION,'title':'Example'}]}))
    env['BLUEPRINT_PUBLIC_EXAMPLES_FILE']=str(manifest)
    access=PublicAccess.from_environment(env)
    assert access.examples=={PUBLIC:REVISION}
    assert verifier not in repr(access) and 'private-secret' not in repr(access)
    manifest.write_text(json.dumps([{'building_id':PUBLIC,'revision_id':REVISION}]*2))
    with pytest.raises(RuntimeError):PublicAccess.from_environment(env)


def test_startup_validates_exact_revisions_and_collects_embedded_source_ids(access):
    store=Store();access.validate_store(store)
    assert store.calls==[('revision',PUBLIC,REVISION)]
    assert access.protected_source_ids=={PUBLIC,SOURCE}
    store.revision=lambda *args:(_ for _ in ()).throw(ValueError('private exception value'))
    with pytest.raises(RuntimeError) as caught:access.validate_store(store)
    assert 'private exception' not in str(caught.value)


def test_unlock_secure_cookie_tamper_rotation_and_logout(access,verifier,caplog):
    response=access.unlock(request('/api/access/unlock','POST',origin='https://demo.example'),'test-only-shared-code')
    cookie=response.headers['set-cookie'];assert all(x in cookie for x in ('Secure','HttpOnly','SameSite=strict','Path=/'))
    assert 'Domain=' not in cookie and 'Max-Age' not in cookie and 'test-only-shared-code' not in cookie
    assert response.headers['cache-control']=='no-store'
    jar=SimpleCookie();jar.load(cookie);token=jar[COOKIE_NAME].value
    req=request(cookie=f'{COOKIE_NAME}={token}')
    assert access.is_editor(req) and access.status(req)['shared_workspace']
    assert not access.is_editor(request(cookie=f'{COOKIE_NAME}={token[:-1]}x'))
    rotated=PublicAccess(True,access.examples,{},verifier,'new-secret')
    assert not rotated.is_editor(req)
    rotated=PublicAccess(True,access.examples,{},hash_access_code('new-test-code'),access.session_secret)
    assert not rotated.is_editor(req)
    with pytest.raises(HTTPException) as caught:access.unlock(request('/api/access/unlock','POST'),'incorrect-sensitive-value')
    assert caught.value.status_code==401 and 'incorrect-sensitive-value' not in caught.value.detail
    assert 'incorrect-sensitive-value' not in caplog.text
    logout=access.lock(request('/api/access/lock','POST',cookie=f'{COOKIE_NAME}={token}'))
    assert 'Max-Age=0' in logout.headers['set-cookie']


@pytest.mark.parametrize('origin,site',[('https://other.example',None),('null',None),(None,'cross-site'),(None,'same-site')])
def test_cross_origin_mutations_reject_before_credentials(access,origin,site):
    with pytest.raises(HTTPException) as caught:access.authorize_http(request('/api/access/unlock','POST',origin=origin,site=site))
    assert caught.value.status_code==403


@pytest.mark.parametrize('path',[
    '/', '/chat','/static/app.js','/api/health','/api/access','/api/buildings',f'/api/buildings/{PUBLIC}',
    f'/api/buildings/{PUBLIC}/assumptions',f'/api/documents/{PUBLIC}/scene',f'/api/documents/{PUBLIC}/model.ifc',
    f'/api/documents/{PUBLIC}/pages/1',f'/api/buildings/{PUBLIC}/revisions/{REVISION}/pages/1',
    f'/api/buildings/{PUBLIC}/revisions/{REVISION}/evidence/0Ab_cd$'])
def test_anonymous_exact_public_read_routes(access,path):
    access.authorize_http(request(path));access.authorize_http(request(path,'HEAD'))


@pytest.mark.parametrize('path',[
    '/api/unknown','/docs','/openapi.json',f'/api/buildings/{PRIVATE}',f'/api/documents/{PRIVATE}/scene',
    f'/api/documents/{PRIVATE}/model.ifc',f'/api/documents/{PRIVATE}/pages/1',
    f'/api/buildings/{PUBLIC}/conversation',f'/api/jobs/{REVISION}',
    f'/api/buildings/{PUBLIC}/sources/{SOURCE}/original',f'/api/buildings/{PUBLIC}/revisions/{NEW_REVISION}/pages/1',
    f'/api/buildings/{PUBLIC}/revisions/{NEW_REVISION}/evidence/id',f'/api/documents/{PUBLIC}/scene/extra',
    f'/api/resources/{SOURCE}',f'/api/buildings/{PUBLIC}%2fconversation'])
def test_anonymous_nonpublic_read_routes_are_uniformly_hidden(access,path):
    with pytest.raises(HTTPException) as caught:access.authorize_http(request(path))
    assert caught.value.status_code==404


@pytest.mark.parametrize('path',[
    '/api/documents','/api/questions','/api/ask','/api/chat','/api/chat/actions','/api/new-future-paid-route',
    f'/api/documents/{PUBLIC}/scene',f'/api/buildings/{PUBLIC}/sources',f'/api/buildings/{PUBLIC}/extraction',
    f'/api/buildings/{PUBLIC}/reconstruction',f'/api/buildings/{PUBLIC}/refinements',f'/api/jobs/{REVISION}/stop'])
def test_paid_or_mutating_routes_require_code_before_body(access,path):
    with pytest.raises(HTTPException) as caught:access.authorize_http(request(path,'POST'))
    assert caught.value.status_code==401


def test_pinned_reads_and_qa_do_not_follow_current(access):
    store=Store();anonymous=request();editor=request(cookie=editor_cookie(access))
    for req in (anonymous,editor):
        assert access.document(store,req,PUBLIC).revision_id==REVISION
        with pytest.raises(HTTPException):access.document(store,req,PUBLIC,NEW_REVISION)
    with pytest.raises(HTTPException):access.question_document(store,anonymous,PUBLIC)
    assert access.question_document(store,editor,PUBLIC).revision_id==REVISION
    with pytest.raises(HTTPException):access.document(store,anonymous,PRIVATE)
    assert access.document(store,editor,PRIVATE).revision_id==NEW_REVISION
    rows=access.public_buildings(store)
    assert len(rows)==1 and rows[0]['revision_id']==REVISION and rows[0]['public_example'] and rows[0]['read_only_model']
    assert rows[0]['pinned_revision_id']==REVISION and 'jobs' not in rows[0]
    assert not access.descriptor(store.get(PRIVATE))['public_example']


def test_code_holder_cannot_edit_examples_but_can_ask_and_use_private_work(access):
    req=request(cookie=editor_cookie(access));store=Store()
    access.authorize_http(request('/api/questions','POST',cookie=editor_cookie(access)))
    assert access.question_document(store,req,PUBLIC).revision_id==REVISION
    with pytest.raises(HTTPException) as caught:access.require_editable(req,PUBLIC)
    assert caught.value.status_code==409 and 'copy' not in caught.value.detail
    access.require_editable(req,PRIVATE)
    access.authorize_http(request(f'/api/buildings/{PUBLIC}/conversation',cookie=editor_cookie(access)))


@pytest.mark.parametrize('position',[0,1,2])
def test_whole_multipart_batch_blocks_curated_source_in_every_position(access,position):
    access.validate_store(Store());payloads=[(b'private-'+str(i).encode(),'private.png') for i in range(3)]
    payloads[position]=(b'curated source','renamed.png')
    with pytest.raises(HTTPException) as caught:access.require_uploadable(request(cookie=editor_cookie(access)),payloads)
    assert caught.value.status_code==409
    access.require_uploadable(request(cookie=editor_cookie(access)),[(b'different source','new.png')])


def test_local_mode_keeps_existing_workflow():
    access=PublicAccess();req=request('/api/anything','POST',origin='https://other.example')
    access.authorize_http(req);access.require_editor(req);access.require_editable(req,PUBLIC)
    assert access.is_editor(req) and not access.status(req)['shared_workspace']



def test_private_qa_keeps_existing_stale_revision_guard(access):
    editor=request(cookie=editor_cookie(access));store=Store()
    assert access.question_document(store,editor,PRIVATE,NEW_REVISION).revision_id==NEW_REVISION
    with pytest.raises(HTTPException) as caught:access.question_document(store,editor,PRIVATE,REVISION)
    assert caught.value.status_code==409
