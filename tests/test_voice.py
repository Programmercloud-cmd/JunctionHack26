"""Deterministic voice routes: no credentials or external provider calls."""
import asyncio
from contextlib import asynccontextmanager
from io import BytesIO
import threading

from fastapi.testclient import TestClient
from PIL import Image
import pytest

from app.main import create_app
from app.scene import Scene, SceneElement, SourceRef, Property, SceneFloor
from app.voice import document_vocabulary
from app.voice_providers import VoiceEvent


class FakeTranscriber:
    def __init__(self, mode="normal"):
        self.mode = mode
        self.closed = threading.Event()
        self.connecting = threading.Event()
        self.audio = []
        self.terms = None
        self.end_called = False

    @asynccontextmanager
    async def connect(self, vocabulary, language_codes):
        self.terms, self.languages = vocabulary, language_codes
        self.connecting.set()
        try:
            if self.mode == "connecting":
                await asyncio.Future()
            if self.mode == "error":
                raise RuntimeError("SECRET_PROVIDER_BODY_AND_KEY")
            self.queue = asyncio.Queue()
            yield self
        finally:
            self.closed.set()

    async def send_audio(self, data):
        self.audio.append(data)
        await self.queue.put(VoiceEvent(text="Talotek", final=False))
        if self.mode == "pause":
            await self.queue.put(VoiceEvent(text="First phrase.", final=True))
            await self.queue.put(VoiceEvent(terminal=True))

    async def end_audio(self):
        self.end_called = True
        if self.mode == "timeout":
            return
        await asyncio.sleep(.01)
        await self.queue.put(VoiceEvent(text="Talotekniikka", final=True))
        await self.queue.put(VoiceEvent(terminal=True))

    async def events(self):
        while True:
            yield await self.queue.get()


class FakeSpeech:
    def __init__(self, mode="normal"):
        self.mode, self.text, self.closed = mode, None, False

    async def synthesize(self, text):
        self.text = text
        if self.mode == "error":
            raise RuntimeError("SECRET_PROVIDER_BODY_AND_KEY")
        if self.mode == "timeout":
            await asyncio.Future()
        return b"ID3fixture-audio"

    async def aclose(self):
        self.closed = True


@pytest.fixture
def voice_app(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fixture-never-sent")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "fixture-never-sent")
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "fixture-voice")
    monkeypatch.setenv("VOICE_CONNECT_TIMEOUT_SECONDS", ".2")
    monkeypatch.setenv("VOICE_FINALIZATION_TIMEOUT_SECONDS", ".05")
    monkeypatch.setenv("VOICE_SPEECH_TIMEOUT_SECONDS", ".05")
    transcription, speech = FakeTranscriber(), FakeSpeech()
    app = create_app(storage_root=tmp_path, transcription_factory=lambda: transcription, speech_factory=lambda: speech)
    with TestClient(app) as client:
        image = BytesIO()
        Image.new("RGB", (40, 40), "white").save(image, format="PNG")
        doc_id = client.post("/api/documents", files={"file": ("fixture.png", image.getvalue(), "image/png")}).json()["document_id"]
        yield client, app, doc_id, transcription, speech


def start(ws, doc_id, words=None):
    ws.send_json({"type": "start", "document_id": doc_id, "custom_vocabulary": words or []})


def test_config_has_readiness_but_no_keys(voice_app):
    client, *_ = voice_app
    data = client.get("/api/voice/config").json()
    assert data["transcription_ready"] and data["speech_ready"]
    assert data["transcription_model"] == "gemini-3.5-transcribe-live"
    assert "fixture" not in str(data)


def test_missing_scene_allows_manual_words_and_deduplicates(voice_app):
    client, _, doc_id, provider, _ = voice_app
    vocab = client.get(f"/api/documents/{doc_id}/voice-vocabulary").json()
    assert vocab["terms"] == [] and "after model generation" in vocab["warnings"][0]
    with client.websocket_connect("/api/voice/transcribe") as ws:
        start(ws, doc_id, ["  Väinämöinen  room ", "väinämöinen ROOM", "", "Åland"])
        assert ws.receive_json() == {"type": "ready"}
        ws.send_json({"type": "cancel"})
    assert provider.terms == ["Väinämöinen room", "Åland"]
    assert provider.closed.wait(1)


def test_stream_interim_final_stop_and_cleanup(voice_app):
    client, _, doc_id, provider, _ = voice_app
    with client.websocket_connect("/api/voice/transcribe") as ws:
        start(ws, doc_id)
        assert ws.receive_json()["type"] == "ready"
        ws.send_bytes(b"\x00\x00" * 1600)
        assert ws.receive_json() == {"type": "transcript", "text": "Talotek", "final": False}
        ws.send_json({"type": "stop"})
        assert ws.receive_json() == {"type": "transcript", "text": "Talotekniikka", "final": True}
        assert ws.receive_json() == {"type": "done"}
    assert provider.audio == [b"\x00\x00" * 1600]
    assert provider.end_called and provider.closed.wait(1)


def test_intermediate_turn_does_not_close_recording(voice_app):
    client, _, doc_id, provider, _ = voice_app
    provider.mode = "pause"
    with client.websocket_connect("/api/voice/transcribe") as ws:
        start(ws, doc_id)
        ws.receive_json()
        for _ in range(2):
            ws.send_bytes(b"\0\0")
            assert ws.receive_json()["final"] is False
            assert ws.receive_json()["text"] == "First phrase."
        ws.send_json({"type": "stop"})
        assert ws.receive_json()["text"] == "Talotekniikka"
        assert ws.receive_json()["type"] == "done"
    assert len(provider.audio) == 2


def test_finalization_timeout_is_error_not_success(voice_app):
    client, _, doc_id, provider, _ = voice_app
    provider.mode = "timeout"
    with client.websocket_connect("/api/voice/transcribe") as ws:
        start(ws, doc_id)
        ws.receive_json()
        ws.send_bytes(b"\0\0")
        assert ws.receive_json()["type"] == "transcript"
        ws.send_json({"type": "stop"})
        result = ws.receive_json()
        assert result["type"] == "error" and "incomplete" in result["message"]
    assert provider.closed.wait(1)


@pytest.mark.parametrize("command", ["cancel", "disconnect"])
def test_cancel_while_connecting_closes_provider(voice_app, command):
    client, _, doc_id, provider, _ = voice_app
    provider.mode = "connecting"
    with client.websocket_connect("/api/voice/transcribe") as ws:
        start(ws, doc_id)
        assert provider.connecting.wait(1)
        if command == "cancel":
            ws.send_json({"type": "cancel"})
        else:
            ws.close()
    assert provider.closed.wait(1)


def test_connection_timeout_safe_and_closes_provider(voice_app):
    client, _, doc_id, provider, _ = voice_app
    provider.mode = "connecting"
    with client.websocket_connect("/api/voice/transcribe") as ws:
        start(ws, doc_id)
        result = ws.receive_json()
        assert result["type"] == "error" and "timed out" in result["message"]
    assert provider.closed.wait(1)


def test_disconnect_while_finalizing_closes_provider(voice_app):
    client, _, doc_id, provider, _ = voice_app
    provider.mode = "timeout"
    with client.websocket_connect("/api/voice/transcribe") as ws:
        start(ws, doc_id)
        ws.receive_json()
        ws.send_json({"type": "stop"})
        ws.close()
    assert provider.closed.wait(1)


def test_provider_error_is_sanitized(voice_app):
    client, _, doc_id, provider, _ = voice_app
    provider.mode = "error"
    with client.websocket_connect("/api/voice/transcribe") as ws:
        start(ws, doc_id)
        result = ws.receive_json()
        assert result["type"] == "error" and "SECRET" not in str(result)
    assert provider.closed.wait(1)


@pytest.mark.parametrize("words", [[f"Room {i}" for i in range(1001)], [42]])
def test_invalid_vocabulary_never_calls_provider(voice_app, words):
    client, _, doc_id, provider, _ = voice_app
    with client.websocket_connect("/api/voice/transcribe") as ws:
        start(ws, doc_id, words)
        result = ws.receive_json()
        assert result["type"] == "error"
    assert provider.terms is None


def test_invalid_pcm_rejected_without_forwarding(voice_app):
    client, _, doc_id, provider, _ = voice_app
    with client.websocket_connect("/api/voice/transcribe") as ws:
        start(ws, doc_id)
        ws.receive_json()
        ws.send_bytes(b"odd")
        assert ws.receive_json()["type"] == "error"
    assert not provider.audio and provider.closed.wait(1)


def test_unknown_document_and_foreign_origin(voice_app):
    from starlette.websockets import WebSocketDisconnect
    client, _, _, provider, _ = voice_app
    with client.websocket_connect("/api/voice/transcribe") as ws:
        start(ws, "absent")
        assert "not found" in ws.receive_json()["message"]
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/voice/transcribe", headers={"origin": "https://foreign.example"}):
            pass
    assert provider.terms is None


def test_native_geometryless_and_derived_names_only(voice_app):
    client, app, doc_id, provider, _ = voice_app
    document = app.state.documents.get(doc_id)
    document.scene = Scene(document_id=doc_id,source_kind="ifc",units="m",catalog_complete=True,elements=[
        SceneElement(id="a",kind="room",name="  Talotekniikka  ",storey_id="storey",source=SourceRef(kind="ifc",global_id="a",step_id=1),properties=[Property(name="Storey.Name",value="Upper floor"), Property(name="Height",value=987654)]),
        SceneElement(id="b",kind="wall",name="Do not use wall",source=SourceRef(kind="ifc",global_id="b",step_id=2)),
    ])
    vocab = client.get(f"/api/documents/{doc_id}/voice-vocabulary").json()
    assert vocab["rooms"] == [{"id":"a","name":"Talotekniikka","floor_label":"Upper floor"}]
    assert vocab["terms"] == ["Talotekniikka", "Upper floor"]
    assert "987654" not in str(vocab)
    with client.websocket_connect("/api/voice/transcribe") as ws:
        start(ws, doc_id, ["plant room"])
        ws.receive_json()
        ws.send_json({"type":"cancel"})
    assert provider.terms == ["Talotekniikka", "Upper floor", "plant room"]
    document.scene.source_kind = "image"
    document.scene.derived = True
    assert "not factual evidence" in document_vocabulary(document)["warnings"][0]


@pytest.mark.parametrize("text", ["One room is shown.", "The inspected drawing lacks a height dimension.", "The labels remain unclear."])
def test_speech_preserves_exact_answer_and_closes(voice_app, text):
    client, _, doc_id, _, provider = voice_app
    response = client.post("/api/voice/speech", json={"document_id":doc_id,"text":text})
    assert response.status_code == 200 and response.content == b"ID3fixture-audio"
    assert response.headers["content-type"] == "audio/mpeg"
    assert response.headers["cache-control"] == "no-store"
    assert provider.text == text and provider.closed


@pytest.mark.parametrize("mode", ["error", "timeout"])
def test_speech_errors_preserve_text_fallback(voice_app, mode):
    client, _, doc_id, _, provider = voice_app
    provider.mode = mode
    response = client.post("/api/voice/speech",json={"document_id":doc_id,"text":"Answer"})
    assert response.status_code == 502 and "written answer" in response.json()["detail"]
    assert "SECRET" not in response.text and provider.closed


def test_speech_bounds_and_invalid_request_do_not_echo_input(voice_app):
    client, _, doc_id, _, provider = voice_app
    for text in ["", "x" * 6001]:
        response = client.post("/api/voice/speech",json={"document_id":doc_id,"text":text})
        assert response.status_code == 400
    assert provider.text is None
    response = client.post("/api/voice/speech",json={"document_id":doc_id,"text":{"secret":"NEVER_ECHO"}})
    assert response.status_code == 400 and "NEVER_ECHO" not in response.text
    assert client.post("/api/voice/speech",json={"document_id":"missing","text":"Answer"}).status_code == 404


@pytest.mark.asyncio
async def test_speech_disconnect_cancels_pending_generation():
    from types import SimpleNamespace
    from fastapi import FastAPI, Request
    from app.voice import attach_voice_routes

    entered, cancelled = asyncio.Event(), asyncio.Event()
    class Speech(FakeSpeech):
        async def synthesize(self, text):
            entered.set()
            try:
                await asyncio.Future()
            finally:
                cancelled.set()

    provider = Speech()
    application = FastAPI()
    application.state.documents = SimpleNamespace(get=lambda _: object())
    attach_voice_routes(application, speech_factory=lambda: provider)
    endpoint = next(route.endpoint for route in application.routes if route.path == "/api/voice/speech")
    messages = asyncio.Queue()
    await messages.put({"type":"http.request", "body":b'{"document_id":"fixture","text":"Answer"}', "more_body":False})
    request = Request({"type":"http", "method":"POST", "scheme":"http", "server":("testserver",80), "path":"/api/voice/speech", "query_string":b"", "headers":[]}, messages.get)
    task = asyncio.create_task(endpoint(request))
    await asyncio.wait_for(entered.wait(), 1)
    await messages.put({"type":"http.disconnect"})
    response = await asyncio.wait_for(task, 1)
    assert response.status_code == 204 and cancelled.is_set() and provider.closed
