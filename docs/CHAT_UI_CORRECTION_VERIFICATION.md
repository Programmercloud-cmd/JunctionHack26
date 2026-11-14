# Reopened chat UI correction — verification and integration

This is a corrective release candidate, **not full acceptance of the reopened workflow**. The UI defects described below are corrected and independently browser-reviewed. Fresh live window-count questions reached existing QA but failed in provider calls; one live source intent also timed out. These failures remain open and are not erased by fixture passes or historical successful retries.

## Base, coordination and ownership

All original UI commits through `9b20a0b` had already been integrated. This work uses `/tmp/junction-chat-ui-corrections`, branch `feat/chat-ui-corrections`, from main `9a001f3`. Main's reviewed `37c4dd1` was cherry-picked as `fe44534` before controller edits, preserving its mapping notices, submitted-value attribution, model-poll join and comparison-layer fixes. No other worktree was modified or pushed. Main owns integration/deployment, provider transport/settings, QA, reconstruction/refinement, persistence and public access.

The reviewed plan is [CHAT_UI_CORRECTION_PLAN.md](CHAT_UI_CORRECTION_PLAN.md); the updated contract is [CHAT_UI_CONTRACT.md](CHAT_UI_CONTRACT.md). Main agreed the narrow routing and ownership changes in `/tmp/junction-ui-coordination.md`. Existing public access, exact example revision pins, immutable models, provider switch and all operation endpoints remain intact. No new dependency, inference runtime, format, model, timeout, retry or processing budget.

## Failures reproduced and corrected

- Exact “How many windows does this building have?” on actual saved 1794 and 11397 produced valid live `question` actions with an `all`/window selector. The old resolver incorrectly required exactly one object and returned clarification instead of QA. General selectors now preserve original wording/document revision and delegate to existing source QA; no mesh/inventory count becomes an answer. Explicit focused/named references remain validated and revision-pinned.
- Physical orbit/wheel during a delayed valid question changed navigation epoch and discarded the entire response, with zero QA submissions. Questions now have a captured document/revision/reply lifetime independent of viewer movement. Mixed batches suppress stale camera/navigation effects only. Genuine cross-document visits, forged responses and stale mutations remain rejected.
- A no-selector whole-blueprint request now opens a whole supplied page with `bbox:null`, not an implicit selected object. Source/page controls are direct and revision-aware. Failed image preloads retain the previous view. Old source citations never borrow current page labels/bounds or current user values.
- Persistent Blueprints/3D model/Return to selection, page choices, themes and independent overlays work without intent inference. No-model tabs do not reconstruct. An explicit build action still uses the existing operation. Provider-unavailable local mode retains the visible saved-building entry point.
- Selected-object evidence is persistent outside chat scrolling. Presence, representation, property origin, object/floor assumptions, matching-revision user inputs and exact source links remain visible with overlays off. The legend distinguishes observations, interpretations, derivations, user values, assumptions, unresolved records and non-factual proposals. A source link does not validate every property. A markers use actual selected/highlighted meshes; unresolved records have no fabricated mesh.
- Review found that disabling selection highlight left clicked-object emissive styling visible. The new appearance flag suppresses inspection/concept selection styling while retaining the selected ID, source and camera. Answer highlights and assumptions remain independent.
- A new group selection now clears the previous focused inspector and viewer selection, retaining the new group IDs. This prevents a stale “Show in original” button from implying the old object is still the captured referent.
- Review also found stale clarification responses could hijack a later free-text request. Clarifications/suggestions are request-bound; older responses cannot take over newer input.
- Main's fresh 1732 findings are covered: restored answers retain job/request identity to avoid duplicate cards after polling; workspace headers use existing terminal outcome labels; terminal failures remove pending-model progress without deleting job/evidence history.
- The full browser suite found an integration regression: explicit comparison after reconstruction retained the earlier source revision, so the correct cross-revision guard hid the overlay. Enabling comparison now opens the model-pinned original first. Independent browser review on two actual saved 1794 revisions confirmed the overlay appears on the matching original and disappears again when returning to exact older evidence. Failed page loads retain the previous view. The revision guard remains intact.

## Credential-safe diagnosis and remaining live failures

The historical generic count exception cannot be reconstructed: the old boundary discarded its cause. We do not claim the plural-selector fix proves that exception's root cause. The additive router now emits one safe diagnostic per failing invocation: application-generated reference, stage, exception class, schema-known field paths/error types and numeric HTTP status where available. Unknown JSON keys, prompt/request IDs, bodies, source text and exception messages are excluded. The generic response includes the reference. `httpx.TimeoutException` receives an explicit timeout outcome; no retry or evidence-insufficiency conclusion is added.

Fresh live Gemini browser runs used unchanged actual saved originals/models and the configured Gemini provider:

| Actual run | Observed outcome |
|---|---|
| saved 11397, no selected object, “Show the original blueprint” | Valid source action in 9.49 s; pinned whole original opened without an invented region. |
| saved 11397, exact window-count question during physical orbit/wheel and source/model switches | Valid question action in 9.26 s and exactly one QA submission. QuestionIntent and source gate validated; DraftAnswer provider call failed after 44.901 s against its existing 45 s timeout. No answer/evidence conclusion. |
| saved 1794, same whole-blueprint request | Valid source action in 9.77 s; exact original opened. |
| saved 1794, exact count during the same combined interactions | Valid question action in 11.61 s and one QA submission. Existing QA QuestionIntent failed with provider_error after 58.896 s; no finish/tokens returned. No answer/evidence conclusion. |
| saved 11397, tour then “Show this window in the original blueprint.” | Intent HTTP 502 after 46.95 s. Safe log captured `provider_response / ReadTimeout`; no action executed, model/source retained. |

Main independently confirmed that provider, source-context and reasoning code are byte-identical between the worktrees. The configured 45 seconds is an inactivity timeout; stage elapsed time also includes preparation. The QA records do not preserve the underlying exception class/status, so those failures cannot be conclusively labeled `ReadTimeout`. The later intent failure does preserve that class. No schema incompatibility or duplicate QA call was demonstrated.

Thus **fresh successful end-to-end count QA and live tour/source continuation are not established in this pass**. Count routing and navigation concurrency are demonstrated separately from provider completion. These failures were sent to the main session with private job/call metadata; no core files or limits were changed to hide them, and further blind retries stopped.

Private evidence: `/tmp/chat-ui-correction-diagnosis/` (three baseline semantic probes), `/tmp/chat-ui-corrective-live/report.json`, `/tmp/chat-ui-corrective-live-1794/report.json` plus `failure-stages.json`, and `/tmp/chat-ui-corrective-tour-live/report.json`. These contain verification records, not runtime fixtures or fallback logic.

## Independent actual-browser evidence

The reviewer directly used Chromium, actual saved 11397/1794 originals and geometry, and a separately imported previously accepted 11397 with user-supplied 1.6 relative height. Intent/QA delays in combined race checks were explicitly deterministic fixtures, not inference. Reports are under `/tmp/chat-ui-corrective-review/`:

- `combined-report.json`: whole-page no-focus view; camera/tour-preserving source/model switches; captured focused QA through physical orbit, changed selection and stale mixed navigation; exact source regions; both themes and narrow layout; recoverable source failure; zero reconstruction and JavaScript errors.
- `provenance-report.json`: actual accepted user height, independent overlays, exact source revision/bbox, actual unresolved objects and decorative proposals without changing source counts.
- `old-source-report.json`: two real stored revisions; old exact citation retained while current input rows are excluded; current whole-page browsing remains unhighlighted.
- `selection-highlight-report.json`: retained selected ID with appearance disabled; independent answer state.
- `public-browser-report.json`: real local public middleware plus an actual pinned example, test-only access credentials and a provider that cannot run. Anonymous direct controls work, no conversation request, intent 401, unlock without replay, immutable mutation 409, zero provider calls. This is not a public deployment test.
- `logging-boundary-report.json`: unexpected outer-boundary failure is logged once with a correlated reference; private exception values redacted and provider closed.

The final independent review is `/tmp/chat-ui-corrective-review/IMPLEMENTATION_REVIEW.md`. Additional rechecks cover request-bound clarifications, terminal status/history, cleared stale group evidence, provider-unavailable entry, distinct legend rows in both themes, and fixture-only page/source choices. Independent reviewers did not implement reviewed changes. Aggregate final checks are recorded below.

## Final checks and acceptance status

Final command, on the committed runtime implementation:

```sh
RUN_BROWSER_TESTS=1 PLAYWRIGHT_BROWSERS_PATH=/tmp/junction-playwright bash scripts/test.sh
```

**791 passed, 1 skipped in 301.93 seconds.** The earlier full run had 788 passes, one skip and the comparison regression described above. That regression was fixed, independently rechecked on actual artifacts, and covered by the final full run plus a dedicated failed-page/revision regression. `git diff --check` is clean. No failing automated check was discarded or relabeled as a pass.

Independent plan review and implementation review are complete for the bounded UI corrections, including direct browser interaction. No UI implementation blockers remain from those reviews. **Overall live acceptance remains open**: both fresh exact-count QA attempts failed in existing provider calls, focused-source intent timed out, and the historical generic exception has no recoverable cause. These are handed back to the core-owning main session with safe evidence; successful fixtures, earlier retries or unrelated public QA do not close them.

## Artifact integrity

Real HTTP export checks on saved 1794, saved 11397 and the accepted-height 11397 all remain byte-identical to their imported IFCs, drawing-derived, with unchanged model revision and zero extraction/reconstruction/refinement jobs. Original source navigation uses stored coordinates and revisions. Evidence: `/tmp/chat-ui-corrective-artifacts.json`. The accepted-height file was imported from an existing reviewed artifact; no new refinement inference was performed here.

Multi-page/source discovery, no-model states, stale mutation guards and precise asynchronous races also use explicitly labeled deterministic fixtures. This pass does not establish new extraction/reconstruction fidelity, live OpenAI behavior, successful fresh count inference, or deployment acceptance.

## Focused commits and integration

| Commit | Change |
|---|---|
| `a8f6204` | Independently reviewed corrective plan. |
| `af2ee31` | General factual scope, whole-original navigation and credential-safe intent diagnostics. |
| `bcaad71` | Specific safe transport-timeout outcome and diagnostic correlation checks. |
| `70f8bb6` | Independent viewer selection appearance and assumption markers. |
| `28f12e7` | Captured question lifetime, exact source revisions, comparison and terminal/history corrections. |
| `e7b873c` | Compact navigation, themes, independent toggles and persistent property provenance. |

These changes follow `fe44534`, which is already present in main as `37c4dd1`; do not apply that shared commit twice. Main's release `a470a11` adds no further changes to the owned runtime paths after `37c4dd1`. Integrate the focused corrective commits onto the current main state rather than replacing files or resetting the other worktree. This branch does not deploy or change public configuration. The final documentation commit records this contract and handoff.

The isolated local preview on port 34552 was restarted onto the final code without running new inference. Its copied verification store retains successful navigation and failed QA jobs for inspection. Private `/tmp` evidence is local to this machine; the durable conclusions and limitations are recorded here.
