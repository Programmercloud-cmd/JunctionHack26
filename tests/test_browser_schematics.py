"""Display-only unresolved annotations with actual IFC geometry and fake inference."""
import os
import re
import socket
import threading
import time

import pytest

from test_browser import ask, upload
from test_browser_3d import scene_page, snapshot, generate_scene, control, action
from test_browser_v3 import SemanticFixtureProvider

pytestmark=pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS")!="1",reason="opt-in browser checks")


class AnnotationProvider(SemanticFixtureProvider):
    def reconstruct(self,document):
        from app.building import BuildingDescription, UnresolvedDescription
        description=super().reconstruct(document)
        first=description.floors[0]
        for item in first.features+first.boundaries:
            points=item.polygon if hasattr(item,"polygon") else item.segment
            xs=[p[0] for p in points];ys=[p[1] for p in points]
            item.source.bbox=[max(0,min(xs)-.005),max(0,min(ys)-.005),min(1,max(xs)+.005),min(1,max(ys)+.005)]
        first.unresolved.append(UnresolvedDescription(label="Unlocated source feature",category="other",source=first.source,
            reason="Unlocalized: only the coarse floor source region is available."))
        second=first.model_copy(deep=True);second.label="Second floor"
        second.source.page=2
        for item in second.boundaries+second.openings+second.features+second.unresolved:
            item.source.page=2
        return BuildingDescription(floors=[first,second],limitations=description.limitations)

    def answer(self,document,question,gate,crop=None):
        if gate.decision!="sufficient":return super().answer(document,question,gate,crop)
        from app.schemas import DraftAnswer,Evidence
        room=next(e for e in document.scene.elements if e.kind=="room" and e.source.page==2)
        return DraftAnswer(status="answered",answer="Fixture: Room A on page 2.",evidence=[Evidence(page=2,bbox=room.source.bbox,label=room.name,observation="Fixture original room region")],highlight_ids=[room.id])


@pytest.fixture
def annotation_server(tmp_path,monkeypatch):
    import uvicorn
    from app.main import create_app
    monkeypatch.setenv("AI_PROVIDER","gemini");monkeypatch.setenv("GEMINI_API_KEY","fixture-never-sent")
    AnnotationProvider.unresolved_only=False
    app=create_app(provider_factory=AnnotationProvider,storage_root=tmp_path/"uploads")
    sock=socket.socket();sock.bind(("127.0.0.1",0))
    server=uvicorn.Server(uvicorn.Config(app,log_level="error"))
    thread=threading.Thread(target=server.run,kwargs={"sockets":[sock]},daemon=True);thread.start()
    deadline=time.monotonic()+5
    while not server.started and time.monotonic()<deadline:time.sleep(.02)
    assert server.started
    yield f"http://127.0.0.1:{sock.getsockname()[1]}"
    server.should_exit=True;thread.join(timeout=5);sock.close()


def test_unresolved_annotations_preserve_geometry_highlights_and_source(annotation_server,scene_page,tmp_path):
    from playwright.sync_api import expect
    page=scene_page;page.goto(annotation_server);upload(page,pdf=True)
    generate_scene(page)
    page.wait_for_function("window.blueprintViewer?.data.derived===true",timeout=30000)
    scene=page.evaluate("window.blueprintViewer.data")
    unresolved=[e for e in scene["elements"] if e["representation"]=="unresolved"]
    assert len(unresolved)==4
    initial=snapshot(page)
    assert initial["mesh_count"]==len([e for e in scene["elements"] if e["geometry"]])
    assert len(initial["annotations"])==4
    assert all(e["id"] not in [m["id"] for m in initial["elements"]] for e in unresolved)
    expect(page.locator("#unresolved-model-count")).to_have_text("4 unresolved source items")
    assert len([a for a in initial["annotations"] if a["floor_level"]])==2
    page.evaluate("window.annotationGeometry=JSON.stringify(window.blueprintViewer.data.elements);window.savedViewer=window.blueprintViewer")
    # Raised initial view reveals interiors without changing model coordinates.
    assert page.evaluate("""() => {const v=window.blueprintViewer,d=v.camera.position.clone().sub(v.controls.target);return d.z/Math.hypot(d.x,d.y)>1;}""")
    floor=scene["floors"][0]
    action(page,{"type":"set_floor","floor_id":floor["id"]})
    expect(page.locator("#unresolved-model-count")).to_have_text("2 unresolved source items on this floor")
    visible=[a for a in snapshot(page)["annotations"] if a["visible"]]
    assert len(visible)==2 and all(a["floor_id"]==floor["id"] for a in visible)
    localized=page.locator('.unresolved-annotation[data-annotation-kind="source-region"]:visible')
    expect(localized).to_have_attribute("aria-label",re.compile("not model geometry"))
    localized.click()
    expect(page.locator("#page-label")).to_contain_text("page 1 (1/2)")
    expect(page.locator("#comparison-selection-detail")).to_contain_text("Symbol is too ambiguous")
    expect(page.locator("#evidence-overlay")).to_be_visible()
    assert page.locator("#evidence-overlay").evaluate("el=>el.style.left")=="70%"
    assert snapshot(page)["highlight_ids"]==[]
    control(page,"Show model")
    coarse=page.locator('.unresolved-annotation[data-annotation-kind="floor"]:visible')
    coarse.focus();coarse.press("Enter")
    expect(page.locator("#comparison-selection-detail")).to_contain_text("no precise object location or geometry")
    expect(page.locator("#comparison-inspect")).to_be_hidden()
    control(page,"Show model");action(page,{"type":"set_floor"})
    action(page,{"type":"set_separation","enabled":False})
    assert not snapshot(page)["exploded"]
    action(page,{"type":"set_separation","enabled":True})
    assert snapshot(page)["exploded"]
    assert page.evaluate("window.annotationGeometry===JSON.stringify(window.blueprintViewer.data.elements)")
    ask(page,"Where is Room A?")
    expect(page.locator("#chat-log .chat-answer").last).to_contain_text("Fixture: Room A on page 2.")
    answer=snapshot(page)
    assert len(answer["highlight_ids"])==1
    assert all(m["opacity"]==.1 for m in answer["elements"] if m["id"] not in answer["highlight_ids"])
    assert all(e["id"] not in answer["highlight_ids"] for e in unresolved)
    assert all(a["visible"] for a in answer["annotations"])
    control(page,"Show assumptions")
    assert snapshot(page)["highlight_ids"]==answer["highlight_ids"]
    control(page,"Hide answer highlights")
    assert snapshot(page)["show_assumptions"]
    # Even a bad display API request cannot turn an unresolved annotation into a mesh highlight.
    page.evaluate("id=>window.blueprintViewer.setHighlights([id],true)",unresolved[0]["id"])
    assert snapshot(page)["highlight_ids"]==[]
    assert page.evaluate("window.annotationGeometry===JSON.stringify(window.blueprintViewer.data.elements)")
    with page.expect_download() as download:action(page,{"type":"download_ifc"})
    artifact=tmp_path/"annotated.ifc";download.value.save_as(artifact)
    original_id=scene["document_id"]
    page.locator("#file-input").set_input_files(str(artifact))
    page.wait_for_function("id=>window.blueprintViewer?.data.document_id&&window.blueprintViewer.data.document_id!==id",arg=original_id)
    assert page.locator(".model-annotations").count()==1
    assert page.locator(".unresolved-annotation").count()==4
    assert page.evaluate("window.savedViewer.annotations.length")==0
    assert page.evaluate("window.blueprintViewer.data.elements")==scene["elements"]
    page.screenshot(path="/tmp/junction-schematic-annotations.png",full_page=True)


def test_all_unresolved_keeps_source_notice_without_fake_model(annotation_server,scene_page):
    from playwright.sync_api import expect
    AnnotationProvider.unresolved_only=True
    page=scene_page;page.goto(annotation_server);upload(page,pdf=True)
    generate_scene(page)
    page.wait_for_function("window.blueprintViewer?.data.derived===true")
    expect(page.locator("#no-model-geometry")).to_be_visible()
    expect(page.locator("#model-canvas-container")).to_be_hidden()
    expect(page.locator("#unresolved-model-count")).to_have_text("4 unresolved source items")
    assert snapshot(page)["mesh_count"]==0
    control(page,"Inspect model inventory")
    source=page.locator("#chat-log .chat-inventory-row").filter(has_text="Ambiguous fixture").first.get_by_role("button",name="Original evidence",exact=True)
    source.focus();source.press("Enter")
    expect(page.locator("#page-image")).to_be_visible()
    expect(page.locator("#evidence-overlay")).to_be_visible()
