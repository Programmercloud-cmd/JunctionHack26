# UI correction integration — 2026-11-14

The reviewed UI delivery through `40a2809` was integrated onto `blueprint-qa-isolated` without replacing files or disturbing existing untracked project/dataset directories. The tracked working tree was clean at `8077096`. The shared `37c4dd1` change was not applied twice.

| Delivered commit | Integrated commit |
| --- | --- |
| `a8f6204` | `a8efe04` |
| `af2ee31` | `50f9161` |
| `bcaad71` | `119e415` |
| `70f8bb6` | `4e12e15` |
| `28f12e7` | `de5862a` |
| `e7b873c` | `fb5944e` |
| `40a2809` | `97f5832` |

No conflicts occurred. The public-access middleware, exact example revision pins, immutable-model guards, provider switch, reconstruction/refinement pipelines and deployment configuration were preserved. The UI-owned changes retain the source/geometry revision distinction, original coordinates and independent highlights/assumptions.

## Independent integrated verification

A private snapshot of the live server was verified before serving it locally on HTTPS port 8774: all 613 copied file hashes matched an unchanged live snapshot, with 14 buildings, 11 terminal jobs and nine public examples. No credentials were included in the archive. Two additional historical failed-case bundles were copied unchanged from the UI worktree for controlled live comparison. Public storage was not replaced with this test copy.

The independent reviewer directly used Chromium against the integrated application and actual artifacts. Verified behavior includes:

- Anonymous source/model tabs, source navigation, tour and independent controls without paid calls; code unlock without replay and immutable-example rejection.
- Captured QA during physical orbit, tab changes and selection changes, including stale mixed navigation. This precise race used explicitly injected HTTP responses; it is not a live model claim.
- Persistent property provenance, both themes and narrow layout.
- Fresh 1732's single restored answer card, accurate terminal `needs_attention` header and removal of stale pending-model progress.
- Exact old QA source revision hiding mismatched model overlays; explicit comparison opening the model-pinned source; old evidence hiding the overlay again.

No JavaScript errors or scoped UI implementation blockers were found. The integrated full browser-enabled suite passed **811 tests, one skipped, in 302.19 seconds**. Environment doctor passed. This includes the delivered 791-test implementation plus 20 new diagnostic tests, not an inference-quality benchmark.

## Content-free provider diagnostics

Separately reviewed commit `1bb9c04` adds `exception_type` and `http_status` to existing provider-call records. Labels are fixed known SDK/transport/validation categories, with `UnexpectedError` for unknown classes. Upstream HTTP status is recorded only from known SDK/status exceptions; local application error status is not represented as an upstream response. Every new call resets both fields to null.

No exception messages, request/response bodies, credentials or cause chains are recorded in these fields. Existing call IDs, stages and observer persistence are reused. Original exceptions and outcome classifications propagate unchanged. The existing 45-second inactivity timeout and one SDK attempt are unchanged; no fallback, additional inference stage, prompt or model change was introduced. Mock SDK tests verify failure redaction, Decisions wrapper exceptions, observer persistence, success reset and unchanged schema/output-limit outcomes. Independent review passed all 20 new tests.

## Fresh controlled live checks

These used the exact previously failing question and the same copied historical artifacts/revisions. The originals, configured Gemini models, QA stages and processing settings were unchanged; no reconstruction or model repair ran. Physical orbit and source/model switching occurred while intent was pending. Each count caused exactly one QA submission, retained the captured revision and left the user's final source view in place.

| Case | Transport/workflow result | Source-correctness result |
| --- | --- | --- |
| 11397, `How many windows does this building have?` | Completed in 47.58 s; intent, QuestionIntent, gate, draft and answer review succeeded. Ten citations opened exact source regions. | **Not accepted.** Answer claims five windows per floor and ten total, but omits the long upper-floor right-wall opening beside the staircase, approximately `[.892,.785,.925,.923]`. |
| 1794, same exact question | Completed in 36.06 s through all stages. Three citations opened exact source regions. | **Not accepted.** Answer lists two standard room windows plus balcony glazing, but omits the narrow MH-to-balcony opening above the balcony door, approximately `[.710,.083,.722,.257]`. Its classification/completeness must be addressed, not silently excluded. |
| 11397, `Show this window in the original blueprint.` | Completed in 8.14 s; exact captured first tour object's source bounds and revision opened. | Exact source association verified. |
| 11397, `Back to the model; next window.` | Completed in 6.39 s; returned to the model and advanced the same tour once. | Captured selection/tour continuity verified. |

Both count answers had empty highlight lists: uncertain source-to-model mapping did not invent highlights. All 13 citations were independently clicked and compared with the original drawings. The positive automated answer reviews did **not** establish completeness. No alternate exact total is asserted here; omitted source features already invalidate accepting the complete count claims.

Read-only diagnosis of 11397 found the same omitted opening absent from its saved description, association index and reopened IFC. The fallible inventory contains ten window records. The original 475×650 page was supplied unchanged in size to drafting and review. No cropping/image-loss defect was found. Matching the incomplete inventory does not prove causal dependence on that inventory. The full successful review rationale was not persisted; only its supported decision and call metadata are available. The source-grounded QA completeness gap remains open.

The corresponding read-only check on 1794 also found its omitted window absent from the description, association index and reopened IFC, whose inventory contains two windows. The nearby balcony door is a separate record; a continuous wall record covers the omitted window location. This is another pre-existing extraction omission and a missed original-source QA check. It still does not establish why the model followed that incomplete inventory.

The earlier failed count jobs and focused-source `ReadTimeout` remain preserved. These new successful calls do not retroactively identify their causes, and the historical generic exception is still undiagnosed. Future provider failures can now retain safe class/status evidence. A possible subsequent controlled experiment is to compare drawing-count QA with and without fallible derived inventory context while retaining originals and all settings; it was not performed or adopted in this integration.

Private evidence: `/tmp/junction-ui-integration/live/report.json`, `/tmp/junction-ui-integration/review/IMPLEMENTATION_REVIEW.md`, `/tmp/junction-ui-integration/review/LIVE_ANSWER_REVIEW.md`, actual browser screenshots and `tests.log`. Historical failures remain at the paths documented in [CHAT_UI_CORRECTION_VERIFICATION.md](CHAT_UI_CORRECTION_VERIFICATION.md). No reference dataset answers were used.

## Deployment checkpoint

Exact runtime release `1bb9c04` was deployed after integrated review. All 613 current live file hashes, 436 seed hashes, 14 buildings, 11 terminal jobs, CURRENT pointers and the credential-file hash matched across the update. No copied test data was uploaded and no provider inference ran during deployment. The previous `a470a11` release remains available for rollback.

The final swap briefly returned maintenance 503 responses for new POSTs to prevent new paid work/uploads racing the idle check. Existing jobs and upstream connections were checked before stopping; the normal Caddy configuration was restored and byte-compared afterward. Trusted external HTTPS health returned 200, nine public examples remained visible, the two known private test buildings returned anonymous 404, and POST handling was confirmed restored. UI acceptance remains distinct from the unresolved factual count failures. No push was performed.

Independent post-deployment Chromium verification passed at https://95.133.254.90.sslip.io with normal certificate validation. All nine examples loaded their exact pinned model revisions. Compact tabs, physical orbit, persistent provenance and independent toggles worked in both themes on 11397, 1794 and native IFC, including the original native record. Anonymous controls issued no POST requests. Unlocking did not replay an action; authentication was the only POST in this entire review.

Previously saved supported 1794 QA displayed once with its one validated highlight; the saved 11397 actual-height refusal displayed once with zero highlights. These are the earlier supported label/refusal checks, not the newly rejected count answers. Known private 1732 history had unique job-linked cards and the accurate retained-model/needs-attention status. Its exact older QA source hid the current geometry overlay, explicit comparison opened the model's source revision, and returning to the old citation hid the mismatched overlay again. No JavaScript errors or scoped release blockers were found.

The first reviewer script incorrectly treated a transient null source revision during image preloading as the expected old revision; its wait then timed out. The corrected observation waits for the exact known old revision and passed, without an application change. Evidence and this harness correction are retained under `/tmp/junction-ui-integration/review/public/`.
