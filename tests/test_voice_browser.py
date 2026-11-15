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

from test_browser import upload
from test_browser_3d import SceneFixtureProvider

pytestmark = pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS") != "1", reason="opt-in browser checks")


class VoiceFixtureState:
    mode = "normal"
    speech_mode = "normal"
    answer_mode = "normal"
    sessions = None
    spoken = None
    questions = None
    closed = 0
    speech_closed = 0


@pytest.fixture
def voice_server(tmp_path, monkeypatch):
    import uvicorn
    from app.main import create_app
    from app.voice_providers import VoiceEvent
    from app.voice_config import VoiceError
    state = VoiceFixtureState()
    state.sessions, state.spoken, state.questions = [], [], []
    state.synthesis_started = threading.Event()
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
            state.synthesis_started.set()
            if state.speech_mode == "delay":
                await asyncio.sleep(20)
            if state.speech_mode == "failure":
                raise VoiceError("Fixture speech unavailable.")
            # A valid synthetic WAV is served by the fake speech adapter; production
            # adapter returns MP3. Browser decoding/playback is real in this test.
            output = BytesIO()
            with wave.open(output, "wb") as audio:
                audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(16000)
                audio.writeframes(bytes(16000 * 2 * 2))
            return output.getvalue()
        async def aclose(self):
            state.speech_closed += 1

    class QA(SceneFixtureProvider):
        def answer(self, document, question, gate, crop=None):
            answer = super().answer(document, question, gate, crop)
            if state.answer_mode == "windows" and gate.decision == "sufficient":
                answer.answer = "There are 2 windows, each 1.2 m wide (GlobalId: 2XQY000000000000000001; STEP: #42; IfcWindow). Their height is not established."
                answer.missing_information = ["Window height"]
                answer.next_action = "Check the section drawing."
            return answer
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
    # The source-first browser tests exercise the model animation independently.
    page.emulate_media(reduced_motion="reduce")
    page.goto(url); upload(page)
    page.locator(".composer-voice > summary").click()
    expect(page.locator("#voice-record")).to_be_enabled()
    if model:
        page.locator("#generate-scene").click()
        page.wait_for_function("window.blueprintViewer?.data.elements.length > 0")
        expect(page.locator("#voice-alias-target option")).to_have_count(3)


def submit_and_get_answer(page):
    with page.expect_response("**/api/questions") as response_info:
        page.locator("#ask-button").click()
    job = response_info.value.json()
    endpoint = f"{page.url.rstrip('/')}/api/jobs/{job['id']}"
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        job = page.request.get(endpoint).json()
        if job["status"] == "complete" and job.get("answer"):
            return job["answer"]
        page.wait_for_timeout(150)
    pytest.fail(f"Question job did not return an answer (status: {job['status']})")


def microphone_stopped(page):
    page.wait_for_function("window.voiceTestStreams.every(s => s.getTracks().every(t => t.readyState === 'ended'))")


def test_live_transcript_alias_answer_evidence_and_audio(voice_server, voice_page):
    from playwright.sync_api import expect
    url, state = voice_server; page = voice_page
    ready(page, url, model=True)
    page.locator("#voice-vocabulary").evaluate("e => e.open = true")
    page.locator("#voice-custom-terms").fill("Talotekniikka\nSähkötila")
    page.locator("#voice-alias-name").fill("plant room")
    page.locator("#voice-alias-target").select_option(index=1)
    page.locator("#voice-add-alias").click()
    expect(page.locator("#voice-alias-list")).to_contain_text("plant room → Room A (Source floor)")
    page.locator("#voice-record").click()
    expect(page.locator("#voice-status")).to_contain_text("Listening")
    expect(page.locator("#question")).to_have_value("Where is plant room?")
    expect(page.locator("#ask-button")).to_be_disabled()
    state.mode = "delayed"
    page.locator("#voice-stop-recording").click()
    expect(page.locator("#voice-status")).to_contain_text("Transcript ready")
    expect(page.locator("#question")).to_have_value("Where is Room A (Source floor)?")
    expect(page.locator("#voice-alias-preview")).to_be_visible()
    expect(page.locator("#voice-original-text")).to_have_text("Where is plant room?")
    microphone_stopped(page)
    assert state.sessions[0].ended and state.sessions[0].bytes > 0
    assert {"Room A", "Room B", "plant room", "Talotekniikka", "Sähkötila"} <= set(state.sessions[0].vocabulary)
    page.locator("#voice-auto-read").check()
    page.locator("#ask-button").click()
    expect(page.locator("#answer-text")).to_have_text("Fixture: Room A is shown on this plan.")
    expect(page.locator("#evidence-list button")).to_have_count(1)
    page.wait_for_function("window.blueprintViewer.getSnapshot().highlight_ids.length === 1")
    expect(page.locator("#voice-status")).to_contain_text("Reading answer")
    assert state.spoken == ["Fixture: Room A is shown on this plan."]
    assert state.questions == ["Where is Room A (Source floor)?"]
    page.locator("#voice-stop-speech").click()
    expect(page.locator("#voice-stop-speech")).to_be_hidden()
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


def test_stop_timeout_preserves_text_and_replacement_cleans_microphone(voice_server, voice_page):
    from playwright.sync_api import expect
    url, state = voice_server; page = voice_page
    ready(page, url)
    state.mode = "hang"
    page.locator("#voice-record").click()
    expect(page.locator("#question")).to_have_value("Where is plant room?")
    page.locator("#voice-stop-recording").click()
    expect(page.locator("#voice-error")).to_contain_text("incomplete")
    expect(page.locator("#question")).to_have_value("Where is plant room?")
    expect(page.locator("#question")).to_be_enabled()
    microphone_stopped(page)
    state.mode = "normal"
    page.locator("#question").fill("")
    page.locator("#voice-record").click()
    expect(page.locator("#voice-status")).to_contain_text("Listening")
    upload(page, name="replacement.png")
    microphone_stopped(page)
    expect(page.locator("#voice-custom-terms")).to_have_value("")
    expect(page.locator("#voice-alias-list li")).to_have_count(0)
    expect(page.locator("#voice-record")).to_be_enabled()


def test_cancel_connecting_and_finalizing_and_permission_denial(voice_server, voice_page, monkeypatch):
    from playwright.sync_api import expect

    # Leave enough time for a real pointer click before the fake service times out.
    monkeypatch.setenv("VOICE_FINALIZATION_TIMEOUT_SECONDS", "3")
    url, state = voice_server; page = voice_page
    ready(page, url)
    state.mode = "connecting"
    page.locator("#voice-record").click()
    expect(page.locator("#voice-cancel")).to_be_visible()
    page.locator("#voice-cancel").click()
    microphone_stopped(page)
    expect(page.locator("#voice-record")).to_be_enabled()
    state.mode = "hang"
    page.locator("#question").fill("")
    page.locator("#voice-record").click()
    expect(page.locator("#voice-status")).to_contain_text("Listening")
    page.locator("#voice-stop-recording").click()
    expect(page.locator("#voice-status")).to_contain_text("Finalizing")
    page.locator("#voice-cancel").click()
    microphone_stopped(page)
    expect(page.locator("#voice-record")).to_be_enabled()
    page.evaluate("() => { navigator.mediaDevices.getUserMedia = async () => { throw new DOMException('denied', 'NotAllowedError'); }; }")
    page.locator("#voice-record").click()
    expect(page.locator("#voice-error")).to_contain_text("permission was denied")
    expect(page.locator("#question")).to_be_enabled()


def test_speech_failures_stop_and_negative_answer_are_text_safe(voice_server, voice_page):
    from playwright.sync_api import expect
    url, state = voice_server; page = voice_page
    ready(page, url)
    page.locator("#question").fill("What is the ceiling height?")
    answer_payload = submit_and_get_answer(page)
    expect(page.locator("#result-status")).to_have_text("Missing information")
    state.speech_mode = "failure"
    page.locator("#voice-read").click()
    expect(page.locator("#voice-error")).to_contain_text("Fixture speech unavailable")
    expect(page.locator("#answer-text")).to_have_text("The inspected pages do not establish this answer.")
    assert state.spoken == [answer_payload["spoken_answer"]]
    assert "Height dimension" in state.spoken[0] and "Provide a section drawing." in state.spoken[0]
    state.speech_mode = "delay"
    page.locator("#voice-read").click()
    expect(page.locator("#voice-status")).to_contain_text("Generating")
    page.locator("#voice-stop-speech").click()
    expect(page.locator("#voice-stop-speech")).to_be_hidden()
    expect(page.locator("#question")).to_be_enabled()
    state.speech_mode = "normal"
    page.locator("#question").fill("How many rooms?")
    page.locator("#ask-button").click()
    expect(page.locator("#answer-text")).to_have_text("Fixture: one labeled room.")
    expect(page.locator("#voice-status")).not_to_contain_text("Reading answer")


def test_alias_unicode_boundaries_nonrecursive_and_ambiguous_targets(voice_server, voice_page):
    from playwright.sync_api import expect
    url, _ = voice_server; page = voice_page
    rooms = [{"id": "one", "name": "Tila", "floor_label": "Ground"},
             {"id": "two", "name": "Tila", "floor_label": "Upper"},
             {"id": "bad1", "name": "Office", "floor_label": "Ground"},
             {"id": "bad2", "name": "Office", "floor_label": "Ground"}]
    page.route("**/voice-vocabulary", lambda route: route.fulfill(json={"terms": ["Tila", "Office"], "rooms": rooms, "warnings": []}))
    ready(page, url)
    page.locator("#voice-vocabulary").evaluate("e => e.open = true")
    expect(page.locator('#voice-alias-target option[value="bad1"]')).to_be_disabled()
    for alias, target in [("sähkö", "one"), ("sähkö tila", "two"), ("Tila", "two")]:
        page.locator("#voice-alias-name").fill(alias)
        page.locator("#voice-alias-target").select_option(target)
        page.locator("#voice-add-alias").click()
    page.locator("#question").fill("Näytä SÄHKÖ tila ja sähkö sekä sähkötalo.")
    page.locator("#voice-apply-aliases").click()
    expect(page.locator("#question")).to_have_value("Näytä Tila (Upper) ja Tila (Ground) sekä sähkötalo.")
    expect(page.locator("#voice-original-text")).to_have_text("Näytä SÄHKÖ tila ja sähkö sekä sähkötalo.")
    page.locator("#voice-alias-name").fill("SÄHKÖ")
    page.locator("#voice-add-alias").click()
    expect(page.locator("#voice-error")).to_contain_text("already exists")


def test_missing_voice_credentials_preserves_text_path(voice_server, voice_page):
    from playwright.sync_api import expect
    url, _ = voice_server; page = voice_page
    page.route("**/api/voice/config", lambda route: route.fulfill(json={"transcription_ready": False, "speech_ready": False, "transcription_model": "fixture", "language_codes": []}))
    page.goto(url); upload(page)
    page.locator(".composer-voice > summary").click()
    expect(page.locator("#voice-record")).to_be_disabled()
    expect(page.locator("#voice-setup")).to_contain_text("still type")
    page.locator("#question").fill("How many rooms?")
    page.locator("#ask-button").click()
    expect(page.locator("#answer-text")).to_have_text("Fixture: one labeled room.")


def test_final_fragments_preserve_split_words_and_punctuation(voice_server, voice_page):
    from playwright.sync_api import expect
    url, state = voice_server; page = voice_page
    ready(page, url)
    state.mode = "fragments"
    page.locator("#voice-record").click()
    expect(page.locator("#voice-status")).to_contain_text("Listening")
    page.locator("#voice-stop-recording").click()
    expect(page.locator("#voice-status")).to_contain_text("Transcript ready")
    expect(page.locator("#question")).to_have_value("Talotekniikka?")
    microphone_stopped(page)


def test_alias_nfc_and_repeated_preview_do_not_rewrite_canonical_names(voice_server, voice_page):
    from playwright.sync_api import expect
    url, _ = voice_server; page = voice_page
    rooms = [{"id": "plant", "name": "plant room", "floor_label": "Upper"},
             {"id": "finnish", "name": "Kokous", "floor_label": "Ground"}]
    page.route("**/voice-vocabulary", lambda route: route.fulfill(json={"terms": [], "rooms": rooms, "warnings": []}))
    ready(page, url)
    page.locator("#voice-vocabulary").evaluate("e => e.open = true")
    for alias, target in [("plant", "plant"), ("Va\u0308ina\u0308mo\u0308inen", "finnish")]:
        page.locator("#voice-alias-name").fill(alias)
        page.locator("#voice-alias-target").select_option(target)
        page.locator("#voice-add-alias").click()
    page.locator("#question").fill("Where are plant and Väinämöinen?")
    page.locator("#voice-apply-aliases").click()
    expect(page.locator("#question")).to_have_value("Where are plant room (Upper) and Kokous (Ground)?")
    page.locator("#voice-apply-aliases").click()
    expect(page.locator("#question")).to_have_value("Where are plant room (Upper) and Kokous (Ground)?")


def test_second_spoken_question_starts_fresh_but_preserves_unsent_draft(voice_server, voice_page):
    from playwright.sync_api import expect
    url, state = voice_server; page = voice_page
    ready(page, url)
    for _ in range(2):
        page.locator("#voice-record").click()
        expect(page.locator("#question")).to_have_value("Where is plant room?")
        page.locator("#voice-stop-recording").click()
        expect(page.locator("#voice-status")).to_contain_text("Transcript ready")
        assert submit_and_get_answer(page)["answer"] == "Fixture: one labeled room."
        expect(page.locator("#result")).to_be_visible()
        expect(page.locator("#voice-record")).to_be_enabled()
    assert state.questions and set(state.questions) == {"Where is plant room?"}
    page.locator("#question").fill("On the upper floor:")
    page.locator("#voice-record").click()
    expect(page.locator("#question")).to_have_value("On the upper floor: Where is plant room?")
    page.locator("#voice-stop-recording").click()
    expect(page.locator("#voice-status")).to_contain_text("Transcript ready")
    microphone_stopped(page)


def test_autoplay_blocked_offers_manual_play_without_regenerating(voice_server, voice_page):
    from playwright.sync_api import expect
    url, state = voice_server; page = voice_page
    ready(page, url)
    page.locator("#question").fill("How many rooms?")
    page.locator("#ask-button").click()
    expect(page.locator("#answer-text")).to_have_text("Fixture: one labeled room.")
    page.evaluate("""() => {
      const original = HTMLMediaElement.prototype.play;
      let block = true;
      HTMLMediaElement.prototype.play = function() {
        if (block) { block = false; return Promise.reject(new DOMException('Autoplay blocked', 'NotAllowedError')); }
        return original.call(this);
      };
    }""")
    page.locator("#voice-read").click()
    expect(page.locator("#voice-play")).to_be_visible()
    expect(page.locator("#voice-status")).to_contain_text("Press Play")
    page.locator("#voice-play").click()
    expect(page.locator("#voice-status")).to_contain_text("Reading answer")
    assert state.spoken == ["Fixture: one labeled room."]
    page.locator("#voice-stop-speech").click()
    expect(page.locator("#voice-play")).to_be_hidden()


def test_cancel_pending_microphone_permission_closes_late_stream(voice_server, voice_page):
    from playwright.sync_api import expect
    url, state = voice_server; page = voice_page
    ready(page, url)
    page.evaluate("""() => {
      const original = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
      navigator.mediaDevices.getUserMedia = async (...args) => {
        const stream = await original(...args);
        await new Promise(resolve => setTimeout(resolve, 400));
        return stream;
      };
    }""")
    page.locator("#voice-record").click()
    page.wait_for_function("window.voiceTestStreams.length > 0")
    page.locator("#voice-cancel").click()
    microphone_stopped(page)
    expect(page.locator("#voice-record")).to_be_enabled()
    assert not state.sessions


def test_prepared_speech_defaults_to_conclusion_and_details_are_explicit(voice_server, voice_page):
    from playwright.sync_api import expect
    url, state = voice_server; page = voice_page
    ready(page, url, model=True)
    state.answer_mode = "windows"
    page.locator("#voice-auto-read").check()
    page.locator("#question").fill("How many windows and how wide are they?")
    result = submit_and_get_answer(page)
    expect(page.locator("#answer-text")).to_have_text(result["answer"])
    expect(page.locator("#answer-text")).to_contain_text("GlobalId")
    expect(page.locator("#evidence-list button")).to_have_count(1)
    page.wait_for_function("window.blueprintViewer.getSnapshot().highlight_ids.length === 1")
    expect(page.locator("#voice-status")).to_contain_text("Reading answer")
    assert state.spoken == [result["spoken_answer"]]
    assert "GlobalId" not in state.spoken[0]
    assert "1.2 m" in state.spoken[0] and "height is not established" in state.spoken[0]
    assert "Window height" in state.spoken[0] and "Check the section drawing." in state.spoken[0]
    page.locator("#voice-technical-details").check()
    expect(page.locator("#voice-stop-speech")).to_be_hidden()
    assert len(state.spoken) == 1  # Preference changes never start another billed request.
    page.locator("#voice-read").click()
    expect(page.locator("#voice-status")).to_contain_text("Reading answer")
    assert state.spoken[-1] == result["spoken_answer_with_details"]
    assert "GlobalId" in state.spoken[-1] and "1.2 m" in state.spoken[-1]
    expect(page.locator("#answer-text")).to_have_text(result["answer"])
    page.locator("#voice-stop-speech").click()
    state.speech_mode = "delay"
    state.synthesis_started.clear()
    page.locator("#voice-read").click()
    expect(page.locator("#voice-status")).to_contain_text("Generating")
    assert state.synthesis_started.wait(3)
    requests_before_toggle = len(state.spoken)
    page.locator("#voice-technical-details").uncheck()
    expect(page.locator("#voice-stop-speech")).to_be_hidden()
    expect(page.locator("#voice-status")).to_contain_text("preference updated")
    assert len(state.spoken) == requests_before_toggle


@pytest.mark.parametrize("legacy", [False, True])
def test_unavailable_preparation_never_reads_raw_metadata_but_legacy_still_works(voice_server, voice_page, legacy):
    from playwright.sync_api import expect
    url, state = voice_server; page = voice_page
    def building_route(route):
        response = route.fetch()
        building = response.json()
        for job in building.get("jobs", []):
            if job.get("kind") == "question" and job.get("answer"):
                result = job["answer"]
                result["answer"] = "Written answer with GlobalId: INTERNAL-ONLY."
                for field in ("spoken_answer", "spoken_answer_with_details"):
                    if legacy:
                        result.pop(field, None)
                    else:
                        result[field] = None
        route.fulfill(response=response, json=building)

    page.route("**/api/buildings/*", building_route)
    ready(page, url)
    page.locator("#voice-auto-read").check()
    page.locator("#question").fill("How many rooms?")
    page.locator("#ask-button").click()
    expect(page.locator("#answer-text")).to_have_text("Written answer with GlobalId: INTERNAL-ONLY.")
    expect(page.locator("#evidence-list button")).to_have_count(1)
    if legacy:
        expect(page.locator("#voice-status")).to_contain_text("Reading answer")
        assert state.spoken == ["Written answer with GlobalId: INTERNAL-ONLY."]
    else:
        expect(page.locator("#voice-read")).to_be_disabled()
        expect(page.locator("#voice-auto-read")).to_be_disabled()
        expect(page.locator("#voice-speech-unavailable")).to_be_visible()
        expect(page.locator("#voice-error")).to_contain_text("preparation is unavailable")
        page.locator("#voice-technical-details").check()
        expect(page.locator("#voice-read")).to_be_disabled()
        assert not state.spoken
