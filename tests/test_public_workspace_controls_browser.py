"""Locked visitor controls use saved scene/source records without inference."""
import os

import pytest

from test_browser_3d import scene_page
from test_sourcefirst_browser import setup_routes, static_server

pytestmark = pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS") != "1", reason="opt-in browser checks")


def public_model(page, url, *, native=False):
    scene = {"document_id": "b" * 64, "building_id": "b" * 64, "revision_id": "a" * 32,
             "revision_number": 1, "derived": not native, "units": "m" if native else "relative",
             "layout": "aligned", "floors": [], "elements": [], "warnings": []}
    for index, floor_id in enumerate(["ground:original", "upper:original"]):
        source = ({"kind": "ifc", "global_id": "GlobalId-" + str(index), "step_id": 21 + index}
                  if native else {"kind": "image", "page": 1, "bbox": [0, 0, 1, 1]})
        scene["floors"].append({"id": floor_id, "label": ["Ground storey", "Upper storey"][index],
                                "order": index, "source": source, "base_elevation": index * 4,
                                "reference_height": 3, "reference_height_basis": "Fixture display extent",
                                "scale_status": "known" if native else "unknown", "rotation_degrees": 0,
                                "alignment_status": "supported", "assumptions": []})
        scene["elements"].append({"id": "source-wall-" + str(index), "name": "Source wall " + str(index),
                                  "kind": "wall", "ifc_type": "IfcWall", "storey_id": floor_id,
                                  "geometry_origin": "extracted" if native else "inferred", "source": source,
                                  "properties": [], "assumptions": [],
                                  "geometry": {"type": "box", "center": [index * 2, 0, index * 4 + 1.5],
                                               "size": [1, .2, 3]}})
    document, _, calls = setup_routes(page, scene)
    document.update(public_example=True, read_only_model=True)
    if native:
        document.update(kind="ifc", filename="Original fixture.ifc", pages=[],
                        sources=[{"source_id": "c" * 64, "filename": "Original fixture.ifc", "kind": "ifc", "pages": []}])
    page.route("**/api/access", lambda route: route.fulfill(json={"public_demo": True, "can_work": False, "shared_workspace": True}))
    page.goto(url)
    page.locator("#home-library-list .home-file").first.click()
    page.locator("#home-library-list .home-file").first.click()
    page.wait_for_function("state.viewer?.meshes.size===2 && !state.sessionOpening")
    return document, scene, calls


def test_locked_native_original_record_is_visible_in_evidence_drawer(static_server, scene_page):
    from playwright.sync_api import expect
    page = scene_page
    fetched = []
    def evidence(route):
        fetched.append(route.request.url)
        route.fulfill(json={"source_kind": "ifc", "building_id": "b" * 64, "revision_id": "a" * 32,
                            "record": {"id": "source-wall-0", "name": "Supplied wall record", "ifc_type": "IfcWall",
                                       "geometry_available": True, "source": {"kind": "ifc", "global_id": "GlobalId-0", "step_id": 21},
                                       "values": {"Pset_WallCommon.FireRating": {"value": "REI 60", "provenance": "supplied"}}, "missing": []},
                            "coverage": {"catalog_complete": True}})
    # Register after the general API mock to give the source record priority.
    document, scene, calls = public_model(page, static_server, native=True)
    page.route("**/api/buildings/*/revisions/*/evidence/*", evidence)
    page.evaluate("state.viewer.select('source-wall-0')")
    page.locator("#selection-show-original").click()
    drawer = page.locator("#workspace-native-record")
    expect(drawer).to_be_visible()
    expect(drawer).to_contain_text("GlobalId GlobalId-0")
    expect(drawer).to_contain_text("STEP #21")
    expect(drawer).to_contain_text("Pset_WallCommon.FireRating: REI 60")
    expect(drawer).to_contain_text(document["revision_id"])
    expect(page.locator("#question")).not_to_be_visible()
    expect(page.locator("#chat-column")).not_to_be_visible()
    assert page.locator("#workspace-native-record [id]").count() == 0
    assert len(fetched) == 1 and "/revisions/" + scene["revision_id"] + "/" in fetched[0]
    assert all(method == "GET" for method, _, _ in calls)
    assert not any("chat" in path or "conversation" in path for _, path, _ in calls)
    page.locator("#workspace-evidence-close").click()
    expect(drawer).not_to_be_visible()
    page.locator("#workspace-evidence-toggle").click()
    expect(drawer).to_be_visible()
    assert len(fetched) == 1


@pytest.mark.parametrize("mobile", [False, True])
def test_locked_multifloor_control_filters_and_restores_without_inference(static_server, scene_page, mobile):
    from playwright.sync_api import expect
    page = scene_page
    if mobile:
        page.set_viewport_size({"width": 390, "height": 844})
    document, scene, calls = public_model(page, static_server)
    page.locator("#workspace-model").click()
    before = page.evaluate("JSON.stringify([state.document.revision_id,state.scene,state.evidenceRevision,state.sourceSelection])")
    page.locator("#workspace-view-toggle").click()
    floor = page.locator("#workspace-floor")
    expect(floor).to_be_visible()
    expect(floor.locator("option")).to_have_text(["All floors", "Ground storey", "Upper storey"])
    floor.select_option("upper:original")
    page.wait_for_function("state.viewer.floorFilter==='upper:original'")
    assert page.evaluate("state.viewer.getSnapshot().elements.map(item=>item.visible)") == [False, True]
    assert page.evaluate("chatUI.snapshot().floor_id") == "upper:original"
    floor.select_option("")
    page.wait_for_function("!state.viewer.floorFilter")
    assert page.evaluate("state.viewer.getSnapshot().elements.map(item=>item.visible)") == [True, True]
    assert page.evaluate("JSON.stringify([state.document.revision_id,state.scene,state.evidenceRevision,state.sourceSelection])") == before
    expect(page.locator("#question")).not_to_be_visible()
    bounds = page.locator("#workspace-view").bounding_box()
    assert bounds["x"] >= 0 and bounds["x"] + bounds["width"] <= page.viewport_size["width"]
    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
    assert all(method == "GET" for method, _, _ in calls)
    assert not any("chat" in path or "conversation" in path or "reconstruct" in path or "render" in path for _, path, _ in calls)


@pytest.mark.parametrize("mobile", [False, True])
@pytest.mark.parametrize("native", [False, True])
def test_manual_visible_height_clips_in_view_settings_and_persists_without_inference(static_server, scene_page, mobile, native):
    from playwright.sync_api import expect
    page=scene_page
    if mobile:page.set_viewport_size({"width":390,"height":844})
    document,scene,calls=public_model(page,static_server,native=native)
    original=page.evaluate("JSON.stringify([state.document.revision_id,state.scene])")
    page.locator("#workspace-model").click();page.locator("#workspace-view-toggle").click()
    slider=page.locator("#workspace-view #cutaway-percent");output=page.locator("#cutaway-value")
    expect(page.locator("#cutaway-percent")).to_have_count(1);expect(slider).to_be_visible();expect(slider).to_be_enabled()
    expect(slider).to_have_accessible_name("Visible height");expect(output).to_have_text("100%")
    slider.focus();slider.press("Home")
    assert page.evaluate("state.viewer.cutawayPercent")==0
    assert page.evaluate("state.viewer.getSnapshot().elements.map(element=>element.clipping_planes)")==[[0],[4]]
    slider.evaluate("input=>{input.value='40';input.dispatchEvent(new Event('input',{bubbles:true}));}")
    expect(output).to_have_text("40%")
    planes=page.evaluate("state.viewer.getSnapshot().elements.map(element=>element.clipping_planes[0])")
    assert planes==pytest.approx([1.2,5.2])
    page.locator("#workspace-floor").select_option("upper:original")
    assert page.evaluate("state.viewer.cutawayPercent")==40
    expect(output).to_have_text("40%")
    page.locator("#workspace-concept").click();page.locator("#workspace-view-toggle").click()
    expect(slider).to_be_visible();expect(output).to_have_text("40%")
    assert page.evaluate("state.viewer.concept.cutawayPercent")==40
    page.locator("#workspace-model").click();page.locator("#workspace-view-toggle").click()
    assert page.evaluate("state.viewer.floorFilter")=="upper:original"
    page.evaluate("chatUI.execute({type:'set_cutaway',percent:65})")
    expect(slider).to_have_value("65");expect(output).to_have_text("65%")
    bounds=slider.bounding_box();panel=page.locator("#workspace-view").bounding_box()
    assert bounds["x"]>=panel["x"] and bounds["x"]+bounds["width"]<=panel["x"]+panel["width"]+1
    assert bounds["x"]>=0 and bounds["x"]+bounds["width"]<=page.viewport_size["width"]
    slider.focus();slider.press("End");expect(output).to_have_text("100%")
    assert page.evaluate("state.viewer.getSnapshot().elements.every(element=>element.clipping_planes.length===0)")
    if not native:
        page.locator("#workspace-blueprints").click();page.locator("#workspace-view-toggle").click()
        expect(slider).not_to_be_visible();expect(slider).to_be_disabled()
    assert page.evaluate("JSON.stringify([state.document.revision_id,state.scene])")==original
    assert all(method=="GET" for method,_,_ in calls)
    assert not any("chat" in path or "reconstruct" in path or "render" in path for _,path,_ in calls)
    if not native:
        # A source-only Building can open the model pane without owning a model.
        source_only,_,source_calls=setup_routes(page)
        source_only.update(public_example=True,read_only_model=True)
        page.route("**/api/access",lambda route:route.fulfill(json={"public_demo":True,"can_work":False,"shared_workspace":True}))
        page.goto(static_server);page.locator("#home-library-list .home-file").first.click();page.locator("#home-library-list .home-file").first.click()
        expect(page.locator("#page-image")).to_be_visible();page.locator("#workspace-model").click();page.locator("#workspace-view-toggle").click()
        expect(page.locator("#cutaway-percent")).not_to_be_visible();expect(page.locator("#cutaway-percent")).to_be_disabled()
        assert page.evaluate("state.viewer===null&&state.scene===null")
        assert all(method=="GET" for method,_,_ in source_calls)
