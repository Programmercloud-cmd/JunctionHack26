"""Slim viewer controls, persistent component collapse and reversible project deletion."""
import os

import pytest

from test_browser_3d import scene_page
from test_sourcefirst_browser import static_server
from test_chat_ui_browser import chat_fixture
from test_agent_e2e_browser import agent_server

pytestmark=pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS")!="1",reason="opt-in browser checks")


def test_slim_tabs_files_view_and_evidence_drawers_keep_existing_operations(static_server,scene_page):
    from playwright.sync_api import expect
    page=scene_page;document,scene,calls,pending=chat_fixture(page,static_server)
    expect(page.locator("#workspace-navigation button")).to_have_text(["Drawings","3D Model","Concept"])
    expect(page.locator(".workspace-caption")).not_to_be_visible()
    expect(page.locator("#workspace-tools")).not_to_be_visible()
    expect(page.locator("#workspace-download-ifc")).not_to_be_visible()
    page.locator("#workspace-files-toggle").click()
    expect(page.locator("#workspace-files button")).to_have_text(["Download IFC","Download original","Import"])
    page.route("**/model.ifc",lambda route:route.fulfill(body="ISO-10303-21; SYNTHETIC",content_type="application/octet-stream"))
    page.route("**/sources/*/original",lambda route:route.fulfill(body=b"synthetic original",content_type="application/octet-stream"))
    with page.expect_download():page.locator("#workspace-download-ifc").click()
    with page.expect_download():page.locator("#workspace-download-source").click()
    with page.expect_file_chooser():page.locator("#workspace-attach-sources").click()
    page.locator("#workspace-view-toggle").click()
    expect(page.locator("#workspace-files")).not_to_be_visible()
    page.get_by_role("button",name="Fit to height",exact=True).click()
    assert page.evaluate("drawingFit")=="height"
    page.get_by_role("button",name="Fit to width",exact=True).click()
    page.locator("#workspace-answer_highlights").uncheck()
    page.locator("#workspace-navigation_highlights").uncheck()
    page.locator("#workspace-assumptions").check()
    assert page.evaluate("[chatUI.snapshot().answer_highlighting,chatUI.snapshot().highlighting,chatUI.snapshot().show_assumptions]")==[False,False,True]
    page.keyboard.press("Escape");expect(page.locator("#workspace-view")).not_to_be_visible()
    page.locator("#workspace-evidence-toggle").click()
    page.locator("#assumptions-panel>summary").click()
    expect(page.locator("#assumption-rows input").first).to_be_visible()
    assert page.locator("#assumptions-panel>p").first.evaluate("e=>getComputedStyle(e).color")==page.locator("#chat-connection").evaluate("e=>getComputedStyle(e).color")
    page.locator("#provenance-legend>summary").click()
    expect(page.locator("#provenance-legend")).to_contain_text("excluded from factual QA")
    page.locator("#workspace-evidence-close").click()
    expect(page.locator("#workspace-tools")).not_to_be_visible()
    assert not any(path=="chat/actions" for _,path,_ in calls)


def test_component_panel_stays_collapsed_across_selection_refresh_and_reload(static_server,scene_page):
    from playwright.sync_api import expect
    page=scene_page;chat_fixture(page,static_server)
    page.locator("#workspace-model").click();page.evaluate("state.viewer.select('window-1')")
    toggle=page.locator("#selection-evidence-toggle")
    expect(toggle).to_contain_text("Fixture window-1")
    expect(toggle).to_have_attribute("aria-expanded","true")
    toggle.click();expect(page.locator("#selection-evidence-content")).not_to_be_visible()
    page.evaluate("updateControls();chatUI.onJobs(state.jobs);state.viewer.select('window-2')")
    expect(toggle).to_contain_text("Fixture window-2")
    expect(toggle).to_have_attribute("aria-expanded","false")
    expect(page.locator("#selection-evidence-content")).not_to_be_visible()
    expect(page.locator("#model-caption")).not_to_be_visible()
    assert page.locator("#selection-evidence").bounding_box()["height"]<60
    page.reload();page.locator("#home-library-list .home-file").first.click();page.locator("#home-library-list .home-file").first.click()
    page.wait_for_function("state.viewer?.meshes.size>0")
    page.locator("#workspace-model").click();page.evaluate("state.viewer.select('window-1')")
    expect(toggle).to_have_attribute("aria-expanded","false")
    toggle.click();expect(page.locator("#selection-evidence-content")).to_be_visible()
    expect(page.locator("#selection-evidence-content")).to_contain_text("Display assumption")


def test_header_whitespace_keeps_project_and_only_brand_and_home_navigate(agent_server,scene_page):
    from playwright.sync_api import expect
    page=scene_page;url,app,document,provider=agent_server
    page.goto(url);page.locator("#home-library-list .home-file").first.click();page.locator("#home-library-list .home-file").first.click()
    expect(page.locator("#question")).to_be_visible()
    current=page.evaluate("state.activeSessionId");brand=page.locator(".chat-brand").bounding_box()
    page.mouse.click(brand["x"]+brand["width"]+35,brand["y"]+brand["height"]/2)
    expect(page.locator("#details-panel")).to_be_visible();assert page.evaluate("state.activeSessionId")==current
    page.locator("#home-tab").click();expect(page.locator("#home-library")).to_be_visible()
    page.locator("#home-library-list .home-file").first.click();page.locator("#home-library-list .home-file").first.click()
    page.locator(".chat-brand").click();expect(page.locator("#home-library-title")).to_have_text("Projects")
    assert not provider["messages"]


def test_project_trash_delete_undo_and_reload_preserve_shared_sources(agent_server,scene_page):
    from playwright.sync_api import expect
    page=scene_page;url,app,document,provider=agent_server
    projects=app.state.projects.catalog([document.public()],writable=True);original=projects[0]
    app.state.project_chats.create(original,"Retained chat",document.id)
    shared=app.state.projects.create("Shared file project");app.state.projects.update(shared["id"],add=document.id)
    page.goto(url)
    trash=page.get_by_role("button",name=f"Delete project {original['name']}",exact=True)
    expect(trash).to_be_visible();trash.click()
    expect(page.locator(f'tr[data-project-id="{original["id"]}"]')).to_have_count(0)
    expect(page.locator("#home-library-title")).to_have_text("Projects")
    page.locator("#home-undo-project").click()
    expect(page.locator(f'tr[data-project-id="{original["id"]}"]')).to_be_visible()
    page.locator(f'tr[data-project-id="{original["id"]}"] .home-file').click()
    expect(page.locator("#project-chat-list")).to_contain_text("Retained chat")
    page.locator("#home-projects-back").click();trash.click();page.reload();page.wait_for_function("state.savedBuildingsLoaded")
    expect(page.locator(f'tr[data-project-id="{original["id"]}"]')).to_have_count(0)
    expect(page.locator(f'tr[data-project-id="{shared["id"]}"]')).to_be_visible()
    assert app.state.documents.get(document.id).revision_id==document.revision_id
    page.evaluate("state.health.project_deletion_ready=false;projectLibrary.refresh()")
    expect(page.locator(".project-delete").first).not_to_be_visible()
    assert not provider["messages"]


def test_mobile_drawers_fit_and_keep_source_view_available(static_server,scene_page):
    from playwright.sync_api import expect
    page=scene_page;page.set_viewport_size({"width":390,"height":844});chat_fixture(page,static_server)
    for toggle,panel in [("workspace-files-toggle","workspace-files"),("workspace-view-toggle","workspace-view"),("workspace-evidence-toggle","workspace-tools")]:
        page.locator("#"+toggle).click();expect(page.locator("#"+panel)).to_be_visible()
        page.wait_for_function("id=>document.getElementById(id).getBoundingClientRect().x>=0",arg=panel)
        bounds=page.locator("#"+panel).bounding_box();assert bounds["x"]>=0 and bounds["x"]+bounds["width"]<=390
        page.keyboard.press("Escape")
    expect(page.locator("#page-image")).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
