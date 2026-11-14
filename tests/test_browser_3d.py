"""Real browser/HTTP/IFC geometry acceptance; all inference is explicitly injected.

These fixtures exercise provenance and rendering, not provider model quality.
"""
import os
from pathlib import Path
import socket
import threading
import time

import pytest

from test_browser import FixtureProvider, ask, upload

pytestmark = pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS") != "1", reason="opt-in browser checks")
SAMPLE = Path(os.getenv("IFC_SAMPLE", "/home/jcb/Downloads/junction-dataset-preview/data/ifc_bench/duplex_arc.ifc"))


class SceneFixtureProvider(FixtureProvider):
    reconstruction_calls = 0

    def reconstruct(self, document, page_number=None):
        from app.building import BuildingDescription
        type(self).reconstruction_calls += 1
        return BuildingDescription(floors=[{
            "label":"Source floor", "source":{"page":1,"bbox":[0,0,1,1]},
            "order":None,"order_basis":"No floor order shown","rotation_degrees":0,
            "orientation_basis":"Upright labels","calibration":None,"alignment":None,
            "measurements":[],"openings":[],"boundaries":[],"features":[],"unresolved":[],"rooms":[
                {"label":"Room A","polygon":[[.1,.2],[.6,.2],[.6,.7],[.1,.7]],"basis":"observed","note":"Fixture source perimeter","environment":"indoor"},
                {"label":"Room B","polygon":[[.65,.2],[.9,.2],[.9,.7],[.65,.7]],"basis":"observed","note":"Fixture source perimeter","environment":"indoor"},
            ],
        }],limitations=[])

    def answer(self, document, question, gate, crop=None):
        if document.kind == "ifc":
            raise AssertionError("IFC whole-model counts must be calculated from source, not a generated answer")
        if gate.decision != "sufficient" or not document.scene:
            return super().answer(document, question, gate, crop)
        from app.schemas import DraftAnswer, Evidence
        room = next(e for e in document.scene.elements if e.kind == "room")
        bbox = [.01,.01,.99,.99] if "unmapped" in question else room.source.bbox
        return DraftAnswer(status="answered", answer="Fixture: Room A is shown on this plan.",
            evidence=[Evidence(page=room.source.page, bbox=bbox, label="Room A", observation="Room A source footprint")],
            highlight_ids=[room.id])


@pytest.fixture
def scene_server(tmp_path, monkeypatch):
    import uvicorn
    from app.main import create_app
    monkeypatch.setenv("GEMINI_API_KEY", "fixture-never-sent")
    SceneFixtureProvider.reconstruction_calls = 0
    app = create_app(provider_factory=SceneFixtureProvider, storage_root=tmp_path / "uploads")
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    instance = uvicorn.Server(uvicorn.Config(app, log_level="error"))
    thread = threading.Thread(target=instance.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not instance.started and time.monotonic() < deadline:
        time.sleep(.02)
    assert instance.started
    yield f"http://127.0.0.1:{port}"
    instance.should_exit = True
    thread.join(timeout=5)
    sock.close()


@pytest.fixture
def scene_page():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
        page = browser.new_page(viewport={"width":1440,"height":1100})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        yield page
        browser.close()
        assert not errors


def snapshot(page):
    return page.evaluate("window.blueprintViewer.getSnapshot()")


def generate_scene(page):
    """Wait for automatic interpretation, then explicitly request optional 3D."""
    page.wait_for_function("window.blueprintViewer?.data.derived || (state.document && !state.busy && !state.reconstructionSubmitting)")
    page.wait_for_function("!state.jobs.some(j=>j.kind==='extraction'&&!terminalJob(j))",timeout=30000)
    ask(page, "Show model")
    page.wait_for_function("window.blueprintViewer?.data.derived===true",timeout=30000)
    page.wait_for_function("!state.jobs.some(j=>j.kind==='reconstruction'&&!terminalJob(j))",timeout=30000)
    try:
        page.wait_for_function("chatUI.snapshot().view_mode==='model'")
    except Exception:
        pytest.fail(str(page.evaluate("({workspace:chatUI.snapshot(),jobs:state.jobs.map(j=>({status:j.status,message:j.message})),chat:document.querySelector('#chat-log').innerText})")))


def control(page, question):
    """Exercise a visible chat command and wait for intent dispatch to finish."""
    from playwright.sync_api import expect
    ask(page, question)
    expect(page.locator('#chat-log [data-entry^="routing:"]').filter(has=page.get_by_text("Interpreting your request…", exact=True))).to_have_count(0)


def action(page, *actions):
    """Typed intent fixture entered through chat; the real router validates it."""
    import json
    control(page, "Fixture control: " + json.dumps(actions))


def focus_element(page, identity):
    """Use the visible saved inventory to focus a source-linked object."""
    name = page.evaluate("id=>state.scene.elements.find(item=>item.id===id).name", identity)
    control(page, "Inspect model inventory")
    row = page.locator("#chat-log .chat-inventory-row").filter(has=page.get_by_text(name, exact=True)).last
    row.get_by_role("button", name="Focus", exact=True).click()


def test_completed_model_waits_for_existing_scene_poll(scene_server, scene_page):
    """A complete job is not a missing-model failure while its scene GET waits."""
    from playwright.sync_api import expect
    page = scene_page
    page.goto(scene_server)
    upload(page)
    page.wait_for_function("!state.jobs.some(j=>j.kind==='extraction'&&!terminalJob(j))")
    pending = []
    page.route("**/api/documents/*/scene", lambda route: pending.append(route))
    ask(page, "Show model")
    page.wait_for_function("state.jobs.some(j=>j.kind==='reconstruction'&&j.status==='complete')&&state.pollingEpoch===state.epoch")
    assert len(pending) == 1
    # Let the existing 250ms model-wait loop observe the complete job twice.
    page.wait_for_timeout(600)
    expect(page.locator("#chat-log")).not_to_contain_text("completed without renderable model geometry")
    assert page.evaluate("state.scene===null")
    assert len(pending) == 1
    pending[0].continue_()
    page.wait_for_function("chatUI.snapshot().view_mode==='model'&&state.scene!==null")
    expect(page.locator("#model-canvas-container canvas")).to_be_visible()
    assert SceneFixtureProvider.reconstruction_calls == 1


def test_completed_job_without_scene_reports_absence_after_poll_settles(scene_server, scene_page):
    """An explicitly missing scene is still an error once metadata has settled."""
    from playwright.sync_api import expect
    page = scene_page
    page.goto(scene_server)
    upload(page)
    page.wait_for_function("!state.jobs.some(j=>j.kind==='extraction'&&!terminalJob(j))")
    building = page.evaluate("state.document.building_id")

    def source_only_metadata(route):
        response = route.fetch()
        payload = response.json()
        payload.update(has_scene=False, scene_url=None, geometry_revision_id=None)
        route.fulfill(response=response, json=payload)

    page.route(f"**/api/buildings/{building}", source_only_metadata)
    ask(page, "Show model")
    expect(page.locator("#chat-log")).to_contain_text("completed without renderable model geometry", timeout=15000)
    assert page.evaluate("state.scene===null&&state.pollingEpoch===null")
    assert SceneFixtureProvider.reconstruction_calls == 1


@pytest.mark.skipif(not SAMPLE.exists(), reason="External duplex IFC preview not available")
def test_real_ifc_orbit_counts_highlights_source_and_scene_reuse(scene_server, scene_page):
    from playwright.sync_api import expect
    page = scene_page
    scene_requests = []
    page.on("request", lambda req: scene_requests.append(req.method) if req.url.endswith("/scene") else None)
    page.goto(scene_server)
    page.locator("#file-input").set_input_files(str(SAMPLE))
    page.locator("#home-library-list button").first.click()
    page.wait_for_function("window.blueprintViewer?.getSnapshot().mesh_count > 200", timeout=90000)
    page.locator("#chat-log").get_by_role("button", name="Open saved model", exact=True).click()
    expect(page.locator("#workspace-title")).to_have_text("Saved model · interpretation")
    assert page.evaluate("state.scene.units") == "m"
    assert snapshot(page)["up_axis"] == [0,0,1]
    canvas = page.locator("#model-canvas-container canvas")
    canvas.scroll_into_view_if_needed()
    before = snapshot(page)["camera_position"]
    bounds = canvas.bounding_box()
    page.mouse.move(bounds["x"] + bounds["width"]*.45, bounds["y"] + bounds["height"]*.55)
    page.mouse.down()
    page.mouse.move(bounds["x"] + bounds["width"]*.65, bounds["y"] + bounds["height"]*.6, steps=12)
    page.mouse.up()
    page.wait_for_function("old => window.blueprintViewer.getSnapshot().camera_position.some((x,i)=>Math.abs(x-old[i]) > .01)", arg=before)
    control(page, "Reset model view")
    page.evaluate("window.savedViewer = window.blueprintViewer")

    ask(page, "How many windows are in this IFC model?")
    expect(page.locator("#chat-log .chat-answer").last).to_contain_text("24 windows are recorded in the uploaded IFC model.")
    current = snapshot(page)
    assert len(current["highlight_ids"]) == 24
    assert all(e["opacity"] == .1 for e in current["elements"] if e["id"] not in current["highlight_ids"])
    assert page.locator("#chat-log .chat-answer").last.locator(".chat-citation").count() == 24

    # Project real triangle centroids, then exercise pointer picking/raycasting.
    canvas.scroll_into_view_if_needed()
    candidates = page.evaluate("""() => {
      const v = window.blueprintViewer, rect = v.renderer.domElement.getBoundingClientRect();
      const points = [];
      for (const id of v.highlightIds) {
        const mesh = v.meshes.get(id); if (!mesh) continue;
        const positions = mesh.geometry.attributes.position, index = mesh.geometry.index;
        const center = mesh.position.clone().set(0,0,0);
        for (let i=0;i<3;i++) center.add(mesh.position.clone().fromBufferAttribute(positions,index.getX(i)));
        center.multiplyScalar(1/3).applyMatrix4(mesh.matrixWorld).project(v.camera);
        if (Math.abs(center.x)<.95 && Math.abs(center.y)<.95 && center.z<1) points.push({x:rect.x+(center.x+1)*rect.width/2,y:rect.y+(1-center.y)*rect.height/2});
      } return points;
    }""")
    assert candidates, "Expected at least one window triangle within the camera view"
    for point in candidates:
        page.mouse.click(point["x"],point["y"])
        if snapshot(page)["selected_id"]:
            break
    selected = snapshot(page)["selected_id"]
    assert selected in current["highlight_ids"], "Click should select an actual highlighted IFC window"
    page.locator('#chat-log [data-entry="focused-object"]').get_by_role("button", name="Original source", exact=True).click()
    expect(page.locator("#chat-log .native-record-inspector").last).to_contain_text(selected)
    expect(page.locator("#chat-log .native-record-inspector").last).to_contain_text("STEP #")
    expect(page.locator("#chat-log")).to_contain_text("Original supplied IFC record")

    control(page, "Hide answer highlights")
    off = snapshot(page)
    assert off["highlights_enabled"] is False
    assert all(e["opacity"] != .1 for e in off["elements"])
    control(page, "Show assumptions")
    assert snapshot(page)["show_assumptions"] is True
    assert snapshot(page)["highlights_enabled"] is False
    control(page, "Show answer highlights")
    ask(page, "How many rooms are in this IFC model?")
    expect(page.locator("#chat-log .chat-answer").last).to_contain_text("21 spaces (IfcSpace) are recorded in the uploaded IFC model.")
    rooms = snapshot(page)
    assert len(rooms["highlight_ids"]) == 21
    assert all(e["visible"] for e in rooms["elements"] if e["id"] in rooms["highlight_ids"])
    assert page.evaluate("window.savedViewer === window.blueprintViewer")
    assert scene_requests == ["GET"]
    page.locator("#chat-log .chat-answer").last.locator(".chat-citation").first.click()
    expect(page.locator("#chat-log .native-record-inspector").last).to_contain_text(rooms["highlight_ids"][0])
    page.screenshot(path="/tmp/junction-ifc-acceptance.png", full_page=True)


def test_image_model_assumptions_source_mapping_and_reuse(scene_server, scene_page):
    from playwright.sync_api import expect
    page = scene_page
    scene_requests = []
    page.on("request", lambda req: scene_requests.append(req.method) if req.url.endswith("/scene") else None)
    page.goto(scene_server)
    upload(page)
    generate_scene(page)
    page.wait_for_function("window.blueprintViewer?.getSnapshot().mesh_count > 0", timeout=30000)
    assert page.evaluate("state.scene.units") == "relative"
    assert SceneFixtureProvider.reconstruction_calls == 1
    page.evaluate("window.savedViewer = window.blueprintViewer")
    ask(page, "Which room is Room A?")
    expect(page.locator("#chat-log .chat-answer").last).to_contain_text("Fixture: Room A is shown on this plan.")
    current = snapshot(page)
    assert len(current["highlight_ids"]) == 1
    assert all(e["opacity"] == .1 for e in current["elements"] if e["id"] not in current["highlight_ids"])
    control(page, "Inspect model inventory")
    page.locator("#chat-log .chat-inventory-row").filter(has_text="Room A").get_by_role("button", name="Focus", exact=True).click()
    expect(page.locator('#chat-log [data-entry="focused-object"]')).to_contain_text("not measured source evidence")
    control(page, "Inspect assumptions")
    expect(page.locator("#chat-log .chat-assumption-row").filter(has_text="display_assumption").first).to_be_visible()
    page.locator('#chat-log [data-entry="focused-object"]').get_by_role("button", name="Original source", exact=True).click()
    expect(page.locator("#evidence-overlay")).to_be_visible()
    expect(page.locator("#viewer-caption")).to_contain_text("Saved source region")
    control(page, "Show model")
    control(page, "Show assumptions")
    assert snapshot(page)["show_assumptions"] is True
    assert snapshot(page)["highlights_enabled"] is True
    ask(page, "What is the actual ceiling height?")
    expect(page.locator("#chat-log .chat-answer").last).to_contain_text("Insufficient source evidence")
    assert snapshot(page)["highlight_ids"] == []
    assert page.evaluate("state.scene.units") == "relative"
    ask(page, "unmapped room evidence")
    expect(page.locator("#chat-log .chat-answer").last).to_contain_text("Fixture: Room A is shown on this plan.")
    assert snapshot(page)["highlight_ids"] == []
    page.locator("#chat-log .chat-answer").last.locator("summary").click()
    expect(page.locator("#chat-log .chat-answer").last).to_contain_text("no reliable 3D mapping")
    assert page.evaluate("window.savedViewer === window.blueprintViewer")
    assert scene_requests == ["GET"]
    assert SceneFixtureProvider.reconstruction_calls == 1
    page.set_viewport_size({"width":390,"height":844})
    page.locator("#model-canvas-container canvas").scroll_into_view_if_needed()
    control(page, "Reset model view")
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    assert page.evaluate("""() => {
      const v=window.blueprintViewer;
      for (const x of [v.bounds.min.x,v.bounds.max.x])
        for (const y of [v.bounds.min.y,v.bounds.max.y])
          for (const z of [v.bounds.min.z,v.bounds.max.z]) {
            const point=v.camera.position.clone().set(x,y,z).project(v.camera);
            if (Math.abs(point.x)>1 || Math.abs(point.y)>1) return false;
          }
      return true;
    }""")
    page.screenshot(path="/tmp/junction-image-acceptance.png", full_page=True)
