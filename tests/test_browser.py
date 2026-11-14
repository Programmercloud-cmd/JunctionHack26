"""Opt-in browser integration with real HTTP/upload flow and an injected test provider.

No request reaches Google. This verifies UI behavior, not model correctness.
"""
from io import BytesIO
import os
import socket
import threading
import time

import pytest
from PIL import Image, ImageDraw

pytestmark = pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS") != "1", reason="opt-in browser checks")


class FixtureProvider:
    # This legacy fixture tests pre-review behavior; reviewed QA has dedicated fixtures.
    legacy_fixture_without_review = True
    def __init__(self):
        from app.schemas import Usage
        self.usage = Usage()

    def interpret_chat_actions(self, message, catalog):
        # Intent-only fixture: factual answers still go through the real QA job,
        # source-sufficiency gate and evidence validation below.
        if message.startswith("Fixture control: "):
            import json
            return {"status": "ready", "actions": json.loads(message.removeprefix("Fixture control: "))}
        controls = {
            "Show original page 1": {"type": "show_source", "page": 1},
            "Show model": {"type": "show_model"},
            "Reset model view": {"type": "set_camera", "preset": "fit"},
            "Show assumptions": {"type": "set_visibility", "target": "assumptions", "enabled": True},
            "Hide answer highlights": {"type": "set_visibility", "target": "answer_highlights", "enabled": False},
            "Show answer highlights": {"type": "set_visibility", "target": "answer_highlights", "enabled": True},
            "Inspect model inventory": {"type": "inspect_inventory"},
            "Inspect assumptions": {"type": "inspect_assumptions"},
        }
        return {"status": "ready", "actions": [controls.get(message, {"type": "question", "question": message})]}

    def extract_interpretation(self, document, include_geometry=False):
        from app.building import BuildingDescription
        assert include_geometry is False
        reconstruct=getattr(self,"reconstruct",None)
        return reconstruct(document) if reconstruct else BuildingDescription(floors=[],limitations=["Explicit source-only QA fixture"])

    def enrich_geometry(self, document):
        from app.review_schema import DescriptionPatch
        # This fixture has no additional source-supported geometry to supply.
        return DescriptionPatch(base_revision_id=document.revision_id)

    def review_reconstruction(self, *args, **kwargs):
        from app.review_schema import ReconstructionReview
        return ReconstructionReview(candidate_supported=True,summary="Injected browser review; not a live fidelity claim")

    def gate(self, document, question, crop=None):
        from app.schemas import GateResult
        from app.providers.gemini import ProviderError
        if "failure" in question:
            raise ProviderError("Fixture provider unavailable; no evidence conclusion was made.")
        decision = "insufficient" if "height" in question else "unclear" if "ambiguous" in question else "sufficient"
        return GateResult(decision=decision, confidence=0.8)

    def choose_crop(self, document, question):
        from app.schemas import CropRequest
        return CropRequest(page=1, bbox=[0.1, 0.1, 0.4, 0.4], reason="Inspect label")

    def answer(self, document, question, gate, crop=None):
        from app.schemas import DraftAnswer, Evidence
        if "slow" in question:
            time.sleep(0.7)
        if gate.decision != "sufficient":
            return DraftAnswer(status=gate.decision, answer="The inspected pages do not establish this answer.",
                               missing_information=["Height dimension"], next_action="Provide a section drawing.")
        return DraftAnswer(status="answered", answer="Fixture: one labeled room.", evidence=[
            Evidence(page=len(document.pages), bbox=[0.1, 0.2, 0.6, 0.7], label="Room A",
                     observation="Fixture label on the original page.")])

    def close(self):
        pass


@pytest.fixture
def server(tmp_path, monkeypatch):
    import uvicorn
    from app.main import create_app
    # Used solely for health status; injected provider makes no external calls.
    monkeypatch.setenv("GEMINI_API_KEY", "fixture-never-sent")
    app = create_app(provider_factory=FixtureProvider, storage_root=tmp_path / "uploads")
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    instance = uvicorn.Server(uvicorn.Config(app, log_level="error"))
    thread = threading.Thread(target=instance.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not instance.started and time.monotonic() < deadline:
        time.sleep(0.02)
    assert instance.started
    yield f"http://127.0.0.1:{port}"
    instance.should_exit = True
    thread.join(timeout=5)
    sock.close()


@pytest.fixture
def browser_page():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        yield page
        browser.close()
        assert not errors


def source_bytes(pdf=False):
    image = Image.new("RGB", (600, 400), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((60, 80, 360, 280), outline="black", width=5)
    draw.text((100, 130), "ROOM A", fill="black")
    output = BytesIO()
    if pdf:
        image.save(output, format="PDF", save_all=True, append_images=[image.copy()])
    else:
        image.save(output, format="PNG")
    return output.getvalue()


def upload(page, pdf=False, name=None):
    page.get_by_role("tab", name="Home").click()
    page.get_by_role("button", name="Upload file", exact=True).wait_for(state="visible")
    page.wait_for_function("!document.getElementById('home-upload').disabled")
    with page.expect_response("**/api/documents") as uploaded:
        page.locator("#file-input").set_input_files({
            "name": name or ("two-pages.pdf" if pdf else "plan.png"),
            "mimeType": "application/pdf" if pdf else "image/png", "buffer": source_bytes(pdf),
        })
    assert uploaded.value.ok
    filename = uploaded.value.json()["filename"]
    page.locator("#home-library-list").get_by_role("button", name=filename).click()
    page.locator("#page-image").wait_for(state="visible")


def ask(page, question):
    page.locator("#question").fill(question)
    page.locator("#ask-button").click()


def test_pdf_evidence_navigation_and_replacement(server, browser_page):
    from playwright.sync_api import expect
    page = browser_page
    page.goto(server)
    expect(page.locator("#chat-connection")).to_contain_text("Gemini")
    upload(page, pdf=True)
    ask(page, "Count rooms")
    answer = page.locator("#chat-log .chat-answer").last
    expect(answer).to_contain_text("Fixture: one labeled room.")
    answer.get_by_role("button", name="Room A", exact=True).click()
    expect(page.locator("#page-label")).to_contain_text("page 2 (2/2)")
    expect(page.locator("#evidence-overlay")).to_be_visible()
    assert page.locator("#evidence-overlay").evaluate("el => el.style.left") == "10%"
    ask(page, "Show original page 1")
    expect(page.locator("#page-label")).to_contain_text("page 1 (1/2)")
    expect(page.locator("#evidence-overlay")).to_be_hidden()
    upload(page, name="replacement.png")
    expect(page.locator("#chat-log .chat-answer")).to_have_count(0)
    expect(page.locator("#attachment-summary")).to_contain_text("replacement.png")


def test_limitation_unclear_and_operational_error(server, browser_page):
    from playwright.sync_api import expect
    page = browser_page
    page.goto(server)
    upload(page)
    ask(page, "Ceiling height?")
    answer = page.locator("#chat-log .chat-answer").last
    expect(answer).to_contain_text("Insufficient source evidence")
    answer.locator("summary").click()
    expect(answer.locator("details")).to_contain_text("Provide a section drawing.")
    ask(page, "ambiguous label?")
    expect(page.locator("#chat-log .chat-answer").last).to_contain_text("Source evidence remains unclear")
    ask(page, "failure")
    expect(page.locator("#chat-log")).to_contain_text("no evidence conclusion")
    # Historical refusals remain in the conversation; an operational failure
    # must not append another answer or masquerade as evidence insufficiency.
    expect(page.locator("#chat-log .chat-answer")).to_have_count(2)
    expect(page.locator("#page-image")).to_be_visible()


def test_background_question_keeps_source_available_and_mobile_layout(server, browser_page):
    from playwright.sync_api import expect
    page = browser_page
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(server)
    upload(page)
    ask(page, "slow count")
    page.wait_for_function("state.jobs.some(j=>j.kind==='question'&&!terminalJob(j))")
    expect(page.locator("#file-input")).to_be_enabled()
    expect(page.locator("#page-image")).to_be_visible()
    expect(page.locator("#chat-log .chat-answer").last).to_contain_text("Fixture: one labeled room.")
    expect(page.locator("#file-input")).to_be_enabled()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def test_unconfigured_preview_remains_usable(server, browser_page):
    from playwright.sync_api import expect
    page = browser_page
    # Explicit browser test fixture, replacing only configuration response.
    page.route("**/api/health", lambda route: route.fulfill(json={"status": "ok", "provider_ready": False,
        "model": "fixture", "decision_model": "fixture", "limits": {"max_upload_mb": 10, "max_pages": 5}}))
    page.goto(server)
    expect(page.locator("#chat-connection")).to_have_text("Provider unavailable")
    upload(page)
    expect(page.locator("#chat-log")).to_contain_text("To enable answers")
    page.locator("#question").fill("How many rooms?")
    expect(page.locator("#ask-button")).to_be_disabled()
    expect(page.locator("#page-image")).to_be_visible()


def test_gemini_pipeline_is_identified(server, browser_page):
    from playwright.sync_api import expect
    page = browser_page
    page.goto(server)
    expect(page.locator("#chat-connection")).to_contain_text("Gemini")
    upload(page)
    ask(page, "Count rooms")
    answer = page.locator("#chat-log .chat-answer").last
    expect(answer).to_contain_text("Fixture: one labeled room.")
    answer.locator("summary").click()
    expect(answer.locator("details")).to_contain_text("Evidence sufficiency: sufficient")
    expect(answer.locator("details")).to_contain_text("do not guarantee answer correctness")
    assert page.evaluate("state.health.gate_kind") == "gemini_decisions"


def test_hydrogen_debug_output_logs_once_after_question(server, browser_page, monkeypatch):
    raw_output = '{  "answer": "Unprocessed debug fixture"  }\n'
    answer = FixtureProvider.answer

    def answer_with_raw_output(self, *args, **kwargs):
        self.debug_answer_callback(raw_output)
        return answer(self, *args, **kwargs)

    monkeypatch.setattr(FixtureProvider, "answer", answer_with_raw_output)
    page = browser_page
    messages = []
    page.on("console", lambda message: messages.append(message.text))
    page.goto(server)
    upload(page)
    with page.expect_console_message(predicate=lambda message: message.text == raw_output):
        ask(page, "Count rooms")
    page.evaluate("refreshBuilding()")
    page.evaluate("refreshBuilding()")
    assert messages.count(raw_output) == 1
    assert not page.locator("[data-job-state]").evaluate_all(
        "(nodes, output) => nodes.some(node => node.dataset.jobState.includes(output))", raw_output.strip()
    )
    job = page.evaluate("state.jobs.find(job => job.kind === 'question')")
    assert "debug_hydrogen_outputs" not in page.request.get(f"{server}/api/jobs/{job['id']}").json()
