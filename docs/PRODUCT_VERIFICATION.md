# Progressive product verification and demo

Verified locally on 14 November 2026. The active scope is PRODUCT_SPEC.md. Gemini remains the configured final-demo provider; the reconstruction default is unchanged. No deployment, push, new dependency, renderer service or database was added.

## Launch saved demo

```sh
bash scripts/bootstrap.sh
BLUEPRINT_STORAGE_ROOT=.runtime/product-demo PORT=8000 bash scripts/dev.sh
```

Open http://127.0.0.1:8000 and use **Saved buildings**. Existing `.env.local` credentials are used; do not overwrite them. One application process owns a storage root. The verification server may be running at http://127.0.0.1:8768 with this same store; stop it before launching another process on the store.

Persistent bundles are under `/home/jcb/dev/github/JunctionHack26/.runtime/product-demo/buildings/`. They contain original bytes/pages, immutable revisions, descriptions, reasoning, IFC, browser geometry, identities/frames, reviews, pipeline metadata and jobs. `CURRENT.json` identifies the usable revision. Earlier revisions and rejected candidates remain separate. Runtime/source artifacts are ignored by Git.

| Saved case | Building directory | Tested revision |
| --- | --- | --- |
| 1794 | `3414d4316f6bd31fa922fd80d088a798155560edabec2e2d14468fe1cd2f5e48` | 4, `c5cf6f8fa9d24409a7ba56e21e71604c` |
| 11397 | `ee05918c08c0ea8b58c4ca43f802b8810271b4e33c193508b619d9ad7fefb149` | 2, `501fcb9792ff4e6abd1760f10bc1cd63` |
| Institute plan | `a61aec0c5aa9857274d02b2a6ef7d6506c9763b2a496b0bda907668390125ca1` | 2, `539185686bd64b2c9769c8eb9a41a04b` |
| Institute section | `0bfe85223261b74cead11804538442fbb957f6a64df43a936ed0fae02860bdf1` | 2, `440d325130a94bd889a2357fb1f001d9` |
| Genuine duplex IFC | `707a032566dee8e969a44d95509be46d646440e2443624709f8d3ae2b45f4656` | 1, `b22334a329b64314890776aab0819559` |

The two colorful cases reuse exact saved descriptions/IFCs containing unchanged original pixels, followed by live source/geometry review and targeted Gemini patches. They are **not new PNG extraction runs**. Baselines remain `/tmp/junction-fidelity-v4/schematics/{11397,1794}.ifc` and revision 1 of each bundle. The institute plan and section were fresh PDF extractions from the unchanged dataset files.

## Short demo sequence

1. Open saved 1794. Orbit in inspection mode, switch concept mode, then enable source comparison on the original page. Click a source object and a decorative proposal; their disclosures differ. Assumptions and answer highlighting remain separate controls.
2. Open 11397, switch between both depicted floors, inspect terrace/balcony boundaries and source regions. Ask a floor-specific outdoor-label question and inspect the original citations. Only validated mappings highlight; unsupported associations retain the citations.
3. Ask for actual ceiling height. The drawing does not establish it; visible extrusions cannot support that fact.
4. Open the institute plan. Its office/lab/WC/corridor labels remain intact; concept mode does not add residential furnishing proposals. Open the matching section: original evidence is available, but no fake floor appears.
5. Upload `assets/junction-dataset/data/ifc_bench/duplex_arc.ifc`. Ask **How many windows are in this IFC model?** Native reasoning counts the complete supplied semantic catalog, including meshless records. Inspect original-record citations; source geometry remains unmodified.
6. Stop and restart the application with the same storage root. Open saved buildings immediately without extraction. Repeat-upload content reuses the building. An explicit refinement starts a new source/geometry review; invalid candidates or stopped jobs retain the last usable model.

## Actual source-fidelity findings

Independent review directly operated Chromium: orbit, floors, concept/inspection, cutaway, assumptions, original overlays and pointer source/proposal clicks. Overlays derive from actual reopened IFC geometry, not description polygons. Reviewer agreement alone was not used as fidelity evidence.

| Case/issue | Observed result |
| --- | --- |
| 1794 oversized kitchen/bath partition | Improved: narrowed to the depicted lower partition; sink/counter footprint is no longer obscured. |
| 1794 floor under sink/counter | Improved: corrected footprint follows the partition without the previous notch. |
| 1794 missing bedroom/balcony glazing | Added, but initially overlong. Independent source comparison caught the new extent error after model review accepted it. A narrowly targeted new live Gemini correction restored the depicted solid wall stubs; final revision 4 was reopened and independently checked. |
| 1794 balcony-crossing boundary | Remains incorrect in the saved interpretation. |
| 1794 sink/hob classification | Remains incorrect/uncertain; concept styling is not a semantic repair. |
| 11397 upper facade windows | Two higher windows now correspond visibly to the original openings; improved from the baseline. |
| 11397 lower right upper-floor glazing near stair/bedroom | Still omitted from opening and unresolved inventories. This is extraction omission, not a renderer omission. |
| 11397 outdoor spaces, stairs/furnishings | Both floors remain explicit; outdoor spaces have no invented full enclosure and no observed diagonal door-leaf walls. Schematic features/source links work; door/room details remain approximate. |
| Institute plan | Fresh preview contains 18 labeled office/lab/WC/corridor spaces, 93 total records; broad partitions/window bands follow the drawing. Independent concept inspection found zero residential/decorative proposals. Fine door gaps and small details remain incompletely checked. |
| Institute section | Correctly retained as a source-only section with a clickable original region; no invented floor. |

Review findings and failed attempts remain visible. The product does not claim complete feature coverage, full architectural correctness or a measured accuracy percentage.

## Live processing and failures

- 1794's first live patch violated reviewed-target identity constraints and was rejected before publication. A controlled patch retry was saved and locally validated. The next job reused that **actual live** review/patch response, then made fresh live candidate-review/patch calls; two revisions were accepted. No description was hand-edited. This continuation used 85,136 input/19,323 output tokens and 126.9 seconds of job wall time, excluding the reused earlier calls.
- Independent inspection found the overlong added glazing. Its source-linked developer review fed one fresh Gemini patch and source/geometry review: 52,269 input/14,293 output tokens, 104.9 seconds, one accepted correction. The configured one-attempt run stopped with remaining findings; it did not claim perfection.
- 11397 accepted one targeted correction, then rejected a later inserted object whose source association failed validation. Its usable revision remained intact: 196,471 input/29,274 output tokens, 185.6 seconds.
- Institute extraction published its preview before review. A later patch omitted its required typed record and failed operationally; the preview remains usable. 103,299 input/28,006 output tokens, 158.9 seconds.
- The institute section used 2,691 input/239 output tokens and stayed source-only. Its 111.8-second job wall time includes waiting behind other work.

These are local measured runs, not latency/cost guarantees. Reconstruction provider usage currently reports token totals; wall times above come from persisted job timestamps. Monetary cost was not calculated. Invalid structured model responses still occur, and the app retains the earlier usable result rather than weakening validation or retrying indefinitely.

## QA and regression evidence

[QA_REVIEW_VERIFICATION.md](QA_REVIEW_VERIFICATION.md) records the five-case live baseline/reviewed comparison, original failures, citations/highlights, token usage and per-case timings. Both pipelines answered 3 of 5 selected questions and appropriately refused 2; no answered error was observed in this tiny source/count spot check. This does not demonstrate an accuracy improvement from review.

Deterministic fixtures separately verify confidently wrong draft correction, false-abstention recovery, incomplete aggregate refusal, stale/cancelled QA publication, regressive candidate retention, stable IDs through insertion/reordering, frozen source transforms, portable reopening and camera/control preservation. Fixture corrections are not represented as live model inference.

Final integrated check:

```sh
RUN_BROWSER_TESTS=1 PLAYWRIGHT_BROWSERS_PATH=/tmp/junction-playwright .venv/bin/python -m pytest -q
.venv/bin/python scripts/doctor.py
```

The integrated suite passed 411 tests with 1 optional dataset test skipped; doctor passed. Browser checks use real local HTTP/IFC/rendering with explicitly injected inference fixtures. Separate independent browser runs used real live artifacts and original source comparisons. Software Chromium was available; measured concept preparation was approximately 132 ms for 11397 and 37 ms for 1794, 158–208 draw calls. No reliable interactive FPS claim was established.

After that full run, the final space-label mapping correction passed 99 focused scene/QA/artifact/job tests, including 11 new positive/negative cases; an independent related run passed 86. Its controlled captured live draft maps to the requested terrace ID. Independent fresh browser QA then passed:

- 11397 floor label: correct TERASSI answer, two original citations, one validated highlight, surrounding geometry at 10% opacity and pointer click to original evidence; 10.58 seconds.
- 1794 actual height: insufficient, two original citations, no highlights despite extrusions; 13.44 seconds.
- Genuine duplex count: server-computed 24 windows, 24 citations/highlights, clicked pinned original properties; 16.09 seconds.

These are live inference checks, not fixtures. No browser errors were observed. The first floor-label browser run's missing highlight remains documented alongside the controlled diagnosis and narrow deterministic fix.

The independent reviewer also replayed the exact accepted 1794 revision3→4 scenes through the application's browser revision swap. Camera/target stayed unchanged within numerical tolerance after orbit inertia settled; floor, concept mode, cutaway, assumptions, selected window and all proposal placements survived. A real pointer click opened the corrected window's updated original-source region. This used actual saved Gemini revisions without another inference call or any persisted artifact edits; evidence is `/tmp/product-actual-revision-swap/`.

Temporary independent captures: `/tmp/product-review-live-browser/`, `/tmp/product-review-live-11397/`, `/tmp/product-review-live-1794-corrected/`, `/tmp/product-independent-browser/`. Live QA outputs are under `/tmp/product-live-backend/`; final browser QA responses/captures are under `/tmp/product-review-live-qa-browser/` and `/tmp/product-review-live-11397-qa/`. These temporary files may not survive environment cleanup; the demo bundles do survive application restart.

## Scope and commits

`d1c67af` adds concept/source-proposal presentation and atomic viewer revisions; `490a602` adds durable source-grounded revisions and reviewed structured reasoning; `8b59635` fixes native context coverage and overlapping source associations; `f2cfcbd` integrates persistent background jobs and interactive saved-building flows; `60c01ab` completes the live space-label mapping fix. No commits were pushed.

Remaining limits: single local process, configurable bounded provider calls, occasional invalid model patches, incomplete source-feature coverage, no multi-user/auth/database infrastructure, no detailed roof/dome reconstruction, no new formats or remote renderer. Full replacement extraction conservatively preserves IDs only for uniquely unchanged records; ambiguous replacements are retained as rejected candidates and should use targeted refinement. OpenAI remains an explicit SDK-tested temporary adapter; final live acceptance used Gemini.
