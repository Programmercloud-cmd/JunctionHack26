"""Server-only voice configuration; public readiness never exposes credentials."""
from dataclasses import dataclass
import math
import os


class VoiceError(Exception):
    def __init__(self, message: str, status: int = 502):
        self.message, self.status = message, status


def _timeout(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
        if not math.isfinite(value) or value <= 0:
            raise ValueError
        return value
    except ValueError:
        raise VoiceError(f"Configure {name} as a positive number of seconds and restart the server.", 503) from None


@dataclass(frozen=True)
class VoiceConfig:
    gemini_key: str
    transcription_model: str
    language_codes: list[str]
    elevenlabs_key: str
    voice_id: str
    speech_model: str
    connect_timeout: float
    finalization_timeout: float
    speech_timeout: float

    def public(self):
        return {
            "transcription_ready": bool(self.gemini_key),
            "speech_ready": bool(self.elevenlabs_key and self.voice_id),
            "transcription_model": self.transcription_model,
            "language_codes": self.language_codes,
        }


def voice_settings() -> VoiceConfig:
    return VoiceConfig(
        gemini_key=os.getenv("GEMINI_API_KEY", "").strip(),
        transcription_model=os.getenv("GEMINI_TRANSCRIPTION_MODEL", "gemini-3.5-transcribe-live").strip(),
        language_codes=[code.strip() for code in os.getenv("VOICE_LANGUAGE_CODES", "").split(",") if code.strip()],
        elevenlabs_key=os.getenv("ELEVENLABS_API_KEY", "").strip(),
        voice_id=os.getenv("ELEVENLABS_VOICE_ID", "").strip(),
        speech_model=os.getenv("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2").strip(),
        connect_timeout=_timeout("VOICE_CONNECT_TIMEOUT_SECONDS", 20),
        finalization_timeout=_timeout("VOICE_FINALIZATION_TIMEOUT_SECONDS", 15),
        speech_timeout=_timeout("VOICE_SPEECH_TIMEOUT_SECONDS", 60),
    )
