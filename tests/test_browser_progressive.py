"""Progressive UI against real local HTTP/jobs/IFC with explicitly fake inference."""
import os
import socket
import threading
import time

import pytest
from test_browser import upload,ask
from test_browser_3d import scene_page,snapshot,action,control
from test_browser_concept import ConceptFixtureProvider

pytestmark=pytest.mark.skipif(os.getenv('RUN_BROWSER_TESTS')!='1',reason='opt-in browser checks')


class ProgressiveFixtureProvider(ConceptFixtureProvider):
    def __init__(self):
        super().__init__();self.reconstruction_calls=0;self.review_calls=0
        self.review_entered=threading.Event();self.review_release=threading.Event();self.review_release.set()
        self.answer_entered=threading.Event();self.answer_release=threading.Event();self.answer_release.set()
    def reconstruct(self,document):
        self.reconstruction_calls+=1;d=super().reconstruct(document)
        if 'elevation' in document.filename:d.floors[0].view_type='elevation'
        return d
    def review_reconstruction(self,*args,**kwargs):
        from app.review_schema import ReconstructionReview
        self.review_calls+=1;self.review_entered.set();assert self.review_release.wait(40)
        return ReconstructionReview(candidate_supported=True,summary='Injected browser review; no live fidelity claim',issues=[])
    def answer(self,document,question,gate,crop=None):
        if document.kind=='ifc' and not document.scene.derived:
            from app.schemas import DraftAnswer
            target=next(r for r in document.reasoning['objects']if r['name']==('Source template' if 'template' in question else 'Source window'))
            name='PredefinedType' if 'template' in question else 'Many.P59'
            return DraftAnswer(status='answered',answer='Fixture citation to an original IFC property.',model_evidence=[{'element_id':target['id'],'property_name':name,'label':target['name'],'observation':'Injected citation fixture; inspect original source.'}])
        if 'slow' in question:self.answer_entered.set();assert self.answer_release.wait(40)
        answer=super().answer(document,question,gate,crop)
        if answer.status=='answered':answer.answer=f'Fixture answer: {question}'
        return answer


@pytest.fixture
def progressive_server(tmp_path,monkeypatch):
    import uvicorn
    from app.main import create_app
    monkeypatch.setenv('AI_PROVIDER','gemini');monkeypatch.setenv('GEMINI_API_KEY','fixture-never-sent')
    ProgressiveFixtureProvider.unresolved_only=False
    provider=ProgressiveFixtureProvider();app=create_app(provider_factory=lambda:provider,storage_root=tmp_path/'uploads')
    sock=socket.socket();sock.bind(('127.0.0.1',0));server=uvicorn.Server(uvicorn.Config(app,log_level='error'))
    thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True);thread.start()
    deadline=time.monotonic()+5
    while not server.started and time.monotonic()<deadline:time.sleep(.02)
    assert server.started
    yield f'http://127.0.0.1:{sock.getsockname()[1]}',provider,app
    provider.review_release.set();provider.answer_release.set();server.should_exit=True;thread.join(5);sock.close()


def test_preview_review_stop_saved_reopen_and_current_question(progressive_server,scene_page):
    from playwright.sync_api import expect
    url,provider,app=progressive_server;page=scene_page
    provider.review_release.clear();page.goto(url);expect(page.locator('#chat-connection')).to_contain_text('Gemini')
    upload(page)
    page.wait_for_function("state.document?.interpretation_status==='complete'",timeout=15000)
    assert page.evaluate('window.blueprintViewer===null')
    assert provider.review_calls==0
    ask(page,'Show model')
    page.wait_for_function('window.blueprintViewer?.data.derived===true',timeout=30000)
    assert provider.review_entered.is_set()
    expect(page.locator('#building-review-status')).to_contain_text('review in progress')
    page.wait_for_function("chatUI.snapshot().view_mode==='model'")
    action(page,{'type':'set_view','mode':'concept'},{'type':'set_visibility','target':'assumptions','enabled':True})
    source=page.evaluate("window.blueprintViewer.data.elements.find(e=>e.kind==='furniture')")
    page.evaluate('id=>window.blueprintViewer.select(id)',source['id'])
    page.evaluate('''()=>{const v=window.blueprintViewer;v.camera.position.x+=.4;v.controls.update();v.render();}''')
    before=snapshot(page);provider.review_release.set()
    expect(page.locator('#building-review-status')).to_contain_text('Reviewed',timeout=15000)
    after=snapshot(page);assert after['revision_number']>before['revision_number']
    for field in ('camera_position','camera_target'):assert after[field]==pytest.approx(before[field],abs=1e-10)
    for field in ('mode','selected_id','show_assumptions'):assert after[field]==before[field]
    provider.review_entered.clear();provider.review_release.clear();ask(page,'Fixture control: [{"type":"reconstruct","mode":"refine"}]')
    assert provider.review_entered.wait(10)
    before_stop=snapshot(page)['revision_id']
    page.get_by_role('button',name='Stop this operation',exact=True).click();provider.review_release.set()
    expect(page.locator('#chat-log [data-status="stopped"]')).to_be_visible(timeout=10000)
    expect(page.locator('#building-review-status')).to_contain_text('review stopped')
    expect(page.locator('#building-review-status')).not_to_contain_text('in progress')
    page.wait_for_timeout(200);assert snapshot(page)['revision_id']==before_stop
    building=snapshot(page)['building_id'];calls=provider.reconstruction_calls
    page.reload();page.get_by_role('button',name='Open saved building',exact=True).click();page.locator('#chat-log button',has_text='plan.png').click()
    page.wait_for_function('window.blueprintViewer?.data.derived===true',timeout=30000)
    assert provider.reconstruction_calls==calls
    # Re-uploading identical bytes opens the durable model without a new extraction.
    upload(page);page.wait_for_function('window.blueprintViewer?.data.derived===true',timeout=30000)
    assert provider.reconstruction_calls==calls
    provider.answer_release.clear();ask(page,'slow first question');assert provider.answer_entered.wait(10)
    ask(page,'latest question')
    expect(page.locator('.chat-answer').last).to_contain_text('Fixture answer: latest question',timeout=15000)
    provider.answer_release.set()
    for future in list(app.state.jobs.futures.values()):future.result(10)
    action(page,{'type':'refresh'})
    assert page.evaluate('state.result.answer')=='Fixture answer: latest question'
    ask(page,'What is the actual ceiling height?')
    expect(page.locator('.chat-answer').last).to_contain_text('Insufficient source evidence',timeout=15000)
    page.screenshot(path='/tmp/product-progressive-jobs.png',full_page=True)
    # A late answer for a building left behind cannot populate the new building.
    provider.answer_entered.clear();provider.answer_release.clear()
    ask(page,'slow question for old building');assert provider.answer_entered.wait(10)
    upload(page,pdf=True,name='elevation.pdf')
    page.wait_for_function("state.document?.interpretation_status==='complete'",timeout=15000)
    assert page.evaluate('state.document.unresolved_views.length')>0
    provider.answer_release.set()
    for future in list(app.state.jobs.futures.values()):future.result(10)
    action(page,{'type':'refresh'})
    expect(page.locator('.chat-answer')).to_have_count(0)
    assert page.evaluate('state.document.building_id')!=building



def test_source_only_views_reopen_without_automatic_restart(progressive_server,scene_page):
    from playwright.sync_api import expect
    url,provider,_=progressive_server;page=scene_page;page.goto(url)
    expect(page.locator('#chat-connection')).to_contain_text('Gemini')
    upload(page,name='elevation.png')
    page.wait_for_function("state.document?.interpretation_status==='complete'",timeout=15000)
    assert page.evaluate('state.document.unresolved_views.length')>0
    assert page.evaluate('window.blueprintViewer===null')
    expect(page.locator('#unsupported-views')).to_contain_text('elevation')
    page.get_by_role('button',name='Inspect original',exact=True).click();expect(page.locator('#page-image')).to_be_visible()
    building=page.evaluate('state.document.building_id');calls=provider.reconstruction_calls
    page.reload();page.get_by_role('button',name='Open saved building',exact=True).click();page.locator('#chat-log button',has_text='elevation.png').click()
    page.wait_for_function('state.document!==null')
    assert page.evaluate('state.document.unresolved_views.length')>0
    upload(page,name='elevation.png')
    assert page.evaluate('state.document.unresolved_views.length')>0
    assert provider.reconstruction_calls==calls
    revision=page.evaluate('state.document.revision_number')
    action(page,{'type':'reconstruct','mode':'reconstruct'})
    page.wait_for_function("state.jobs.some(j=>j.kind==='reconstruction'&&j.status==='needs_attention')",timeout=15000)
    assert page.evaluate('state.document.revision_number')==revision, 'A no-floor interpretation remains saved without fabricating a geometry revision'
    expect(page.locator('#chat-log')).to_contain_text('no floor-plan geometry')
    assert provider.reconstruction_calls==calls, 'Explicit geometry reuses the saved source-only interpretation'
    assert page.evaluate('window.blueprintViewer===null')
    page.screenshot(path='/tmp/product-progressive-source-only.png',full_page=True)


def test_native_citations_inspect_pinned_meshless_and_definition_records(progressive_server,scene_page):
    import ifcopenshell
    from playwright.sync_api import expect
    from test_ifc_import import fixture_model,encode
    url,provider,app=progressive_server;page=scene_page
    model,_,window,_=fixture_model()
    properties=model.create_entity('IfcPropertySet',GlobalId=ifcopenshell.guid.new(),Name='Many',HasProperties=[model.create_entity('IfcPropertySingleValue',Name=f'P{i}',NominalValue=model.create_entity('IfcReal',float(i)))for i in range(60)])
    model.create_entity('IfcRelDefinesByProperties',GlobalId=ifcopenshell.guid.new(),RelatedObjects=[window],RelatingPropertyDefinition=properties)
    template=model.create_entity('IfcWindowType',GlobalId=ifcopenshell.guid.new(),Name='Source template',PredefinedType='WINDOW',PartitioningType='SINGLE_PANEL')
    page.goto(url);page.locator('#file-input').set_input_files({'name':'native.ifc','mimeType':'application/x-step','buffer':encode(model)})
    page.wait_for_function('window.blueprintViewer?.data.source_kind==="ifc"',timeout=30000)
    scene=page.evaluate('window.blueprintViewer.data')
    assert template.GlobalId not in [e['id']for e in scene['elements']]
    entry=next(e for e in scene['elements']if e['id']==window.GlobalId)
    assert not entry['geometry']
    ask(page,'Inspect the source window Many.P59 property')
    expect(page.locator('.chat-answer').last.locator('.chat-citation')).to_be_enabled(timeout=10000)
    answered_revision=page.evaluate('state.result.answered_revision_id')
    doc=app.state.documents.get(scene['document_id']);candidate=app.state.documents.prepare(doc)
    app.state.documents.commit(candidate,doc.revision_id,status='available',config={'operation':'fixture source revision'})
    page.evaluate('refreshBuilding()')
    assert page.evaluate('state.document.revision_id')!=answered_revision
    requests=[];page.on('request',lambda request:requests.append(request.url)if '/evidence/'in request.url else None)
    page.locator('.chat-answer').last.locator('.chat-citation').click()
    expect(page.locator('#native-record-values')).to_contain_text('Many.P59: 59')
    expect(page.locator('#native-record-note')).to_contain_text('no viewer geometry')
    expect(page.locator('#native-record-identity')).to_contain_text(answered_revision)
    expect(page.locator('#native-record-values')).to_contain_text('Provenance: supplied')
    expect(page.locator('#native-record-coverage')).to_contain_text('catalog_complete')
    assert f'/revisions/{answered_revision}/evidence/' in requests[-1]
    ask(page,'Inspect the source template')
    expect(page.locator('.chat-answer').last.locator('.chat-citation')).to_contain_text('Source template',timeout=10000)
    expect(page.locator('.chat-answer').last.locator('.chat-citation')).to_be_enabled()
    page.locator('.chat-answer').last.locator('.chat-citation').click()
    expect(page.locator('#native-record-name')).to_have_text('Source template')
    expect(page.locator('#native-record-values')).to_contain_text('PredefinedType: WINDOW')
    expect(page.locator('#native-record-identity')).to_contain_text(template.GlobalId)
    assert provider.reconstruction_calls==0
    page.screenshot(path='/tmp/product-native-evidence.png',full_page=True)
