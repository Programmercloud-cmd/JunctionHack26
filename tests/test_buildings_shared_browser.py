"""Buildings share sources across independent chats; all inference here is synthetic."""
import base64
import os

import pytest
from test_agent_e2e_browser import AgentBrowserProvider, agent_server
from test_browser import source_bytes
from test_browser_3d import scene_page
from test_ifc_generate import description

pytestmark=pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS")!="1",reason="opt-in browser checks")


class SharedFixtureProvider(AgentBrowserProvider):
    def extract_interpretation(self,document,include_geometry=False):
        assert not include_geometry
        return description()
    def answer_agent(self,document,question):
        self.state.setdefault("source_sets",[]).append((document.id,{source["source_id"] for source in document.sources}))
        return super().answer_agent(document,question)


def create_building(page,name):
    page.locator("#home-tab").click();page.locator("#home-new-project").click();page.locator("#project-create-name").fill(name)
    page.locator("#project-create-form button[type=submit]").click()
    page.wait_for_function("name=>document.getElementById('home-project-name').textContent===name",arg=name)
    return page.evaluate("state.homeProjectId")


def upload_drawings(page,files):
    with page.expect_file_chooser() as chooser:page.locator("#home-upload").click()
    with page.expect_response(lambda response:"/scopes/" in response.url and response.url.endswith("/sources")) as uploaded:
        chooser.value.set_files(files)
    assert uploaded.value.ok,uploaded.value.text()
    page.wait_for_function("!state.busy")
    return uploaded.value.json()


def drop_drawing(page,selector,name,data):
    page.evaluate("""([selector,name,encoded])=>{const dt=new DataTransfer();dt.items.add(new File([Uint8Array.from(atob(encoded),c=>c.charCodeAt(0))],name,{type:'image/png'}));document.querySelector(selector).dispatchEvent(new DragEvent('drop',{bubbles:true,cancelable:true,dataTransfer:dt}));}""",[selector,name,base64.b64encode(data).decode()])


def test_empty_chat_initial_batch_second_chat_and_visualizer_append_share_sources(agent_server,scene_page):
    from playwright.sync_api import expect
    url,app,_,state=agent_server;app.state.provider_factory=lambda:SharedFixtureProvider(state);page=scene_page
    page.goto(url);card=create_building(page,"Shared Building")
    page.locator("#new-project-chat").click();expect(page.locator("#question")).to_be_visible()
    first_session=page.evaluate("state.activeSessionId");owner=page.evaluate("state.activeProjectId")
    assert card==owner+":shared"
    page.locator("#question").fill("Hello before drawings");page.locator("#ask-button").click();expect(page.locator("#chat-log")).to_contain_text("Fixture conversation is available")
    page.locator("#back-project-overview").click()
    result=upload_drawings(page,[{"name":"First floor.png","mimeType":"image/png","buffer":source_bytes()+b"fresh shared"},{"name":"Two-page floor.pdf","mimeType":"application/pdf","buffer":source_bytes(pdf=True)}])
    group=result["document_id"];assert len(result["sources"])==2 and len(result["pages"])==3
    assert not app.state.documents.get(group).scene
    page.locator(f'[data-session-id="{first_session}"] .session-name').click();page.wait_for_function("id=>state.document?.document_id===id&&!state.sessionOpening",arg=group)
    assert page.evaluate("state.activeSessionId")==first_session
    expect(page.locator("#chat-log")).to_contain_text("Hello before drawings")
    assert app.state.project_chats.get(owner,first_session)["building_id"] is None
    page.locator("#question").fill("What is marked in these drawings?");page.locator("#ask-button").click();expect(page.locator("#chat-log .chat-answer").last).to_contain_text("Fixture: the marked original")
    assert len(state["source_sets"][-1][1])==2
    page.locator("#back-project-overview").click();page.locator("#new-project-chat").click();page.wait_for_function("id=>state.activeSessionId!==id&&!state.sessionOpening",arg=first_session)
    second_session=page.evaluate("state.activeSessionId");assert second_session!=first_session
    expect(page.locator("#attach-drawings")).to_have_count(0);expect(page.locator("#workspace-attach-sources")).to_have_count(0)
    page.locator("#question").fill("Keep my second chat draft")
    with page.expect_response(lambda response:"/scopes/" in response.url and response.url.endswith("/sources")) as appended:
        drop_drawing(page,"#visual-workspace","Section.png",source_bytes()+b"new section")
    assert appended.value.ok,appended.value.text();page.wait_for_function("!state.busy && state.document?.sources.length===3")
    assert page.evaluate("state.activeSessionId")==second_session and page.evaluate("state.document.document_id")==group
    expect(page.locator("#question")).to_have_value("Keep my second chat draft")
    page.locator("#workspace-blueprints").click();expect(page.locator(".drawing-file-choice")).to_have_count(3)
    page.locator("#drawing-next-file").click();page.wait_for_function("chatUI.sourceView().page===2")
    assert page.evaluate("state.activeSessionId")==second_session
    page.locator("#back-project-overview").click();page.locator(f'[data-session-id="{first_session}"] .session-name').click()
    page.wait_for_function("id=>state.activeSessionId===id&&!state.sessionOpening&&state.document?.sources.length===3",arg=first_session)
    assert page.evaluate("state.activeSessionId")==first_session
    assert not any(job["kind"] in {"render","reconstruction"} for job in app.state.jobs.for_building(group))
    original_messages=app.state.project_chats.get(owner,first_session)["messages"]
    assert original_messages[0]["document_id"] is None and original_messages[-1]["document_id"]==group


def test_file_picker_captures_building_before_the_user_navigates(agent_server,scene_page):
    from playwright.sync_api import expect
    url,app,_,state=agent_server;app.state.provider_factory=lambda:SharedFixtureProvider(state);page=scene_page
    page.goto(url);first_card=create_building(page,"Upload destination A")
    with page.expect_file_chooser() as chooser:page.locator("#home-upload").click()
    second_card=create_building(page,"Visible Building B")
    with page.expect_response(lambda response:"/scopes/" in response.url and response.url.endswith("/sources")) as response:
        chooser.value.set_files({"name":"Captured.png","mimeType":"image/png","buffer":source_bytes()+b"captured"})
    assert response.value.ok and first_card.split(":")[0] in response.value.url
    page.wait_for_function("!state.busy")
    expect(page.locator("#home-project-name")).to_have_text("Visible Building B")
    assert page.evaluate("state.homeProjectId")==second_card
    catalog=page.request.get(url+"/api/buildings").json()["building_scopes"]
    assert next(scope for scope in catalog if scope["id"]==first_card)["source_group_id"]
    assert next(scope for scope in catalog if scope["id"]==second_card)["source_group_id"] is None


def test_legacy_groups_and_general_chats_get_separate_cards_without_rebinding(agent_server,scene_page):
    from playwright.sync_api import expect
    url,app,first,_=agent_server;second=app.state.documents.add(source_bytes()+b"legacy B","Legacy B.png")
    owner=app.state.projects.catalog([first.public(),second.public()],writable=True)[0];owner=app.state.projects.update(owner["id"],add=second.id)
    a=app.state.project_chats.create(owner,"A retained chat",first.id);b=app.state.project_chats.create(owner,"B retained chat",second.id);general=app.state.project_chats.create(owner,"General retained chat")
    snapshots={chat["id"]:app.state.project_chats.get(owner["id"],chat["id"]) for chat in [a,b,general]};page=scene_page;page.goto(url)
    for suffix,chat in [(first.id,a),(second.id,b),("shared",general)]:
        page.locator(f'tr[data-project-id="{owner["id"]}:{suffix}"] .home-file').click()
        expect(page.locator("#project-chat-list [data-session-id]")).to_have_count(1)
        expect(page.locator("#project-chat-list")).to_contain_text(chat["name"])
        page.locator(".session-name").click();page.wait_for_function("id=>state.activeSessionId===id&&!state.sessionOpening",arg=chat["id"])
        assert page.evaluate("state.activeProjectId")==owner["id"] and page.evaluate("state.activeSessionId")==chat["id"]
        assert page.evaluate("state.document?.document_id||null")==chat["building_id"]
        page.locator("#home-tab").click()
    for identity,snapshot in snapshots.items():assert app.state.project_chats.get(owner["id"],identity)==snapshot
    expect(page.locator("#building-scope-notice")).to_contain_text("separate Buildings")
    a_card=page.locator(f'tr[data-project-id="{owner["id"]}:{first.id}"]');a_card.locator(".project-rename").click();a_card.locator("input").fill("Renamed Building A");a_card.locator("input").press("Enter")
    expect(a_card.locator(".home-file")).to_have_text("Renamed Building A")
    b_card=page.locator(f'tr[data-project-id="{owner["id"]}:{second.id}"]');expect(b_card.locator(".home-file")).to_contain_text("Legacy B.png")
    a_card.locator(".project-delete").click();expect(a_card).to_have_count(0);expect(b_card).to_be_visible()
    page.locator("#home-undo-project").click();expect(a_card).to_be_visible();page.reload();expect(a_card).to_be_visible()
    assert app.state.project_chats.get(owner["id"],a["id"])==snapshots[a["id"]]


def test_shared_legacy_upload_restriction_keeps_chat_and_annotation_controls_available(agent_server,scene_page):
    from playwright.sync_api import expect
    url,app,first,_=agent_server;owner=app.state.projects.catalog([first.public()],writable=True)[0]
    other=app.state.projects.create("Other old owner");app.state.projects.update(other["id"],add=first.id);page=scene_page;page.goto(url)
    page.locator(f'tr[data-project-id="{owner["id"]}:{first.id}"] .home-file').click()
    expect(page.locator("#home-upload")).to_be_disabled();expect(page.locator("#project-drop-zone")).to_contain_text("more than one")
    expect(page.locator("#new-project-chat")).to_be_enabled();page.locator("#new-project-chat").click()
    page.wait_for_function("!state.sessionOpening && state.document!==null");expect(page.locator("#question")).to_be_enabled()
    page.locator("#annotation-toggle").click();expect(page.locator("#annotation-point")).to_be_enabled()


def test_first_upload_dropped_into_empty_live_chat_preserves_session_history_and_draft(agent_server,scene_page):
    from playwright.sync_api import expect
    url,app,_,state=agent_server;app.state.provider_factory=lambda:SharedFixtureProvider(state);page=scene_page
    page.goto(url);create_building(page,"Live first drawings");page.locator("#new-project-chat").click()
    expect(page.locator("#question")).to_be_visible();session=page.evaluate("state.activeSessionId");owner=page.evaluate("state.activeProjectId")
    page.locator("#question").fill("Hello before the first upload");page.locator("#ask-button").click();expect(page.locator("#chat-log")).to_contain_text("Fixture conversation is available")
    page.locator("#question").fill("Keep this unsent question")
    with page.expect_response(lambda response:"/scopes/" in response.url and response.url.endswith("/sources")) as uploaded:
        drop_drawing(page,"#chat-column","Live first.png",source_bytes()+b"live-first")
    assert uploaded.value.ok,uploaded.value.text();group=uploaded.value.json()["document_id"]
    page.wait_for_function("id=>state.document?.document_id===id&&!state.busy",arg=group)
    assert page.evaluate("state.activeSessionId")==session and page.evaluate("state.activeProjectId")==owner
    expect(page.locator("#question")).to_have_value("Keep this unsent question")
    expect(page.locator("#chat-log")).to_contain_text("Hello before the first upload")
    expect(page.locator("#page-image")).to_be_visible()
    assert app.state.project_chats.get(owner,session)["building_id"] is None
