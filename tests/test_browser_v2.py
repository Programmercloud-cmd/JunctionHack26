"""Real HTTP/IFC/browser roundtrip with explicitly injected source interpretations."""
from io import BytesIO
import os
import socket
import threading
import time

import pytest
from PIL import Image, ImageDraw

from test_browser import FixtureProvider, ask
from test_browser_3d import scene_page, snapshot, generate_scene

pytestmark = pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS") != "1", reason="opt-in browser checks")


class BuildingFixtureProvider(FixtureProvider):
    calls = 0
    calibrated = False

    def reconstruct(self, document):
        from app.building import BuildingDescription
        type(self).calls += 1
        assert len(document.pages) == 2
        floors = []
        for page, label, bbox, polygon, order in [
            (1, "Ground floor", [0,0,.48,1], [[.1,.2],[.4,.2],[.4,.7],[.1,.7]], 0),
            (1, "Upper floor", [.52,0,1,1], [[.6,.2],[.9,.2],[.9,.7],[.6,.7]], 1),
            (2, "Roof diagram", [0,0,1,1], [[.1,.2],[.4,.2],[.4,.7],[.1,.7]], None),
        ]:
            region = {"page":page,"bbox":bbox}
            floors.append({"label":label,"source":region,"order":order,
                "order_basis":"Visible floor caption" if order is not None else "No floor order shown",
                "rotation_degrees":180,"orientation_basis":"Upside-down source caption",
                "calibration":{"length_m":3,"segment":polygon[:2],"source":region,"note":"Fixture dimension"} if self.calibrated else None,
                "alignment":None,"measurements":[{"label":"Ceiling height","status":"unknown","value":None,"unit":None,"source":None,"note":"No section supplied"}],
                "rooms":[{"label":f"Room {len(floors)+1}","polygon":polygon,"basis":"observed","note":"Visible room perimeter","environment":"indoor"}],"openings":[],"boundaries":[],"features":[],"unresolved":[]})
        return BuildingDescription(floors=floors,limitations=["Injected browser fixture; original drawings remain the answer source."])

    def answer(self, document, question, gate, crop=None):
        if gate.decision != "sufficient":
            return super().answer(document, question, gate, crop)
        from app.schemas import DraftAnswer, Evidence
        assert document.kind == "drawing" and len(document.pages) == 2
        room = next(e for e in document.scene.elements if e.kind == "room" and e.name == "Room 3")
        return DraftAnswer(status="answered",answer="Fixture: Room 3 is shown on page 2.",
            evidence=[Evidence(page=room.source.page,bbox=room.source.bbox,label=room.name,observation="Label visible on original drawing")],highlight_ids=[room.id])


@pytest.fixture
def building_server(tmp_path, monkeypatch):
    import uvicorn
    from app.main import create_app
    monkeypatch.setenv("GEMINI_API_KEY","fixture-never-sent")
    BuildingFixtureProvider.calls = 0
    BuildingFixtureProvider.calibrated = False
    app = create_app(provider_factory=BuildingFixtureProvider,storage_root=tmp_path / "uploads")
    sock = socket.socket(); sock.bind(("127.0.0.1",0))
    server = uvicorn.Server(uvicorn.Config(app,log_level="error"))
    thread = threading.Thread(target=server.run,kwargs={"sockets":[sock]},daemon=True); thread.start()
    deadline = time.monotonic()+5
    while not server.started and time.monotonic()<deadline: time.sleep(.02)
    assert server.started
    yield f"http://127.0.0.1:{sock.getsockname()[1]}"
    server.should_exit = True; thread.join(timeout=5); sock.close()


def upload_building(page):
    pages=[]
    for n in range(2):
        image=Image.new("RGB",(900,600),"white"); draw=ImageDraw.Draw(image)
        for x, room in [(90,"Room 1" if n==0 else "Room 3"),(540,"Room 2")]:
            draw.rectangle((x,120,x+270,420),outline="#293c33",width=10)
            draw.text((x+60,220),room,fill="#293c33")
        pages.append(image.rotate(180))
    output=BytesIO(); pages[0].save(output,format="PDF",save_all=True,append_images=pages[1:])
    page.locator("#file-input").set_input_files({"name":"three-floor-diagrams.pdf","mimeType":"application/pdf","buffer":output.getvalue()})
    page.wait_for_function("!document.getElementById('file-input').disabled && document.getElementById('page-image').naturalWidth > 0")


@pytest.mark.parametrize("calibrated",[False,True])
def test_multifloor_original_regions_explosion_and_ifc_roundtrip(building_server,scene_page,tmp_path,calibrated):
    from playwright.sync_api import expect
    page=scene_page
    BuildingFixtureProvider.calibrated=calibrated
    page.goto(building_server); upload_building(page)
    page.locator("#next-page").click()  # generation still includes every page/panel
    generate_scene(page)
    page.wait_for_function("window.blueprintViewer?.data.derived === true",timeout=30000)
    expect(page.locator("#scene-error")).to_be_hidden()
    expected_badge="Calibrated footprints · assumed heights" if calibrated else "Approximate · unscaled"
    expect(page.locator("#scene-badge")).to_have_text(expected_badge)
    if calibrated:
        expect(page.locator("#scene-summary")).not_to_contain_text("Uncalibrated diagrams preserve drawing proportions")
    else:
        expect(page.locator("#scene-summary")).to_contain_text("Uncalibrated diagrams preserve drawing proportions on each source page")
        expect(page.locator("#scene-summary")).to_contain_text("cannot establish dimensions or compare physical floor sizes")
    assert page.locator("#floor-select option").count()==4
    expect(page.locator("#layout-note")).to_contain_text("not an aligned building")
    scene=page.evaluate("window.blueprintViewer.data")
    floors=scene["floors"]; original_id=scene["document_id"]
    rooms=[e for e in scene["elements"] if e["kind"]=="room"]
    assert len(rooms)==3 and all(e["geometry"]["type"]=="mesh" for e in rooms)
    assert all(e["visible"] for e in snapshot(page)["elements"])
    expect(page.locator("#explode-floors")).to_be_checked()
    assert snapshot(page)["exploded"]
    assert any(e["display_offset_z"]>0 for e in snapshot(page)["elements"])
    page.evaluate("window.savedViewer=window.blueprintViewer;window.sourceGeometry=JSON.stringify(window.blueprintViewer.data.elements)")
    page.locator("#explode-floors").uncheck()
    assert all(e["display_offset_z"]==0 for e in snapshot(page)["elements"])
    assert snapshot(page)["highlights_enabled"]
    page.locator("#explode-floors").check()
    assert any(e["display_offset_z"]>0 for e in snapshot(page)["elements"])
    assert page.evaluate("window.sourceGeometry===JSON.stringify(window.blueprintViewer.data.elements)")
    expect(page.locator("#layout-note")).to_contain_text("adds display spacing")
    page.locator("#floor-select").select_option(floors[0]["id"])
    first_ids={e["id"] for e in scene["elements"] if e["storey_id"]==floors[0]["id"]}
    assert all(e["visible"]==(e["id"] in first_ids) for e in snapshot(page)["elements"])
    room3=next(e for e in rooms if e["name"]=="Room 3")
    page.locator("#element-select").select_option(room3["id"])
    assert snapshot(page)["floor_filter"]==room3["storey_id"]
    expect(page.locator("#element-origin")).to_contain_text("inferred")
    page.locator("#element-source").click()
    expect(page.locator("#page-label")).to_contain_text("page 2 (2/2)")
    expect(page.locator("#evidence-overlay")).to_be_visible()
    assert page.locator("#evidence-overlay").evaluate("e=>e.style.left")=="10%"
    page.locator("#show-model").click()
    page.locator("#floor-select").select_option(floors[0]["id"])
    ask(page,"Where is Room 3?")
    expect(page.locator("#answer-text")).to_have_text("Fixture: Room 3 is shown on page 2.")
    assert snapshot(page)["highlight_ids"]==[room3["id"]]
    assert snapshot(page)["floor_filter"]==floors[0]["id"]
    expect(page.locator("#highlight-note")).to_contain_text("Your view is preserved")
    assert all(e["opacity"]==.1 for e in snapshot(page)["elements"] if e["id"]!=room3["id"])
    page.locator("#show-assumptions").check()
    assert snapshot(page)["highlights_enabled"] and snapshot(page)["exploded"]
    page.locator("#highlight-answer").uncheck()
    assert snapshot(page)["show_assumptions"] and snapshot(page)["exploded"]
    page.locator(".floor-source-link").filter(has_text="Upper floor").click()
    expect(page.locator("#page-label")).to_contain_text("page 1 (1/2)")
    expect(page.locator("#evidence-overlay")).to_be_visible()
    assert page.locator("#evidence-overlay").evaluate("e=>e.style.left")=="52%"
    page.locator("#show-model").click()
    assert page.evaluate("window.savedViewer===window.blueprintViewer")
    with page.expect_download() as download:
        page.locator("#download-ifc").click()
    artifact=tmp_path / "derived.ifc"; download.value.save_as(artifact)
    assert artifact.read_bytes().startswith(b"ISO-10303-21")
    page.locator("#file-input").set_input_files(str(artifact))
    page.wait_for_function("old=>window.blueprintViewer?.data.document_id && window.blueprintViewer.data.document_id!==old",arg=original_id,timeout=30000)
    expect(page.locator("#scene-badge")).to_have_text(expected_badge)
    expect(page.locator("#explode-floors")).to_be_checked()
    if not calibrated:
        expect(page.locator("#scene-summary")).to_contain_text("Relationships across pages or independently resized diagrams remain schematic")
    assert page.evaluate("window.blueprintViewer.data.source_kind")=="image"
    assert page.evaluate("window.blueprintViewer.data.elements.map(e=>e.id)")==[e["id"] for e in scene["elements"]]
    assert BuildingFixtureProvider.calls==1
    page.locator("#element-select").select_option(room3["id"]); page.locator("#element-source").click()
    expect(page.locator("#page-label")).to_contain_text("page 2 (2/2)")
    expect(page.locator("#evidence-overlay")).to_be_visible()
    ask(page,"What is the ceiling height?")
    expect(page.locator("#result-status")).to_have_text("Missing information")
    assert snapshot(page)["highlight_ids"]==[]
    page.locator("#show-model").click(); page.locator("#floor-select").select_option("")
    page.locator("#explode-floors").check()
    page.screenshot(path=f"/tmp/junction-v2-{'calibrated' if calibrated else 'unscaled'}.png",full_page=True)
    if not calibrated:
        # Exercise provenance-only variants of the actual scene. Geometry remains
        # unchanged; incomplete or mixed legacy metadata must not promise new scaling.
        geometry=page.evaluate("JSON.stringify(window.blueprintViewer.data.elements)")
        original=page.evaluate("window.blueprintViewer.data")
        for mode in ["missing","legacy","mixed"]:
            page.evaluate("""async ({scene,mode}) => {
              const variant=structuredClone(scene);
              variant.floors.forEach((floor,index)=>{
                if (mode==='mixed' && index!==0) return;
                floor.assumptions=floor.assumptions.filter(a=>a.property!=='page_extent');
                if(mode!=='missing') floor.assumptions.push({property:'panel_extent',value:10,unit:'relative',reason:'Legacy per-panel display normalization'});
              });
              clearScene();
              await loadScene(variant);
            }""",{"scene":original,"mode":mode})
            expect(page.locator("#scene-summary")).not_to_contain_text("Uncalibrated diagrams preserve drawing proportions")
            expect(page.locator("#scene-badge")).to_have_text("Approximate · unscaled")
            assert page.evaluate("JSON.stringify(window.blueprintViewer.data.elements)")==geometry
