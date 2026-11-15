"""Real local APIs; synthetic review/transcription providers and microphone audio."""
import os

import pytest

from test_agent_e2e_browser import agent_server
from test_browser import source_bytes
from test_browser_3d import scene_page
from test_voice_browser import voice_server,voice_page

pytestmark=pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS")!="1",reason="opt-in browser checks")


def test_tasks_group_by_project_jump_to_exact_message_and_dismiss_without_navigation(agent_server,scene_page):
    from playwright.sync_api import expect
    url,app,document,state=agent_server;page=scene_page
    a=app.state.projects.catalog([document.public()],writable=True)[0]
    a=app.state.projects.update(a["id"],name="Project A")
    other=app.state.documents.add(source_bytes()+b"task-other-project","other.png")
    b=next(p for p in app.state.projects.catalog([document.public(),other.public()],writable=True) if other.id in p["building_ids"])
    b=app.state.projects.update(b["id"],name="Project B")
    runner=app.state.jobs
    with runner.lock:
        pending=runner._new(other,"extraction");runner.set_origin(pending,{"project_id":b["id"]})
        complete=runner._new(other,"refinement");runner._update(complete,status="complete",phase="complete",message="Synthetic completed task")
        runner.set_origin(complete,{"project_id":b["id"]})
    state["pause"]=True
    try:
        page.goto(url);page.locator(f'tr[data-project-id="{a["id"]}:{document.id}"] .home-file').click();page.locator("#new-project-chat").click()
        page.locator("#question").fill("Render my plan for project A.");page.locator("#ask-button").click()
        assert state["entered"].wait(8)
        page.wait_for_function("state.jobs.some(job=>job.kind==='render'&&job.origin?.message_id)")
        job=page.evaluate("state.jobs.find(job=>job.kind==='render')")
        card=page.locator(f'[data-task-id="{job["id"]}"]')
        expect(page.locator("#active-task-list .task-project-group>h3")).to_have_text(["Project A","Project B"])
        card.locator(":scope>summary").click()
        expect(page.locator("#chat-log .task-origin-focus")).to_contain_text("Render my plan for project A.")
        assert page.evaluate("state.activeProjectId")==a["id"]
        assert page.evaluate("state.activeBuildingScopeId")==a["id"]+":"+document.id
        assert not runner.get(job["id"]).get("activity_dismissed")
        state["release"].set()
        page.wait_for_function("id=>state.jobs.some(job=>job.id===id&&job.status==='complete')",arg=job["id"])
        expect(page.locator(f'#task-history-list [data-task-id="{job["id"]}"]')).to_be_visible()
        card.locator(":scope>summary").click()
        expect(page.locator(f'[data-task-id="{job["id"]}"]')).to_have_count(0)
        expect(page.locator("#chat-log .task-origin-focus")).to_contain_text("Render my plan for project A.")
        assert runner.get(job["id"])["activity_dismissed"]
        current=page.evaluate("({project:state.activeProjectId,session:state.activeSessionId})")
        page.locator(f'[data-task-id="{complete}"] .task-dismiss').click()
        expect(page.locator(f'[data-task-id="{complete}"]')).to_have_count(0)
        assert page.evaluate("({project:state.activeProjectId,session:state.activeSessionId})")==current
        assert runner.get(complete)["activity_dismissed"] and runner.get(complete)["status"]=="complete"
        page.reload();page.wait_for_function("state.savedBuildingsLoaded")
        expect(page.locator(f'[data-task-id="{complete}"]')).to_have_count(0)
        expect(page.locator(f'[data-task-id="{job["id"]}"]')).to_have_count(0)
        assert state["messages"]==["Render my plan for project A."]
    finally:state["release"].set()


def test_tasks_collapse_to_right_edge_and_restore_with_arrow(agent_server,scene_page):
    from playwright.sync_api import expect
    url,app,document,_=agent_server;page=scene_page
    project=app.state.projects.catalog([document.public()],writable=True)[0]
    with app.state.jobs.lock:
        identity=app.state.jobs._new(document,"extraction")
        app.state.jobs._update(identity,status="complete",phase="complete")
        app.state.jobs.set_origin(identity,{"project_id":project["id"]})
    page.goto(url)
    toggle=page.locator("#active-task-toggle")
    expect(toggle).to_have_attribute("aria-expanded","true")
    toggle.click();expect(toggle).to_have_accessible_name("Expand active tasks")
    panel=page.locator("#active-tasks").bounding_box()
    assert panel["width"]==pytest.approx(36,abs=1)
    assert panel["x"]+panel["width"]==pytest.approx(page.viewport_size["width"],abs=1)
    page.reload();expect(toggle).to_have_attribute("aria-expanded","false")
    toggle.click();expect(toggle).to_have_accessible_name("Collapse active tasks")
    assert page.locator("#active-tasks").bounding_box()["width"]>200
    page.set_viewport_size({"width":390,"height":844})
    toggle.click();expect(toggle).to_have_attribute("aria-expanded","false")
    assert page.locator("#active-tasks").bounding_box()["width"]==pytest.approx(36,abs=1)
    toggle.click();expect(toggle).to_have_attribute("aria-expanded","true")
    panel=page.locator("#active-tasks").bounding_box();assert panel["x"]+panel["width"]==pytest.approx(390,abs=1)
    page.locator(f'[data-task-id="{identity}"]>summary').click()
    expect(toggle).to_have_attribute("aria-expanded","false")
    expect(page.locator("#home-project-name")).to_have_text(project["name"])
    assert app.state.jobs.get(identity)["activity_dismissed"]


def voice_ready(page,url):
    from playwright.sync_api import expect
    page.goto(url);page.locator("#home-new-project").click()
    page.locator("#project-create-name").fill("Voice Building")
    page.locator("#project-create-form button[type=submit]").click()
    expect(page.locator("#home-project-name")).to_have_text("Voice Building")
    scope=page.evaluate("state.homeProjectId")
    owner=scope.split(":")[0]
    assert scope==owner+":shared"
    with page.expect_file_chooser() as chooser:page.locator("#home-upload").click()
    with page.expect_response(lambda response:response.url.endswith(f"/api/projects/{owner}/scopes/shared/sources")) as uploaded:
        chooser.value.set_files({"name":"voice.png","mimeType":"image/png","buffer":source_bytes()})
    assert uploaded.value.ok,uploaded.value.text()
    group=uploaded.value.json()["document_id"]
    page.wait_for_function("!state.busy")
    page.locator("#new-project-chat").click()
    page.wait_for_function("id=>!state.sessionOpening&&state.document?.document_id===id",arg=group)
    assert page.evaluate("state.activeBuildingScopeId")==scope
    assert page.evaluate("state.activeProjectId")==owner
    expect(page.locator("#voice-record")).to_be_enabled()


def test_microphone_icon_toggle_records_until_muted_without_submitting(voice_server,voice_page):
    from playwright.sync_api import expect
    url,state=voice_server;page=voice_page;voice_ready(page,url)
    mic=page.locator("#voice-record")
    expect(mic).to_have_attribute("aria-pressed","false")
    expect(mic).to_have_accessible_name("Unmute microphone")
    assert mic.bounding_box()["width"]<=44
    assert page.get_by_text("Hold to talk",exact=True).count()==0
    mic.click();page.wait_for_function("voice.mode==='listening'")
    expect(mic).to_have_attribute("aria-pressed","true")
    assert page.locator("#voice-mute-slash").get_attribute("hidden") is not None
    page.locator("#question").focus();assert page.evaluate("voice.mode==='listening'")
    page.wait_for_function("document.getElementById('question').value.includes('plant')")
    mic.focus();mic.press("Space")
    page.wait_for_function("!voice.recording")
    expect(mic).to_have_attribute("aria-pressed","false")
    assert page.locator("#voice-mute-slash").get_attribute("hidden") is None
    assert page.evaluate("voiceTestStreams.every(stream=>stream.getTracks().every(track=>track.readyState==='ended'))")
    assert not state.questions
    mic.click();page.wait_for_function("voice.mode==='listening'")
    page.get_by_role("button",name="Home",exact=True).click()
    page.wait_for_function("!voice.recording")
    expect(mic).to_have_attribute("aria-pressed","false")


def test_muting_during_microphone_startup_stops_late_stream(voice_server,voice_page):
    from playwright.sync_api import expect
    url,state=voice_server;page=voice_page
    page.add_init_script("""(() => {
      const original=navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
      navigator.mediaDevices.getUserMedia=async options=>{await new Promise(resolve=>window.resumeMicrophone=resolve);return original(options);};
    })()""")
    voice_ready(page,url);mic=page.locator("#voice-record")
    mic.click();page.wait_for_function("typeof resumeMicrophone==='function'")
    expect(mic).to_have_attribute("aria-pressed","true")
    mic.click();expect(mic).to_have_attribute("aria-pressed","false")
    page.evaluate("resumeMicrophone()")
    page.wait_for_function("voiceTestStreams.length>0&&voiceTestStreams.every(stream=>stream.getTracks().every(track=>track.readyState==='ended'))")
    assert not page.evaluate("voice.recording") and not state.sessions
