"""Project overview and session isolation through real local HTTP; fake inference."""
import os
from threading import Event

import pytest

from test_agent_e2e_browser import agent_server
from test_browser_3d import scene_page
from test_sourcefirst_browser import static_server, setup_routes

pytestmark=pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS")!="1",reason="opt-in browser checks")


def test_overview_readonly_preview_rename_resume_delete_and_home_navigation(agent_server,scene_page):
    from playwright.sync_api import expect
    url,app,document,_=agent_server;page=scene_page;page.goto(url)
    expect(page.locator(".chat-brand")).to_contain_text("Concrete")
    expect(page.locator("#question")).not_to_be_visible()
    assert page.locator('[role="tablist"]').count()==0
    page.locator("#home-library-list .home-file").first.click()
    expect(page.locator("#project-chats")).to_be_visible()
    expect(page.locator("#chat-preview .preview-empty")).to_contain_text("Concrete")
    expect(page.locator("#question")).not_to_be_visible()
    bounds=[page.locator(s).bounding_box() for s in ["#home-library","#chat-preview","#active-tasks"]]
    assert bounds[0]["x"]<bounds[1]["x"]<bounds[2]["x"]
    page.locator("#new-project-chat").click()
    expect(page.locator("#question")).to_be_visible()
    page.locator("#question").fill("Hello from this project")
    page.locator("#ask-button").click()
    expect(page.locator("#chat-log")).to_contain_text("Fixture conversation is available")
    session=page.evaluate("state.activeSessionId")
    page.locator("#back-project-overview").click()
    row=page.locator(f'[data-session-id="{session}"]')
    expect(row.locator("time")).to_be_visible()
    assert row.locator(".session-info small").count()==0
    row.locator(".session-preview").click()
    expect(page.locator("#chat-preview-content")).to_contain_text("Hello from this project")
    expect(page.locator("#chat-preview")).to_contain_text("Read-only preview")
    assert page.locator("#chat-preview input,#chat-preview textarea,#chat-preview select,#chat-preview form").count()==0
    assert page.locator("#chat-preview").evaluate("el=>parseFloat(getComputedStyle(el).borderRadius)>0")
    row.locator(".session-rename").click();row.locator("input").fill("Design discussion");row.locator("input").press("Enter")
    expect(row.locator(".session-name")).to_have_text("Design discussion")
    row.locator(".session-name").click()
    expect(page.locator("#live-chat-title")).to_have_text("Design discussion")
    expect(page.locator("#chat-log")).to_contain_text("Hello from this project")
    page.locator("#back-project-overview").click()
    row.locator(".session-preview").click()
    expect(page.locator("#chat-preview-content")).to_contain_text("Hello from this project")
    row.locator(".session-delete").click()
    expect(page.locator("#project-chat-list [data-session-id]")).to_have_count(0)
    expect(page.locator("#chat-preview .preview-empty")).to_contain_text("Concrete")
    page.get_by_role("button",name="Home",exact=True).click()
    expect(page.locator("#home-library-title")).to_have_text("Projects")
    expect(page.locator("#chat-preview")).not_to_be_visible()
    expect(page.locator("#question")).not_to_be_visible()
    assert app.state.documents.get(document.id).source_bytes==document.source_bytes


def test_empty_project_new_chat_never_inherits_previous_file_or_session(agent_server,scene_page):
    from playwright.sync_api import expect
    url,app,document,_=agent_server;page=scene_page;requests=[]
    page.on("request",lambda r:requests.append(r.post_data_json) if r.url.endswith("/api/chat") else None)
    page.goto(url);page.locator("#home-library-list .home-file").first.click();page.locator("#new-project-chat").click()
    page.locator("#question").fill("Previous project's discussion")
    page.locator("#ask-button").click();expect(page.locator("#chat-log")).to_contain_text("Fixture conversation is available")
    previous=page.evaluate("({project:state.activeProjectId,session:state.activeSessionId})")
    page.get_by_role("button",name="Home",exact=True).click()
    page.locator("#home-new-project").click();page.locator("#project-create-name").fill("Empty test project")
    page.locator("#project-create-form button[type=submit]").click()
    expect(page.locator("#home-project-name")).to_have_text("Empty test project")
    expect(page.locator("#project-chat-list [data-session-id]")).to_have_count(0)
    expect(page.locator("#question")).not_to_be_visible()
    page.locator("#new-project-chat").click()
    expect(page.locator("#question")).to_be_visible()
    assert page.evaluate("state.document===null&&state.scene===null")
    assert page.evaluate("state.activeProjectId")!=previous["project"]
    page.locator("#question").fill("How many marked rooms are there?")
    page.locator("#ask-button").click()
    expect(page.locator("#chat-log")).to_contain_text("Attach or open drawing/IFC sources")
    assert requests[-1]["document_id"] is None and requests[-1]["workspace"]["geometry_revision_id"] is None
    assert requests[-1]["project_id"]!=previous["project"] and requests[-1]["session_id"]!=previous["session"]
    assert page.evaluate("state.document===null")
    page.locator("#back-project-overview").click();page.locator(".session-preview").click()
    expect(page.locator("#chat-preview-content")).not_to_contain_text("Previous project's discussion")
    expect(page.locator("#chat-preview-content")).to_contain_text("How many marked rooms")


def test_anonymous_project_file_opens_readonly_without_chat_history(static_server,scene_page):
    from playwright.sync_api import expect
    page=scene_page;document,_,calls=setup_routes(page)
    document["read_only_model"]=True;document["public_example"]=True
    page.route("**/api/access",lambda route:route.fulfill(json={"public_demo":True,"can_work":False,"shared_workspace":True}))
    page.goto(static_server);page.locator("#home-library-list .home-file").first.click()
    expect(page.locator("#project-chats-status")).to_contain_text("Unlock")
    page.locator("#home-library-list .home-file").first.click()
    expect(page.locator("#visual-workspace")).to_be_visible()
    expect(page.locator("#page-image")).to_be_visible()
    expect(page.locator("#question")).not_to_be_visible()
    assert not any("/chats" in path for _,path,_ in calls)


def test_pending_reply_stays_in_its_original_session_after_project_navigation(agent_server,scene_page):
    from playwright.sync_api import expect
    url,app,_,_=agent_server;page=scene_page
    provider=app.state.provider_factory();respond=provider.converse_agent;entered=Event();release=Event()
    def delayed(*args,**kwargs):
        entered.set();assert release.wait(15);return respond(*args,**kwargs)
    provider.converse_agent=delayed;app.state.provider_factory=lambda:provider
    try:
        page.goto(url);page.locator("#home-library-list .home-file").first.click();page.locator("#new-project-chat").click()
        page.locator("#question").fill("Delayed original-project reply")
        page.locator("#ask-button").click();assert entered.wait(5)
        captured=page.evaluate("({project:state.activeProjectId,session:state.activeSessionId})")
        page.get_by_role("button",name="Home",exact=True).click()
        page.locator("#home-new-project").click();page.locator("#project-create-name").fill("Other project while answering")
        page.locator("#project-create-form button[type=submit]").click()
        expect(page.locator("#home-project-name")).to_have_text("Other project while answering")
        release.set()
        page.wait_for_function("""async captured => {
          const response=await fetch(`/api/projects/${captured.project}/chats/${captured.session}`);
          return (await response.json()).messages.length===2;
        }""",arg=captured)
        expect(page.locator("#home-project-name")).to_have_text("Other project while answering")
        expect(page.locator("#question")).not_to_be_visible()
        expect(page.locator("#chat-preview .preview-empty")).to_contain_text("Concrete")
        expect(page.locator("#project-chat-list [data-session-id]")).to_have_count(0)
    finally:release.set()


def test_preview_evidence_expands_original_without_opening_a_live_session(agent_server,scene_page):
    from playwright.sync_api import expect
    url,app,document,state=agent_server;page=scene_page
    app.state.documents.append_conversation(document.id,{"id":"fixture-user","role":"user","question":"Inspect source","timestamp":100.0,"revision_id":document.revision_id})
    app.state.documents.append_conversation(document.id,{"id":"fixture-answer","role":"assistant","revision_id":document.revision_id,"timestamp":101.0,
        "answer":{"status":"answered","answer":"Synthetic source preview only","answered_revision_id":document.revision_id,
            "evidence":[{"page":1,"bbox":[.1,.1,.8,.8],"label":"Original fixture page","observation":"Synthetic evidence"}]}})
    page.goto(url);page.locator("#home-library-list .home-file").first.click();page.locator(".session-preview").click()
    page.locator("#chat-preview summary").click();page.locator("#chat-preview .preview-source").click()
    expect(page.locator("#chat-preview img")).to_be_visible()
    assert page.evaluate("state.document===null&&!state.activeSessionId")
    expect(page.locator("#question")).not_to_be_visible()
    assert not state["messages"]


def test_opening_file_disables_drawing_until_session_ready_and_detaches_previous_chat_marks(agent_server,scene_page):
    from playwright.sync_api import expect
    url,_,_,_=agent_server;page=scene_page;held=[];blocked=False
    def session_history(route):
        nonlocal blocked
        if not blocked and route.request.method=="GET":blocked=True;held.append(route)
        else:route.continue_()
    page.route("**/api/projects/*/chats/*",session_history)
    page.goto(url);page.locator("#home-library-list .home-file").first.click()
    with page.expect_request("**/api/projects/*/chats/*"):
        page.locator("#home-library-list .home-file").first.click()
    expect(page.locator("#annotation-point")).to_be_disabled()
    expect(page.locator("#question")).not_to_be_visible()
    held.pop().continue_()
    expect(page.locator("#question")).to_be_visible()
    page.locator("#annotation-toggle").click()
    page.locator("#annotation-point").click();bounds=page.locator("#annotation-overlay").bounding_box()
    page.locator("#annotation-overlay").click(position={"x":bounds["width"]*.3,"y":bounds["height"]*.3})
    expect(page.locator("#annotation-attachments button")).to_have_count(1)
    page.locator("#back-project-overview").click();page.locator("#new-project-chat").click()
    expect(page.locator("#question")).to_be_visible()
    expect(page.locator("#annotation-attachments button")).to_have_count(0)
    assert len(page.evaluate("blueprintAnnotations.rows()"))==1
    pending_marks=[]
    def save_mark(route):
        if route.request.method=="POST":pending_marks.append(route)
        else:route.continue_()
    page.route("**/api/buildings/*/annotations",save_mark)
    page.locator("#annotation-point").click()
    with page.expect_request(lambda request:request.url.endswith("/annotations") and request.method=="POST"):
        page.locator("#annotation-overlay").click(position={"x":bounds["width"]*.6,"y":bounds["height"]*.6})
    page.locator("#back-project-overview").click();page.locator("#new-project-chat").click()
    expect(page.locator("#question")).to_be_visible()
    pending_marks.pop().continue_()
    page.wait_for_function("blueprintAnnotations.rows().length===2")
    expect(page.locator("#annotation-attachments button")).to_have_count(0)
