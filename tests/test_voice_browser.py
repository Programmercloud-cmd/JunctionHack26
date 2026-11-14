"""Opt-in Chromium voice flow. Injected providers and synthetic mic audio only.

No network request reaches Google or ElevenLabs. These checks establish browser,
protocol, evidence and cleanup behavior, not speech recognition quality.
"""
import asyncio
from contextlib import asynccontextmanager
from io import BytesIO
import os
import socket
import threading
import time
import wave

import pytest

from test_browser import source_bytes, upload
from test_browser_3d import SceneFixtureProvider, generate_scene

pytestmark = pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS") != "1", reason="opt-in browser checks")


class VoiceFixtureState:
    mode = "normal"
    sessions = None
    spoken = None
    questions = None
    closed = 0


@pytest.fixture
def voice_server(tmp_path, monkeypatch):
    import uvicorn
    from app.main import create_app
    from app.voice_providers import VoiceEvent
    from app.voice_config import VoiceError
    state = VoiceFixtureState()
    state.sessions, state.spoken, state.questions = [], [], []
    for name in ("GEMINI_API_KEY", "ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID"):
        monkeypatch.setenv(name, "fixture-never-sent")
    monkeypatch.setenv("VOICE_FINALIZATION_TIMEOUT_SECONDS", "0.3")

    class Session:
        def __init__(self, vocabulary):
            self.vocabulary = vocabulary
            self.queue = asyncio.Queue()
            self.frames = 0
            self.bytes = 0
            self.ended = False
        async def send_audio(self, data):
            assert len(data) % 2 == 0
            self.bytes += len(data)
            self.frames += 1
            if state.mode == "fragments":
                return
            if self.frames == 1:
                await self.queue.put(VoiceEvent(text="Where is ", final=True))
                await self.queue.put(VoiceEvent(text="plant", final=False))
            elif self.frames == 2:
                await self.queue.put(VoiceEvent(text="plant room?", final=False))
        async def end_audio(self):
            self.ended = True
            if state.mode == "hang":
                return
            if state.mode == "delayed":
                await asyncio.sleep(.15)
            if state.mode == "fragments":
                for text in ("Talotek", "niikka", "?"):
                    await self.queue.put(VoiceEvent(text=text, final=True))
            else:
                await self.queue.put(VoiceEvent(text="plant room?", final=True))
            await self.queue.put(VoiceEvent(terminal=True))
        async def events(self):
            while True:
                yield await self.queue.get()

    class Transcriber:
        @asynccontextmanager
        async def connect(self, vocabulary, language_codes):
            if state.mode == "connecting":
                await asyncio.sleep(20)
            if state.mode == "failure":
                raise VoiceError("Fixture transcription unavailable.")
            session = Session(vocabulary)
            state.sessions.append(session)
            try:
                yield session
            finally:
                state.closed += 1

    class Speech:
        async def synthesize(self, text):
            state.spoken.append(text)
            output = BytesIO()
            with wave.open(output, "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(16_000)
                audio.writeframes(bytes(16_000 * 2 * 10))
            return output.getvalue()
        async def aclose(self):
            pass

    class QA(SceneFixtureProvider):
        def gate(self, document, question, crop=None):
            state.questions.append(question)
            return super().gate(document, question, crop)

    app = create_app(provider_factory=QA, transcription_factory=Transcriber,
                     speech_factory=Speech, storage_root=tmp_path / "uploads")
    sock = socket.socket(); sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started and time.monotonic() < deadline:
        time.sleep(.02)
    assert server.started
    yield f"http://127.0.0.1:{sock.getsockname()[1]}", state
    server.should_exit = True; thread.join(timeout=5); sock.close()


@pytest.fixture
def voice_page():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        page.add_init_script("""(() => {
          const original = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
          window.voiceTestStreams = [];
          navigator.mediaDevices.getUserMedia = async (...args) => {
            const stream = await original(...args); window.voiceTestStreams.push(stream); return stream;
          };
        })();""")
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        yield page
        browser.close()
        assert not errors


def ready(page, url, model=False):
    from playwright.sync_api import expect
    page.goto(url)
    page.locator("#file-input").set_input_files({
        "name": "plan.png", "mimeType": "image/png", "buffer": source_bytes(),
    })
    page.locator("#home-library-list button").first.click()
    expect(page.locator("#attachment-summary")).to_contain_text("plan.png")
    expect(page.locator("#voice-record")).to_be_enabled()
    if model:
        generate_scene(page)
        page.wait_for_function("window.blueprintViewer?.data.elements.length > 0")


def submit_and_get_answer(page):
    with page.expect_response("**/api/questions") as response_info:
        page.locator("#ask-button").click()
    job = response_info.value.json()
    page.wait_for_function(
        """async id => {
            const response = await fetch('/api/jobs/' + id);
            const job = await response.json();
            return job.status === 'complete';
        }""", arg=job["id"],
    )
    return page.request.get(f"{page.url.rstrip('/')}/api/jobs/{job['id']}").json()["answer"]


def microphone_stopped(page):
    page.wait_for_function("window.voiceTestStreams.every(s => s.getTracks().every(t => t.readyState === 'ended'))")


def hold_pointer(page):
    page.locator("#voice-record").hover()
    page.mouse.down()


def test_pointer_hold_transcribes_and_keeps_draft_for_explicit_send(voice_server, voice_page):
    from playwright.sync_api import expect

    url, state = voice_server
    page = voice_page
    ready(page, url, model=True)
    mic = page.get_by_role("button", name="Hold to talk")
    expect(mic).to_have_count(1)
    expect(page.locator(".prompt-row #voice-record")).to_be_visible()
    expect(page.locator(".voice-panel")).to_have_count(0)

    page.locator("#question").fill("On the upper floor:")
    hold_pointer(page)
    expect(page.locator("#voice-status")).to_contain_text("Listening")
    expect(page.locator("#question")).to_have_value("On the upper floor: Where is plant room?")
    expect(page.locator("#ask-button")).to_be_disabled()
    state.mode = "delayed"
    page.mouse.move(20, 20)
    page.mouse.up()
    microphone_stopped(page)
    expect(page.locator("#voice-status")).to_contain_text("Transcript ready")
    expect(page.locator("#question")).to_have_value("On the upper floor: Where is plant room?")
    assert not state.questions and not state.spoken
    assert state.sessions[0].ended and state.sessions[0].bytes > 0
    assert {"Room A", "Room B"} <= set(state.sessions[0].vocabulary)

    page.locator("#question").fill("Where is Room A?")
    assert submit_and_get_answer(page)["answer"] == "Fixture: Room A is shown on this plan."
    assert state.questions == ["Where is Room A?"]
    assert not state.spoken
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


@pytest.mark.parametrize("key", ["Space", "Enter"])
def test_keyboard_hold_preserves_final_fragments_and_ignores_repeat(voice_server, voice_page, key):
    from playwright.sync_api import expect

    url, state = voice_server
    page = voice_page
    ready(page, url)
    state.mode = "fragments"
    page.locator("#voice-record").focus()
    page.keyboard.down(key)
    expect(page.locator("#voice-status")).to_contain_text("Listening")
    page.keyboard.down(key)
    page.keyboard.up(key)
    expect(page.locator("#voice-status")).to_contain_text("Transcript ready")
    expect(page.locator("#question")).to_have_value("Talotekniikka?")
    microphone_stopped(page)
    assert len(state.sessions) == 1 and not state.questions
    expect(page.locator("#voice-record")).to_be_focused()
    page.keyboard.down(key)
    expect(page.locator("#voice-status")).to_contain_text("Listening")
    page.keyboard.up(key)
    expect(page.locator("#voice-status")).to_contain_text("Transcript ready")
    microphone_stopped(page)
    assert len(state.sessions) == 2 and not state.questions


def test_release_during_permission_closes_late_stream(voice_server, voice_page):
    from playwright.sync_api import expect

    url, state = voice_server
    page = voice_page
    ready(page, url)
    page.evaluate("""() => {
      const original = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
      navigator.mediaDevices.getUserMedia = async (...args) => {
        const stream = await original(...args);
        await new Promise(resolve => { window.completeMicPermission = resolve; });
        return stream;
      };
    }""")
    hold_pointer(page)
    page.wait_for_function("Boolean(window.completeMicPermission)")
    page.mouse.up()
    expect(page.locator("#voice-record")).to_have_text("Hold to talk")
    page.evaluate("window.completeMicPermission()")
    microphone_stopped(page)
    assert not state.sessions


def test_blur_releases_capture_and_timeout_preserves_transcript(voice_server, voice_page):
    from playwright.sync_api import expect

    url, state = voice_server
    page = voice_page
    ready(page, url)
    state.mode = "hang"
    hold_pointer(page)
    expect(page.locator("#question")).to_have_value("Where is plant room?")
    page.locator("#question").focus()
    microphone_stopped(page)
    page.mouse.up()
    expect(page.locator("#voice-error")).to_contain_text("incomplete")
    expect(page.locator("#question")).to_have_value("Where is plant room?")
    expect(page.locator("#question")).to_be_editable()
    assert state.sessions[0].ended


def test_home_navigation_during_hold_cancels_capture(voice_server, voice_page):
    from playwright.sync_api import expect

    url, state = voice_server
    page = voice_page
    ready(page, url)
    hold_pointer(page)
    expect(page.locator("#voice-status")).to_contain_text("Listening")
    page.get_by_role("tab", name="Home").evaluate("tab => tab.click()")
    page.locator("#file-input").set_input_files({
        "name": "replacement.pdf",
        "mimeType": "application/pdf",
        "buffer": source_bytes(pdf=True),
    })
    microphone_stopped(page)
    page.mouse.up()
    page.locator("#home-library-list button").filter(has_text="replacement.pdf").click()
    expect(page.locator("#attachment-summary")).to_contain_text("replacement.pdf")
    expect(page.locator("#voice-record")).to_be_enabled()
    assert not state.sessions[0].ended


def test_missing_voice_credentials_preserves_text_path(voice_server, voice_page):
    from playwright.sync_api import expect

    url, _ = voice_server
    page = voice_page
    page.route("**/api/voice/config", lambda route: route.fulfill(json={"transcription_ready": False}))
    page.goto(url)
    upload(page)
    expect(page.locator("#voice-record")).to_be_disabled()
    expect(page.locator("#voice-record")).to_have_attribute("title", "Voice transcription is unavailable")
    page.locator("#question").fill("How many rooms?")
    assert submit_and_get_answer(page)["answer"] == "Fixture: one labeled room."


def test_spoken_answers_opt_in_and_cancel_without_replaying_history(voice_server, voice_page):
    from playwright.sync_api import expect

    url, state = voice_server
    page = voice_page
    ready(page, url)
    toggle = page.get_by_role("button", name="Read answers aloud")
    expect(toggle).to_have_attribute("aria-pressed", "false")
    page.locator("#question").fill("How many rooms?")
    submit_and_get_answer(page)
    expect(page.locator(".chat-answer")).to_be_visible()
    toggle.click()
    expect(toggle).to_have_attribute("aria-pressed", "true")
    assert not state.spoken

    page.locator("#question").fill("What is the ceiling height?")
    result = submit_and_get_answer(page)
    expect(page.locator("#voice-speech-status")).to_contain_text("Reading the answer aloud")
    assert state.spoken == [result["spoken_answer"]]
    toggle.click()
    expect(toggle).to_have_attribute("aria-pressed", "false")
    assert page.evaluate("voice.speech === null")

    page.locator("#question").fill("How many rooms?")
    submit_and_get_answer(page)
    expect(page.locator(".chat-answer")).to_have_count(3)
    assert state.spoken == [result["spoken_answer"]]


def test_autoplay_fallback_plays_same_audio_without_regenerating(voice_server, voice_page):
    from playwright.sync_api import expect

    url, state = voice_server
    page = voice_page
    ready(page, url)
    page.evaluate("""() => {
        const play = Audio.prototype.play;
        Audio.prototype.play = function() {
            Audio.prototype.play = play;
            return Promise.reject(new DOMException("Autoplay blocked", "NotAllowedError"));
        };
    }""")
    page.get_by_role("button", name="Read answers aloud").click()
    page.locator("#question").fill("How many rooms?")
    result = submit_and_get_answer(page)
    fallback = page.get_by_role("button", name="Play answer audio")
    expect(fallback).to_be_visible()
    fallback.click()
    expect(page.locator("#voice-speech-status")).to_contain_text("Reading the answer aloud")
    assert state.spoken == [result["spoken_answer"]]
