"""Real browser -> FastAPI -> durable bundle tests, using explicit synthetic providers."""
import os
import socket
from threading import Event, Thread
import time

import pytest

from app.review_schema import AnswerReview
from app.schemas import DraftAnswer, Usage
from test_browser import source_bytes, browser_page
from test_ifc_generate import description

pytestmark = pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS") != "1", reason="opt-in browser checks")


class AgentBrowserProvider:
    def __init__(self, state):
        self.state = state
        self.usage = Usage()

    def route_agent(self, message, context):
        self.state["messages"].append(message)
        return {"tool": "render" if "render" in message.lower() else "technical_basic" if "marked" in message.lower() else "conversation",
                "evidence_scope": "sources_only"}

    def converse_agent(self, message, context):
        return {"message": "Fixture conversation is available without a file.", "ui_request": None}

    def answer_agent(self, document, question):
        self.state["question_annotations"] = document.conversation_context.get("user_annotations", [])
        return {"draft": DraftAnswer(status="answered", answer="Fixture: the marked original page depicts a room.",
            evidence=[{"page": 1, "bbox": [.1, .2, .7, .8], "label": "Fixture room", "observation": "Synthetic original room footprint"}]),
            "clarification": None, "ui_request": None}

    def review_answer(self, *args, **kwargs):
        return AnswerReview(decision="supported")

    def revise_answer(self, *args, **kwargs):
        raise AssertionError("The supported synthetic answer needs no correction")

    def gate(self, *args, **kwargs):
        raise AssertionError("The agent product path must never preflight source sufficiency")

    def resolve_intent(self, *args, **kwargs):
        raise AssertionError("The agent product path must preserve the original message")

    def render_candidate(self, document, **kwargs):
        from app.review_schema import DescriptionPatch
        return DescriptionPatch(base_revision_id=document.revision_id) if document.description else description()

    def review_render(self, document, **kwargs):
        if self.state["pause"]:
            self.state["entered"].set()
            assert self.state["release"].wait(20)
        return {"candidate_supported": True, "satisfied": True, "summary": "Synthetic independent browser reviewer", "issues": []}

    def close(self):
        pass


@pytest.fixture
def agent_server(tmp_path, monkeypatch):
    import uvicorn
    from app.bundles import BuildingStore
    from app.identities import assign_identities
    from app.main import create_app
    from app.reasoning import build_reasoning
    root = tmp_path / "store"
    store = BuildingStore(root)
    original = store.add(source_bytes(), "Agent fixture plan.png")
    candidate = store.prepare(original)
    candidate.description = assign_identities(candidate, description())
    candidate.interpretation_status = "complete"
    candidate.reasoning = build_reasoning(candidate)
    document = store.commit(candidate, original.revision_id, status="interpreted")
    store.close()
    monkeypatch.setenv("GEMINI_API_KEY", "fixture-never-sent")
    state = {"messages": [], "question_annotations": [], "pause": False, "entered": Event(), "release": Event()}
    app = create_app(provider_factory=lambda: AgentBrowserProvider(state), storage_root=root)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    instance = uvicorn.Server(uvicorn.Config(app, log_level="error"))
    thread = Thread(target=instance.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not instance.started and time.monotonic() < deadline:
        time.sleep(.02)
    assert instance.started
    try:
        yield f"http://127.0.0.1:{port}", app, document, state
    finally:
        state["release"].set()
        instance.should_exit = True
        thread.join(5)
        sock.close()


def test_document_free_conversation_uses_only_new_chat_endpoint(agent_server, browser_page):
    from playwright.sync_api import expect
    url, app, document, state = agent_server
    page = browser_page
    submitted = []
    page.on("request", lambda request: submitted.append(request.url) if request.method == "POST" else None)
    page.goto(url)
    page.locator("#home-new-project").click()
    page.locator("#project-create-name").fill("Conversation project")
    page.locator("#project-create-form button[type=submit]").click()
    page.locator("#new-project-chat").click()
    page.locator("#question").fill("Hello there")
    page.locator("#ask-button").click()
    expect(page.locator("#chat-log")).to_contain_text("Fixture conversation is available without a file.")
    assert state["messages"] == ["Hello there"]
    assert any(url.endswith("/api/chat") for url in submitted)
    assert not any(url.endswith(("/api/chat/actions", "/api/questions", "/api/ask")) for url in submitted)


def test_blueprint_measurement_to_chat_render_model_mark_and_stop(agent_server, browser_page):
    from playwright.sync_api import expect
    from app.annotations import list_annotations
    url, app, document, state = agent_server
    page = browser_page
    page.goto(url)
    page.locator("#home-library-list").get_by_role("button", name="Agent fixture plan.png", exact=True).click()
    page.locator("#home-library-list").get_by_role("button", name="Agent fixture plan.png", exact=True).click()
    expect(page.locator("#page-image")).to_be_visible()
    floor_id = document.description.floors[0].persistent_id
    page.wait_for_function("id => Array.from(document.getElementById('annotation-floor').options).some(o=>o.value===id)", arg=floor_id)
    page.locator("#annotation-toggle").click()
    page.locator("#annotation-measure").click()
    page.locator("#annotation-value").fill("6")
    page.locator("#annotation-unit").select_option("m")
    page.locator("#annotation-floor").select_option(floor_id)
    bounds = page.locator("#annotation-overlay").bounding_box()
    with page.expect_response(f"**/api/buildings/{document.id}/annotations") as saved:
        page.mouse.move(bounds["x"] + bounds["width"] * .6, bounds["y"] + bounds["height"] * .7)
        page.mouse.down()
        page.mouse.move(bounds["x"] + bounds["width"] * .9, bounds["y"] + bounds["height"] * .7, steps=6)
        page.mouse.up()
    assert saved.value.ok, saved.value.text()
    mark = saved.value.json()
    expect(page.locator("#annotation-attachments")).to_contain_text("6 m")
    page.locator("#question").fill("What is marked on this blueprint?")
    page.locator("#ask-button").click()
    expect(page.locator("#chat-log .chat-answer").last).to_contain_text("Fixture: the marked original page depicts a room.")
    # Source-only worker sees a pointer, not the numerical value as an original fact.
    assert state["question_annotations"][0]["id"] == mark["id"]
    assert "value" not in state["question_annotations"][0]
    page.locator("#question").fill("Render the marked blueprint.")
    page.locator("#ask-button").click()
    page.wait_for_function("state.jobs.some(j=>j.kind==='render'&&j.status==='complete') && state.document?.review_status==='render_consensus'", timeout=20000)
    saved_document = app.state.documents.get(document.id)
    assert saved_document.description.floors[0].calibration.provenance == "user_provided"
    assert saved_document.description.floors[0].calibration.length_m == 6
    assert saved_document.source_bytes == source_bytes()
    page.locator("#workspace-model").click()
    page.wait_for_function("window.blueprintViewer?.meshes.size > 0")
    page.locator("#annotation-point").click()
    screen = page.evaluate("""async () => {
      const THREE = await import('three'), viewer = window.blueprintViewer;
      const mesh = [...viewer.meshes.values()][0]; mesh.geometry.computeBoundingSphere();
      const point = mesh.geometry.boundingSphere.center.clone().applyMatrix4(mesh.matrixWorld).project(viewer.camera);
      const rect = viewer.renderer.domElement.getBoundingClientRect();
      return {x:rect.x+(point.x+1)*rect.width/2, y:rect.y+(1-point.y)*rect.height/2};
    }""")
    with page.expect_response(f"**/api/buildings/{document.id}/annotations") as model_saved:
        page.mouse.click(screen["x"], screen["y"])
    assert model_saved.value.ok, model_saved.value.text()
    model_mark = model_saved.value.json()
    assert model_mark["space"] == "model" and len(model_mark["points"][0]) == 3
    assert model_mark["revision_id"] == saved_document.revision_id
    assert model_mark["object_id"] in {e.id for e in saved_document.scene.elements}
    expect(page.locator(f'#model-annotation-overlay [data-annotation-id="{model_mark["id"]}"]')).to_be_visible()
    assert page.evaluate("window.blueprintViewer.controls.enabled")
    page.locator("#annotation-marks").click()
    page.locator("#annotation-clear").click()
    state["pause"] = True
    page.locator("#question").fill("Render again.")
    page.locator("#ask-button").click()
    page.wait_for_function("state.jobs.some(j=>j.kind==='render'&&j.status==='running')", timeout=10000)
    assert state["entered"].wait(10)
    running = next(job for job in app.state.jobs.for_building(document.id) if job["kind"] == "render" and job["status"] == "running")
    page.locator(f'[data-entry="job:{running["id"]}"]').get_by_role("button", name="Stop this operation", exact=True).click()
    page.wait_for_function("id => state.jobs.some(j=>j.id===id&&j.status==='stopped')", arg=running["id"])
    state["release"].set()
    app.state.jobs.futures[running["id"]].result(10)
    assert app.state.documents.get(document.id).revision_id == saved_document.revision_id
    assert len(list_annotations(app.state.documents, document.id)) == 2
