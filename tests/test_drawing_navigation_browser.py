"""Drawing-file browsing stays inside a Building and never switches its chat."""
import os
from threading import Event

import pytest
from test_agent_e2e_browser import agent_server
from test_browser import source_bytes
from test_browser_3d import scene_page
from test_sourcefirst_browser import static_server, setup_routes

pytestmark = pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS") != "1", reason="opt-in browser checks")


def grouped_sources(app, first, *, pdf=False):
    document = app.state.documents.add_many([(source_bytes(pdf=pdf) + (b"" if pdf else b"second"),
        "Two-page drawing.pdf" if pdf else "Second plan with a long descriptive filename.png")], building_id=first.id)
    project = app.state.projects.catalog([document.public()], writable=True)[0]
    return project, document


def open_first(page, url, project, document):
    page.goto(url)
    page.locator(f'tr[data-project-id="{project["id"]}:{document.id}"] .home-file').click()
    page.locator(f'tr[data-building-id="{document.id}"] .home-file').first.click()
    page.wait_for_function("!state.sessionOpening && state.document !== null")


def test_file_picker_arrows_preserve_chat_draft_marks_and_mobile_bounds(agent_server, scene_page):
    from playwright.sync_api import expect
    url, app, first, provider = agent_server
    project, document = grouped_sources(app, first)
    app.state.documents.add(source_bytes() + b"outside", "Outside this Building.png")
    page = scene_page
    open_first(page, url, project, document)
    session = page.evaluate("state.activeSessionId")
    page.locator("#question").fill("Keep this draft while inspecting another drawing")
    page.locator("#annotation-toggle").click();page.locator("#annotation-point").click()
    page.locator("#annotation-overlay").click(position={"x":90,"y":110})
    expect(page.locator("#annotation-attachments button")).to_have_count(1)
    mark_ids = page.evaluate("blueprintAnnotations.selectedIds()")
    page.locator("#annotation-point").click()
    expect(page.locator("#drawing-previous-file")).to_be_disabled()
    page.locator("#workspace-blueprints").click()
    expect(page.locator(".drawing-file-choice")).to_have_count(2)
    expect(page.locator("#drawing-file-picker")).not_to_contain_text("Outside")
    page.keyboard.press("Escape");expect(page.locator("#drawing-file-picker")).not_to_be_visible()
    page.locator("#drawing-next-file").click();page.wait_for_function("chatUI.sourceView().page===2")
    assert page.evaluate("state.activeSessionId") == session
    assert page.evaluate("state.document.document_id") == document.id
    expect(page.locator("#question")).to_have_value("Keep this draft while inspecting another drawing")
    assert page.evaluate("blueprintAnnotations.selectedIds()") == mark_ids
    expect(page.locator("#drawing-next-file")).to_be_disabled()
    assert len(app.state.project_chats.catalog(project)) == 1 and not provider["messages"]
    page.locator("#drawing-previous-file").click();page.wait_for_function("chatUI.sourceView().page===1")
    page.set_viewport_size({"width":390,"height":844});page.locator("#workspace-blueprints").click()
    for selector in ["#drawing-previous-file","#drawing-next-file","#drawing-file-picker"]:
        bounds=page.locator(selector).bounding_box();assert bounds["x"]>=0 and bounds["x"]+bounds["width"]<=391
    top,viewer,bottom=[page.locator(selector).bounding_box() for selector in ["#drawing-previous-file","#viewer","#drawing-next-file"]]
    assert top["height"]>=44 and bottom["height"]>=44
    assert top["y"]+top["height"]<=viewer["y"]+1 and bottom["y"]>=viewer["y"]+viewer["height"]-1


def test_grouped_pdf_files_and_pages_keep_the_same_session(agent_server, scene_page):
    from playwright.sync_api import expect
    url,app,first,provider=agent_server;project,document=grouped_sources(app,first,pdf=True);page=scene_page
    open_first(page,url,project,document);session=page.evaluate("state.activeSessionId")
    page.locator("#workspace-blueprints").click();expect(page.locator("#drawing-file-picker")).to_contain_text("2 pages")
    page.locator("#drawing-next-file").click();page.wait_for_function("chatUI.sourceView().page===2")
    page.locator("#workspace-view-toggle").click();page.locator("#workspace-next-page").click();page.wait_for_function("chatUI.sourceView().page===3")
    expect(page.locator("#drawing-next-file")).to_be_disabled()
    page.locator("#drawing-previous-file").click();page.wait_for_function("chatUI.sourceView().page===1")
    assert page.evaluate("state.activeSessionId")==session and not provider["messages"]


def test_failed_and_cancelled_page_loads_retain_previous_view_and_chat(agent_server, scene_page):
    from playwright.sync_api import expect
    url,app,first,_=agent_server;project,document=grouped_sources(app,first);page=scene_page
    open_first(page,url,project,document);session=page.evaluate("state.activeSessionId");page.locator("#question").fill("Retain draft")
    route_pattern=f"**/api/buildings/{document.id}/revisions/*/pages/2"
    page.route(route_pattern,lambda route:route.fulfill(status=503));page.locator("#drawing-next-file").click()
    expect(page.locator("#workspace-control-status")).to_contain_text("previous view is retained")
    assert page.evaluate("chatUI.sourceView().page")==1 and page.evaluate("state.activeSessionId")==session
    expect(page.locator("#question")).to_have_value("Retain draft")
    page.unroute(route_pattern);held=[];page.route(route_pattern,lambda route:held.append(route))
    page.locator("#drawing-next-file").click();page.wait_for_function("projectLibrary.drawingBusy()")
    expect(page.locator("#question")).to_be_enabled();page.locator("#home-tab").click();assert held
    held[0].fulfill(body=source_bytes(),content_type="image/png");page.wait_for_function("!projectLibrary.drawingBusy()")
    expect(page.locator("#home-library")).to_be_visible();assert page.evaluate("chatUI.sourceView().page")==1


def test_pending_answer_stays_in_chat_without_resetting_new_file_view(agent_server, scene_page):
    from playwright.sync_api import expect
    url,app,first,_=agent_server;project,document=grouped_sources(app,first);provider=app.state.provider_factory();respond=provider.converse_agent
    entered,release=Event(),Event()
    def delayed(*args,**kwargs):entered.set();assert release.wait(15);return respond(*args,**kwargs)
    provider.converse_agent=delayed;app.state.provider_factory=lambda:provider;page=scene_page
    try:
        open_first(page,url,project,document);session=page.evaluate("state.activeSessionId")
        page.locator("#question").fill("Pending answer while browsing drawings");page.locator("#ask-button").click();assert entered.wait(5)
        page.locator("#drawing-next-file").click();page.wait_for_function("chatUI.sourceView().page===2");release.set()
        expect(page.locator("#chat-log")).to_contain_text("Fixture conversation is available")
        assert page.evaluate("state.activeSessionId")==session and page.evaluate("chatUI.sourceView().page")==2
    finally:release.set()


def test_native_and_pinned_drawing_groups_are_separate_readonly_buildings(static_server, scene_page):
    from copy import deepcopy
    from playwright.sync_api import expect
    page=scene_page;document,_,calls=setup_routes(page);drawing=deepcopy(document)
    drawing.update(document_id="e"*64,building_id="e"*64,filename="Pinned drawing.png",public_example=True,read_only_model=True,pinned_revision_id=document["revision_id"])
    drawing["sources"][0]["filename"]="Pinned drawing.png"
    document.update(kind="ifc",filename="Original native.ifc",pages=[],public_example=True,read_only_model=True,has_scene=True,scene_url="/api/documents/native/scene")
    project={"id":"f"*32,"name":"Pinned examples","building_ids":[document["document_id"],drawing["document_id"]],"read_only":True}
    page.route("**/api/buildings",lambda route:route.fulfill(json={"buildings":[document,drawing],"projects":[project]}))
    page.route(f'**/api/buildings/{drawing["document_id"]}',lambda route:route.fulfill(json=drawing))
    page.route("**/api/documents/native/scene",lambda route:route.fulfill(json={"document_id":document["document_id"],"building_id":document["document_id"],"revision_id":document["revision_id"],"derived":False,"units":"m","floors":[],"elements":[],"warnings":[]}))
    page.route("**/api/access",lambda route:route.fulfill(json={"public_demo":True,"can_work":False,"shared_workspace":True}))
    page.goto(static_server);expect(page.locator("#home-library-list tr")).to_have_count(2)
    page.locator(f'tr[data-project-id="{project["id"]}:{document["document_id"]}"] .home-file').click();page.locator("#home-library-list .home-file").first.click()
    page.wait_for_function("state.document?.kind==='ifc'");page.locator("#workspace-blueprints").click();expect(page.locator(".drawing-file-choice")).to_have_count(0)
    page.locator("#home-tab").click();page.locator(f'tr[data-project-id="{project["id"]}:{drawing["document_id"]}"] .home-file').click();page.locator("#home-library-list .home-file").first.click()
    page.wait_for_function("state.document?.kind==='drawing'");expect(page.locator("#page-image")).to_be_visible()
    assert page.evaluate("state.document.revision_id")==drawing["pinned_revision_id"] and page.evaluate("state.activeSessionId") is None
    assert all(method=="GET" for method,_,_ in calls) and not any("/chats" in path for _,path,_ in calls)


def test_failed_target_assumptions_cannot_leave_previous_building_values(agent_server, scene_page):
    from playwright.sync_api import expect
    url,app,first,_=agent_server;second=app.state.documents.add(source_bytes()+b"other","Other Building.png")
    project=app.state.projects.catalog([first.public(),second.public()],writable=True)[0];app.state.projects.update(project["id"],add=second.id);page=scene_page
    page.route(f"**/api/buildings/{first.id}/assumptions",lambda route:route.fulfill(json={"building_id":first.id,"revision_id":first.revision_id,"rows":[{"id":"old-height","property":"floor_height","scope":{"floor_id":"fixture-floor"},"label":"First Building only","value":3,"unit":"m","provenance":"unknown","editable":True,"source":{"page":1,"bbox":[.1,.1,.4,.4]}}]}))
    page.route(f"**/api/buildings/{second.id}/assumptions",lambda route:route.fulfill(status=503,json={"detail":"Target assumptions unavailable"}))
    open_first(page,url,project,first);page.wait_for_function("state.assumptionRows.some(row=>row.id==='old-height')")
    page.locator("#home-tab").click();page.locator(f'tr[data-project-id="{project["id"]}:{second.id}"] .home-file').click();page.locator("#home-library-list .home-file").first.click()
    page.wait_for_function("id=>state.document?.document_id===id&&!state.sessionOpening",arg=second.id)
    assert page.evaluate("[state.assumptionRows,state.assumptionsRevision,state.assumptionDataRevision]")==[[],None,None]
    expect(page.locator("#assumption-rows")).not_to_contain_text("First Building only")
    assert page.locator("#assumption-rows input,#assumption-rows button").count()==0
