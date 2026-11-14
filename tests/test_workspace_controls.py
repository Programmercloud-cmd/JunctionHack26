"""Explicit deterministic provenance/interaction fixtures, not source inference."""
import os
import pytest
from test_chat_ui_browser import chat_fixture
from test_browser_3d import scene_page
from test_sourcefirst_browser import static_server
pytestmark=pytest.mark.skipif(os.getenv('RUN_BROWSER_TESTS')!='1',reason='opt-in Chromium checks')

def test_persistent_controls_property_provenance_and_independent_overlays(static_server,scene_page):
    from playwright.sync_api import expect
    page=scene_page;doc,scene,calls,_=chat_fixture(page,static_server)
    page.get_by_role('button',name='3D model',exact=True).click()
    page.evaluate("blueprintViewer.select('window-1')")
    card=page.locator('#selection-evidence')
    expect(card).to_contain_text('Recorded as depicted in the source')
    expect(card).to_contain_text('Display assumption')
    expect(card).to_contain_text('Fixture display height')
    page.locator('#workspace-assumptions').check()
    expect(page.locator('.assumption-annotation[data-element-id="window-1"]')).to_be_visible()
    page.locator('#workspace-answer_highlights').uncheck()
    page.locator('#workspace-navigation_highlights').uncheck()
    assert page.evaluate("blueprintViewer.meshes.get('window-1').material.emissive.getHex()") == 0
    assert page.evaluate('blueprintViewer.selectedId') == 'window-1'
    assert page.evaluate('chatUI.snapshot().show_assumptions')
    page.locator('#workspace-assumptions').uncheck()
    expect(card).to_contain_text('Fixture display height')
    expect(page.locator('.assumption-annotation[data-element-id="window-1"]')).to_be_hidden()
    before=page.evaluate('blueprintViewer.getCameraState()')
    card.get_by_role('button',name='Show in original',exact=True).click()
    expect(page.locator('#evidence-overlay')).to_be_visible()
    assert page.evaluate('state.sourceSelection.bbox')==scene['elements'][0]['source']['bbox']
    page.get_by_role('button',name='3D model',exact=True).click()
    after=page.evaluate('blueprintViewer.getCameraState()')
    for field in ['position','target','up']:assert after[field]==pytest.approx(before[field],abs=1e-10)
    page.locator('#workspace-theme').select_option('dark')
    expect(page.locator('html')).to_have_attribute('data-theme','dark')
    expect(page.locator('#workspace-theme')).to_have_css('background-color', 'rgb(25, 24, 22)')
    expect(card).to_contain_text('Fixture display height')
    page.locator('#workspace-theme').select_option('light')
    page.get_by_role('button',name='Blueprints',exact=True).click()
    expect(page.locator('#evidence-overlay')).to_be_hidden()
    page.get_by_role('button',name='Return to selection',exact=True).click()
    assert page.evaluate('chatUI.snapshot().focused_id')=='window-1'
    assert not any(method=='POST' and ('chat/actions' in path or 'reconstruction' in path or 'questions' in path) for method,path,*_ in calls)


def test_property_rows_are_revision_scoped_and_proposals_are_separate(static_server,scene_page):
    from playwright.sync_api import expect
    page=scene_page;doc,scene,calls,_=chat_fixture(page,static_server)
    page.get_by_role('button',name='3D model',exact=True).click()
    page.evaluate("""()=>{state.assumptionDataRevision=state.scene.revision_id;state.assumptionRows=[{property:'display_height',label:'Supplied floor display height',value:2.4,unit:'relative',provenance:'user_provided',scope:{floor_id:'f1'},reason:'Fixture user value, not source fact'}];blueprintViewer.select('window-1')}""")
    card=page.locator('#selection-evidence');expect(card).to_contain_text('User-provided');expect(card).to_contain_text('2.4 relative')
    page.evaluate("state.assumptionDataRevision='other-revision';workspaceControls.refresh()")
    expect(card).not_to_contain_text('2.4 relative');expect(card).to_contain_text('another revision')
    page.evaluate("inspectElement(state.scene.elements.find(e=>e.id==='unresolved-window'))")
    expect(card).to_contain_text('Unresolved · no mesh');expect(card).to_contain_text('Uncertain host')
    expect(page.locator('#workspace-return-selection')).to_be_disabled()
    page.evaluate("inspectProposal({id:'fixture-proposal',kind:'proposal',host_id:'window-1',label:'Fixture decoration',note:'Not depicted'})")
    expect(card).to_contain_text('Non-factual proposal');expect(card).to_contain_text('Excluded from factual QA')
    expect(card.get_by_role('button',name='Show host in original')).to_be_visible()


def test_new_group_selection_clears_stale_focused_evidence(static_server,scene_page):
    from playwright.sync_api import expect
    page=scene_page;chat_fixture(page,static_server)
    page.get_by_role('button',name='3D model',exact=True).click()
    page.evaluate("blueprintViewer.select('window-1')")
    expect(page.locator('#selection-evidence')).to_contain_text('Fixture window-1')
    page.evaluate("chatUI.execute({type:'select',ids:['window-2'],unresolved_ids:[],deferred:false})")
    assert page.evaluate('chatUI.snapshot().focused_id') is None
    assert page.evaluate('blueprintViewer.selectedId') is None
    assert page.evaluate('state.selectedElement') is None
    assert page.evaluate('chatUI.inspection()') is None
    assert page.evaluate('chatUI.snapshot().selected_ids')==['window-2']
    expect(page.locator('#selection-evidence')).not_to_contain_text('Fixture window-1')


def test_fullscreen_and_chat_pane_resize(static_server, scene_page):
    from playwright.sync_api import expect

    page = scene_page
    chat_fixture(page, static_server)
    divider = page.get_by_role("separator", name="Resize chat pane")
    bounds = divider.bounding_box()
    x, y = bounds["x"] + bounds["width"] / 2, bounds["y"] + bounds["height"] / 2
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 150, y, steps=4)
    page.mouse.up()
    assert int(divider.get_attribute("aria-valuenow")) > 30
    divider.press("Home")
    expect(divider).to_have_attribute("aria-valuenow", "25")
    divider.press("ArrowRight")
    expect(divider).to_have_attribute("aria-valuenow", "28")

    for view, toggle in [("blueprint", None), ("3D model", "3D model")]:
        if toggle:
            page.get_by_role("button", name=toggle, exact=True).click()
        page.get_by_role("button", name=f"Full screen: {view}").click()
        page.wait_for_function("""document.fullscreenElement?.id === 'visual-workspace' ||
            document.getElementById('visual-workspace').classList.contains('workspace-expanded')""")
        page.get_by_role("button", name="Exit full screen").click()
        expect(page.get_by_role("button", name=f"Full screen: {view}")).to_be_visible()
        expect(divider).to_have_attribute("aria-valuenow", "28")
