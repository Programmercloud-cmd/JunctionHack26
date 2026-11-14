"""Small voice adapters. Transcription hints are never answer evidence."""
from contextlib import asynccontextmanager
from dataclasses import dataclass
from urllib.parse import quote

import httpx
from google import genai
from google.genai import types
from elevenlabs import AsyncElevenLabs
from elevenlabs.core.api_error import ApiError

from .voice_config import VoiceError, voice_settings


@dataclass(frozen=True)
class VoiceEvent:
    text: str = ""
    final: bool = False
    terminal: bool = False


class GeminiSession:
    def __init__(self, session):
        self.session = session

    async def send_audio(self, audio: bytes):
        await self.session.send_realtime_input(audio=types.Blob(data=audio, mime_type="audio/pcm;rate=16000"))

    async def end_audio(self):
        # One manually delimited recording, so an earlier automatic-VAD turn
        # cannot accidentally acknowledge the user's Stop.
        await self.session.send_realtime_input(activity_end=types.ActivityEnd())

    async def events(self):
        # SDK receive() ends at each turn boundary, not at socket closure.
        while True:
            received = False
            async for response in self.session.receive():
                received = True
                content = response.server_content
                if not content:
                    continue
                interim = content.interim_input_transcription
                final = content.input_transcription
                if interim and interim.text:
                    yield VoiceEvent(text=interim.text)
                if final and final.text:
                    yield VoiceEvent(text=final.text, final=True)
                # Dedicated TEXT transcription acknowledges the manual activity with
                # generation_complete; it need not emit the live-agent turn_complete.
                if content.generation_complete or content.turn_complete:
                    yield VoiceEvent(terminal=True)
            if not received:
                raise VoiceError("Google transcription connection closed before finalization. Review the received text or record again.")


class GeminiTranscriptionProvider:
    def __init__(self, *, client_factory=None):
        self.client_factory = client_factory or genai.Client

    @asynccontextmanager
    async def connect(self, vocabulary: list[str], language_codes: list[str]):
        config = voice_settings()
        if not config.gemini_key:
            raise VoiceError("Set GEMINI_API_KEY on the server to enable live transcription.", 503)
        client = self.client_factory(api_key=config.gemini_key, http_options={"api_version": "v1beta"})
        try:
            live_config = types.LiveConnectConfig(
                response_modalities=["TEXT"],
                input_audio_transcription=types.AudioTranscriptionConfig(
                    custom_vocabulary=vocabulary, language_codes=language_codes,
                ),
                realtime_input_config=types.RealtimeInputConfig(
                    automatic_activity_detection=types.AutomaticActivityDetection(disabled=True),
                ),
            )
            async with client.aio.live.connect(model=config.transcription_model, config=live_config) as session:
                await session.send_realtime_input(activity_start=types.ActivityStart())
                yield GeminiSession(session)
        finally:
            await client.aio.aclose()


class ElevenLabsSpeechProvider:
    def __init__(self, *, client=None):
        self.config = voice_settings()
        self.client = client or httpx.AsyncClient(timeout=self.config.speech_timeout)
        self.sdk = AsyncElevenLabs(
            api_key=self.config.elevenlabs_key,
            timeout=self.config.speech_timeout,
            httpx_client=self.client,
        )

    async def synthesize(self, text: str) -> bytes:
        if not self.config.elevenlabs_key or not self.config.voice_id:
            raise VoiceError("Set ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID on the server to enable spoken answers.", 503)
        try:
            # Keep the response context open while consuming its async stream so
            # cancellation closes the underlying HTTP response immediately.
            async with self.sdk.text_to_speech.with_raw_response.convert(
                voice_id=quote(self.config.voice_id, safe=""),
                text=text,
                model_id=self.config.speech_model,
                output_format="mp3_44100_128",
                request_options={"max_retries": 0},
            ) as response:
                content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                if content_type not in {"audio/mpeg", "audio/mp3"}:
                    raise VoiceError("ElevenLabs did not return playable audio. The written answer is still available.")
                audio = b"".join([chunk async for chunk in response.data])
                if not audio:
                    raise VoiceError("ElevenLabs did not return playable audio. The written answer is still available.")
                return audio
        except (httpx.HTTPError, ApiError):
            raise VoiceError("ElevenLabs could not generate speech. Check the server credentials, voice access and service availability; the written answer is still available.") from None

    async def aclose(self):
        await self.client.aclose()
