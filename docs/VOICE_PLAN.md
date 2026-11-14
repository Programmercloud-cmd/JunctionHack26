# Reviewed voice implementation plan

User-authorized addition to Blueprint QA: Google live transcription with building-specific vocabulary and room aliases, existing grounded question answering, ElevenLabs spoken answers. This work is isolated on `feat/voice-interaction` in `JunctionHack26-voice`. Existing uncommitted source was copied without uploads, dataset files or secrets; no commits were made.

## Accepted scope and ownership

- Root: architecture, `app/main.py`, dependency declarations, configuration placeholders, diagnostics, documentation and integrated checks.
- Backend implementer: `app/voice*.py`, non-browser `tests/test_voice*.py`; injectable Google/ElevenLabs adapters, vocabulary catalog, WebSocket and speech routes.
- Frontend implementer: static UI/voice/worklet modules and `tests/test_voice_browser.py`; recording, transcript editing, per-document terms/aliases, playback and lifecycle cleanup.
- Independent reviewer: read-only plan and implementation reviews, no implementation ownership.

[VOICE_CONTRACT.md](VOICE_CONTRACT.md) defines the shared contract. Existing upload, question, evidence, geometry and provider-selection contracts remain in force.

## Review decisions

The independent plan review found two blockers, resolved in one revision: correct finalization across speech turns, and room identity through the text-only question API. Use explicit manual activity start/end with automatic VAD disabled, plus a finalization deadline that reports incompleteness rather than success. Native IFC floor labels include `Storey.Name`; alias replacements contain floor qualification when necessary and ambiguous duplicate targets are disallowed.

## Acceptance

1. Browser microphone produces real PCM frames; partial transcription updates are replaceable, finals retained and editable; explicit Ask follows the existing evidence flow.
2. Hints include all cached room names, including geometry-less records and reopened drawing-derived labels, plus user terms. No extra label-extraction provider call; no-scene drawings explain manual hints.
3. Aliases use visible canonical replacements, Unicode boundaries and stable per-document targets; no fuzzy automatic room selection.
4. ElevenLabs reads exact displayed answer text; insufficient/unclear meaning and citations remain visible. Missing credentials, provider failure and playback blocking preserve text usability.
5. Stop/cancel/document replacement/new question/navigation release resources and ignore stale callbacks; provider faults never become evidence judgments.
6. Deterministic adapter/API/browser tests and existing regressions pass; independent changed-behavior review has no unresolved blockers. Live verification and gaps are recorded separately.

Defer always-listening conversation, automatic submission, voice model-control commands, fuzzy resolution, persistent aliases and voice cloning. MP3 is fully fetched before playback; no additional rendering, cloud hosting, auth, database, frontend build or runtime agents.
