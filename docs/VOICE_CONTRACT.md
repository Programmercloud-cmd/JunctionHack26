# Voice interaction contract

Root owns this integration contract. Voice input/output augment the existing source-grounded question flow; they do not establish building facts.

## Endpoints

Current product speech posts `{project_id,session_id,document_id:null|string,text}` to `/api/voice/speech`. The server validates the owned session and its effective source group before constructing the paid speech provider. Empty Building chats can speak; a stale null document after first upload fails rather than adopting new evidence silently. Existing document-only speech clients remain compatible. All requests retain workspace/window authorization, same-origin checks, safe errors, no-store audio and the existing text bound. Public configuration exposes readiness, never the shared key or per-user credentials.

The agent `/api/chat` path prepares technical speech using the existing deterministic formatter after answer validation and calculation replacement. Validated structured clarification uses its human-readable question. Normal conversation and message-only clarification use their accepted reply text. Each newest accepted reply is spoken at most once while the user has opted in, and captured owner/session/document/request guards reject stale audio. Factual explicit-null preparation remains a denial of audio, never a raw-text fallback.

- `GET /api/voice/config`: `{transcription_ready,speech_ready,transcription_model,language_codes}`. Readiness means configuration is present, not successful provider access. Voice transcription uses Gemini independently of the selected QA provider.
- `GET /api/documents/{id}/voice-vocabulary`: `{terms:[str],rooms:[{id,name,floor_label}],warnings:[str]}`. Names come from cached room elements including geometry-less IFC records, plus floor names. Native floors can come from `Storey.Name`. Drawing names are fallible recognition hints and become available after reconstruction or generated-IFC reopening; no extra extraction request is made. Custom terms work before a scene exists. No generated dimensions or assumptions enter recognition or factual answering.
- WebSocket `/api/voice/transcribe`: initial JSON `{type:"start",document_id,custom_vocabulary:[str]}`. Server deduplicates building/custom vocabulary, validates document and configuration, opens Google, and emits `{type:"ready"}`. Client then streams signed little-endian PCM16 mono at 16 kHz as binary messages. AudioWorklet converts the actual browser sample rate. Server emits `{type:"transcript",text,final:boolean}`; finals append and interim text replaces the previous interim. Client `{type:"stop"}` flushes audio and waits for finalization; `{type:"cancel"}` or disconnect aborts. Google automatic activity detection is disabled: one recording uses `activity_start` before PCM and `activity_end` after the final PCM chunk. This avoids mistaking an earlier pause completion for Stop completion. The adapter keeps receiving across SDK receive loops and awaits the manual turn terminal acknowledgment. Successful completion emits `{type:"done"}`. Operational failures emit `{type:"error",message}` with safe text and preserve already received transcript text. Never treat a timeout as successful finalization.
- `POST /api/voice/speech`: `{document_id,text}` -> `audio/mpeg`, no-store. UI sends the selected server-prepared spoken version. `/api/ask` adds `spoken_answer` and `spoken_answer_with_details`, prepared only after source-reference/calculation validation. Default speech omits recognized coordinate lists, bounding boxes, opaque object IDs and citation annotations, unless the original question explicitly requests that category. The “Read technical details” option selects the full-detail version. All missing-information entries and the next action are included; uncertainty and useful measurements stay intact. No summarizer or new factual inference. The full written answer, evidence and highlights are unchanged. Unknown documents return 404, missing configuration 503, upstream failures 502. Full MP3 is fetched before playback.

## Aliases and evidence

Aliases are user-defined, per-document browser-memory mappings to a selected room. Exact Unicode-boundary matching is case-insensitive, longest-first and nonrecursive. The UI shows the recognized text and editable canonical replacement before explicit Ask. Duplicate room names require floor qualification; duplicated name+floor targets are ambiguous and cannot receive an ID-specific alias through the text-only question API. Aliases and custom terms are hints, never evidence. The existing question endpoint, sufficiency gate, source citations and highlight validation remain authoritative.

## Lifecycle and limits

Only a user action opens the microphone. Recording and playback exclude one another. Stop, cancel, document replacement, new questions and page departure release microphone tracks, audio processing, sockets, pending synthesis and playback resources as appropriate. Delayed callbacks from an older recording/document cannot modify the current question or answer. Browser playback restrictions expose a manual playback fallback. Voice failures preserve ordinary text input, answers and citations.

Google documents at most 1,000 custom-vocabulary phrases; excess combined hints are explicitly rejected rather than truncated. There is no additional recording-duration or room-count cap. Configurable connection/finalization/synthesis deadlines release stalled operations; a finalization deadline reports incomplete transcription. Speech is limited to 6,000 characters, matching the original draft-answer bound; an expanded final answer may exceed that and remains text-only with a clear error, never silent truncation. Provider cancellation cannot reverse already billed work.

## Provider references

Verified 2026-11-14 against current documentation and installed google-genai 3.3.0:
- https://aistudio.google.com/docs/live-api/live-transcribe — Gemini Live transcription and custom vocabulary.
- https://elevenlabs.io/docs/api-reference/text-to-speech/convert — ElevenLabs text-to-speech MP3 conversion.

Factories are injected for deterministic tests; fixture transcription and speech must never be described as live inference. Recognition improvement requires paired recordings with/without hints; configuration acceptance alone is insufficient.

## Spoken-answer presentation

[Spoken-answer behavior](SPOKEN_ANSWERS.md) supersedes the initial exact-main-text playback rule. Both speech fields are optional for compatibility; explicit null means speech preparation is unavailable and must not fall back to raw metadata. A presentation failure leaves the grounded written answer usable. The browser falls back to the legacy main answer only when the speech fields are entirely absent. Changing the technical-details option stops pending/current playback; it does not issue a new synthesis request by itself.
