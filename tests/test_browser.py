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

    def gate(self, document, question, crop=None):
        from app.schemas import GateResult
        from app.provider import ProviderError
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
    page.locator("#file-input").set_input_files({
        "name": name or ("two-pages.pdf" if pdf else "plan.png"),
        "mimeType": "application/pdf" if pdf else "image/png", "buffer": source_bytes(pdf),
    })
    page.locator("#page-image").wait_for(state="visible")
    page.wait_for_function("!document.getElementById('file-input').disabled")


def ask(page, question):
    page.locator("#question").fill(question)
    page.locator("#ask-button").click()


def test_pdf_evidence_navigation_and_replacement(server, browser_page):
    from playwright.sync_api import expect
    page = browser_page
    page.goto(server)
    expect(page.locator("#connection-label")).to_have_text("Gemini configured")
    upload(page, pdf=True)
    ask(page, "Count rooms")
    expect(page.locator("#answer-text")).to_have_text("Fixture: one labeled room.")
    page.locator(".evidence-item").click()
    expect(page.locator("#page-label")).to_have_text("Page 2 of 2")
    expect(page.locator("#evidence-overlay")).to_be_visible()
    assert page.locator("#evidence-overlay").evaluate("el => el.style.left") == "10%"
    page.locator("#previous-page").click()
    expect(page.locator("#evidence-overlay")).to_be_hidden()
    upload(page, name="replacement.png")
    expect(page.locator("#result")).to_be_hidden()
    expect(page.locator("#filename")).to_have_text("replacement.png")


def test_limitation_unclear_and_operational_error(server, browser_page):
    from playwright.sync_api import expect
    page = browser_page
    page.goto(server)
    upload(page)
    ask(page, "Ceiling height?")
    expect(page.locator("#result-status")).to_have_text("Missing information")
    expect(page.locator("#next-text")).to_have_text("Provide a section drawing.")
    ask(page, "ambiguous label?")
    expect(page.locator("#result-status")).to_have_text("Unable to resolve confidently")
    ask(page, "failure")
    expect(page.locator("#ask-error")).to_contain_text("no evidence conclusion")
    expect(page.locator("#result")).to_be_hidden()


def test_background_question_keeps_source_available_and_mobile_layout(server, browser_page):
    from playwright.sync_api import expect
    page = browser_page
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(server)
    upload(page)
    ask(page, "slow count")
    expect(page.locator("#file-input")).to_be_enabled()
    expect(page.locator("#answer-text")).to_have_text("Fixture: one labeled room.")
    expect(page.locator("#file-input")).to_be_enabled()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def test_unconfigured_preview_remains_usable(server, browser_page):
    from playwright.sync_api import expect
    page = browser_page
    # Explicit browser test fixture, replacing only configuration response.
    page.route("**/api/health", lambda route: route.fulfill(json={"status": "ok", "provider_ready": False,
        "model": "fixture", "decision_model": "fixture", "limits": {"max_upload_mb": 10, "max_pages": 5}}))
    page.goto(server)
    expect(page.locator("#provider-banner")).to_be_visible()
    upload(page)
    page.locator("#question").fill("How many rooms?")
    expect(page.locator("#ask-button")).to_be_disabled()
    expect(page.locator("#page-image")).to_be_visible()


def test_openai_pipeline_is_identified(server, browser_page):
    from playwright.sync_api import expect
    page = browser_page
    page.route("**/api/health", lambda route: route.fulfill(json={"status": "ok", "provider_ready": True,
        "provider": "openai", "provider_label": "OpenAI", "credential_env": "OPENAI_API_KEY",
        "gate_kind": "structured_classification", "model": "fixture-openai", "decision_model": "fixture-openai",
        "limits": {"max_upload_mb": 10, "max_pages": 5}}))
    page.goto(server)
    expect(page.locator("#connection-label")).to_have_text("OpenAI configured")
    expect(page.locator("#provider-mode")).to_contain_text("Final demo uses Gemini")
    upload(page)
    ask(page, "Count rooms")
    expect(page.locator("#answer-text")).to_have_text("Fixture: one labeled room.")
    expect(page.locator("#run-details-list")).to_contain_text("Structured classification (no confidence score)")
