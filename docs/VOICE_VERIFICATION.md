# Voice verification — 2026-11-14

## Integrated regression

Voice baseline suite: **220 passed in 104.40 seconds**, including the existing real-browser/source/IFC regressions and 44 voice route/provider/browser checks. Command:

```bash
RUN_BROWSER_TESTS=1 PLAYWRIGHT_BROWSERS_PATH=/tmp/junction-playwright IFC_SAMPLE=/home/jcb/dev/github/JunctionHack26/assets/junction-dataset/data/ifc_bench/duplex_arc.ifc bash scripts/test.sh
```

Two additional focused browser cases passed after suite collection: autoplay rejection exposes manual playback without another synthesis request, and a microphone stream resolving after Cancel is stopped. Total: **222 passing checks** (220 integrated + 2 focused). Afterward, user-requested ElevenLabs onboarding replaced the HTTP-only adapter internals with the official SDK. The bounded SDK change passed 39 focused tests and independent re-review; UI/API contracts were unchanged. Dependency diagnostics and `pip check` pass.

Independent read-only implementation reviewer ran 44 focused tests, including actual Chromium. Review cleared Unicode-normalized/idempotent aliases, exact transcript-fragment joining, and fresh consecutive questions while retaining unsent drafts. No outstanding acceptance blockers.

## Live Google verification

A locally generated Flite voice spoke: “Where is the mechanical room on the ground floor?” No uploaded user recording or evaluation answer was used.

- Current Gemini transcription model accepted vocabulary hints and PCM16/16kHz streaming.
- The adapter produced three interim events, the exact final question and successful completion.
- Live service emitted `generation_complete` after final transcription rather than `turn_complete`; the dedicated manual-turn adapter recognizes both. Silence without completion times out explicitly rather than inventing success.
- Real Chromium with a synthetic microphone WAV passed upload → custom vocabulary → Record/Stop → exact editable transcript → existing live Gemini source gate/answer → one source citation. No JavaScript errors. This verifies integration with a synthetic source, not general recognition or answer accuracy.
- Evidence artifacts: `/tmp/junction-voice-live-report.json`, `/tmp/junction-voice-live-browser.png`; synthetic inputs `/tmp/junction-voice-browser.wav` and `/tmp/junction-voice-source.png`. These temporary files contain no credentials.

Two preliminary browser probes timed out because the test attempted to fill a field inside a collapsed details panel. Opening the panel fixed the harness; the final real-browser flow completed.

## Live ElevenLabs and complete voice flow

The HTTP adapter and browser audio path passed deterministic tests. Browser tests use a valid injected synthetic WAV; they do not verify real ElevenLabs MP3 output. User-requested CLI onboarding completed browser authorization and confirmed the saved key and SDK integration. `elevenlabs==2.78.0` is pinned. The account exposes the premade George voice, and the documented model-catalog endpoint confirms `eleven_multilingual_v2` supports speech. Existing Gemini configuration was then securely configured in this worktree’s ignored `.env.local`. The user explicitly approved the credit-consuming test. The onboarding test returned HTTP 200 and saved `/tmp/elevenlabs-hello-HBkSzS.mp3`.

The final real Chromium flow used both live services and the existing source-grounded QA pipeline with synthetic microphone audio and a labelled source drawing:

- Google returned the exact question, “Where is the mechanical room on the ground floor?”
- Blueprint returned a supported answer with two original-source citations.
- The app sent the exact displayed answer text to the official ElevenLabs SDK and received HTTP 200, `audio/mpeg`, 154,270 bytes.
- Chromium decoded the MP3 and playback time advanced. Stop released the audio object and object URL; the answer remained visible.
- No JavaScript errors occurred. This verifies live integration, not subjective voice quality or general transcription accuracy.

Safe artifacts: `/tmp/junction-voice-full-live-report.json`, `/tmp/junction-voice-full-live-browser.png`, and `/tmp/junction-voice-live-answer.mp3`. No provider credentials or request bodies were printed or committed.

## Spoken-answer formatting followup

Final integrated suite after this change: **286 passed in 127.17 seconds**, including real Chromium and native IFC checks, using the command above. Independent read-only review ran **71 focused formatter/integration/browser checks** and additional semantic-preservation probes. No remaining blockers; dependency and patch checks pass.

The formatter has 55 focused regressions covering metadata removal, labelled identifier/citation lists, explicit positive/negative requests, unknown qualifiers, compound sentence subjects, decimal fractions such as `.5 m`, numeric ranges, ordinary bracketed options, window marks, source scope and missing-information/next-action text. Integration verifies formatting occurs after calculation/reference validation without extra inference calls, and optional preparation failure cannot discard written answers. Browser tests verify exact selected speech, the explicit details toggle, null/legacy behavior and unchanged written answers/citations/highlights.

A new **live** Gemini → prepared speech → ElevenLabs → Chromium playback check used a synthetic window drawing. The spoken version retained approximately **1.2 m**, the unspecified width of W2, and unspecified window heights. The full written answer and all **three citations** stayed visible. ElevenLabs returned HTTP 200 and a 328,558-byte MP3; browser playback advanced. Selecting technical details stopped existing audio without starting another request. No JavaScript errors occurred.

Artifacts: `/tmp/junction-window-spoken-report.json`, `/tmp/junction-window-spoken-browser.png`, `/tmp/junction-window-spoken-answer.mp3`; source `/tmp/junction-spoken-windows-source.png`. These verify integration and representative window phrasing, not general building-answer accuracy or subjective pronunciation quality.

## Remaining verification limits

No paired with/without-hints recognition benchmark was run; do not claim measured accuracy improvement. Real microphone/accent/noise quality and voice pronunciation still require user rehearsal.
