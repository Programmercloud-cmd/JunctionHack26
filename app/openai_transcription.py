"""Explicit OpenAI batch transcription behind the existing PCM websocket contract."""
import asyncio
from contextlib import asynccontextmanager, suppress
from io import BytesIO
import wave

from openai import AsyncOpenAI

from .voice_config import VoiceError, voice_settings
from .voice_providers import VoiceEvent


class OpenAITranscriptionSession:
    def __init__(self, client, config, vocabulary, language_codes):
        self.client, self.config = client, config
        self.vocabulary, self.language_codes = list(vocabulary), list(language_codes)
        self.audio = bytearray()
        self.stopped = asyncio.Event()
        self.started = False

    async def send_audio(self, data):
        if self.stopped.is_set():
            raise VoiceError("Audio must be sent before Stop.", 400)
        if not data or len(data) % 2:
            raise VoiceError("Audio must be mono signed 16-bit PCM at 16 kHz.", 400)
        self.audio.extend(data)

    async def end_audio(self):
        self.stopped.set()

    async def events(self):
        await self.stopped.wait()
        if self.started:
            raise VoiceError("This recording has already been submitted.", 400)
        self.started = True
        if not self.audio:
            raise VoiceError("No recorded audio was received. Record again or type your question.", 400)
        container = BytesIO()
        with wave.open(container, "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16000)
            audio.writeframes(self.audio)
        self.audio.clear()
        arguments = {"model": self.config.transcription_model,
                     "file": ("recording.wav", container.getvalue(), "audio/wav"),
                     "response_format": "json"}
        if self.config.transcription_model == "gpt-transcribe" or self.config.transcription_model.startswith("gpt-transcribe-"):
            arguments["prompt"] = "Transcribe the recording exactly. Vocabulary suggestions are spelling hints, not required output; do not add words that were not spoken."
            keywords, other_hints = [], []
            for term in self.vocabulary:
                (other_hints if any(char in term for char in "<>\r\n") else keywords).append(term)
            extra = {}
            if keywords:
                extra["keywords"] = keywords
            if other_hints:
                arguments["prompt"] += " Additional spelling context: " + ", ".join(other_hints)
            languages = []
            for code in self.language_codes:
                code = code.lower()
                # Retain supported Chinese regional codes; the existing Gemini
                # locale convention en-US/fi-FI maps to ISO-639-1 here.
                if "-" in code and not code.startswith("zh-") and len(code.split("-", 1)[0]) == 2:
                    code = code.split("-", 1)[0]
                if code not in languages:
                    languages.append(code)
            if languages:
                extra["languages"] = languages
            if extra:
                arguments["extra_body"] = extra
        else:
            # Explicit legacy model overrides retain their original API contract.
            if self.vocabulary:
                arguments["prompt"] = "Vocabulary hints for spelling only; do not invent speech: " + ", ".join(self.vocabulary)
            if len(self.language_codes) == 1:
                language = self.language_codes[0].split("-", 1)[0].lower()
                if len(language) == 2 and language.isalpha():
                    arguments["language"] = language
        try:
            result = await self.client.audio.transcriptions.create(**arguments)
        except asyncio.CancelledError:
            raise
        except Exception:
            raise VoiceError("OpenAI transcription failed. Check the selected model, credentials and connection; you can still type your question.") from None
        text = getattr(result, "text", None)
        if not isinstance(text, str):
            raise VoiceError("OpenAI did not return a valid transcript. Record again or type your question.")
        if text:
            yield VoiceEvent(text=text, final=True)
        yield VoiceEvent(terminal=True)


class OpenAITranscriptionProvider:
    def __init__(self, *, client_factory=None):
        self.client_factory = client_factory or AsyncOpenAI

    @asynccontextmanager
    async def connect(self, vocabulary, language_codes):
        config = voice_settings()
        if not config.openai_key:
            raise VoiceError("Set OPENAI_API_KEY on the server to enable OpenAI transcription.", 503)
        client = None
        session = None
        try:
            client = self.client_factory(api_key=config.openai_key, max_retries=0,
                                         timeout=config.finalization_timeout)
            session = OpenAITranscriptionSession(client, config, vocabulary, language_codes)
            yield session
        except (VoiceError, asyncio.CancelledError):
            raise
        except Exception:
            raise VoiceError("OpenAI transcription is unavailable. Check the selected model, credentials and connection.") from None
        finally:
            if session is not None:
                session.audio.clear()
            if client is not None:
                with suppress(Exception):
                    await client.close()
