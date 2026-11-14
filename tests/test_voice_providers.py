"""Provider wire contracts with injected transports; no live calls."""
import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx
import pytest
from google.genai import types

from app.voice_config import VoiceError, voice_settings
from app.voice_providers import GeminiTranscriptionProvider, GeminiSession, ElevenLabsSpeechProvider


@pytest.mark.asyncio
async def test_google_wire_manual_activity_vocabulary_and_pcm(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    sent, captured = [], {}

    class Session:
        async def send_realtime_input(self, **kwargs):
            sent.append(kwargs)

    class Live:
        @asynccontextmanager
        async def connect(self, **kwargs):
            captured.update(kwargs)
            yield Session()
            captured["session_closed"] = True

    class AsyncClient:
        live = Live()
        async def aclose(self):
            captured["client_closed"] = True

    def factory(**kwargs):
        captured["auth"] = kwargs
        return SimpleNamespace(aio=AsyncClient())

    provider = GeminiTranscriptionProvider(client_factory=factory)
    async with provider.connect(["Väinämöinen", "Talotekniikka"], ["fi-FI"]) as session:
        await session.send_audio(b"\0\0" * 1600)
        await session.end_audio()
    config = captured["config"]
    assert captured["model"] == "gemini-3.5-transcribe-live"
    assert config.response_modalities == [types.Modality.TEXT]
    assert config.input_audio_transcription.custom_vocabulary == ["Väinämöinen", "Talotekniikka"]
    assert config.input_audio_transcription.language_codes == ["fi-FI"]
    assert config.realtime_input_config.automatic_activity_detection.disabled is True
    assert isinstance(sent[0]["activity_start"], types.ActivityStart)
    assert sent[1]["audio"].mime_type == "audio/pcm;rate=16000"
    assert sent[1]["audio"].data == b"\0\0" * 1600
    assert isinstance(sent[2]["activity_end"], types.ActivityEnd)
    assert captured["client_closed"] and captured["session_closed"]


@pytest.mark.asyncio
async def test_google_events_repeat_sdk_receive_and_dedicated_completion():
    class Session:
        calls = 0
        async def receive(self):
            self.calls += 1
            if self.calls == 1:
                yield types.LiveServerMessage(server_content=types.LiveServerContent(
                    interim_input_transcription=types.Transcription(text="mech")))
                yield types.LiveServerMessage(server_content=types.LiveServerContent(
                    input_transcription=types.Transcription(text="mechanical room")))
                yield types.LiveServerMessage(server_content=types.LiveServerContent(generation_complete=True))
            elif self.calls == 2:
                yield types.LiveServerMessage(server_content=types.LiveServerContent(
                    input_transcription=types.Transcription(text="next phrase"), turn_complete=True))
            else:
                await asyncio.Future()

    sdk = Session()
    events = GeminiSession(sdk).events()
    interim, final, completed, next_final, next_completed = [await anext(events) for _ in range(5)]
    assert interim.text == "mech" and not interim.final and not interim.terminal
    assert final.text == "mechanical room" and final.final and not final.terminal
    assert completed.terminal and not completed.text
    assert next_final.text == "next phrase" and next_final.final
    assert next_completed.terminal and sdk.calls == 2
    await events.aclose()


@pytest.mark.asyncio
async def test_google_empty_receive_fails_without_busy_loop():
    class Session:
        async def receive(self):
            if False:
                yield None
    with pytest.raises(VoiceError, match="closed"):
        await anext(GeminiSession(Session()).events())


@pytest.mark.asyncio
async def test_elevenlabs_wire_exact_text_voice_and_audio(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "fake-secret")
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "configured-voice")
    monkeypatch.setenv("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2")
    captured = []
    def handler(request):
        captured.append(request)
        return httpx.Response(200, headers={"content-type":"audio/mpeg"}, content=b"ID3audio")
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = ElevenLabsSpeechProvider(client=client)
    try:
        assert await provider.synthesize("The source does not establish a height.") == b"ID3audio"
        request = captured[0]
        assert request.url.path == "/v1/text-to-speech/configured-voice"
        assert request.url.params["output_format"] == "mp3_44100_128"
        assert request.headers["xi-api-key"] == "fake-secret"
        import json
        assert json.loads(request.content) == {"text":"The source does not establish a height.","model_id":"eleven_multilingual_v2"}
    finally:
        await provider.aclose()
    assert client.is_closed


@pytest.mark.asyncio
@pytest.mark.parametrize("status, content_type, body", [(401,"application/json",b"SECRET_BODY"),(200,"application/json",b"SECRET_BODY"),(200,"audio/mpeg",b"")])
async def test_elevenlabs_rejects_errors_non_audio_and_empty(monkeypatch,status,content_type,body):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "fake-secret")
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "configured-voice")
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(status,headers={"content-type":content_type},content=body)))
    provider = ElevenLabsSpeechProvider(client=client)
    try:
        with pytest.raises(VoiceError) as error:
            await provider.synthesize("Answer")
        assert "SECRET" not in error.value.message and error.value.status == 502
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_missing_credentials_no_transport(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.delenv("ELEVENLABS_VOICE_ID", raising=False)
    with pytest.raises(VoiceError, match="GEMINI_API_KEY"):
        async with GeminiTranscriptionProvider(client_factory=lambda **_: pytest.fail("unexpected client")).connect([], []):
            pass
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: pytest.fail("unexpected request")))
    provider = ElevenLabsSpeechProvider(client=client)
    try:
        with pytest.raises(VoiceError, match="ELEVENLABS_API_KEY"):
            await provider.synthesize("Answer")
    finally:
        await provider.aclose()


@pytest.mark.parametrize("value", ["0","-1","nan","inf","secret-value"])
def test_invalid_timeout_is_safe_configuration_error(monkeypatch,value):
    monkeypatch.setenv("VOICE_FINALIZATION_TIMEOUT_SECONDS",value)
    with pytest.raises(VoiceError) as error:
        voice_settings()
    assert error.value.status == 503
    assert "secret-value" not in error.value.message


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [429, 500])
async def test_elevenlabs_sdk_never_retries_generation(monkeypatch, status):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "fake-secret")
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "configured-voice")
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={"detail": "PRIVATE_UPSTREAM_ERROR"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = ElevenLabsSpeechProvider(client=client)
    try:
        with pytest.raises(VoiceError) as error:
            await provider.synthesize("Answer")
        assert len(calls) == 1
        assert "PRIVATE_UPSTREAM_ERROR" not in error.value.message
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_elevenlabs_sdk_stream_cancellation_closes_response(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "fake-secret")
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "configured-voice")
    entered = asyncio.Event()

    class BlockingAudio(httpx.AsyncByteStream):
        closed = False

        async def __aiter__(self):
            yield b"ID3" + b"x" * 1021
            entered.set()
            await asyncio.Future()

        async def aclose(self):
            self.closed = True

    stream = BlockingAudio()
    client = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda _: httpx.Response(200, headers={"content-type": "audio/mpeg"}, stream=stream)))
    provider = ElevenLabsSpeechProvider(client=client)
    task = asyncio.create_task(provider.synthesize("Answer"))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert stream.closed
    finally:
        await provider.aclose()
    assert client.is_closed


@pytest.mark.asyncio
async def test_elevenlabs_sdk_transport_timeout_is_safe_and_single_attempt(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "fake-secret")
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "configured-voice")
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("PRIVATE_REQUEST_DETAILS", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = ElevenLabsSpeechProvider(client=client)
    try:
        with pytest.raises(VoiceError) as error:
            await provider.synthesize("Answer")
        assert len(calls) == 1
        assert "PRIVATE_REQUEST_DETAILS" not in error.value.message
    finally:
        await provider.aclose()
