"""Deterministic race/navigation regressions; fixtures are not live inference."""
import copy
import json
import os

import pytest
from playwright.sync_api import expect

from test_chat_ui_browser import chat_fixture, response, say
from test_browser_3d import scene_page
from test_sourcefirst_browser import static_server

pytestmark = pytest.mark.skipif(os.getenv('RUN_BROWSER_TESTS') != '1', reason='opt-in browser checks')


def delayed_actions(page):
    pending = []
    page.route('**/api/chat/actions', lambda route: pending.append((route, json.loads(route.request.post_data))))
    return pending


def finish(pending, actions, index=0):
    route, body = pending.pop(index)
    route.fulfill(json=response(body, actions))
    return body


def qa_posts(calls):
    return [json.loads(body) for method, path, body in calls if method == 'POST' and path == 'questions']


def physical_orbit(page):
    canvas = page.locator('#model-canvas-container canvas')
    box = canvas.bounding_box()
    x, y = box['x'] + box['width'] * .6, box['y'] + box['height'] * .6
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 75, y + 25, steps=6)
    page.mouse.up()
    page.mouse.wheel(0, 90)
    page.wait_for_timeout(200)


def test_question_survives_orbit_view_switch_and_stale_mixed_navigation(static_server, scene_page):
    page = scene_page
    doc, _, calls, _ = chat_fixture(page, static_server)
    page.evaluate("chatUI.execute({type:'switch_model'})")
    pending = delayed_actions(page)
    message = 'How many windows does this building have?'
    say(page, message)
    page.wait_for_timeout(50)
    assert len(pending) == 1
    physical_orbit(page)
    page.evaluate("chatUI.execute({type:'browse_source'})")
    page.evaluate("chatUI.execute({type:'switch_model'})")
    camera = page.evaluate('chatUI.snapshot().camera')
    finish(pending, [{'type': 'set_camera', 'preset': 'top'}, {'type': 'question', 'question': message, 'revision_id': doc['revision_id']}])
    page.wait_for_function('state.jobs.some(j=>j.kind==="question")')
    assert len(qa_posts(calls)) == 1
    assert qa_posts(calls)[0]['question'] == message
    assert qa_posts(calls)[0]['revision_id'] == doc['revision_id']
    assert page.evaluate('chatUI.snapshot().view_mode') == 'model'
    after = page.evaluate('chatUI.snapshot().camera')
    assert max(abs(a - b) for key in ['position', 'target'] for a, b in zip(camera[key], after[key])) < .001
    expect(page.locator('#chat-log')).not_to_contain_text('superseded')
    assert not any('reconstruction' in path for _, path, _ in calls)


def test_captured_focus_reply_and_concurrent_questions_survive_later_selection(static_server, scene_page):
    page = scene_page
    doc, scene, calls, _ = chat_fixture(page, static_server)
    page.evaluate("chatUI.execute({type:'switch_model'});blueprintViewer.select('window-1');state.clarificationReply='reply-one'")
    pending = delayed_actions(page)
    say(page, 'What is this window made of?')
    page.wait_for_timeout(50)
    first = pending[0][1]
    assert first['workspace']['focused_id'] == 'window-1'
    page.evaluate("blueprintViewer.select('window-2');state.clarificationReply='reply-two'")
    say(page, 'What does this window show?')
    page.wait_for_timeout(50)
    second = pending[1][1]
    assert second['workspace']['focused_id'] == 'window-2'
    page.evaluate("state.clarificationReply='newer-reply';chatUI.execute({type:'browse_source'})")
    for index, body, ident in [(1, second, 'window-2'), (0, first, 'window-1')]:
        source = next(e['source'] for e in scene['elements'] if e['id'] == ident)
        action = {'type': 'question', 'question': body['message'], 'revision_id': doc['revision_id'],
                  'navigation_reference': {'object_id': ident, 'source': source, 'source_revision_id': doc['revision_id']}}
        finish(pending, [action, action], index=index)
        page.wait_for_timeout(100)
    page.wait_for_function('state.jobs.filter(j=>j.kind==="question").length===2')
    posts = qa_posts(calls)
    assert len(posts) == 2
    assert [post['reply_to'] for post in posts] == ['reply-two', 'reply-one']
    assert 'window-2' in posts[0]['question'] and 'window-1' in posts[1]['question']
    assert page.evaluate('state.clarificationReply') == 'newer-reply'
    assert page.evaluate('state.questionRequest.id') == second['request_id']
    page.evaluate('requestId=>{const job=state.jobs.find(j=>j.request_id===requestId);chatUI.mergeConversation([{id:"older-qa-clarification",role:"assistant",job_id:job.id,answer:{status:"clarification",answer:"Fixture older question needs clarification",evidence:[],clarification:{suggestions:[]}}}])}', first['request_id'])
    assert page.evaluate('state.clarificationReply') == 'newer-reply'
    assert page.evaluate('chatUI.snapshot().focused_id') == 'window-2'
    assert page.evaluate('chatUI.snapshot().view_mode') == 'source'


def test_cross_document_roundtrip_and_stale_mutation_remain_guarded(static_server, scene_page):
    page = scene_page
    doc, _, calls, _ = chat_fixture(page, static_server)
    pending = delayed_actions(page)
    say(page, 'What is depicted?')
    page.wait_for_timeout(50)
    other = copy.deepcopy(doc)
    other.update(document_id='e'*64, building_id='e'*64, has_scene=False, scene_url=None, geometry_revision_id=None)
    page.route('**/api/buildings/'+'e'*64, lambda route: route.fulfill(json={**other, 'jobs': []}))
    page.evaluate('(id)=>chatUI.execute({type:"open_saved",building_id:id})', other['building_id'])
    page.evaluate('(id)=>chatUI.execute({type:"open_saved",building_id:id})', doc['building_id'])
    finish(pending, [{'type': 'question', 'question': 'What is depicted?', 'revision_id': doc['revision_id']}])
    page.wait_for_timeout(150)
    assert not qa_posts(calls)
    say(page, 'Set height to 3 metres.')
    page.wait_for_timeout(50)
    page.evaluate("state.document.revision_id='d'.repeat(32)")
    finish(pending, [{'type': 'refine', 'edits': [], 'supporting_source_ids': []}])
    expect(page.locator('#chat-log')).to_contain_text('building revision changed')
    assert not any(path.endswith('/refinements') for _, path, _ in calls)


def test_pinned_pages_preload_failure_and_provider_free_view_state(static_server, scene_page):
    page = scene_page
    doc, scene, calls, _ = chat_fixture(page, static_server)
    page.evaluate("chatUI.execute({type:'select',ids:['window-1','window-2'],unresolved_ids:[]});chatUI.execute({type:'tour',command:'start'});chatUI.execute({type:'tour',command:'pause'})")
    captured = page.evaluate('chatUI.snapshot()')
    old = 'f'*32
    # No cached catalog for this old revision: only the exact cited page is shown.
    page.evaluate('(action)=>chatUI.execute(action)', {'type': 'show_source', 'source_revision_id': old,
                  'source': {'kind': 'image', 'page': 7, 'bbox': [.1, .2, .3, .4]}})
    view = page.evaluate('chatUI.sourceView()')
    assert view['revision_id'] == old and [p['page'] for p in view['pages']] == [7]
    expect(page.locator('#page-image')).to_have_attribute('src', f'{static_server}/api/buildings/{doc["building_id"]}/revisions/{old}/pages/7')
    assert page.evaluate('state.sourceSelection.bbox') == [.1, .2, .3, .4]
    page.evaluate("chatUI.execute({type:'browse_source'})")
    assert page.evaluate('chatUI.sourceView().revision_id') == doc['revision_id']
    assert page.evaluate('state.sourceSelection.bbox') is None
    page.evaluate("chatUI.execute({type:'switch_model'})")
    now = page.evaluate('chatUI.snapshot()')
    assert now['selected_ids'] == captured['selected_ids'] and now['tour'] == captured['tour']
    assert now['focused_id'] == captured['focused_id']
    assert max(abs(a-b) for key in ['position','target'] for a,b in zip(now['camera'][key],captured['camera'][key])) < .001
    page.route('**/revisions/'+'9'*32+'/pages/1', lambda route: route.fulfill(status=503, body='fixture page failure'))
    error = page.evaluate("async()=>{try{await chatUI.execute({type:'show_source',source_revision_id:'9'.repeat(32),source:{page:1,bbox:null}});return null}catch(e){return e.message}}")
    assert 'previous view is retained' in error
    assert page.evaluate('chatUI.snapshot().view_mode') == 'model'
    assert not any(path in ['chat/actions','questions'] or 'reconstruction' in path for _, path, _ in calls)


def test_visibility_controls_do_not_pause_tour_and_missing_model_tab_does_not_build(static_server, scene_page):
    page = scene_page
    _, _, calls, _ = chat_fixture(page, static_server)
    page.evaluate("chatUI.execute({type:'select',ids:['window-1','window-2'],unresolved_ids:[]});chatUI.execute({type:'tour',command:'start'})")
    before = page.evaluate('chatUI.snapshot()')
    page.evaluate("chatUI.execute({type:'set_visibility',target:'assumptions',enabled:true});chatUI.execute({type:'set_theme',theme:'dark'})")
    after = page.evaluate('chatUI.snapshot()')
    assert after['tour'] == before['tour'] and after['navigation_epoch'] == before['navigation_epoch']
    assert page.evaluate('chatUI.inspection().record.id') == 'window-1'
    page.evaluate("chatUI.execute({type:'tour',command:'pause'});clearScene();chatUI.execute({type:'switch_model'})")
    expect(page.locator('#no-model-geometry')).to_be_visible()
    expect(page.locator('#chat-log')).to_contain_text('No saved 3D model is available')
    assert not any('reconstruction' in path for _, path, _ in calls)


def test_question_http_completion_keeps_user_view_and_response_identity_is_checked(static_server, scene_page):
    page = scene_page
    doc, _, calls, _ = chat_fixture(page, static_server)
    pending = delayed_actions(page)
    qa_pending = []
    page.route('**/api/questions', lambda route: qa_pending.append((route, json.loads(route.request.post_data))))
    say(page, 'What spaces are depicted?')
    page.wait_for_timeout(50)
    finish(pending, [{'type': 'question', 'question': 'What spaces are depicted?', 'revision_id': doc['revision_id']}])
    page.wait_for_timeout(50)
    assert len(qa_pending) == 1
    page.evaluate("chatUI.execute({type:'switch_model'})")
    physical_orbit(page)
    page.evaluate("chatUI.execute({type:'browse_source'})")
    page.locator('#question').fill('Keep this unsent draft')
    route, body = qa_pending.pop()
    route.fulfill(json={'id': 'delayed-question', 'building_id': doc['building_id'], 'kind': 'question',
                        'status': 'complete', 'request_id': body['request_id'], 'phase': 'complete',
                        'answer': {'status': 'insufficient', 'answer': 'Fixture refusal, not live inference.',
                                   'evidence': [], 'highlight_ids': [], 'gate': {'decision': 'insufficient'},
                                   'answered_revision_id': doc['revision_id'], 'display_revision_id': doc['revision_id']}})
    expect(page.locator('#chat-log')).to_contain_text('Fixture refusal')
    assert page.evaluate('chatUI.snapshot().view_mode') == 'source'
    expect(page.locator('#question')).to_have_value('Keep this unsent draft')
    say(page, 'What is this?')
    page.wait_for_timeout(50)
    page.evaluate("chatUI.execute({type:'switch_model'})")
    route, body = pending.pop()
    bad = response(body, [{'type': 'question', 'question': 'What is this?', 'revision_id': doc['revision_id']}])
    bad['request_id'] = 'mismatched-response'
    route.fulfill(json=bad)
    expect(page.locator('#chat-log')).to_contain_text('did not match the captured workspace')
    assert not qa_pending


def test_provider_unavailable_keeps_saved_buildings_discoverable(static_server, scene_page):
    page = scene_page
    doc, _, calls, _ = chat_fixture(page, static_server)
    page.route('**/api/health', lambda route: route.fulfill(json={
        'provider_ready': False, 'provider_label': 'Gemini', 'provider': 'gemini',
        'credential_env': 'GEMINI_API_KEY',
        'limits': {'max_upload_mb': 10, 'max_ifc_mb': 25, 'max_pages': 5}}))
    # Reload represents starting the app with an existing cached building and
    # unavailable inference. The preceding upload only establishes fixture data.
    page.goto(static_server)
    page.wait_for_function('window.chatUI && state.health && !state.providerReady')
    expect(page.locator('[data-entry="provider-setup"]')).to_be_visible()
    expect(page.locator('#welcome-saved')).to_be_visible()
    expect(page.locator('#welcome-saved')).to_be_in_viewport()
    page.locator('#welcome-saved').click()
    page.get_by_role('button', name=doc['filename'], exact=True).click()
    page.wait_for_function('state.document && state.viewer?.meshes.size===3')
    page.evaluate("chatUI.execute({type:'switch_model'})")
    expect(page.locator('#visual-workspace')).to_be_visible()
    assert page.evaluate('state.document.document_id') == doc['document_id']
    assert not any(path == 'chat/actions' or 'reconstruction' in path for _, path, _ in calls)


def test_late_clarification_does_not_claim_new_question_and_choice_keeps_its_request(static_server, scene_page):
    page = scene_page
    doc, _, calls, _ = chat_fixture(page, static_server)
    pending = delayed_actions(page)
    say(page, 'Show the ambiguous item')
    page.wait_for_timeout(30)
    older = pending[0][1]
    say(page, 'What spaces are depicted?')
    page.wait_for_timeout(30)
    newer = finish(pending, [{'type': 'question', 'question': 'What spaces are depicted?', 'revision_id': doc['revision_id']}], index=1)
    page.wait_for_function('state.jobs.some(j=>j.kind==="question")')
    route, body = pending.pop()
    clarification = response(body, [])
    clarification.update(status='clarification', clarification={'message': 'Which item?', 'suggestions': ['Fixture window-1']})
    route.fulfill(json=clarification)
    expect(page.locator('#chat-log')).to_contain_text('Which item?')
    say(page, 'Show the original blueprint')
    page.wait_for_timeout(30)
    assert pending[-1][1]['message'] == 'Show the original blueprint'
    finish(pending, [{'type': 'show_source', 'page': 1}])
    page.wait_for_function('chatUI.snapshot().view_mode==="source"')
    page.get_by_role('button', name='Fixture window-1', exact=True).click()
    page.wait_for_timeout(30)
    assert pending[-1][1]['message'] == 'Original request: Show the ambiguous item\nUser clarification: Fixture window-1'
    finish(pending, [{'type': 'show_source', 'page': 1}])
    assert len(qa_posts(calls)) == 1


def test_reopened_answer_uses_persisted_job_identity_on_poll(static_server, scene_page):
    page = scene_page
    doc, _, calls, _ = chat_fixture(page, static_server)
    answer = {'status': 'answered', 'answer': 'Persisted fixture answer, not live inference.',
              'answered_revision_id': doc['revision_id'], 'display_revision_id': doc['revision_id'],
              'evidence': [], 'highlight_ids': [], 'gate': None}
    message = {'id': 'saved-assistant', 'role': 'assistant', 'job_id': 'saved-question', 'answer': answer}
    jobs = []
    page.route('**/api/buildings/'+doc['building_id']+'/conversation', lambda route: route.fulfill(json={'messages': [message]}))
    page.route('**/api/buildings/'+doc['building_id'], lambda route: route.fulfill(json={**doc, 'jobs': jobs}))
    page.goto(static_server)
    page.locator('#welcome-saved').click()
    page.get_by_role('button', name=doc['filename'], exact=True).click()
    expect(page.locator('.chat-answer')).to_have_count(1)
    jobs.append({'id': 'saved-question', 'request_id': 'saved-request', 'building_id': doc['building_id'],
                 'kind': 'question', 'status': 'complete', 'phase': 'complete', 'answer': answer})
    page.evaluate('refreshBuilding()')
    page.evaluate('refreshConversation()')
    expect(page.locator('.chat-answer')).to_have_count(1)
    expect(page.locator('.chat-answer')).to_have_attribute('data-job-id', 'saved-question')
    expect(page.locator('.chat-answer')).to_have_attribute('data-request-id', 'saved-request')
    assert not any(method == 'POST' and path != 'documents' for method, path, _ in calls)


@pytest.mark.parametrize('status', ['needs_attention', 'failed'])
def test_terminal_model_job_clears_progress_and_uses_retained_status(static_server, scene_page, status):
    page = scene_page
    doc, scene, calls, _ = chat_fixture(page, static_server, model=False)
    job = {'id': 'pending-model-job', 'building_id': doc['building_id'], 'kind': 'reconstruction',
           'status': 'running', 'phase': 'reviewing', 'message': 'Fixture review is processing.'}
    page.route('**/api/buildings/'+doc['building_id']+'/reconstruction', lambda route: route.fulfill(json=job))
    page.evaluate("()=>{window.modelResult=null;void chatUI.execute({type:'show_model'}).catch(error=>window.modelResult=error.message)}")
    expect(page.locator('[data-entry="pending-model"]')).to_be_visible()
    page.evaluate('(scene)=>loadScene(scene)', scene)
    terminal = {**job, 'status': status, 'phase': 'complete', 'message': 'Fixture rejected candidate; model retained.'}
    page.route('**/api/buildings/'+doc['building_id'], lambda route: route.fulfill(json={**doc, 'has_scene': True, 'review_status': 'preview_reviewing', 'jobs': [terminal]}))
    page.evaluate('job=>{state.document.has_scene=true;state.document.review_status="preview_reviewing";state.jobs=[job];renderBuildingStatus();renderJobs();chatUI.onDocument(state.document)}', terminal)
    page.wait_for_function('window.modelResult!==null')
    expect(page.locator('[data-entry="pending-model"]')).to_have_count(0)
    expect(page.locator('[data-entry="job:pending-model-job"]')).to_contain_text('model retained')
    expect(page.locator('#workspace-status')).to_contain_text('Model retained')
    expect(page.locator('#workspace-status')).to_contain_text('needs attention' if status == 'needs_attention' else 'processing failed')
    expect(page.locator('#workspace-status')).not_to_contain_text('preview reviewing')


def test_comparison_opens_model_pinned_original_and_old_evidence_stays_unoverlaid(static_server, scene_page):
    page = scene_page
    doc, scene, calls, _ = chat_fixture(page, static_server)
    page.evaluate("chatUI.execute({type:'browse_source'})")
    old_url = page.locator('#page-image').get_attribute('src')
    updated = copy.deepcopy(scene)
    updated.update(revision_id='d'*32, revision_number=2)
    updated['comparison'] = [{'element_id': 'window-1', 'floor_id': 'f1', 'page': 1,
                              'layer': 'openings', 'polygons': [[[.1, .2], [.3, .2], [.3, .5], [.1, .5]]],
                              'lines': [], 'method': 'Explicit deterministic comparison fixture'}]
    page.evaluate('scene=>loadScene(scene)', updated)
    page.evaluate("document.getElementById('show-comparison').checked=true;renderComparison()")
    expect(page.locator('#comparison-overlay')).to_be_hidden()
    assert page.locator('#page-image').get_attribute('src') == old_url
    before = page.evaluate('chatUI.snapshot()')
    failed_page = '**/revisions/'+updated['revision_id']+'/pages/1'
    def unavailable(route): route.fulfill(status=503, body='Fixture original unavailable')
    page.route(failed_page, unavailable)
    failure = page.evaluate("async()=>{try{await chatUI.execute({type:'set_comparison',enabled:true});return null}catch(error){return error.message}}")
    assert 'previous view is retained' in failure
    assert page.locator('#page-image').get_attribute('src') == old_url
    assert page.evaluate('chatUI.sourceView().revision_id') == doc['revision_id']
    expect(page.locator('#comparison-overlay')).to_be_hidden()
    page.unroute(failed_page, unavailable)
    page.evaluate("chatUI.execute({type:'set_comparison',enabled:true})")
    expect(page.locator('#comparison-overlay')).to_be_visible()
    expect(page.locator('#page-image')).to_have_attribute('src', f'{static_server}/api/buildings/{doc["building_id"]}/revisions/{updated["revision_id"]}/pages/1')
    assert page.evaluate('chatUI.sourceView().revision_id') == updated['revision_id']
    assert page.evaluate('chatUI.snapshot().selected_ids') == before['selected_ids']
    page.evaluate("chatUI.execute({type:'set_comparison',layer:'openings',enabled:false})")
    expect(page.locator('#comparison-overlay')).to_be_visible()
    expect(page.locator('#comparison-overlay [data-layer="openings"]')).to_have_count(0)
    page.evaluate('(revision)=>chatUI.execute({type:"show_source",source_revision_id:revision,source:{page:1,bbox:[.1,.2,.3,.5]}})', doc['revision_id'])
    expect(page.locator('#page-image')).to_have_attribute('src', old_url)
    expect(page.locator('#comparison-overlay')).to_be_hidden()
    assert page.evaluate('state.sourceSelection.bbox') == [.1, .2, .3, .5]
    assert not any(method == 'POST' and path != 'documents' for method, path, _ in calls)
