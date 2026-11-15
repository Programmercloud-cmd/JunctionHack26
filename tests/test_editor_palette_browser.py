"""Editor palette and theme regressions through Chromium and real local APIs."""
import os

import pytest

from test_agent_e2e_browser import agent_server
from test_browser_3d import scene_page
from test_bundles_revisions import build
from test_ifc_generate import description

pytestmark=pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS")!="1",reason="opt-in browser checks")


def open_file(page,url):
    page.goto(url)
    page.locator("#home-library-list .home-file").first.click()
    page.locator("#home-library-list .home-file").first.click()
    page.wait_for_function("state.activeSessionId&&!state.sessionOpening")


@pytest.mark.parametrize("theme",["light","dark"])
def test_concept_preserves_chat_theme_and_composer_style(agent_server,scene_page,theme):
    from playwright.sync_api import expect
    url,app,document,provider=agent_server;page=scene_page
    build(app.state.documents,app.state.documents.get(document.id),description())
    page.emulate_media(color_scheme=theme)
    open_file(page,url);page.wait_for_function("state.viewer?.meshes.size>0")
    def appearance():
        return page.evaluate("""() => Object.fromEntries(['body','#chat-shell','#chat-scroll','#composer-slot','#question'].map(selector=>{
          const c=getComputedStyle(document.querySelector(selector));return [selector,[c.backgroundColor,c.color,c.padding,c.maxWidth]];
        }))""")
    baseline=appearance()
    page.locator("#workspace-concept").click()
    page.wait_for_function("chatUI.snapshot().view_mode==='concept'&&state.viewer.mode==='concept'")
    assert appearance()==baseline
    expect(page.locator("html")).to_have_attribute("data-theme",theme)
    expect(page.locator("#annotation-toggle")).not_to_be_visible()
    expect(page.locator("#workspace-fullscreen svg")).to_be_visible()
    page.locator("#question").fill("A draft stays in the selected theme")
    page.evaluate("updateControls();chatUI.onJobs(state.jobs)")
    expect(page.locator("#question")).to_be_focused()
    expect(page.locator("#question")).to_have_value("A draft stays in the selected theme")
    page.locator("#workspace-model").click()
    assert appearance()==baseline
    assert not provider["messages"]


def test_rolling_palette_parameters_saved_tag_highlight_and_fullscreen(agent_server,scene_page):
    from playwright.sync_api import expect
    from app.annotations import list_annotations
    url,app,document,provider=agent_server;page=scene_page
    open_file(page,url)
    palette=page.locator("#annotation-tools");toggle=page.locator("#annotation-toggle")
    expect(toggle).to_have_accessible_name("Open drawing tools")
    expect(page.locator("#annotation-tool-row")).not_to_be_visible()
    expect(page.locator("#annotation-parameters")).not_to_be_visible()
    expect(page.locator("#annotation-navigate")).to_have_count(0)
    content=page.locator("#workspace-content").bounding_box();initial=toggle.bounding_box()
    assert initial["x"]==pytest.approx(content["x"]+12,abs=1)
    assert initial["y"]==pytest.approx(content["y"]+12,abs=1)
    toggle.click()
    expect(page.locator("#annotation-tool-row")).to_be_visible()
    expect(toggle).to_have_attribute("aria-expanded","true")
    page.wait_for_timeout(350)
    assert toggle.bounding_box()["x"]>initial["x"]+150
    page.locator("#annotation-measure").click()
    expect(page.locator("#annotation-value")).to_be_visible()
    expect(page.locator("#annotation-unit")).to_be_visible()
    expect(page.locator("#annotation-floor")).to_be_visible()
    assert page.locator("#annotation-parameters").bounding_box()["y"]>page.locator("#annotation-tool-row").bounding_box()["y"]+40
    page.locator("#annotation-draw").click()
    expect(page.locator("#annotation-value")).not_to_be_visible()
    expect(page.locator("#annotation-label")).to_be_visible()
    page.locator("#annotation-label").fill("Entrance detail")
    bounds=page.locator("#annotation-overlay").bounding_box()
    page.mouse.move(bounds["x"]+bounds["width"]*.25,bounds["y"]+bounds["height"]*.55);page.mouse.down()
    page.mouse.move(bounds["x"]+bounds["width"]*.65,bounds["y"]+bounds["height"]*.65,steps=8);page.mouse.up()
    expect(page.locator("#annotation-attachments button")).to_have_count(1)
    mark=list_annotations(app.state.documents,document.id)[0]
    page.locator("#annotation-attachments button").click()
    page.locator("#annotation-marks").click()
    tag=page.locator("#annotation-saved button").filter(has_text="Entrance detail")
    expect(tag).to_be_visible();tag.click()
    expect(page.locator(f'#annotation-overlay [data-annotation-id="{mark["id"]}"]')).to_have_class("tag-highlight")
    expect(tag).to_have_attribute("aria-pressed","true")
    expect(tag).to_be_focused()
    page.evaluate("updateControls();chatUI.onJobs(state.jobs)")
    expect(tag).to_be_focused()
    expect(page.locator("#annotation-attachments button")).to_have_count(0)
    page.locator("#annotation-attach-saved").click()
    expect(page.locator("#annotation-attachments button")).to_have_count(1)
    page.locator("#annotation-eraser").click()
    expect(page.locator("#annotation-parameters")).not_to_be_visible()
    page.locator("#annotation-eraser").click()
    expect(page.locator("#annotation-eraser")).to_have_attribute("aria-pressed","false")
    expect(page.locator("#annotation-overlay")).not_to_have_class("drawing-active")
    toggle.click();expect(toggle).to_have_attribute("aria-expanded","false")
    fullscreen=page.locator("#workspace-fullscreen")
    expect(fullscreen.locator("svg")).to_be_visible()
    assert fullscreen.text_content()==""
    box=fullscreen.bounding_box()
    assert content["x"]+content["width"]-box["x"]-box["width"]==pytest.approx(12,abs=1)
    assert box["y"]==pytest.approx(content["y"]+12,abs=1)
    fullscreen.click();expect(fullscreen).to_have_accessible_name("Exit full screen")
    fullscreen.click();expect(fullscreen).to_have_accessible_name("Full screen: blueprint")
    assert not provider["messages"]


def test_model_tool_deselect_and_mobile_palette_fit(agent_server,scene_page):
    from playwright.sync_api import expect
    url,app,document,provider=agent_server;page=scene_page
    build(app.state.documents,app.state.documents.get(document.id),description())
    page.set_viewport_size({"width":390,"height":844})
    open_file(page,url);page.wait_for_function("state.viewer?.meshes.size>0")
    page.locator("#workspace-model").click();page.locator("#annotation-toggle").click()
    page.locator("#annotation-point").click()
    assert not page.evaluate("state.viewer.controls.enabled")
    page.locator("#annotation-point").click()
    assert page.evaluate("state.viewer.controls.enabled")
    expect(page.locator("#annotation-parameters")).not_to_be_visible()
    page.locator("#annotation-measure").click()
    expect(page.locator("#annotation-value")).to_be_visible()
    expect(page.locator("#annotation-floor")).not_to_be_visible()
    page.locator("#annotation-toggle").click()
    assert page.evaluate("state.viewer.controls.enabled")
    page.locator("#annotation-toggle").click()
    for selector in ["#annotation-tool-row","#annotation-toggle","#workspace-fullscreen"]:
        box=page.locator(selector).bounding_box()
        assert 0<=box["x"]<390 and box["x"]+box["width"]<=390
    assert page.locator("#model-pane").bounding_box()["height"]>=320
    page.locator("#workspace-blueprints").click()
    page.locator("#annotation-measure").click()
    expect(page.locator("#annotation-floor")).to_be_visible()
    parameters=page.locator("#annotation-parameters").bounding_box()
    image=page.locator("#page-image").bounding_box()
    assert image["y"]>=parameters["y"]+parameters["height"]
    assert page.locator("#drawing-pane").bounding_box()["height"]>=320
    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
    assert not provider["messages"]
