"""Project drawing navigation, real HTTP/session ownership, synthetic inference only."""
import os
from threading import Event

import pytest
from test_agent_e2e_browser import agent_server
from test_browser import source_bytes
from test_browser_3d import scene_page
from test_sourcefirst_browser import static_server, setup_routes

pytestmark = pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS") != "1", reason="opt-in browser checks")


def project_files(app, first):
    second = app.state.documents.add(source_bytes() + b"second", "Second plan with a long descriptive filename.png")
    app.state.documents.add(source_bytes() + b"outside", "Outside this project.png")
    project = app.state.projects.catalog([first.public(), second.public()], writable=True)[0]
    app.state.projects.update(project["id"], add=second.id)
    return project, second


def open_first(page, url, project, first):
    page.goto(url)
    page.locator(f'tr[data-project-id="{project["id"]}"] .home-file').click()
    page.locator(f'tr[data-building-id="{first.id}"] .home-file').click()
    page.wait_for_function("!state.sessionOpening && state.document !== null")


def test_project_files_picker_arrows_owned_sessions_and_mobile(agent_server, scene_page):
    from playwright.sync_api import expect
    url, app, first, provider = agent_server
    project, second = project_files(app, first)
    page = scene_page
    open_first(page, url, project, first)
    original_session = page.evaluate("state.activeSessionId")
    expect(page.locator("#drawing-previous-file")).to_be_disabled()
    expect(page.locator("#drawing-next-file")).to_be_enabled()
    page.locator("#workspace-blueprints").click()
    expect(page.locator("#drawing-file-picker")).to_be_visible()
    expect(page.locator(".drawing-file-choice")).to_have_count(2)
    expect(page.locator("#drawing-file-picker")).not_to_contain_text("Outside")
    page.keyboard.press("Escape")
    expect(page.locator("#drawing-file-picker")).not_to_be_visible()
    page.locator("#workspace-blueprints").click()
    page.locator("#question").click()
    expect(page.locator("#drawing-file-picker")).not_to_be_visible()
    page.locator("#drawing-next-file").click()
    page.wait_for_function("id => state.document?.document_id===id&&!state.sessionOpening", arg=second.id)
    second_session = page.evaluate("state.activeSessionId")
    assert second_session != original_session
    assert app.state.project_chats.get(project["id"], second_session)["building_id"] == second.id
    expect(page.locator("#drawing-next-file")).to_be_disabled()
    page.locator("#question").fill("Hello from the second file")
    page.locator("#ask-button").click()
    expect(page.locator("#chat-log")).to_contain_text("Fixture conversation is available")
    assert provider["messages"] == ["Hello from the second file"]
    page.locator("#drawing-previous-file").click()
    page.wait_for_function("id => state.activeSessionId===id&&!state.sessionOpening", arg=original_session)
    expect(page.locator("#chat-log")).not_to_contain_text("Hello from the second file")
    page.set_viewport_size({"width": 390, "height": 844})
    page.locator("#workspace-blueprints").click()
    expect(page.locator(".drawing-file-choice")).to_have_count(2)
    for selector in ["#drawing-previous-file", "#drawing-next-file", "#drawing-file-picker"]:
        bounds = page.locator(selector).bounding_box()
        assert bounds["x"] >= 0 and bounds["x"] + bounds["width"] <= 391
    top, viewer, bottom = [page.locator(selector).bounding_box() for selector in ["#drawing-previous-file", "#viewer", "#drawing-next-file"]]
    assert top["height"] >= 44 and bottom["height"] >= 44
    assert top["y"] + top["height"] <= viewer["y"] + 1
    assert bottom["y"] >= viewer["y"] + viewer["height"] - 1


def test_grouped_sources_change_files_not_pdf_pages_and_keep_session(agent_server, scene_page):
    from playwright.sync_api import expect
    url, app, first, provider = agent_server
    grouped = app.state.documents.add_many([(source_bytes(pdf=True), "Two-page drawing.pdf")], building_id=first.id)
    project = app.state.projects.catalog([grouped.public()], writable=True)[0]
    page = scene_page
    open_first(page, url, project, grouped)
    session = page.evaluate("state.activeSessionId")
    page.locator("#workspace-blueprints").click()
    expect(page.locator(".drawing-file-choice")).to_have_count(2)
    expect(page.locator("#drawing-file-picker")).to_contain_text("2 pages")
    page.locator("#drawing-next-file").click()
    page.wait_for_function("chatUI.sourceView().page===2&&!state.sessionOpening")
    assert page.evaluate("state.activeSessionId") == session
    page.locator("#workspace-view-toggle").click()
    page.locator("#workspace-next-page").click()
    page.wait_for_function("chatUI.sourceView().page===3")
    expect(page.locator("#drawing-next-file")).to_be_disabled()
    page.locator("#drawing-previous-file").click()
    page.wait_for_function("chatUI.sourceView().page===1")
    assert page.evaluate("state.activeSessionId") == session
    assert not provider["messages"]


def test_failed_image_keeps_original_context_and_cancelled_load_does_not_reopen(agent_server, scene_page):
    from playwright.sync_api import expect
    url, app, first, _ = agent_server
    project, second = project_files(app, first)
    page = scene_page
    open_first(page, url, project, first)
    captured = page.evaluate("({id:state.document.document_id,session:state.activeSessionId,revision:state.document.revision_id})")
    page.locator("#question").fill("Keep this draft")
    page.route(f"**/api/buildings/{second.id}/revisions/*/pages/*", lambda route: route.fulfill(status=503))
    page.locator("#drawing-next-file").click()
    expect(page.locator("#workspace-control-status")).to_contain_text("previous view is still open")
    assert page.evaluate("({id:state.document.document_id,session:state.activeSessionId,revision:state.document.revision_id})") == captured
    expect(page.locator("#question")).to_have_value("Keep this draft")
    assert len(app.state.project_chats.catalog(project)) == 1
    page.unroute(f"**/api/buildings/{second.id}/revisions/*/pages/*")
    held = []
    page.route(f"**/api/buildings/{second.id}", lambda route: held.append(route))
    page.locator("#drawing-next-file").click()
    page.wait_for_function("projectLibrary.drawingBusy()")
    expect(page.locator("#question")).to_be_disabled()
    page.locator("#home-tab").click()
    assert held
    held[0].fulfill(json=second.public())
    page.wait_for_function("!projectLibrary.drawingBusy()")
    expect(page.locator("#home-library")).to_be_visible()
    assert page.evaluate("state.document.document_id") == first.id


def test_pending_answer_remains_in_old_file_chat(agent_server, scene_page):
    from playwright.sync_api import expect
    url, app, first, _ = agent_server
    project, second = project_files(app, first)
    provider = app.state.provider_factory()
    respond = provider.converse_agent
    entered, release = Event(), Event()
    def delayed(*args, **kwargs):
        entered.set()
        assert release.wait(15)
        return respond(*args, **kwargs)
    provider.converse_agent = delayed
    app.state.provider_factory = lambda: provider
    page = scene_page
    try:
        open_first(page, url, project, first)
        session = page.evaluate("state.activeSessionId")
        page.locator("#question").fill("Pending first-file answer")
        page.locator("#ask-button").click()
        assert entered.wait(5)
        page.locator("#drawing-next-file").click()
        page.wait_for_function("id=>state.document?.document_id===id&&!state.sessionOpening", arg=second.id)
        release.set()
        page.wait_for_function("""async ids=>{const r=await fetch(`/api/projects/${ids.project}/chats/${ids.session}`);return (await r.json()).messages.length===2;}""", arg={"project": project["id"], "session": session})
        expect(page.locator("#chat-log")).not_to_contain_text("Pending first-file answer")
        expect(page.locator("#chat-log")).not_to_contain_text("Fixture conversation is available")
        assert page.evaluate("state.document.document_id") == second.id
    finally:
        release.set()


def test_locked_native_file_can_choose_project_drawings_without_mutating_pins(static_server, scene_page):
    from copy import deepcopy
    from playwright.sync_api import expect
    page = scene_page
    document, _, calls = setup_routes(page)
    drawing = deepcopy(document)
    drawing.update(document_id="e" * 64, building_id="e" * 64, filename="Pinned drawing.png", public_example=True,
                   read_only_model=True, pinned_revision_id=document["revision_id"])
    drawing["sources"][0].update(filename="Pinned drawing.png")
    document.update(kind="ifc", filename="Original native.ifc", pages=[], public_example=True, read_only_model=True,
                    pinned_revision_id=document["revision_id"], has_scene=True, scene_url="/api/documents/native/scene")
    document["sources"][0].update(kind="ifc", filename="Original native.ifc", pages=[])
    project = {"id": "f" * 32, "name": "Pinned examples", "building_ids": [document["document_id"], drawing["document_id"]],
               "active_building_id": document["document_id"], "read_only": True}
    page.route("**/api/buildings", lambda route: route.fulfill(json={"buildings": [document, drawing], "projects": [project]}))
    page.route("**/api/projects", lambda route: route.fulfill(json={"projects": [project]}))
    page.route(f'**/api/buildings/{drawing["document_id"]}', lambda route: route.fulfill(json=drawing))
    page.route("**/api/documents/native/scene", lambda route: route.fulfill(json={"document_id": document["document_id"],
        "building_id": document["document_id"], "revision_id": document["revision_id"], "derived": False,
        "units": "m", "floors": [], "elements": [], "warnings": []}))
    page.route("**/api/access", lambda route: route.fulfill(json={"public_demo": True, "can_work": False, "shared_workspace": True}))
    page.goto(static_server)
    page.locator("#home-library-list .home-file").first.click()
    page.locator(f'tr[data-building-id="{document["document_id"]}"] .home-file').click()
    page.wait_for_function("state.document?.kind==='ifc'&&!state.sessionOpening")
    page.locator("#workspace-evidence-toggle").click()
    expect(page.locator("#workspace-tools")).to_be_visible()
    page.locator("#workspace-blueprints").click()
    expect(page.locator("#drawing-file-picker")).to_be_visible()
    expect(page.locator("#workspace-tools")).not_to_be_visible()
    expect(page.locator(".drawing-file-choice")).to_have_count(1)
    page.locator(".drawing-file-choice").click()
    page.wait_for_function("state.document?.kind==='drawing'&&!state.sessionOpening")
    expect(page.locator("#page-image")).to_be_visible()
    expect(page.locator("#question")).not_to_be_visible()
    assert page.evaluate("state.document.revision_id") == drawing["pinned_revision_id"]
    assert page.evaluate("state.activeSessionId") is None
    assert all(method == "GET" for method, _, _ in calls)
    assert not any("/chats" in path for _, path, _ in calls)


def test_failed_target_assumptions_cannot_leave_previous_file_values(agent_server, scene_page):
    from playwright.sync_api import expect
    url, app, first, _ = agent_server
    project, second = project_files(app, first)
    page = scene_page
    page.route(f"**/api/buildings/{first.id}/assumptions", lambda route: route.fulfill(json={
        "building_id": first.id, "revision_id": first.revision_id, "rows": [{"id": "old-height", "property": "floor_height",
        "scope": {"floor_id": "fixture-floor"}, "label": "First file height only", "value": 3, "unit": "m",
        "provenance": "unknown", "editable": True, "source": {"page": 1, "bbox": [.1, .1, .4, .4]}}]}))
    page.route(f"**/api/buildings/{second.id}/assumptions", lambda route: route.fulfill(status=503, json={"detail": "Target assumptions unavailable"}))
    open_first(page, url, project, first)
    page.wait_for_function("state.assumptionRows.some(row=>row.id==='old-height')")
    assert page.locator("#assumption-rows input").count() == 2
    assert page.locator("#assumption-rows button").count() == 1
    page.locator("#drawing-next-file").click()
    page.wait_for_function("id=>state.document?.document_id===id&&!state.sessionOpening", arg=second.id)
    assert page.evaluate("[state.assumptionRows,state.assumptionsRevision,state.assumptionDataRevision]") == [[], None, None]
    expect(page.locator("#assumption-rows")).not_to_contain_text("First file height only")
    assert page.locator("#assumption-rows input,#assumption-rows button").count() == 0
    assert page.locator("#assumption-support option").all_text_contents() == [second.filename]
