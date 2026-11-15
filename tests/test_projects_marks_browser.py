"""Actual browser/API persistence for projects and mark edits; no live inference."""
import os
import base64

import pytest

from test_agent_e2e_browser import agent_server
from test_browser import source_bytes
from test_browser_3d import scene_page

pytestmark=pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS")!="1",reason="opt-in browser checks")


def dropped_files(page,files):
    return page.evaluate_handle("""files => {
      const transfer=new DataTransfer();
      for(const file of files){const bytes=Uint8Array.from(atob(file.data),char=>char.charCodeAt(0));transfer.items.add(new File([bytes],file.name,{type:'image/png'}));}
      return transfer;
    }""",[{"name":name,"data":base64.b64encode(data).decode()} for name,data in files])


def test_drop_files_on_project_row_and_files_page_preserves_target_and_blocks_invalid_edits(agent_server,scene_page):
    from playwright.sync_api import expect
    url,app,document,provider_state=agent_server;page=scene_page
    app.state.jobs.extract=lambda *args,**kwargs:[]
    target=app.state.projects.create("Drop target")
    page.goto(url)
    row=page.locator(f'tr[data-project-id="{target["id"]}:shared"]')
    transfer=dropped_files(page,[("plan.png",source_bytes()),("section.png",source_bytes()+b"drop-section")])
    row.dispatch_event("dragover",{"dataTransfer":transfer})
    expect(row).to_have_class("project-drop-active")
    row.dispatch_event("drop",{"dataTransfer":transfer})
    expect(row.locator(".project-files")).to_have_text("▤ 2")
    assert page.evaluate("state.homeProjectId==null")
    assert len(app.state.documents.get(document.id).sources)==1
    assert page.evaluate("id=>state.projects.find(p=>p.id!==id).building_ids.length",target["id"])==1
    row.locator(".project-files").click()
    expect(page.locator("#home-library")).to_be_visible()
    zone=page.locator("#project-drop-zone")
    transfer=dropped_files(page,[("elevation.png",source_bytes()+b"drop-elevation")])
    zone.dispatch_event("dragover",{"dataTransfer":transfer})
    expect(zone).to_have_class("project-drop-zone project-drop-active")
    zone.dispatch_event("drop",{"dataTransfer":transfer})
    expect(page.locator("#home-library-list tr")).to_have_count(3)
    assert len(next(p for p in page.request.get(url+"/api/buildings").json()["projects"] if p["id"]==target["id"])["building_ids"])==1
    transfer=dropped_files(page,[("bad.txt",b"not a drawing")])
    zone.dispatch_event("drop",{"dataTransfer":transfer})
    expect(page.locator("#home-library-error")).to_contain_text("Choose JPG")
    expect(page.locator("#home-library-list tr")).to_have_count(3)
    transfer=dropped_files(page,[("valid.png",source_bytes()+b"partial-drop"),("broken.png",b"not a valid image")])
    zone.dispatch_event("drop",{"dataTransfer":transfer})
    expect(page.locator("#home-library-list tr")).to_have_count(3)
    expect(page.locator("#home-library-error")).to_be_visible()
    page.evaluate("state.busy='upload';updateControls()")
    zone.dispatch_event("drop",{"dataTransfer":dropped_files(page,[("blocked.png",source_bytes()+b"blocked")])})
    expect(page.locator("#home-remove-status")).to_contain_text("Wait for the current upload")
    page.evaluate("state.busy=null;Object.assign(state.buildingScopes.find(p=>p.id===state.homeProjectId),{upload_allowed:false,upload_reason:'This Building is read-only.'});projectLibrary.refresh()")
    page.locator("#home-library").dispatch_event("drop",{"dataTransfer":transfer})
    expect(page.locator("#home-remove-status")).to_contain_text("read-only")
    assert not provider_state["messages"]


def test_project_button_labels_have_contrast_in_both_themes(agent_server,scene_page):
    url,_,_,_=agent_server;page=scene_page
    for theme in ["light","dark"]:
        page.emulate_media(color_scheme=theme);page.goto(url)
        page.wait_for_function("state.savedBuildingsLoaded")
        for selector in ["#home-new-project",".project-files",".project-rename"]:
            contrast=page.locator(selector).first.evaluate("""button=>{
              const style=getComputedStyle(button),luminance=color=>{
                const channels=color.match(/[\\d.]+/g).slice(0,3).map(value=>Number(value)/255).map(value=>value<=.04045?value/12.92:((value+.055)/1.055)**2.4);
                return channels[0]*.2126+channels[1]*.7152+channels[2]*.0722;
              };
              const a=luminance(style.color),b=luminance(style.backgroundColor);return (Math.max(a,b)+.05)/(Math.min(a,b)+.05);
            }""")
            assert contrast>=4.5,(theme,selector,contrast)
        page.locator(".project-files").first.click()
        assert page.locator("#home-projects-back").evaluate("button=>{const s=getComputedStyle(button);return s.color!==s.backgroundColor;}")


def test_projects_preview_rename_files_upload_and_resume(agent_server,scene_page):
    from playwright.sync_api import expect
    url,app,document,provider_state=agent_server;page=scene_page
    app.state.jobs.extract=lambda *args,**kwargs:[]
    page.goto(url)
    row=page.locator("#home-library-list tr").first
    expect(row.locator("img")).to_be_visible()
    row.get_by_role("button",name="Rename Building Agent fixture plan.png").click()
    editor=row.locator("input")
    editor.fill("Apartment refurbishment")
    page.evaluate("refreshSavedBuildings()")
    expect(editor).to_be_focused()
    page.keyboard.type(" 2026")
    editor.press("Enter")
    expect(page.locator("#home-library-list")).to_contain_text("Apartment refurbishment 2026")
    page.reload()
    page.get_by_role("button",name="Drawings in Apartment refurbishment 2026",exact=True).click()
    expect(page.locator("#home-library")).to_be_visible()
    expect(page.locator("#home-library-title")).to_have_text("Drawings")
    expect(page.locator("#home-project-name")).to_have_text("Apartment refurbishment 2026")
    page.locator("#home-projects-back").click()
    page.locator("#home-new-project").click()
    page.locator("#project-create-name").fill("Extension project")
    page.locator("#project-create-form").get_by_role("button",name="Create Building",exact=True).click()
    expect(page.locator("#home-project-name")).to_have_text("Extension project")
    expect(page.locator("#home-library-status")).to_contain_text("No drawings")
    page.locator("#file-input").set_input_files([
        {"name":"plan.png","mimeType":"image/png","buffer":source_bytes()},
        {"name":"section.png","mimeType":"image/png","buffer":source_bytes()+b"second-project-file"}])
    page.wait_for_function("state.busy===null")
    expect(page.locator("#home-library-list tr")).to_have_count(2)
    expect(page.locator("#home-library")).to_be_visible()
    # Grouped sources remain one shared evidence group; no misleading per-source membership removal.
    expect(page.locator(".home-remove-file")).to_have_count(0)
    page.locator("#home-library-list .home-file").filter(has_text="section.png").click()
    expect(page.locator("#details-panel")).to_be_visible()
    expected=page.evaluate("state.document.document_id")
    page.locator("#home-tab").click()
    page.locator("#home-library-list .home-file").filter(has_text="Extension project").click()
    page.locator("#home-library-list .home-file").filter(has_text="section.png").click()
    expect(page.locator("#details-panel")).to_be_visible()
    assert page.evaluate("state.document.document_id")==expected
    page.reload()
    page.locator("#home-library-list .home-file").filter(has_text="Extension project").click()
    page.locator("#home-library-list .home-file").filter(has_text="section.png").click()
    page.wait_for_function("id=>state.document?.document_id===id",arg=expected)
    assert not provider_state["messages"]


def stroke(page,start,end):
    bounds=page.locator("#annotation-overlay").bounding_box()
    page.locator("#annotation-draw").click()
    page.mouse.move(bounds["x"]+bounds["width"]*start[0],bounds["y"]+bounds["height"]*start[1]);page.mouse.down()
    page.mouse.move(bounds["x"]+bounds["width"]*end[0],bounds["y"]+bounds["height"]*end[1],steps=8);page.mouse.up()


def test_stroke_erase_undo_redo_persist_and_pan_mode(agent_server,scene_page):
    from playwright.sync_api import expect
    from app.annotations import list_annotations
    url,app,document,_=agent_server;page=scene_page
    page.goto(url);page.locator("#home-library-list .home-file").first.click();page.locator("#home-library-list .home-file").first.click()
    expect(page.locator("#annotation-overlay")).to_be_visible()
    page.locator("#annotation-toggle").click()
    stroke(page,(.55,.55),(.8,.8))
    expect(page.locator("#annotation-attachments button")).to_have_count(1)
    first=list_annotations(app.state.documents,document.id)[0]["id"]
    stroke(page,(.85,.2),(.95,.3))
    expect(page.locator("#annotation-attachments button")).to_have_count(2)
    page.locator("#annotation-undo").click()
    expect(page.locator("#annotation-attachments button")).to_have_count(1)
    page.locator("#annotation-redo").click()
    expect(page.locator("#annotation-attachments button")).to_have_count(2)
    bounds=page.locator("#annotation-overlay").bounding_box()
    page.locator("#annotation-eraser").click()
    page.mouse.move(bounds["x"]+bounds["width"]*.55,bounds["y"]+bounds["height"]*.8);page.mouse.down()
    page.mouse.move(bounds["x"]+bounds["width"]*.8,bounds["y"]+bounds["height"]*.55,steps=8);page.mouse.up()
    expect(page.locator("#annotation-attachments button")).to_have_count(1)
    assert first not in {row["id"] for row in list_annotations(app.state.documents,document.id)}
    page.locator("#annotation-undo").click()
    expect(page.locator("#annotation-attachments button")).to_have_count(2)
    assert first in {row["id"] for row in list_annotations(app.state.documents,document.id)}
    page.locator("#annotation-redo").click()
    expect(page.locator("#annotation-attachments button")).to_have_count(1)
    page.locator("#annotation-point").click()
    page.locator("#annotation-point").click()
    expect(page.locator("#annotation-status")).to_contain_text("Drawing tools are off")
    expect(page.locator("#annotation-point")).to_have_attribute("aria-pressed","false")
    page.reload();page.locator("#home-library-list .home-file").first.click();page.locator("#home-library-list .home-file").first.click()
    expect(page.locator("#annotation-overlay [data-annotation-id]")).to_have_count(1)
    page.locator("#annotation-toggle").click()
    expect(page.locator("#annotation-undo")).to_be_disabled()
    expect(page.locator("#annotation-redo")).to_be_disabled()


def test_model_eraser_restores_exact_anchor_and_point_measurement_redo_branches(agent_server,scene_page):
    from playwright.sync_api import expect
    from app.annotations import list_annotations
    from test_bundles_revisions import build
    from test_ifc_generate import description
    url,app,document,_=agent_server;page=scene_page
    build(app.state.documents,app.state.documents.get(document.id),description())
    page.goto(url);page.locator("#home-library-list .home-file").first.click();page.locator("#home-library-list .home-file").first.click();page.wait_for_function("state.viewer?.meshes.size>0")
    page.locator("#workspace-model").click();page.locator("#annotation-toggle").click();page.locator("#annotation-point").click()
    position=page.evaluate("""() => {
      const v=state.viewer,mesh=[...v.meshes.values()][0];mesh.geometry.computeBoundingSphere();
      const p=mesh.geometry.boundingSphere.center.clone();mesh.localToWorld(p);p.project(v.camera);
      const r=v.renderer.domElement.getBoundingClientRect();return {x:r.x+(p.x+1)*r.width/2,y:r.y+(1-p.y)*r.height/2};
    }""")
    page.mouse.click(position["x"],position["y"])
    expect(page.locator("#annotation-attachments button")).to_have_count(1)
    saved=list_annotations(app.state.documents,document.id)[0]
    page.locator("#annotation-eraser").click()
    assert not page.evaluate("state.viewer.controls.enabled")
    page.mouse.click(position["x"],position["y"])
    expect(page.locator("#annotation-attachments button")).to_have_count(0)
    assert page.evaluate("state.viewer.controls.enabled")
    page.locator("#annotation-undo").click()
    expect(page.locator("#annotation-attachments button")).to_have_count(1)
    assert list_annotations(app.state.documents,document.id)==[saved]
    page.locator("#workspace-blueprints").click()
    page.locator("#annotation-measure").click()
    page.locator("#annotation-value").fill("4")
    floor=page.locator("#annotation-floor option").nth(1).get_attribute("value")
    page.locator("#annotation-floor").select_option(floor)
    bounds=page.locator("#annotation-overlay").bounding_box()
    page.mouse.move(bounds["x"]+bounds["width"]*.6,bounds["y"]+bounds["height"]*.7);page.mouse.down()
    page.mouse.move(bounds["x"]+bounds["width"]*.9,bounds["y"]+bounds["height"]*.7,steps=5);page.mouse.up()
    expect(page.locator("#annotation-attachments button")).to_have_count(2)
    page.locator("#annotation-undo").click()
    expect(page.locator("#annotation-attachments button")).to_have_count(1)
    page.locator("#annotation-redo").click()
    expect(page.locator("#annotation-attachments button")).to_have_count(2)
    page.locator("#annotation-undo").click()
    expect(page.locator("#annotation-attachments button")).to_have_count(1)
    page.locator("#annotation-point").click();page.locator("#annotation-overlay").click(position={"x":bounds["width"]*.8,"y":bounds["height"]*.8})
    expect(page.locator("#annotation-attachments button")).to_have_count(2)
    expect(page.locator("#annotation-redo")).to_be_disabled()
