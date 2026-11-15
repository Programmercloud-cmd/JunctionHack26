"""Restored release controls and stable interaction, with explicit API fixtures."""
import json
import os

import pytest
from test_browser_3d import scene_page
from test_chat_ui_browser import chat_fixture
from test_sourcefirst_browser import static_server

pytestmark=pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS")!="1",reason="opt-in browser checks")


def test_details_typing_and_scroll_survive_control_and_job_updates(static_server,scene_page):
    from playwright.sync_api import expect
    page=scene_page
    document,scene,calls,pending=chat_fixture(page,static_server)
    text="I can type a complete sentence without clicking the composer again."
    page.locator("#question").click()
    page.keyboard.type(text,delay=10)
    expect(page.locator("#question")).to_have_value(text)
    expect(page.locator("#question")).to_be_focused()
    page.evaluate("""() => {
      chatUI.mergeConversation(Array.from({length:40},(_,i)=>({id:'history-'+i,role:'assistant',answer:{status:'conversation',answer:'Saved note '+i+'\\n'.repeat(10),tool:'conversation'}})));
      const scroll=document.getElementById('chat-scroll');scroll.scrollTop=240;
    }""")
    page.wait_for_timeout(60)
    top=page.locator("#chat-scroll").evaluate("el=>el.scrollTop")
    page.evaluate("""() => {for(let i=0;i<4;i++){updateControls();chatUI.onDocument(state.document);chatUI.onJobs(state.jobs);chatUI.openWorkspace('model');}}""")
    page.wait_for_timeout(60)
    assert page.locator("#chat-scroll").evaluate("el=>el.scrollTop")==pytest.approx(top,abs=1)
    page.keyboard.type(" Still typing.")
    expect(page.locator("#question")).to_have_value(text+" Still typing.")
    page.locator("#home-tab").click()
    expect(page.locator("#question")).not_to_be_visible()
    page.locator("#home-library-list .home-file").first.click()
    page.locator("#home-library-list .home-file").first.click()
    expect(page.locator("#visual-workspace")).to_be_visible()


def test_concept_downloads_and_correction_controls_are_reachable(static_server,scene_page):
    from playwright.sync_api import expect
    page=scene_page
    document,scene,calls,pending=chat_fixture(page,static_server)
    page.locator("#workspace-concept").click()
    page.wait_for_function("chatUI.snapshot().view_mode==='concept'&&state.viewer.mode==='concept'")
    assert page.evaluate("state.scene.revision_id")==document["revision_id"]
    page.route("**/model.ifc",lambda route:route.fulfill(body="ISO-10303-21; SYNTHETIC TEST",content_type="application/octet-stream"))
    page.route("**/sources/*/original",lambda route:route.fulfill(body=b"synthetic original",content_type="application/octet-stream"))
    page.locator("#workspace-files-toggle").click()
    with page.expect_download():page.locator("#workspace-download-ifc").click()
    with page.expect_download():page.locator("#workspace-download-source").click()
    page.locator("#workspace-evidence-toggle").click()
    page.locator("#assumptions-panel>summary").click()
    number=page.locator("#assumption-rows input[type=number]").first
    expect(number).to_be_visible()
    number.fill("3.4")
    with page.expect_request("**/refinements") as submitted:page.locator("#apply-assumptions").click()
    body=json.loads(submitted.value.post_data)
    assert body["edits"][0]["value"]==3.4
    assert body["edits"][0]["unit"]=="m"


def test_attach_additional_files_in_details_uses_source_endpoint(static_server,scene_page):
    from playwright.sync_api import expect
    page=scene_page
    document,scene,calls,pending=chat_fixture(page,static_server)
    assert page.locator("#file-input").get_attribute("multiple") is not None
    with page.expect_file_chooser() as chooser:page.locator("#attach-drawings").click()
    with page.expect_request("**/sources") as submitted:
        chooser.value.set_files([{"name":"section-a.svg","mimeType":"image/svg+xml","buffer":b'<svg xmlns="http://www.w3.org/2000/svg"/>'},
                                 {"name":"section-b.svg","mimeType":"image/svg+xml","buffer":b'<svg xmlns="http://www.w3.org/2000/svg" width="2"/>'}])
    assert submitted.value.method=="POST"
    page.wait_for_function("state.busy===null")
    expect(page.locator("#visual-workspace")).to_be_visible()
    assert page.evaluate("state.document.document_id")==document["document_id"]


def test_active_tasks_reports_render_votes_and_stops_real_job_id(static_server,scene_page):
    from playwright.sync_api import expect
    page=scene_page
    document,scene,calls,pending=chat_fixture(page,static_server)
    job={"id":"parity-render","building_id":document["document_id"],"kind":"render","status":"running","phase":"render_review_2",
         "created_at":1700000000,"updated_at":1700000001,"message":"Second independent reviewer is inspecting the candidate.",
         "reviewer_votes":[{"reviewer":1,"candidate_supported":True,"satisfied":True}]}
    page.route("**/api/jobs/parity-render/stop",lambda route:route.fulfill(json={**job,"status":"stopped","phase":"stopped"}))
    page.evaluate("job=>{state.jobs=[job];chatUI.onJobs(state.jobs)}",job)
    expect(page.locator("#active-task-count")).to_have_text("1")
    card=page.locator('[data-task-id="parity-render"]')
    expect(card).to_contain_text("Reviewer 1: satisfied")
    expect(card).to_contain_text(document["filename"])
    card.get_by_role("button",name="Stop task",exact=True).click()
    expect(page.locator("#active-task-count")).to_have_text("0")
    expect(card).to_have_attribute("data-status","stopped")


def test_model_arrival_and_tab_click_share_one_viewer_and_ignore_closed_document(static_server,scene_page):
    from playwright.sync_api import expect
    page=scene_page
    document,scene,calls,pending=chat_fixture(page,static_server)
    page.evaluate("""async scene => {
      clearScene();
      await Promise.all([loadScene(scene),loadScene(scene)]);
    }""",scene)
    expect(page.locator("#model-canvas-container canvas")).to_have_count(1)
    assert page.evaluate("state.viewer.meshes.size")==3
    page.evaluate("""async scene => {
      clearScene();
      const loading=loadScene(scene);
      state.epoch++;
      await loading;
    }""",scene)
    expect(page.locator("#model-canvas-container canvas")).to_have_count(0)
    assert page.evaluate("state.scene===null&&state.viewer===null")


def test_home_upload_remains_available_after_readonly_example_while_details_edits_stay_disabled(static_server,scene_page):
    from playwright.sync_api import expect
    page=scene_page
    chat_fixture(page,static_server)
    page.evaluate("state.document.read_only_model=true;state.taskAccess={public_demo:true,can_work:true};updateControls()")
    expect(page.locator("#attach-drawings")).to_be_disabled()
    page.locator("#home-tab").click()
    expect(page.locator("#question")).not_to_be_visible()
    page.locator("#home-library-list .home-file").first.click()
    expect(page.locator("#home-upload")).to_be_enabled()
    with page.expect_file_chooser():page.locator("#home-upload").click()
