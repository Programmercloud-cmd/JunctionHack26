# Colorful-355 measurement QA and render reliability

The current agentic implementation was committed and pushed as `4609946` before this investigation. The user reported an output-limit error on a footprint question using two drawn dimensions and repeated rendering errors from the earlier sequential-review implementation.

## Observed saved evidence

The saved local `colorful-355.png` run used `dual-hydrogen-v1`, not the deployed parallel-review implementation. Three retained creator calls ended with `MAX_TOKENS`: visible/thought token counts were 32,021/33,515, 41,945/23,591 and 39,854/25,682 respectively. Each pair totals the configured 65,536 allowance. Both retained review calls completed normally. Changing review scheduling alone does not address this creator failure.

The initial source interpretation has two floors and seventeen room records without traced polygons, walls or openings. That is source-only interpretation, not a finished reconstruction. A creator correction must add explicit physical geometry; room bounds never imply walls. The old render request contained no attached annotation IDs, so its generated candidates did not use the saved dimensions.

Two saved measurements each specify 10 m on one room in the first-floor view. Their pixel spans are approximately 682.6 and 522.1 pixels in the original 2730 × 2048 image. The inferred image scales differ by about 31%. The dimensions can support a directly attributed 10 × 10 m rectangular-region calculation; they do not establish one consistent scale for extrapolating the complete exterior footprint. A footprint answer must distinguish that room from the building outline and clarify the calibration rather than silently stretching the drawing.

The failed synchronous footprint turn was not saved with call-stage telemetry. The exact historical failing stage cannot be established. The advanced technical worker did use high thinking with the general 8,192 output-token allowance, creating a concrete truncation exposure. This is separate from the directly observed rendering failures.

## Corrective behavior

Advanced agent answers use a default 65,536 output-token allowance, while basic answers keep 8,192. `GEMINI_AGENT_ANSWER_TOKENS` optionally overrides the selected worker's allowance; corrective drafts reuse it. The existing Q&A deadline remains. Truncated responses are still rejected and never published as answers.

Calculation operands may reference either an inspected drawing citation or an exact permitted user-value ID. The server resolves and verifies the selected user value and unit, requires explicit attribution, normalizes compatible length units, validates the output dimensionality, and records original user inputs separately from normalized computation and drawing observations. Unknown, changed or source-only user operands fail validation. Native IFC calculation authority is unchanged.

Creators receive compact incremental-patch guidance, with one suggested outstanding geometry/finding focus and complete original/review context. This is guidance rather than a rejection rule for larger valid patches. Output-limit retries explicitly request a smaller coherent correction and retain the remaining findings. Both reviewers still inspect the complete reopened candidate in parallel. No total, iteration, cost or no-progress stop was introduced.

Content-free rendering call metadata is retained on failed attempts and late completion after Stop, including role, finish reason, token counts and fixed failure category. Provider bodies, private thoughts and exception text are not included. Original sources and last usable revisions remain intact.

Explicit mark attachment remains the current workflow pending the user's preference. Saved marks are not silently attached across revisions or source views.

## Verification

Independent implementation review cleared the fixes after 96 focused QA/provider/backend checks and the render recovery regressions. An isolated actual Gemini retry of the exact footprint question, with both saved measurements attached, completed with a targeted calibration clarification: approximately 68.3 pixels/m horizontally versus 52.2 pixels/m vertically, with a choice of which dimension to use. It returned no invented footprint. The explicitly configured local advanced worker was `gemini-flash-latest`, with 11,503 thought tokens and 124 visible tokens; this observed request exceeds the former 8,192 allowance, but does not establish the exact stage of the historical failure. Original user-store file hashes were unchanged.

Integrated worktree checks passed **941 tests / 121 optional skipped** in 82.79 seconds and **nine focused Chromium checks** in 39.04 seconds. Doctor and diff checks passed. The tested snapshot also passed 941 tests / 121 optional skipped in 86.04 seconds and is now deployed at https://agentic.95.133.254.90.sslip.io/. Its code-only update retained all 476 runtime-file hashes. The old demo remains unchanged.

The separate actual Hydrogen rendering test completed in **three rounds / nine successful calls**, using an isolated copy without arbitrarily choosing between the conflicting calibration marks. Both final reviewers supported and were satisfied with the same recomputed candidate digest. The saved model has **19 rooms with nonempty polygons, 51 explicit boundaries, 26 openings, 17 features and 113 mesh objects**, across both depicted floors. These are generated inventory totals, not independently established counts of actual construction features. Its first creator returned a valid `DescriptionPatch` in 118.005 seconds, using 16,783 visible and 15,873 thought tokens; deterministic IFC generation and reopening succeeded. Both reviewers completed normally in parallel (65.483 and 51.958 seconds). Their support veto preserved the original published revision and their full findings feed the next correction. The final candidate completed after the entry/vestibule correction in round three. Independent inspection reopened the actual IFC, checked saved/exported revision 4 and its ancestry, and matched embedded source/page bytes to the originals. Actual Chromium checks verified the downloaded IFC, one canvas, orbit, both floor controls, same-revision Concept and reload with zero script errors and no additional paid requests. This demonstrates recovery from the reported empty-geometry failure, not a full geometric fidelity audit.

The idle local preview on port 8012 was restarted with the fixes; all 125 stored files retained identical hashes. The temporary port 8013 verification server was stopped after the browser checks. User stores were not replaced with verification copies. Detailed artifacts remain privately under `/tmp/junction-agentic-diagnostics/`, including the completed rendering root `render-355-1794718991884766905`.
