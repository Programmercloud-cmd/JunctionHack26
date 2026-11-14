# Chat-first UI — verification and handoff

**Historical checkpoint, not final acceptance.** The user reopened this delivery because factual routing, whole-blueprint navigation, navigation concurrency and visible provenance were inadequate. See the [corrective plan](CHAT_UI_CORRECTION_PLAN.md) and [correction verification](CHAT_UI_CORRECTION_VERIFICATION.md). Successful retries below do not diagnose the original failures or establish acceptance of the corrected workflow.

Implemented in `/tmp/junction-chat-ui`, branch `feat/chat-first-ui`, from `fdfd4e3`. Plan, backend, viewer and integrated UI passed independent review, including direct Chromium interaction. No push or modification of another worktree. Reconstruction, refinement, QA, persistence and provider implementations remain owned by the main session.

## Delivery

[CHAT_UI_PLAN.md](CHAT_UI_PLAN.md) records the reviewed plan; [CHAT_UI_CONTRACT.md](CHAT_UI_CONTRACT.md) defines captured workspace, typed actions, identity resolution and existing-operation adapters. Main-session agreement and integration replies are in `/tmp/junction-ui-coordination.md`.

Initial presentation is chat with attachments. Visual requests open a right workspace. Chat covers saved buildings, upload/append, source/model/concept views, selection, cameras, tours, independent visibility, floors, cutaway, separation, comparison, assumptions/inventory, downloads, retries, reconstruction/refinement and job stopping. Existing app.js operations retain hidden compatibility DOM anchors; they are not exposed toolbars. Answers render once with citations/checks. Exact Chronicle light/dark tokens come from `AI_Chronicle_UI/src/web/styles/global.css`, blob `4396f7a3594369ea3a38c6c0ebdb620496f9703c`.

Submission synchronously pauses the tour and copies focus, ordered IDs, position, camera and revision. Code resolves identities; no screenshot rediscovery. Interpretation and geometry revisions remain separate. Navigation/answer highlights and assumptions are independently controlled. Failed/rejected/stopped operations retain usable evidence and model state.

## Automated checks

- Required `bash scripts/test.sh`: **563 passed, 36 optional skipped** after the final proposal preservation change.
- New Chromium suites (`test_chat_ui_browser.py`, `test_chat_viewer.py`): **11 passed** in 27.70 seconds.
- Independent backend rerun: **27 passed**.
- Environment doctor: Python 3.12.3 and required existing packages available. No dependency change.
- Diff validation clean.

Deterministic fixtures cover source-only upload/QA, both palettes, long-chat layout, cached/deferred model selection, recoverable errors, delayed tour interruption beyond the five-second timer, exact source/back-next, visibility independence, refinement outcomes, recovery-event revision pins, removed-object evidence, camera preservation, repeated identical QA, mismatched responses and visual controls. Viewer fixtures additionally use physical pointer orbit, rotated meshes, uncertain orientations, geometry-less records and atomic revision replacement. These verify mechanics, not model inference quality.

## Independent browser review

The reviewer directly used actual saved11397 and native duplex geometry with explicitly intercepted deterministic intent responses, inspecting both themes at desktop/narrow sizes. Eight-window selection, top-down, tour/captured interruption, pinned original evidence, same-tour next, assumptions/highlights, failures, unresolved source-only records, orbit/zoom/pan, floor/cutaway/separation and native property records passed without JavaScript errors or phantom native drawing pages. Recovery/revision cases were independently exercised in Chromium.

Review found and cleared desktop grid overflow, dark-button contrast, recovery-event DTO mapping, quantity/calibration attribution and automatic revision-selection handling. The reviewer did not implement reviewed changes. Private evidence: `/tmp/chat-ui-review/REVIEW.md`, scripts, reports and screenshots.

The final proposal hook was independently exercised on actual saved1794: physical canvas selection, explicit non-factual attribution, exact host-source revision/bbox, four proposals listed separately from 36 source objects, no invented source for a missing-host fixture, and unchanged navigation epoch during automatic refresh. All assertions passed with zero browser errors in `/tmp/chat-ui-review/proposal-report.json`. The reviewer produced this browser evidence before its final reporting turn hit the session usage limit; the root inspected its script, report and screenshot.

## Actual artifacts and backend operations

The separate `.runtime/chat-ui-verification` store contains unchanged imports:

| Artifact | Verified state |
|---|---|
| `/tmp/junction-fidelity-v4/schematics/1794.ifc` | Drawing-derived; 2 rendered windows; original page retained. |
| `/tmp/junction-fidelity-v4/schematics/11397.ifc` | Drawing-derived; 8 rendered and 2 unresolved windows; original page retained. |
| Native `duplex_arc.ifc` | Genuine IFC; no drawing pages/extraction jobs; original record inspection. |

These are saved interpretation/model counts, not extraction completeness. Both derived IFC downloads are byte-identical to their imports; scene/geometry revision IDs agree; pinned page URLs return original PNGs. Reopening/navigation made no reconstruction call. Evidence: `/tmp/chat-ui-artifact-check.json`.

A separate unchanged1794 run used **real HTTP/refinement jobs, IFC generation/reopening and browser polling**, with **deterministic injected review judgments, not live inference**:

- Accepted `2 relative` display height: complete job, new revision and actual Z geometry; 36 IDs and two-window selection preserved; camera drift zero.
- Rejected `2.4 relative`: needs_attention; accepted revision/geometry unchanged; submitted value retained and labeled “submitted; see outcome”.
- Two `/refinements` requests, two injected judgments, zero browser errors. Entry used the typed chat action adapter, not natural-language refinement interpretation. No QA/reconstruction endpoint or new network-provider call was claimed.

Independent review checked the script, saved scenes/jobs and screenshots. Evidence: `/tmp/chat-ui-real-refinement/report.json`; its temporary server was stopped.

## New live Gemini evidence

Configured Gemini and the existing reviewed QA pipeline were used; no production fixture/fallback. Final live Chromium sequence on saved11397 passed:

| Message | Result | Intent latency |
|---|---|---:|
| Show me all windows in the 3D model. | Cached model; 8 rendered IDs, 2 separately unresolved. | 14.69 s |
| Show this from above. | Top-down, selection retained. | 15.32 s |
| Show the windows individually. | Ordered geometry-oriented tour. | 22.09 s |
| Show this window in the original blueprint. | Immediate submit pause; exact captured ID/bbox and pinned revision. | 9.40 s |
| Back to the model; next window. | Restored model; same tour advanced once. | 8.15 s |
| Use dark theme. | Exact Chronicle palette. | 7.95 s |
| What actual ceiling height is established by the original drawing? | Existing QA returned **insufficient**, one inspection, no invented height. | 18.21 s routing |

QA reported 27.481 s and 118,657 input/831 output tokens. Intent calls used approximately 7.3–7.6k input tokens each. No JavaScript errors. This is one real sequence, not general language/reconstruction accuracy. Evidence: `/tmp/chat-ui-live-browser/report.json` and screenshots.

The first live source command failed: a broad operation union emitted two model actions. Prompt clarification alone reproduced it. The repair uses one explicit wire action-type enum, then strict per-operation validation; unrelated non-null fields are rejected. A focused live probe resolved the exact source object in 6.15 s, followed by the complete passing sequence. No runtime retry, regex navigation fallback, new model or provider-pipeline change was added. Failed-run evidence is retained in `/tmp/chat-ui-live-browser-first-failure` and `/tmp/chat-ui-source-intent-after-fix.json`.

An additional positive factual question, “Name one room label that is clearly visible in the original drawing”, initially failed operationally during intent routing before any QA job. The first browser harness did not preserve the underlying provider/validation failure, so its cause is unknown. A controlled diagnostic on a copied store subsequently returned a valid, revision-pinned `question` action in 16.11 seconds with unchanged code (`/tmp/chat-ui-question-probe/report.json`). This does not erase the original failure or establish a fix; no runtime retry was added.

The complete live browser recheck on saved1794 then passed: 15.14-second intent, existing QA `answered` with one evidence citation and one inspection (27.831 seconds; 57,520 input/698 output tokens), workspace stayed closed until citation selection, exact original bbox/revision opened, and zero browser errors. Evidence: `/tmp/chat-ui-live-positive-recheck/report.json`. Its first assertion incorrectly expected `sufficient`/`citations` instead of the existing `answered`/`evidence` schema; the corrected check reopened the persisted live answer and clicked its citation without another inference call. This verifies original-source QA with a cached model present, not fresh source-only extraction.

## Choices and limitations

- Natural-language navigation makes one intent call (about 8–22 s measured). Compact controls and manual orbit/zoom/pan are deterministic and avoid that call. Tour pause/capture occurs immediately.
- One extra factual intent failed operationally and succeeded on later explicit verification calls with unchanged code; the original cause was not captured. General intent reliability remains a limitation, not a claim established by the successful sequences.
- Tour timing is five seconds, with pause/next/resume; no object cap was added.
- Actual mesh covariance guides close-ups. Minor/major horizontal variance below 0.16 permits a geometry-aligned view; ambiguous axes get a labeled approximate oblique view. This never changes geometry or establishes exterior orientation. Z-up top-down retains the orbit controller's numerical epsilon.
- Persistent numeric edits require an explicit quantity/unit pair; digits/common English number words are supported. Unrecognized phrasing clarifies. Calibration currently requires normalized original-page endpoints plus distance: the navigation catalog has no authoritative distance endpoints to invent. Model-authored boxes cannot replace exact scoped saved source regions.
- Fresh live extraction/reconstruction and live refinement-quality assessment were not repeated here; those are the main session's work. Existing source-fidelity limitations remain. OpenAI transport is deterministically tested, not newly live-verified.
- Navigation/progress turns are session UI state. Existing factual conversation/building/job persistence remains backend-owned.
- Legacy browser tests tied to removed toolbars remain opt-in; the new suites cover changed interactions, and the full default suite passes.

## Run and integrate

Private local verification server: `http://127.0.0.1:34551`. It serves only the isolated UI store and loads existing credentials without copying/printing secrets. Stop it before starting another process against that store. For standalone setup use normal bootstrap/environment configuration, then:

```sh
BLUEPRINT_STORAGE_ROOT=.runtime/chat-ui-verification PORT=34551 bash scripts/dev.sh
```

This checkout uses an ignored `.venv` symlink to the existing environment. Private scripts, stores, screenshots, originals and provider results are not committed.

Focused commits: `2525c8a` plan/contract; `258fe74` viewer; `cf7ed66` routing; `0068ebf` chat UI; `e9cb6a8` live source-routing repair; `bc8caf8` proposal attribution. Final documentation commit follows in branch history. Main reliability commits `f932467`, `3064e21`, `5f6eb51` were not cherry-picked. Preserve both sets on integration: the chat renderer understands recovery events, event-specific base revisions/evidence and submitted-versus-applied attribution.

This is a **local UI** delivery. The main session's later public-access/deployment work is separately owned. No unlock UI, visitor isolation or shared-example copy contract was invented here. HTTP401 is displayed as an operational error and never silently retried. Public catalog scoping and mutation authorization must be enforced by deployment integration, not assumed from chat selectors.
