"""Source comparison and unresolved inventory: actual IFC meshes, injected interpretation."""
import os
import socket
import threading
import time

import pytest

from test_browser import FixtureProvider, upload
from test_browser_3d import scene_page, snapshot, generate_scene

pytestmark = pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS") != "1", reason="opt-in browser checks")


class SemanticFixtureProvider(FixtureProvider):
    unresolved_only = False

    def reconstruct(self, document):
        from app.building import BuildingDescription
        def region(bbox): return {"page":1,"bbox":bbox}
        def boundary(key, kind, segment):
            return {"key":key,"kind":kind,"label":key,"segment":segment,"source":region([.08,.18,.92,.72]),"thickness_segment":[],"basis":"observed","note":"Explicit source boundary"}
        def feature(kind, label, polygon):
            return {"kind":kind,"label":label,"polygon":polygon,"source":region([.1,.2,.6,.7]),"basis":"observed","note":"Footprint symbol; vertical dimensions unknown"}
        floor={"label":"Source floor","source":region([0,0,1,1]),"order":None,"order_basis":"Not shown","rotation_degrees":180,
               "orientation_basis":"Fixture rotation for original-coordinate comparison","calibration":None,"alignment":None,"measurements":[],
               "rooms":[],"boundaries":[],"openings":[],"features":[],
               "unresolved":[{"label":"Ambiguous fixture","category":"fixture","source":region([.7,.75,.9,.9]),"reason":"Symbol is too ambiguous to classify or reconstruct."}]}
        if not self.unresolved_only:
            floor["rooms"]=[{"label":"Room A","polygon":[[.1,.2],[.6,.2],[.6,.7],[.1,.7]],"basis":"observed","note":"Source room footprint","environment":"indoor"},
                {"label":"Terrace","polygon":[[.65,.2],[.9,.2],[.9,.7],[.65,.7]],"basis":"observed","note":"Open outdoor footprint","environment":"outdoor"}]
            floor["boundaries"]=[boundary("North wall","wall",[[.1,.2],[.6,.2]]),boundary("Terrace open edge","open_edge",[[.65,.2],[.9,.2]]),boundary("Terrace railing","railing",[[.9,.2],[.9,.7]])]
            floor["openings"]=[{"kind":"door","label":"North door","segment":[[.25,.2],[.35,.2]],"source":region([.24,.18,.36,.25]),"host_wall":"North wall","basis":"observed","note":"Visible gap"}]
            floor["features"]=[feature("chair","Chair",[[.2,.3],[.3,.3],[.3,.4],[.2,.4]]),feature("stairs","Stair footprint",[[.4,.3],[.5,.3],[.5,.5],[.4,.5]])]
        return BuildingDescription(floors=[floor],limitations=["Injected browser fixture; not live source interpretation."])


@pytest.fixture
def semantic_server(tmp_path,monkeypatch):
    import uvicorn
    from app.main import create_app
    monkeypatch.setenv("GEMINI_API_KEY","fixture-never-sent")
    SemanticFixtureProvider.unresolved_only=False
    app=create_app(provider_factory=SemanticFixtureProvider,storage_root=tmp_path/"uploads")
    sock=socket.socket(); sock.bind(("127.0.0.1",0))
    instance=uvicorn.Server(uvicorn.Config(app,log_level="error"))
    thread=threading.Thread(target=instance.run,kwargs={"sockets":[sock]},daemon=True); thread.start()
    deadline=time.monotonic()+5
    while not instance.started and time.monotonic()<deadline: time.sleep(.02)
    assert instance.started
    yield f"http://127.0.0.1:{sock.getsockname()[1]}"
    instance.should_exit=True; thread.join(timeout=5); sock.close()


def generate(page,server):
    page.goto(server); upload(page)
    generate_scene(page)
    page.wait_for_function("window.blueprintViewer?.data.derived === true",timeout=30000)


def test_actual_geometry_overlay_layers_clicks_unresolved_and_reopen(semantic_server,scene_page,tmp_path):
    from playwright.sync_api import expect
    page=scene_page; generate(page,semantic_server)
    scene=page.evaluate("window.blueprintViewer.data")
    assert scene["comparison"]
    expect(page.locator("#inventory-counts")).to_contain_text("1 unresolved")
    assert any(e["kind"]=="stairs" and e["representation"]=="schematic" for e in scene["elements"])
    assert len([e for e in scene["elements"] if e["kind"]=="wall"])==1
    page.locator("#show-drawing").click()
    page.locator("#comparison-details").evaluate("(details) => { details.open = true; }")
    page.locator("#show-comparison").check()
    expect(page.locator("#comparison-overlay")).to_be_visible()
    expect(page.locator("#comparison-note")).to_contain_text("assumed opening heights")
    for layer in ["spaces","walls","openings","features","unresolved"]:
        assert page.locator(f'#comparison-overlay [data-layer="{layer}"]').count()>0
    wall=next(e for e in scene["elements"] if e["kind"]=="wall")
    wall_entry=next(e for e in scene["comparison"] if e["element_id"]==wall["id"])
    assert wall_entry["cut_height"] is not None
    room=next(e for e in scene["elements"] if e["kind"]=="room")
    # The source is rotated 180° in 3D, but the actual comparison stays in its original page region.
    room_entry=next(e for e in scene["comparison"] if e["element_id"]==room["id"])
    points=[p for ring in room_entry["polygons"] for p in ring]
    assert min(p[0] for p in points)==pytest.approx(.1)
    assert max(p[0] for p in points)==pytest.approx(.6)
    page.locator('[data-comparison-layer="spaces"]').uncheck()
    assert page.locator('#comparison-overlay [data-layer="spaces"]').count()==0
    assert snapshot(page)["highlights_enabled"] and not snapshot(page)["show_assumptions"]
    page.locator("#comparison-opacity").fill("30")
    expect(page.locator("#comparison-opacity-value")).to_have_text("30%")
    chair=next(e for e in scene["elements"] if e["semantic_type"]=="chair")
    page.locator("#inventory-panel").evaluate("(details) => { details.open = true; }")
    page.locator("#inventory-details summary").click()
    expect(page.locator("#inventory-kind-counts")).to_contain_text("chair: 1")
    page.locator(f'.inventory-source-item[data-element-id="{chair["id"]}"]').click()
    expect(page.locator("#comparison-selection-name")).to_have_text("Chair")
    selected=page.locator(f'#comparison-overlay [data-element-id="{chair["id"]}"]')
    selected.click()
    expect(page.locator("#comparison-selection-name")).to_have_text("Chair")
    selected.focus(); selected.press("Enter")
    expect(page.locator("#comparison-selection-name")).to_have_text("Chair")
    page.locator("#comparison-inspect").click()
    expect(page.locator("#element-identity")).to_contain_text("schematic")
    expect(page.locator("#element-geometry-note")).to_contain_text("not source measurements")
    page.locator("#inventory-panel > summary").click()
    page.locator(".unresolved-item").click()
    expect(page.locator("#comparison-selection-name")).to_have_text("Ambiguous fixture")
    expect(page.locator("#comparison-selection-detail")).to_contain_text("Source region only")
    expect(page.locator("#evidence-overlay")).to_be_visible()
    assert page.locator("#evidence-overlay").evaluate("e=>e.style.left")=="70%"
    page.locator("#comparison-inspect").click()
    expect(page.locator("#element-geometry-note")).to_contain_text("Unresolved source item")
    original_id=scene["document_id"]
    with page.expect_download() as download: page.locator("#download-ifc").click()
    target=tmp_path/"semantic.ifc"; download.value.save_as(target)
    page.locator("#file-input").set_input_files(str(target))
    page.wait_for_function("id=>window.blueprintViewer?.data.document_id && window.blueprintViewer.data.document_id!==id",arg=original_id)
    expect(page.locator("#inventory-counts")).to_contain_text("1 unresolved")
    page.locator("#show-drawing").click()
    page.locator("#comparison-details").evaluate("(details) => { details.open = true; }")
    page.locator("#show-comparison").check()
    assert page.locator('#comparison-overlay [data-layer="unresolved"]').count()==1
    assert page.locator('#comparison-overlay [data-layer="walls"]').count()>0
    page.set_viewport_size({"width":390,"height":844})
    assert page.evaluate("document.documentElement.scrollWidth<=window.innerWidth")
    expect(page.locator("#comparison-overlay")).to_be_visible()


def test_all_unresolved_preserves_source_without_claiming_3d_success(semantic_server,scene_page):
    from playwright.sync_api import expect
    SemanticFixtureProvider.unresolved_only=True
    page=scene_page; generate(page,semantic_server)
    page.locator("#show-model").click()
    page.locator("#model-details").evaluate("(details) => { details.open = true; }")
    expect(page.locator("#no-model-geometry")).to_be_visible()
    expect(page.locator("#no-model-geometry")).to_contain_text("No 3D geometry")
    expect(page.locator("#model-canvas-container")).to_be_hidden()
    expect(page.locator("#inventory-counts")).to_have_text("0 reconstructed · 0 schematic · 1 unresolved.")
    assert snapshot(page)["mesh_count"]==0
    page.locator("#inventory-panel > summary").click()
    page.locator(".unresolved-item").click()
    expect(page.locator("#page-image")).to_be_visible()
    expect(page.locator("#evidence-overlay")).to_be_visible()
    assert page.locator('#comparison-overlay [data-layer="unresolved"]').count()==1
    assert page.locator('#comparison-overlay [data-layer="spaces"]').count()==0
