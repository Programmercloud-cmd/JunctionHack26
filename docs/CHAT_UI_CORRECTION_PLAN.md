# Chat UI corrective plan

Status: independently reviewed and approved in one round, with no blocking planning gaps. The reviewer directly operated the baseline in Chromium; approval concerns this corrective plan, not implemented acceptance. The prior `CHAT_UI_VERIFICATION.md` records historical checks, not acceptance of the reopened user failures. Worktree `/tmp/junction-chat-ui-corrections`, branch `feat/chat-ui-corrections`, base integrated main `9a001f3`. All seven prior UI commits were already integrated. Main's uncommitted changes remain untouched; coordination is `/tmp/junction-ui-coordination.md`.

## Scope and ownership

Correct the five reported interaction failures with the existing plain JS UI, Three.js viewer, additive chat-action router and operation endpoints. The user explicitly permits compact visible controls: chat-first no longer means chat-only. Keep exact Chronicle themes. Do not add a frontend framework, renderer, inference runtime, format, provider, dependency or increased inference/reconstruction budget.

| Owner | Files / bounded work |
|---|---|
| Planner | This plan only; respond to independent findings. |
| Root | Coordination, final action/state contract, integration, diagnostics and focused commits. Own new `app/static/workspace-controls.js`/`.css`, `index.html`, minimal `app.js` hooks and dedicated control/provenance browser tests. Own `viewer.js` only if an actual marker gap requires a small correction. |
| Backend implementer | `app/chat_actions.py` and new dedicated action tests; safe router diagnostics and evidence-backed intent repair, whole-document source resolution. |
| Frontend implementer | `app/static/chat-workspace.js` and dedicated controller browser tests: action lifetimes, captured QA context, exact source/view state, public-access compatibility and controller hooks for persistent controls. |
| Independent reviewers | Read-only plan/implementation review; directly use Chromium against actual sources/models and combined interactions. Reviewers do not implement the change they independently approve. |
| Main reliability session | Providers, QA/sufficiency/review, reconstruction/refinement, persistence, public-access enforcement and deployment. No rewrite or replacement of these files. |

Main's pending controller changes add unmapped-answer/floor notices, submitted-value scope/reason, a completed-model polling race fix and comparison-layer behavior. Incorporate only coordinated committed deltas; do not restore whole files or overwrite main's working tree. Preserve integrated `access.js`/`access.css`, gated composer, no automatic paid replay, pinned immutable examples and anonymous conversation suppression. A public-control change must stay within the agreed server policy; client selectors never become authorization.

Main has agreed this corrective ownership and is freezing/reviewing its pending controller delta. Cherry-pick that reviewed commit before controller implementation. Main owns migration of legacy `test_browser*.py`, `test_revision_recovery_browser.py` and `test_sourcefirst_browser.py`; use dedicated corrective tests to avoid overlapping edits. Local isolated browser verification is authorized; do not run concurrent paid requests against the public deployment.

Dependent implementation begins after planning blockers are resolved. Maximum two plan-review rounds; root resolves remaining disagreement with evidence or scope reduction. An implementation blocker remains open until fixed and independently rechecked, or explicitly reported as unresolved.

The controller remains the single owner of selection, tour, navigation state and typed execution. The new compact-control module renders controller state and invokes its deterministic interface; it does not create another state machine or bypass existing operation/access adapters.

## 1. Diagnose factual routing before changing its behavior

Reproduce the exact message **“How many windows does this building have?”** on an actual saved drawing-derived model with originals. Preserve a credential-safe diagnostic for each failing stage: request validation, configured-provider transport/structured response validation, canonical action validation, identity resolution or public-access rejection. Record request correlation, exception class, safe validation field paths/error types, provider usage and outcome; never log credentials, raw request/response values, source bytes or dataset reference answers. The existing catch-all safe error cannot be the only diagnostic. Also capture the first failure; later success is not a diagnosis.

Inspect the actual offending structured shape when available through a private controlled probe, exposing only types/field names in the report. Repair only the demonstrated router contract/prompt/validation mismatch. Keep the existing configured Gemini/OpenAI switch, one intent call, provider closure and strict identity/argument validation. Do not broadly ignore malformed non-null fields, substitute mesh counts, silently retry, or implement a parallel QA pipeline. If the cause is upstream or cannot be reproduced, retain the failure and state the diagnostic limit plainly instead of claiming it solved.

A factual count produces a `question` action and sends the original wording through existing `/api/questions`, including the existing sufficiency gate, source inspection, citations, review and refusals. The intent catalog is navigation data. “How many windows does this building have?” must not be answered from renderable IDs, inventory totals or interpretation coverage. “Select all modeled windows” remains a deterministic selection of saved renderable records, explicitly separate from a source count.

## 2. Whole-document and focused source navigation

Define two distinct cases within the existing source action contract before dependent implementation:

- `show_source` with no object selector and no page means browse the supplied originals at the captured interpretation revision. It opens the retained valid whole-page choice or the first supplied page, never implicitly the focused object. A visible source/page chooser lists all supplied originals using original filename/source-page labels. Opening a collection does not require clarification merely because it has several pages.
- An explicit page resolves against that revision's supplied page catalog. Keep chooser metadata and served image URL on the same revision, including after opening old selected-object evidence. A named source/page ambiguity may ask a focused clarification with discoverable exact choices. Do not interpret absence of a selected object as source ambiguity.
- “Show this object in its original blueprint” uses the captured object's saved geometry revision and exact stored source reference/bbox. Whole-page navigation has no fabricated highlight region. No nearest-object association, tighter crop or changed coordinate system.
- Native IFC has original records, not drawing pages. Expose record guidance/control without an empty or invented blueprint. Public example source/page reads stay manifest-pinned.

Record any small DTO addition (such as an explicit whole-document target) in `CHAT_UI_CONTRACT.md` and coordinate it before dependent edits. Prefer the current no-selector semantics and page metadata over a new route or persistence format.

## 3. Persistent compact navigation

After a document opens, show a compact persistent control strip with **Blueprints**, **3D model**, supplied page/source choice (with previous/next where useful), and **Return to selection**. Provide accessible labels/current state and keyboard focus; controls remain discoverable when chat scrolls and at narrow viewport widths. Keep a small theme choice and legend/toggles near the workspace, without restoring sprawling settings panels.

These controls execute local typed actions immediately and never call `/api/chat/actions`. Tabs do not call QA or reconstruction. If no model is saved, the 3D tab shows a clear no-model state and an explicit “Build model” action using the existing operation; clicking the tab itself must not request generation. Missing drawings similarly show accurate native/source guidance. A failed read is recoverable and retains the current usable view.

Switching views preserves the saved model camera, selected IDs, focused object, ordered tour IDs/index and independent visibility settings. Pause an active tour while viewing original evidence without resetting its position; returning alone does not advance or reframe. **Return to selection** is the explicit framing action. “Back to model; next window” continues the same tour exactly once. Page navigation is independent of focused selection: users can browse other pages and then return to the exact selected-object evidence.

## 4. Separate question lifetime from navigation lifetime

Keep the existing immutable submission capture: pause tour synchronously, then capture document identity/epoch, interpretation and displayed geometry revisions, focused ID, selected IDs, camera, tour and navigation epoch before awaiting. Also capture QA clarification/reply context rather than reading a later mutable `state.clarificationReply` at dispatch.

Use explicit per-action execution classes, not one blanket stale-response check:

| Class | Guard and outcome |
|---|---|
| Factual `question` | Validate echoed request/document/revision context. Within the same document, execute once against the captured revision/reference despite orbit, zoom, pan, selection change, page/view switch or another harmless navigation. A later selection cannot replace “this object”. Existing QA revision rules remain authoritative. |
| Workspace navigation | Requires the captured navigation epoch as well as document identity. If the user has since moved the view, suppress only the delayed navigation/camera effect; do not cancel a valid factual question in the same response or show a generic interruption error. Provide a precise unobtrusive status only when needed. |
| Persistent operation | Retain server validation and captured base revision, immutable-example checks and existing job rules. A changed document/revision rejects the operation; never silently rebase or re-target it from current selection. |

Validate response identity before dispatch even when its navigation part is stale. Handle mixed question/navigation batches explicitly: the original source question remains executable without applying stale movement, and no implicit navigation dependency can alter its reference. Do not execute stale dependent navigation after pending reconstruction. Genuine cross-document switches discard undispatched work from the old document; already submitted jobs remain backend-owned and must not move or populate the new document's workspace. Revisions changed during processing stay pinned/visibly attributed; do not treat camera movement as a revision change. Avoid global busy locks and deduplicate dispatch by request identity.

QA completion must not steal the camera, change the current tab, restore old selection or erase the composer. The answer may update its independently controlled highlight set only where mappings are reliable and revision-compatible. Source citations retain their answered revision even if current geometry changed.

## 5. Visible provenance at object and property level

Provide a persistent compact selected-object summary adjacent to the workspace, outside scrolling conversation and independent of overlay visibility. Show original label/stable identity, representation (reconstructed/schematic/unresolved), stored evidence basis, source page/record and revision, plus **Show in original** using the exact stored reference. Retain prior-revision evidence for removed objects with a clear stale/removed label. Selecting an unresolved item shows its evidence and missing-geometry state without inventing a mesh or frame target.

Render property distinctions from existing authoritative fields rather than infer them from rendering: `SceneElement.properties[].origin`, element/floor `assumptions`, `evidence_basis`, relevant scoped assumption rows and saved user-value attribution. Presence marked depicted in source does not establish height, placement, dimensions or every other property. Label source observations as saved source-supported interpretation, derivations as derived with supplied basis where available, user values as user-provided (not observed), display choices as display assumptions, unresolved/unknown fields explicitly, and decorative proposals as non-factual and excluded from QA/counts/IFC export. Missing provenance remains unknown/interpretation; a source button is not a blanket validation badge.

The existing assumptions endpoint returns a revision ID. Only combine its rows with selected geometry when their revisions match; otherwise show the newer interpretation rows separately with their revision or use the pinned scene's own stored assumptions. Do not silently attach current user values to an older displayed object. If additional pinned server data is genuinely needed, propose the narrow interface to the main session before implementation; do not add a parallel persistence/read path.

Show a discoverable legend explaining observation, derivation, user-provided, assumption, unresolved and proposal labels. Manual controls for **Answer highlights**, **Selection highlight**, and **Assumption overlays** are independent. Reuse existing viewer assumption markers; inspect their visibility and selection behavior on real models. Toggling assumptions must not hide selected-object provenance, change camera/selection/tour or make a source-linked presence validate assumed properties. Proposals use their own visible summary and optional host-support link labeled as host evidence, not proposal evidence.

## Verification and acceptance

Start with deterministic regression fixtures for the observed bugs, then actual artifact/HTTP/browser checks and fresh live Gemini runs. Fixtures may delay responses or inject a precise invalid wire shape to make races/failures reproducible; clearly mark them and never put a fixture fallback in production. Do not rerun reconstruction merely to obtain review data. Reuse unchanged saved models/originals, including renderable windows and separately unresolved objects. Use copied isolated stores and record endpoint/provider-call counts to prove navigation/source QA did not invoke extraction/reconstruction/refinement.

The independent plan reviewer must directly operate the baseline browser, including ordinary source navigation and a delayed question plus physical orbit. The independent implementation reviewer must directly perform the changed integrated flow, not merely read tests or screenshots. Minimum acceptance matrix:

1. Exact live window-count question reaches existing QA and produces supported original evidence or an honest insufficiency/unclear refusal; no modeled-count substitution. Preserve any failures with their safe diagnostic stage. Try ordinary paraphrases and focused questions, not only the exact regression string.
2. “Show the original blueprint” with no selected object opens originals. Multi-source/page choices are discoverable and direct; “this object” opens its exact captured bbox/revision. Whole-page viewing adds no invented evidence region. Native record behavior remains honest.
3. Physically orbit, zoom and pan while intent interpretation is pending; also switch Blueprints/3D and pages while intent and QA are processing. The question runs once and completes in chat with captured revision/context, while camera/tab remain where the user put them. Repeat with a changed selected object, multiple concurrent questions and a mixed question/navigation response. Preserve existing clarification follow-up attribution independently for each captured request.
4. A genuine cross-document switch and stale refinement still protect the current workspace. Failed routing, page HTTP failure and rejected mutations retain sources/model and allow another operation; public 401 offers the existing unlock flow without automatic replay.
5. Tabs/page/return-selection work with provider unavailable and anonymous pinned examples without paid requests. No-model tab does not reconstruct; explicit existing build action still works with its original access/review protections.
6. Inspect actual objects with source-supported presence plus assumed height/placement, a user-provided value, derivation and unresolved record. Summary and source link remain visible with assumption overlays off. Each of the three highlight/toggle states can change without changing the other two. Decorative proposals stay distinct and do not change factual counts.
7. Start a tour, switch to the exact original source, return to unchanged model camera/selection/tour position, then advance once. Verify both themes, desktop/narrow layout, keyboard access and no browser errors.
8. Run focused routing/public-access/controller/viewer tests and required repository checks. Test no source coordinates/IDs/revision provenance changes, provider switch retained, immutable examples remain protected, and no paid inference caused by direct navigation.

Completion requires reproduced-failure evidence, the demonstrated fix or explicitly unresolved cause, independent direct-browser review without blocking findings, passing required checks and a new truthful handoff. Record fixture vs actual-artifact vs live-provider evidence separately, latency and residual failures. Focused commits only; no push or main-worktree writes. Historical successful retries and test counts alone do not satisfy acceptance.

## Independent plan review evidence

The reviewer directly interacted with actual saved11397 and original sources in both themes. Physical orbit/wheel during a delayed deterministic response to the exact window-count question suppressed the valid question action (zero QA posts) and displayed the generic superseded message. The reviewer also confirmed missing visible manual navigation/assumption controls and a selected-object card that scrolled away and lacked property-level provenance. Evidence is retained at `/tmp/chat-ui-corrective-review/baseline-report.json` with screenshots. Deterministic intent delay demonstrates the race, not live inference reliability. The reviewer approved this plan and the controller/control-module ownership split without blockers; implementation still needs the full independent browser/live acceptance above.
