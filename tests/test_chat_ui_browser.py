"""Deterministic chat interaction fixtures, not live model inference."""
import json
import os

import pytest

from test_browser import source_bytes
from test_browser_3d import scene_page
from test_sourcefirst_browser import static_server, setup_routes

pytestmark = pytest.mark.skipif(os.getenv('RUN_BROWSER_TESTS') != '1', reason='opt-in browser checks')


def chat_fixture(page, url, *, model=True):
    doc, messages, calls = setup_routes(page)
    scene = {
        'document_id': doc['document_id'], 'building_id': doc['building_id'],
        'revision_id': doc['revision_id'], 'revision_number': 1,
        'derived': True, 'units': 'relative', 'layout': 'aligned', 'warnings': [],
        'floors': [{'id': 'f1', 'label': 'Fixture assembly floor', 'order': 0,
                    'source': {'kind': 'image', 'page': 1, 'bbox': [0, 0, 1, 1]},
                    'scale_status': 'unknown', 'alignment_status': 'supported', 'rotation_degrees': 0,
                    'base_elevation': 0, 'reference_height': 3, 'assumptions': []}],
        'elements': [],
    }
    for ident, kind, x, y in [('window-1', 'window', -2, 0), ('window-2', 'window', 2, 0), ('wall-1', 'wall', 0, 1)]:
        scene['elements'].append({'id': ident, 'name': f'Fixture {ident}', 'kind': kind,
            'storey_id': 'f1', 'ifc_type': 'IfcWindow' if kind == 'window' else 'IfcWall',
            'geometry_origin': 'inferred', 'representation': 'reconstructed', 'evidence_basis': 'observed',
            'source': {'kind': 'image', 'page': 1, 'bbox': [.1 if x < 0 else .5, .2, .3 if x < 0 else .8, .5]},
            'assumptions': [{'property': 'height', 'value': 1, 'reason': 'Fixture display height'}],
            'properties': [], 'geometry': {'type': 'box', 'size': [1.2, .15, 1] if kind == 'window' else [5, .2, 3], 'center': [x, y, 1.5]}})
    scene['elements'].append({'id': 'unresolved-window', 'name': 'Fixture unresolved window', 'kind': 'window',
        'representation': 'unresolved', 'storey_id': 'f1', 'geometry_origin': 'inferred', 'geometry': None,
        'source': {'kind': 'image', 'page': 1, 'bbox': [.2, .6, .4, .8]}, 'note': 'Uncertain host', 'properties': [], 'assumptions': []})
    if model:
        doc.update(has_scene=True, scene_url=f'/api/documents/{doc["document_id"]}/scene', geometry_revision_id=doc['revision_id'])
        page.route('**/api/documents/*/scene', lambda route: route.fulfill(json=scene))
    pending = []
    def action_route(route):
        body = json.loads(route.request.post_data)
        calls.append(('POST', 'chat/actions', route.request.post_data))
        message = body['message']
        actions = {
            'Show me all windows in the 3D model.': [{'type': 'show_model'}, {'type': 'select', 'ids': ['window-1', 'window-2'], 'unresolved_ids': ['unresolved-window'], 'deferred': False}],
            'Show this from above.': [{'type': 'set_camera', 'preset': 'top'}],
            'Show the windows individually.': [{'type': 'tour', 'command': 'start'}],
            'Back to the model; next window.': [{'type': 'show_model'}, {'type': 'tour', 'command': 'next'}],
            'Use dark theme.': [{'type': 'set_theme', 'theme': 'dark'}],
            'Use light theme.': [{'type': 'set_theme', 'theme': 'light'}],
            'Show assumptions.': [{'type': 'set_visibility', 'target': 'assumptions', 'enabled': True}],
            'Hide answer highlights.': [{'type': 'set_visibility', 'target': 'answer_highlights', 'enabled': False}],
            'What spaces are depicted?': [{'type': 'question', 'question': message, 'revision_id': doc['revision_id']}],
        }.get(message)
        if message == 'Show this window in the original blueprint.':
            focused = body['workspace']['focused_id']
            element = next(e for e in scene['elements'] if e['id'] == focused)
            actions = [{'type': 'show_source', 'object_id': focused, 'source': element['source'], 'source_revision_id': scene['revision_id']}]
            pending.append((route, body, actions))
            return
        if message == 'Recoverable failure':
            return route.fulfill(status=503, json={'detail': 'Fixture operational failure; previous model retained.'})
        if actions is None:
            return route.fulfill(status=422, json={'detail': 'Unmapped deterministic test command'})
        route.fulfill(json=response(body, actions))
    page.route('**/api/chat/actions', action_route)
    page.goto(url)
    page.locator('#file-input').set_input_files({'name': 'fixture.png', 'mimeType': 'image/png', 'buffer': source_bytes()})
    page.wait_for_function('state.document !== null')
    if model:
        page.wait_for_function('window.blueprintViewer?.meshes.size === 3')
    return doc, scene, calls, pending


def response(body, actions):
    return {'request_id': body['request_id'], 'document_id': body.get('document_id'),
            'revision_id': body.get('revision_id'), 'geometry_revision_id': body['workspace'].get('geometry_revision_id'),
            'navigation_epoch': body['workspace']['navigation_epoch'], 'status': 'ready', 'actions': actions,
            'message': 'Deterministic interaction fixture; no live inference.', 'clarification': None, 'usage': {}}


def say(page, message):
    page.locator('#question').fill(message)
    page.locator('#ask-button').click()


def test_chat_layout_themes_selection_tour_and_captured_source(static_server, scene_page):
    from playwright.sync_api import expect
    page = scene_page
    doc, scene, calls, pending = chat_fixture(page, static_server)
    expect(page.locator('#visual-workspace')).to_be_hidden()
    say(page, 'Use dark theme.')
    expect(page.locator('html')).to_have_attribute('data-theme', 'dark')
    assert page.evaluate('getComputedStyle(document.documentElement).getPropertyValue("--background").trim()') == '#121110'
    say(page, 'Show me all windows in the 3D model.')
    expect(page.locator('#visual-workspace')).to_be_visible()
    page.wait_for_function('chatUI.snapshot().selected_ids.length === 2')
    assert page.evaluate('chatUI.snapshot().selected_ids') == ['window-1', 'window-2']
    assert not any('reconstruction' in path for _, path, _ in calls)
    say(page, 'Show this from above.')
    page.wait_for_function('Math.abs(blueprintViewer.camera.position.z-blueprintViewer.controls.target.z)>3')
    assert page.evaluate('chatUI.snapshot().selected_ids') == ['window-1', 'window-2']
    say(page, 'Show the windows individually.')
    page.wait_for_function('chatUI.snapshot().tour.running')
    assert page.evaluate('chatUI.snapshot().focused_id') == 'window-1'
    say(page, 'Show this window in the original blueprint.')
    page.wait_for_function('!chatUI.snapshot().tour.running')
    assert pending and pending[0][1]['workspace']['focused_id'] == 'window-1'
    page.wait_for_timeout(250)
    assert page.evaluate('chatUI.snapshot().focused_id') == 'window-1'
    route, body, actions = pending.pop()
    route.fulfill(json=response(body, actions))
    expect(page.locator('#evidence-overlay')).to_be_visible()
    expect(page.locator('#page-image')).to_have_attribute('src', f'{static_server}/api/buildings/{doc["building_id"]}/revisions/{scene["revision_id"]}/pages/1')
    say(page, 'Back to the model; next window.')
    page.wait_for_function('chatUI.snapshot().focused_id === "window-2"')
    assert page.evaluate('chatUI.snapshot().tour.index') == 1
    say(page, 'Show assumptions.')
    say(page, 'Hide answer highlights.')
    page.wait_for_function('chatUI.snapshot().show_assumptions && !chatUI.snapshot().answer_highlighting')
    assert page.evaluate('chatUI.snapshot().selected_ids') == ['window-1', 'window-2']
    say(page, 'Use light theme.')
    expect(page.locator('html')).to_have_attribute('data-theme', 'light')
    assert page.evaluate('getComputedStyle(document.documentElement).getPropertyValue("--background").trim()') == '#fbfaf8'


def test_source_only_qa_single_answer_and_recoverable_failure(static_server, scene_page):
    from playwright.sync_api import expect
    page = scene_page
    _, _, calls, _ = chat_fixture(page, static_server, model=False)
    say(page, 'What spaces are depicted?')
    expect(page.locator('#chat-log .chat-answer')).to_have_count(1)
    expect(page.locator('#chat-log .chat-answer')).to_contain_text('Fixture: an assembly hall is depicted.')
    page.locator('#chat-log .chat-citation').first.click()
    expect(page.locator('#evidence-overlay')).to_be_visible()
    assert not any('reconstruction' in path or path.endswith('/scene') for _, path, _ in calls)
    before = page.locator('#chat-log .chat-turn').count()
    say(page, 'Recoverable failure')
    expect(page.locator('#chat-log')).to_contain_text('Fixture operational failure')
    page.evaluate('refreshConversation()')
    expect(page.locator('#chat-log .chat-answer')).to_have_count(1)
    assert page.locator('#chat-log .chat-turn').count() >= before


def test_recovery_event_sources_and_atomic_revision_state(static_server, scene_page):
    """Actual reliability DTO shapes; revision changes are fixture publications."""
    from playwright.sync_api import expect
    import copy
    page=scene_page
    doc,scene,_,_=chat_fixture(page,static_server)
    page.evaluate("chatUI.execute({type:'select',ids:['window-1','window-2'],unresolved_ids:[]})")
    page.evaluate("chatUI.execute({type:'tour',command:'start'})")
    page.evaluate("chatUI.execute({type:'tour',command:'pause'})")
    before=page.evaluate('chatUI.snapshot()')
    updated=copy.deepcopy(scene);updated['revision_id']='d'*32;updated['revision_number']=2
    page.evaluate('scene=>loadScene(scene)',updated)
    assert page.evaluate('chatUI.snapshot().navigation_epoch')==before['navigation_epoch']
    assert page.evaluate('chatUI.snapshot().selected_ids')==before['selected_ids']
    assert page.evaluate('chatUI.snapshot().focused_id')=='window-1'
    after=page.evaluate('chatUI.snapshot().camera')
    assert after['position']==pytest.approx(before['camera']['position'],abs=1e-8)
    removed=copy.deepcopy(updated);removed['revision_id']='e'*32;removed['revision_number']=3
    removed['elements']=[e for e in removed['elements'] if e['id']!='window-1']
    page.evaluate('scene=>loadScene(scene)',removed)
    assert page.evaluate('chatUI.snapshot().focused_id') is None
    page.locator('[data-entry="focused-object"] button',has_text='Original source').click()
    expect(page.locator('#page-image')).to_have_attribute('src',f'{static_server}/api/buildings/{doc["building_id"]}/revisions/{updated["revision_id"]}/pages/1')
    job={'id':'recovery-fixture','building_id':doc['building_id'],'kind':'refinement','status':'needs_attention','phase':'review','message':'Fixture candidate rejected; prior model retained.',
         'base_revision_id':'a'*32,'submitted_values':[{'property':'display_height','value':3,'unit':'relative','scope':{'floor_id':'f1'}}],
         'recovery_events':[{'kind':'rejection','feedback':{'code':'scope_rejected','target_id':'window-1','explanation':'Fixture unauthorized target','expected_contract':'Keep authorized targets'}},
          {'kind':'authorization','base_revision_id':'d'*32,'decisions':[{'decision':'denied','target_id':'window-1','reason':'Fixture no supporting evidence','evidence':{'page':1,'bbox':[.1,.2,.3,.5]}}]}]}
    page.evaluate('job=>chatUI.onJobs([job])',job)
    card=page.locator('[data-entry="job:recovery-fixture"]')
    expect(card).to_contain_text('scope_rejected');expect(card).to_contain_text('Denied');expect(card).to_contain_text('submitted; see outcome')
    card.locator('details').last.evaluate('(e)=>e.open=true')
    card.get_by_text('Inspect reviewed target in original source',exact=True).click()
    expect(page.locator('#page-image')).to_have_attribute('src',f'{static_server}/api/buildings/{doc["building_id"]}/revisions/{"d"*32}/pages/1')
    assert page.evaluate('state.scene.revision_id')=='e'*32


def test_repeated_qa_and_mismatched_action_response(static_server,scene_page):
    from playwright.sync_api import expect
    page=scene_page;doc,_,calls,_=chat_fixture(page,static_server,model=False)
    say(page,'What spaces are depicted?')
    expect(page.locator('#chat-log .chat-answer')).to_have_count(1)
    say(page,'What spaces are depicted?')
    expect(page.locator('#chat-log .chat-answer')).to_have_count(2)
    assert page.locator('#chat-log .chat-user',has_text='What spaces are depicted?').count()==2
    page.evaluate('refreshConversation()')
    expect(page.locator('#chat-log .chat-answer')).to_have_count(2)
    def wrong(route):
        body=json.loads(route.request.post_data);result=response(body,[{'type':'set_theme','theme':'dark'}]);result['request_id']='foreign';route.fulfill(json=result)
    page.route('**/api/chat/actions',wrong)
    page.evaluate("chatUI.execute({type:'set_theme',theme:'light'})")
    say(page,'Use dark theme.')
    expect(page.locator('#chat-log')).to_contain_text('did not match the captured workspace')
    expect(page.locator('html')).to_have_attribute('data-theme','light')


def test_missing_model_and_refinement_outcomes_reuse_existing_endpoints(static_server,scene_page):
    from playwright.sync_api import expect
    import copy
    page=scene_page;doc,scene,calls,_=chat_fixture(page,static_server,model=False)
    geometry_requested=[]
    def reconstruction(route):
        geometry_requested.append(json.loads(route.request.post_data))
        doc.update(has_scene=True,geometry_revision_id=doc['revision_id'],scene_url=f'/api/documents/{doc["document_id"]}/scene')
        route.fulfill(json={'id':'model-fixture','building_id':doc['building_id'],'kind':'reconstruction','status':'complete','phase':'complete','message':'Fixture model generated'})
    page.route('**/api/buildings/*/reconstruction',reconstruction)
    page.route('**/api/documents/*/scene',lambda route:route.fulfill(json=scene))
    def intent(route):
        body=json.loads(route.request.post_data)
        if body['message']=='Build windows':actions=[{'type':'show_model'},{'type':'select','selector':{'target':'all','kind':'window'},'ids':[],'unresolved_ids':[],'deferred':True}]
        else:actions=[{'type':'refine','edits':[{'property':'display_height','scope':{'floor_id':'f1'},'value':3,'unit':'relative','reason':'Fixture supplied input'}],'supporting_source_ids':[]}]
        route.fulfill(json=response(body,actions))
    page.route('**/api/chat/actions',intent)
    say(page,'Build windows')
    page.wait_for_function('chatUI.snapshot().selected_ids.length===2')
    assert len(geometry_requested)==1 and geometry_requested[0]['base_revision_id']=='a'*32
    before=page.evaluate('chatUI.snapshot()')
    submitted=[]
    def refine(route):
        submitted.append(json.loads(route.request.post_data));route.fulfill(json={'id':'refine-fixture','building_id':doc['building_id'],'kind':'refinement','status':'needs_attention','phase':'review','message':'Fixture rejected; previous model retained','submitted_values':[{'property':'display_height','value':3,'unit':'relative'}]})
    page.route('**/api/buildings/*/refinements',refine)
    say(page,'Set display height to 3 relative units')
    expect(page.locator('#chat-log')).to_contain_text('Fixture rejected; previous model retained')
    assert submitted[0]['base_revision_id']=='a'*32
    assert page.evaluate('state.scene.revision_id')=='a'*32
    assert page.evaluate('chatUI.snapshot().selected_ids')==before['selected_ids']
    # A later accepted backend publication is swapped atomically by the existing adapter.
    accepted=copy.deepcopy(scene);accepted['revision_id']='d'*32;accepted['revision_number']=2
    page.evaluate('scene=>loadScene(scene)',accepted)
    assert page.evaluate('chatUI.snapshot().geometry_revision_id')=='d'*32
    assert page.evaluate('chatUI.snapshot().selected_ids')==before['selected_ids']


def test_desktop_chat_stays_in_viewport_and_buttons_retheme(static_server,scene_page):
    page=scene_page
    chat_fixture(page,static_server)
    page.evaluate("chatUI.execute({type:'show_model'})")
    page.evaluate("async()=>{for(let i=0;i<30;i++)await chatUI.execute({type:'set_visibility',target:'assumptions',enabled:!!(i%2)});await chatUI.execute({type:'set_theme',theme:'dark'});}")
    bounds=page.evaluate("""()=>{const rect=id=>{const r=document.getElementById(id).getBoundingClientRect();return {top:r.top,bottom:r.bottom,height:r.height}};const old=document.querySelector('[data-entry="source-status"] button');const style=getComputedStyle(old);return {header:rect('chat-column'),composer:rect('chat-composer'),canvas:rect('model-canvas-container'),viewport:innerHeight,foreground:style.color,background:style.backgroundColor}}""")
    assert bounds['header']['top']>=0 and bounds['header']['bottom']<=bounds['viewport']+1
    assert bounds['composer']['top']>=0 and bounds['composer']['bottom']<=bounds['viewport']+1
    assert 100<bounds['canvas']['height']<bounds['viewport']
    assert bounds['foreground']=='rgb(238, 234, 228)'
    assert bounds['background']=='rgb(25, 24, 22)'


def test_visual_controls_reveal_model_and_reject_missing_model(static_server,scene_page):
    from playwright.sync_api import expect
    page=scene_page;chat_fixture(page,static_server)
    for action in [{'type':'set_floor','floor_id':'f1'},{'type':'set_separation','enabled':True},{'type':'set_cutaway','percent':60}]:
        page.evaluate("chatUI.execute({type:'close_workspace'})")
        expect(page.locator('#visual-workspace')).to_be_hidden()
        page.evaluate('action=>chatUI.execute(action)',action)
        expect(page.locator('#visual-workspace')).to_be_visible()
    page.evaluate("chatUI.execute({type:'set_view',mode:'concept'})")
    page.evaluate("chatUI.execute({type:'close_workspace'})")
    page.evaluate("chatUI.execute({type:'set_cutaway',percent:50})")
    assert page.evaluate('chatUI.snapshot().view_mode')=='concept'
    page.evaluate("state.document.kind='ifc';state.document.pages=[]")
    page.evaluate("chatUI.execute({type:'set_view',mode:'source'})")
    expect(page.locator('[data-entry="native-source-guidance"]')).to_contain_text('original records rather than blueprint pages')
    assert page.evaluate('chatUI.snapshot().view_mode')=='concept'
    page.evaluate('clearScene()')
    for action in [{'type':'set_floor','floor_id':None},{'type':'set_separation','enabled':True},{'type':'set_cutaway','percent':60}]:
        outcome=page.evaluate('async action=>{try{await chatUI.execute(action);return "unexpected success"}catch(error){return error.message}}',action)
        assert 'needs a saved model' in outcome


def test_concept_proposal_chat_attribution_and_host_source(static_server,scene_page):
    from playwright.sync_api import expect
    page=scene_page;doc,scene,_,_=chat_fixture(page,static_server)
    page.evaluate("chatUI.execute({type:'set_view',mode:'concept'})")
    count=page.evaluate('state.scene.elements.length')
    proposal={'id':'proposal:fixture-plant','kind':'proposal','host_id':'window-1','source_id':None,'label':'Fixture decorative planting','note':'Fixture proposal; not depicted source evidence or an IFC export object.'}
    page.evaluate('record=>{blueprintViewer.concept.records.set(record.id,record);inspectProposal(record)}',proposal)
    card=page.locator('[data-entry="selected-proposal"]')
    expect(card).to_contain_text('decorative proposal, not factual source evidence')
    expect(card).to_contain_text('Fixture decorative planting')
    assert page.evaluate('chatUI.snapshot().focused_id') is None
    card.get_by_text('Supporting source area · host object',exact=True).click()
    expect(page.locator('#page-image')).to_have_attribute('src',f'{static_server}/api/buildings/{doc["building_id"]}/revisions/{doc["revision_id"]}/pages/1')
    page.wait_for_function('bbox => JSON.stringify(state.sourceSelection?.bbox) === JSON.stringify(bbox)',
                           arg=scene['elements'][0]['source']['bbox'])
    page.evaluate("chatUI.execute({type:'inspect_inventory'})")
    expect(page.locator('.chat-proposals')).to_contain_text('separate from the source-object inventory')
    page.locator('.chat-proposals').get_by_role('button',name='Inspect proposal',exact=True).last.click()
    expect(card).to_contain_text('Fixture decorative planting')
    assert page.evaluate('state.scene.elements.length')==count
