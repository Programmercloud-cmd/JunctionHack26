"""Browser contract checks with explicit API fixtures; no live inference claims."""
import copy
import os
from pathlib import Path
import socket
import threading
import time

import pytest
from test_browser import source_bytes, ask, FixtureProvider
from test_browser_3d import scene_page, action, control

pytestmark=pytest.mark.skipif(os.getenv('RUN_BROWSER_TESTS')!='1',reason='opt-in browser checks')


@pytest.fixture
def static_server():
    import uvicorn
    from fastapi import FastAPI
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles
    root=Path(__file__).resolve().parents[1]/'app'/'static'
    app=FastAPI();app.mount('/static',StaticFiles(directory=root),name='static')
    @app.get('/')
    def index():return FileResponse(root/'index.html')
    sock=socket.socket();sock.bind(('127.0.0.1',0))
    server=uvicorn.Server(uvicorn.Config(app,log_level='error'))
    thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True);thread.start()
    deadline=time.monotonic()+5
    while not server.started and time.monotonic()<deadline:time.sleep(.02)
    assert server.started
    yield f'http://127.0.0.1:{sock.getsockname()[1]}'
    server.should_exit=True;thread.join(5);sock.close()


def setup_routes(page,scene=None):
    building='b'*64;revision='a'*32
    document={'document_id':building,'building_id':building,'filename':'Assembly plan.png','kind':'drawing',
        'revision_id':revision,'revision_number':1,'review_status':'source_available','interpretation_status':'complete',
        'geometry_status':'available' if scene else 'not_requested','geometry_revision_id':revision if scene else None,
        'has_scene':bool(scene),'scene_url':f'/api/documents/{building}/scene' if scene else None,
        'pages':[{'page':1,'width':600,'height':400,'source_id':'c'*64,'source_page':1,'source_filename':'Assembly plan.png',
        'image_url':f'/api/buildings/{building}/revisions/{revision}/pages/1'}],
        'warnings':[],'sources':[{'source_id':'c'*64,'filename':'Assembly plan.png','kind':'png','pages':[{'page':1}]}]}
    messages=[];requests=[];jobs=[]
    def handle(route):
        path=route.request.url.split('/api/',1)[1];requests.append((route.request.method,path,route.request.post_data))
        if path=='access':data={'public_demo':False,'can_work':True,'shared_workspace':False}
        elif path=='chat/actions':
            import json
            request=json.loads(route.request.post_data);message=request['message']
            if message.startswith('Fixture control: '):actions=json.loads(message.removeprefix('Fixture control: '))
            elif message=='Set Assembly floor height to 3.4 m':actions=[{'type':'refine','edits':[{'scope':{'floor_id':'f1'},'property':'floor_height','value':3.4,'unit':'m','reason':'User supplied height; not observed in source'}]}]
            else:actions=[{'type':'question','question':message,'revision_id':request.get('revision_id')}]
            data={**{k:request.get(k) for k in ('request_id','document_id','revision_id')},'geometry_revision_id':request.get('workspace',{}).get('geometry_revision_id'),'navigation_epoch':request.get('workspace',{}).get('navigation_epoch'),'status':'ready','actions':actions,'message':'Explicit fake intent only','usage':{}}
        elif path=='health':data={'provider_ready':True,'provider_label':'Gemini','provider':'gemini','limits':{'max_upload_mb':10,'max_ifc_mb':25,'max_pages':5}}
        elif '/pages/' in path:return route.fulfill(content_type='image/png',body=source_bytes())
        elif path=='documents':data={**document,'is_new_upload':True,'extraction_jobs':[]}
        elif path=='buildings':data={'buildings':[document]}
        elif path==f'buildings/{building}':data={**document,'jobs':jobs}
        elif path.endswith('/conversation'):data={'conversation_id':building,'messages':messages}
        elif path.endswith('/assumptions'):data={'building_id':building,'revision_id':document['revision_id'],'rows':[
            {'id':'height','scope':{'floor_id':'f1'},'property':'floor_height','label':'Assembly floor height','value':None,'unit':'m','provenance':'unknown','reason':'No source height supplied','source':{'page':1,'bbox':[0,0,1,1]},'editable':True}]}
        elif path.endswith('/refinements'):
            data={'id':'edit-job','building_id':building,'kind':'refinement','status':'complete','phase':'complete','message':'Fixture submitted values saved','issues':[]};jobs.insert(0,data)
        elif path.endswith('/sources'):
            document['revision_id']='d'*32;document['revision_number']=2
            document['pages'].append({'page':2,'source_page':1,'source_filename':'Section.png','width':600,'height':400,'image_url':f'/api/documents/{building}/pages/2'})
            data={**document,'extraction_jobs':[]}
        elif path=='questions':
            import json
            request=json.loads(route.request.post_data);question=request['question'];identifier=str(len(messages)+1)
            answer={'status':'clarification' if 'How many' in question else 'answered','answer':'Which floor?' if 'How many' in question else 'Fixture: an assembly hall is depicted.',
                'clarification':{'message':'Which floor?','suggestions':['Ground floor','Both floors'],'free_text_allowed':True} if 'How many' in question else None,
                'answered_revision_id':revision,'display_revision_id':document['revision_id'],'gate':None,'inspection_passes':0,'usage':{},'highlight_ids':[],
                'support_summary':'Fixture support explanation, not live inference','evidence':[] if 'How many' in question else [{'page':1,'bbox':[.1,.2,.6,.7],'label':'Assembly hall','observation':'Original label'}]}
            messages.extend([{'id':identifier+'u','role':'user','question':question,'revision_id':revision},
                {'id':identifier+'a','role':'assistant','answer':answer,'revision_id':revision}])
            data={'id':'job'+identifier,'building_id':building,'kind':'question','question':question,'request_id':request['request_id'],'status':'complete','phase':'complete','message':'Fixture checked','answer':answer,'issues':[]};jobs.insert(0,data)
        elif path.endswith('/scene') and scene:data=scene
        else:return route.fulfill(status=404,json={'detail':'Unexpected test route: '+path})
        route.fulfill(json=data)
    page.route('**/api/**',handle)
    return document,messages,requests


def test_source_first_chat_append_pinned_evidence_and_batch_inputs(static_server,scene_page):
    from playwright.sync_api import expect
    page=scene_page;document,messages,requests=setup_routes(page)
    page.goto(static_server)
    page.locator('#file-input').set_input_files([{'name':'plan.png','mimeType':'image/png','buffer':source_bytes()},{'name':'section.png','mimeType':'image/png','buffer':source_bytes()}])
    page.get_by_role('button',name='Inspect original',exact=True).click()
    expect(page.locator('#page-image')).to_be_visible()
    assert not any('reconstruction' in path or path.endswith('/scene') for _,path,_ in requests)
    page.locator('#question').fill('How many spaces?');page.locator('#ask-button').click()
    expect(page.locator('.chat-answer').last).to_contain_text('Clarify your question')
    page.locator('.chat-answer').last.locator('summary').click()
    expect(page.locator('.chat-answer').last).to_contain_text('Fixture support')
    page.locator('.chat-answer').last.get_by_role('button',name='Ground floor',exact=True).click()
    expect(page.locator('.chat-answer').last).to_contain_text('assembly hall')
    expect(page.locator('.chat-user')).to_have_count(2)
    import json
    submitted=[json.loads(body) for method,path,body in requests if path=='questions']
    assert submitted[1]['reply_to']=='1a' and submitted[1]['clarification_response']=='Ground floor'
    # Appending a source preserves the conversation and old answer citations.
    page.evaluate("state.uploadMode='append'")
    page.locator('#file-input').set_input_files({'name':'section.png','mimeType':'image/png','buffer':source_bytes()})
    expect(page.locator('.chat-user')).to_have_count(2)
    page.locator('.chat-citation',has_text='Assembly hall').click()
    expect(page.locator('#evidence-overlay')).to_be_visible()
    expect(page.locator('#page-image')).to_have_attribute('src',f'{static_server}/api/buildings/{document["building_id"]}/revisions/{"a"*32}/pages/1')
    assert not any(path.endswith('/refinements') for _,path,_ in requests)
    ask(page,'Set Assembly floor height to 3.4 m')
    page.wait_for_function("state.jobs.some(j=>j.kind==='refinement')")
    edit=json.loads(next(body for _,path,body in requests if path.endswith('/refinements')))
    assert edit['edits'][0]['value']==3.4 and edit['edits'][0]['unit']=='m'
    assert edit['base_revision_id']=='d'*32


def test_native_clipping_all_floors_preserves_meshes_and_mode(static_server,scene_page):
    page=scene_page;document,_,_=setup_routes(page)
    page.goto(static_server)
    page.locator('#file-input').set_input_files({'name':'plan.png','mimeType':'image/png','buffer':source_bytes()})
    page.wait_for_function('state.document!==null')
    scene={'document_id':document['document_id'],'building_id':document['building_id'],'revision_id':'a'*32,'revision_number':1,
        'derived':False,'units':'m','layout':'aligned','floors':[],'elements':[],'warnings':[],
        'uncontained_reference':{'base_elevation':0,'reference_height':8,'basis':'Scene extent display reference'}}
    for i,z in enumerate([0,4]):
        fid=f'f{i}';scene['floors'].append({'id':fid,'label':f'Supplied storey {i}','source':{'kind':'ifc','global_id':fid},'base_elevation':z,'reference_height':4,'reference_height_basis':'Supplied storey separation','elevation_basis':'IFC placement','scale_status':'known','order':i,'rotation_degrees':0,'alignment_status':'supported','assumptions':[]})
        scene['elements'].append({'id':f'w{i}','name':'Source wall','kind':'wall','ifc_type':'IfcWall','storey_id':fid,'geometry_origin':'extracted','assumptions':[],'properties':[],'source':{'kind':'ifc','global_id':f'w{i}'},'geometry':{'type':'box','center':[i*2,0,z+2],'size':[1,.2,4]}})
    page.evaluate('(scene)=>loadScene(scene)',scene);page.wait_for_function('window.blueprintViewer?.meshes.size===2')
    assert page.locator('#floor-select option').count()==3
    before=page.evaluate('Array.from(blueprintViewer.meshes.values(),m=>Array.from(m.geometry.attributes.position.array))')
    action(page,{'type':'set_cutaway','percent':50})
    result=page.evaluate('blueprintViewer.getSnapshot()')
    assert result['cutaway_percent']==50 and [e['clipping_planes'] for e in result['elements']]==[[2],[6]]
    action(page,{'type':'set_floor','floor_id':'f1'})
    assert [e['visible'] for e in page.evaluate('blueprintViewer.getSnapshot().elements')]==[False,True]
    action(page,{'type':'set_view','mode':'concept'})
    assert page.evaluate('blueprintViewer.concept.cutawayPercent')==50
    assert page.evaluate('Array.from(blueprintViewer.concept.floors.values(),f=>f.plane.constant)')==[2,6]
    action(page,{'type':'set_cutaway','percent':0})
    assert page.evaluate('Array.from(blueprintViewer.concept.floors.values(),f=>f.plane.constant)')==[0,4]
    action(page,{'type':'set_cutaway','percent':100})
    action(page,{'type':'set_view','mode':'model'})
    assert page.evaluate('Array.from(blueprintViewer.meshes.values(),m=>m.material.clippingPlanes.length)')==[0,0]
    after=page.evaluate('Array.from(blueprintViewer.meshes.values(),m=>Array.from(m.geometry.attributes.position.array))')
    assert after==before


@pytest.fixture
def sourcefirst_server(tmp_path,monkeypatch):
    """Real backend with a deterministic source interpreter and reviewers."""
    import uvicorn
    from app.main import create_app
    from app.schemas import Usage,QuestionIntent,Clarification,GateResult,DraftAnswer,Evidence
    from app.review_schema import ReconstructionReview,AnswerReview
    from test_ifc_generate import description,floor,room
    class Provider:
        def interpret_chat_actions(self,message,catalog):
            if message=='Set Assembly floor height to 3.4 m':
                return {'status':'ready','actions':[{'type':'refine','edits':[{'scope':{'floor_id':catalog['floors'][0]['id']},'property':'floor_height','value':3.4,'unit':'m','reason':'Explicit user height, not source-observed'}]}]}
            return FixtureProvider.interpret_chat_actions(self,message,catalog)
        def __init__(self):self.usage=Usage();self.extract_calls=0;self.review_calls=0
        def extract_interpretation(self,document,include_geometry=False):
            assert include_geometry is False
            self.extract_calls+=1
            return description(floor('Assembly floor',rooms=[room(label='Assembly hall')]))
        def enrich_geometry(self,document):raise AssertionError('Complete fixture geometry must be reused')
        def reconstruct(self,*args):raise AssertionError('Source-first uses extraction and explicit enrichment')
        def review_reconstruction(self,*args,**kwargs):
            self.review_calls+=1
            return ReconstructionReview(candidate_supported=True,summary='Explicit fake review; not model-fidelity evidence',
                candidate_assessment={'delta_support':'supported','source_conflicts':[],'new_regressions':[],
                    'pre_existing_issue_ids':[],'unresolved':[],'unresolved_delta':[],'issue_resolutions':[]} if kwargs.get('change_context') else None)
        def resolve_intent(self,document,question):
            if question=='How many spaces?':return QuestionIntent(action='clarify',clarification=Clarification(message='Which floor?',suggestions=['Assembly floor']))
            return QuestionIntent(action='answer',resolved_question=question)
        def gate(self,document,question,crop=None):return GateResult(decision='insufficient' if 'height' in question else 'sufficient')
        def answer(self,document,question,gate,crop=None):
            if gate.decision=='insufficient':return DraftAnswer(status='insufficient',answer='The original drawing does not establish actual height.',missing_information=['Source height dimension'])
            return DraftAnswer(status='answered',answer='Fixture: the assembly hall label is depicted.',evidence=[Evidence(page=1,bbox=[.1,.2,.6,.7],label='Assembly hall',observation='Fixture original label')],support_summary='The cited original label supports this fixture answer.')
        def review_answer(self,*args,**kwargs):return AnswerReview(decision='supported')
        def revise_answer(self,*args,**kwargs):raise AssertionError('Supported fixture needs no correction')
        def close(self):pass
    provider=Provider();monkeypatch.setenv('GEMINI_API_KEY','fixture-never-sent')
    app=create_app(provider_factory=lambda:provider,storage_root=tmp_path/'bundle')
    sock=socket.socket();sock.bind(('127.0.0.1',0));instance=uvicorn.Server(uvicorn.Config(app,log_level='error'))
    thread=threading.Thread(target=instance.run,kwargs={'sockets':[sock]},daemon=True);thread.start()
    deadline=time.monotonic()+5
    while not instance.started and time.monotonic()<deadline:time.sleep(.02)
    assert instance.started
    yield f'http://127.0.0.1:{sock.getsockname()[1]}',provider,app
    instance.should_exit=True;thread.join(5);sock.close()


def test_real_source_only_chat_explicit_ifc_and_user_height(sourcefirst_server,scene_page):
    from playwright.sync_api import expect
    url,provider,app=sourcefirst_server;page=scene_page;page.goto(url)
    page.locator('#file-input').set_input_files({'name':'assembly.png','mimeType':'image/png','buffer':source_bytes()})
    page.wait_for_function("state.document?.interpretation_status==='complete'",timeout=15000)
    assert provider.extract_calls==1 and provider.review_calls==0
    assert page.evaluate('window.blueprintViewer===null')
    building=page.evaluate('state.document.building_id')
    assert app.state.documents.get(building).description is not None
    page.locator('#question').fill('How many spaces?');page.locator('#ask-button').click()
    expect(page.locator('.chat-answer').last).to_contain_text('Clarify your question',timeout=15000)
    page.locator('.chat-answer').last.get_by_role('button',name='Assembly floor',exact=True).click()
    expect(page.locator('.chat-answer').last).to_contain_text('assembly hall label',timeout=15000)
    expect(page.locator('.chat-user')).to_have_count(2)
    page.locator('.chat-answer').last.locator('.chat-citation').click();expect(page.locator('#evidence-overlay')).to_be_visible()
    control(page,'Show model')
    page.wait_for_function('window.blueprintViewer?.meshes.size>0',timeout=30000)
    page.wait_for_function("state.jobs.some(j=>j.kind==='reconstruction'&&j.status==='complete')",timeout=15000)
    assert provider.extract_calls==1 and provider.review_calls==1
    action(page,{'type':'set_view','mode':'concept'})
    before=page.evaluate('blueprintViewer.getSnapshot()')
    ask(page,'Set Assembly floor height to 3.4 m')
    page.wait_for_function("state.jobs.some(j=>j.kind==='refinement'&&['complete','needs_attention','failed'].includes(j.status))",timeout=15000)
    job=page.evaluate("state.jobs.find(j=>j.kind==='refinement')")
    assert job['status']=='complete',job
    after=page.evaluate('blueprintViewer.getSnapshot()')
    assert after['mode']=='concept' and after['camera_position']==pytest.approx(before['camera_position'])
    assert app.state.documents.get(building).user_values[0]['value']==3.4
    assert provider.review_calls==2
    page.locator('#question').fill('What actual height is shown in the drawing?');page.locator('#ask-button').click()
    expect(page.locator('.chat-answer').last).to_contain_text('Insufficient source evidence',timeout=15000)
    calls=provider.extract_calls
    page.locator('#file-input').set_input_files({'name':'renamed.png','mimeType':'image/png','buffer':source_bytes()})
    page.wait_for_function('window.blueprintViewer?.meshes.size>0',timeout=15000)
    assert provider.extract_calls==calls
    assert sum(m['role']=='user' for m in app.state.documents.conversation(building))==3


def test_queued_question_response_preserves_newly_typed_followup(static_server,scene_page):
    """A delayed enqueue response must not erase text typed for the next turn."""
    import json
    from playwright.sync_api import expect
    page=scene_page;document,_,_=setup_routes(page);pending=[]
    page.route('**/api/questions',lambda route:pending.append(route))
    page.goto(static_server)
    page.locator('#file-input').set_input_files({'name':'plan.png','mimeType':'image/png','buffer':source_bytes()})
    page.locator('#question').fill('First question')
    with page.expect_request('**/api/questions'):page.locator('#ask-button').click()
    page.locator('#question').fill('A newly typed follow-up')
    assert len(pending)==1
    submitted=json.loads(pending[0].request.post_data)
    pending[0].fulfill(json={'id':'pending-question','building_id':document['building_id'],'kind':'question',
        'request_id':submitted['request_id'],'question':submitted['question'],'status':'queued','phase':'queued','message':'Explicit delayed queue fixture','issues':[]})
    expect(page.locator('#ask-button')).to_be_enabled()
    expect(page.locator('#question')).to_have_value('A newly typed follow-up')


def test_failed_job_exposes_only_sanitized_diagnostic_as_text(static_server,scene_page):
    from playwright.sync_api import expect
    page=scene_page;document,_,_=setup_routes(page)
    diagnostic="Gemini reached its output token limit. <retry> explicitly when ready."
    failed={"id":"failed-dxf","building_id":document["building_id"],"kind":"reconstruction","status":"failed",
        "phase":"failed","message":"Source processing failed operationally; saved interpretation retained.",
        "diagnostic_message":diagnostic,"issues":[],"internal_detail":"INTERNAL_ONLY_NOT_FOR_DISPLAY"}
    page.route(f'**/api/buildings/{document["building_id"]}',lambda route:route.fulfill(json={**document,"jobs":[failed]}))
    page.goto(static_server)
    page.locator('#file-input').set_input_files({'name':'plan.png','mimeType':'image/png','buffer':source_bytes()})
    row=page.locator('[data-entry="job:failed-dxf"]')
    expect(row).to_be_visible()
    expect(row).to_contain_text(diagnostic)
    expect(row).to_contain_text('saved interpretation retained')
    expect(row).not_to_contain_text('INTERNAL_ONLY_NOT_FOR_DISPLAY')
    assert row.locator('retry').count()==0
