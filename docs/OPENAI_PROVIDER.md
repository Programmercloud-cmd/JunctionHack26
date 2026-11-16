# OpenAI provider: setup and verification

Concrete can use Gemini or OpenAI through the same source-first chat, QA, UI and reconstruction pipeline. `AI_PROVIDER` selects the server-wide provider; it is not a per-chat setting. Gemini remains the default. Provider failures never switch to the other provider automatically.

## Configure OpenAI

Edit the existing ignored `.env.local` without replacing unrelated settings. Set `AI_PROVIDER=openai` and configure `OPENAI_API_KEY` privately. The blank key below is a placeholder, not a usable credential:

```dotenv
AI_PROVIDER=openai
OPENAI_API_KEY=
OPENAI_MODEL=gpt-6.1-sol
OPENAI_BASIC_MODEL=gpt-6-luna
OPENAI_DECISION_MODEL=gpt-6-luna
OPENAI_TRANSCRIPTION_MODEL=gpt-transcribe
```

Restart after changing providers or models. The normal `bash scripts/dev.sh` default is localhost port 8000; the current isolated OpenAI verification preview uses **http://127.0.0.1:8013/**. Run `.venv/bin/python scripts/doctor.py` to check configuration/dependencies. Key presence and readiness do not establish successful provider access. OpenAI mode does not need a Gemini key; credentials stay server-side and are never returned to the browser.

The account used for verification exposes `gpt-6.1-sol` and `gpt-6-luna`, and both passed real Responses structured-output probes. Availability can differ for another account. Role overrides are independent from Gemini settings:

| Role | OpenAI setting | Default |
| --- | --- | --- |
| Base model / advanced fallback | `OPENAI_MODEL` | `gpt-6.1-sol` |
| Advanced technical QA | `OPENAI_ADVANCED_MODEL` | base model |
| Source interpretation | `OPENAI_INTERPRETATION_MODEL` | base model |
| Legacy reconstruction | `OPENAI_RECONSTRUCTION_MODEL` | base model |
| Render creator and both reviewers | `OPENAI_RENDER_MODEL` | base model |
| Conversation and basic technical QA | `OPENAI_BASIC_MODEL` | `gpt-6-luna` |
| Routing | `OPENAI_ROUTER_MODEL` | basic model |
| Shared UI actions | `OPENAI_UI_MODEL` | basic model |
| Legacy clarification | `OPENAI_CLARIFICATION_MODEL` | basic model |
| Decisions-compatible support review | `OPENAI_DECISION_MODEL` | basic model |

See [`.env.example`](../.env.example) for explicit role settings and optional OpenAI answer token/deadline/reasoning overrides. Shared QA and reconstruction settings retain their existing meaning. An unsupported model, missing selected key, refusal, output limit or malformed response is an operational error, not a reason to fall back or report insufficient source evidence.

## Same evidence and review contracts

The adapter uses the OpenAI Responses API with strict structured output while retaining the existing prompts, original images/crops, native IFC records, typed schemas and local validation. Transport schema adaptation does not replace canonical Pydantic/domain validation or weaken citation, calculation, source/revision, user-input or geometry checks. Incomplete or rejected output is not accepted as a partial factual answer.

A normal OpenAI model implements the Decisions-compatible contract: each answer returns the existing `choice` selected from the caller's criteria and `confidence: null`. This is compatibility data, not an accuracy score. Product chat still routes the exact original message to a capability and has no evidence-sufficiency preflight. Ordinary factual QA retains router → selected worker → support review, with the existing correction/re-review when needed.

Rendering retains one creator followed by two independent reviewers in parallel against the same reopened IFC candidate. A valid full round has three model calls, separate from routing and source interpretation. Existing source-support/satisfaction votes, Stop, revision guards and retained usable results remain authoritative; there is no new total round/time/cost cap. Sharing this orchestration does not by itself verify OpenAI render transport or geometric fidelity—see the current result below.

Saved Buildings, shared sources, chats, annotations and cached models are not copied or rebound when the configured provider changes. Original-source authority, user-provided measurement attribution, unknown-scale handling and derived-IFC limitations remain unchanged. [Product/source contract](SOURCE_FIRST_CONTRACT.md) · [agentic rendering contract](AGENTIC_CHAT_CONTRACT.md#rendering)

## Transcription and speech output

OpenAI mode uses **`gpt-transcribe`**, configurable through `OPENAI_TRANSCRIPTION_MODEL`. The existing browser websocket sends mono PCM16 at 16 kHz. Audio stays buffered in memory until Stop, then one WAV transcription request produces a final editable draft and completion event. There are no interim transcript updates in this mode and dictation never sends a chat message automatically. Cancel/disconnect before Stop makes no transcription request; in-flight cancellation closes the client. Gemini mode keeps its existing Live adapter, and ElevenLabs speech output is unchanged.

The adapter follows the [OpenAI file-transcription guide](https://developers.openai.com/api/docs/guides/speech-to-text): `gpt-transcribe` receives prompt context plus `keywords` and plural `languages` hints. `VOICE_LANGUAGE_CODES=fi,en` supplies expected languages; existing locale hints such as `fi-FI`/`en-US` map to `fi`/`en`. Keywords are spelling hints, not required words or factual evidence. Unsupported keyword characters remain in prompt context rather than being silently lost. Explicit legacy model overrides keep their corresponding singular-language request path without automatic fallback.

**Representative Finnish/English speech, construction terminology, numbers/units and background noise have not been validated with real recordings.** Transport/fixture tests do not establish recognition quality. Review and edit the draft, especially measurements, before sending. [Voice setup](VOICE.md)

## Verification checkpoint — 16 November 2026

These results distinguish actual provider runs from injected tests. They are local verification; public deployment is recorded separately after activation.

| Check | Observed result |
| --- | --- |
| Account catalog and Luna/Sol structured-output probes | Both configured model IDs passed real Responses requests. |
| Browser conversation on localhost 8013 | Luna-backed `/api/chat` returned HTTP 200 and rendered its answer; no browser script errors. |
| Synthetic-plan interpretation using Sol | Passed. One observed run took 26.4 seconds; this is not a latency/fidelity benchmark. |
| Basic label QA with Luna | Answered with source citations and supported Luna review, one review pass. |
| Advanced QA with Sol and Luna review | Derived **80 m²** from original **10 m × 8 m** dimensions; supported in one review pass. |
| Shared UI with Luna | Original-drawing request returned the validated UI action. |
| Sol rendering | **Completed in one round/three calls:** one creator plus two parallel reviewers, both satisfied/source-supporting for the same candidate. The reopened IFC contains five meshes; exact original source bytes were retained. |
| Deterministic integration checkpoint | **1,188 passed / 149 optional skipped** on the final immutable snapshot; 143 focused provider/voice/render checks also passed. |
| Adapter checks | 26 focused tests passed, including strict schema normalization, original images and ordinary-model decision payloads. |
| Voice checks | 70 focused injected SDK/websocket and existing voice regressions passed. No live multilingual/noise recognition-quality claim. |

Earlier tests found an unsupported `$ref` annotation sibling in OpenAI's strict wire schema; local-reference inlining fixed it without weakening canonical validation. Another test reached both reviewers but correctly withheld a model whose initial floor source box clipped outer walls. The interpretation prompt now requests a complete floor region with a modest margin, preserving separate panels and all existing validators/frozen frames. A fresh drawing then completed the round above; the earlier source/history and manually stopped jobs remain preserved.

A simple-area question in the earlier **gpt-5.4-mini** profile remained unclear after review. That historical result is not a Luna failure or evidence of general accuracy. Successful synthetic tests and reviewer agreement do not establish fidelity on arbitrary building plans. Finnish/English speech, terminology, numbers/units and background noise still need representative real-recording tests.

## Publication

Published at [the agentic demo](https://agentic.95.133.254.90.sslip.io/) as frozen content `21662833b2ccffeeb48c17e6633f9eb95170113a7551083d5f25d3fe2bbd2048`. Actual production Luna chat, Sol interpretation and cited Luna QA passed. Independent public checks confirmed the role map, nine read-only examples and required access code. Activation preserved all 1,550 runtime-file hashes and the original site; the prior release/environment remain available for rollback. See [deployment evidence](AGENTIC_DEPLOYMENT.md#current-openai-provider-release--2026-11-16). Local OpenAI selection uses the user's existing ignored key; no credentials belong in this document or the release archive.
