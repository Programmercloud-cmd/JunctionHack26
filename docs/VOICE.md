# Voice setup and use

## Setup

Run commands from the repository root. On a fresh checkout, install dependencies with `bash scripts/bootstrap.sh`.

Configure `.env.local` using the placeholders in `.env.example`:

- `GEMINI_API_KEY`: Google key for live transcription (also used for Gemini QA).
- `GEMINI_TRANSCRIPTION_MODEL=gemini-3.5-transcribe-live`.
- `VOICE_LANGUAGE_CODES=`: empty for automatic language detection; optional comma-separated language codes such as `en-US,fi-FI`.
- `ELEVENLABS_API_KEY`: your ElevenLabs key.
- `ELEVENLABS_VOICE_ID`: a voice available to that account.
- `ELEVENLABS_MODEL_ID=eleven_multilingual_v2`.
- `VOICE_CONNECT_TIMEOUT_SECONDS=20`, `VOICE_FINALIZATION_TIMEOUT_SECONDS=15`, `VOICE_SPEECH_TIMEOUT_SECONDS=60`: configurable stalled-operation deadlines.

The official ElevenLabs Python SDK is pinned in the lockfile and uses the existing HTTP transport with automatic retries disabled. Voice uses server-side credentials; the browser sends audio only to the local app. Readiness means configuration exists, not that provider access is verified. Diagnose with `.venv/bin/python scripts/doctor.py`, run with `bash scripts/dev.sh` and open http://127.0.0.1:8000. Microphone capture needs localhost or HTTPS and browser microphone permission.

## Use

1. Upload a plan/PDF/IFC. Native IFC names are available immediately. Drawings gain automatic hints after Generate Model; reopened generated IFC restores those hints.
2. Add custom words if needed. Names interpreted from drawings are fallible and remain recognition hints.
3. Add an easier alias by selecting its room. Floor-qualified names distinguish repeated room names. A duplicated name on the same floor requires explicit clarification instead of an ambiguous alias. Aliases/terms last only for this document in the current page session.
4. Record, speak, and Stop. Review the recognized words and any alias replacement, edit the question, and press Ask. Recording never submits a question automatically.
5. Read the answer aloud or enable automatic reading. Spoken wording omits recognized technical annotations while retaining measurements and uncertainty. Select “Read technical details” to include those annotations. Stop cancels pending synthesis/playback. The full written answer, citations and highlights remain available.

## Boundaries

Hints influence recognition without guaranteeing it. Google documents at most 1,000 combined phrases; excess hints produce an explicit error. No extra provider call extracts labels solely for voice. Rooms omitted by reconstruction are absent from automatic hints and can be added manually.

Speech uses a deterministic presentation of the validated answer, including refusal/uncertainty wording, every missing-information entry and the next action. Coordinate lists, bounding boxes, opaque IDs and citation annotations are omitted by default; direct requests for those details or the “Read technical details” option retain them. Full written answers and visual evidence are preserved. See [spoken-answer behavior](SPOKEN_ANSWERS.md). The app downloads a complete MP3 before playback, so speech starts after synthesis completes. Speech supports up to 6,000 characters and never silently truncates longer answers. Browser autoplay restrictions may require manual playback.

Stopping recording waits for Google's manual turn completion. Timeout or interrupted finalization preserves received text with an error; review before submission. Starting another interaction invalidates stale callbacks. Cancelling a provider request does not undo any usage already incurred. Audio is forwarded during the active session and is not persisted by this app. Provider retention follows the provider/account settings.

## Verification

The [original voice branch verification report](VOICE_VERIFICATION.md) records: 220 integrated tests plus 2 focused browser cases passed, and the complete live browser flow passed through Google transcription, source-grounded answering, ElevenLabs speech generation and playback/Stop. The SDK update additionally passed 39 focused tests and independent review. Deterministic fixtures are explicitly injected and are not evidence of live recognition or speech quality. Test vocabulary benefit with paired recordings using the same audio with and without hints before claiming an accuracy improvement.
