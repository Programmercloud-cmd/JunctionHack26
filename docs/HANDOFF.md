# Agent handoff — 2026-11-14, reconstruction V3

## Status

V3 implements explicit physical boundaries, real wall-hosted openings, indoor/outdoor spaces, schematic stairs/furnishings/fixtures, persistent unresolved records and an original-page comparison of actual reopened IFC geometry. **Full visual fidelity acceptance is not yet met.** Live source comparisons still find omitted/misplaced features; do not confuse passing API, IFC or browser checks with complete reconstruction.

Read [RECONSTRUCTION_V3_PLAN.md](RECONSTRUCTION_V3_PLAN.md), [RECONSTRUCTION_V3_CONTRACT.md](RECONSTRUCTION_V3_CONTRACT.md) and [RECONSTRUCTION_V3_DIAGNOSIS.md](RECONSTRUCTION_V3_DIAGNOSIS.md). V2 verification is historical. No commits, pushes, deployment, new dependencies or services.

## Latest floor-scale repair

Per-floor bbox normalization was confirmed to enlarge the upper 11397 diagram by 13.88% relative to equal source-image spans. Uncalibrated floors now share a full-page display scale; bbox centering affects translation only. Supported calibration is unchanged. New page_extent provenance/UI explicitly means preserved drawing proportions, not physical scale or equal drawing scales. Separate pages and independently resized diagrams remain schematic. Old artifacts keep their stored transforms.

The exact saved Gemini description was regenerated with stable IDs and original source coordinates, without another extraction call. Corrected IFC: `/tmp/junction-page-scale/colorful-11397-page-scale.ifc`. 237 backend tests, two targeted browser regressions, real-artifact browser verification and independent review passed. See [FLOOR_SCALE_FIX.md](FLOOR_SCALE_FIX.md) for measurements, assumptions and source/export round-trip evidence. Prior visual extraction limitations remain separate.

## Latest 502 repair

The reported unchanged 11397 failure was reproduced and fixed: Gemini returned valid JSON with five line-shaped open-edge citations, but positive-area source validation rejected the entire description. Boundary-only line support now preserves the exact original citation and adds labeled one-pixel selection padding; floor/QA citations and physical thickness validation stay strict. See [RECONSTRUCTION_502_FIX.md](RECONSTRUCTION_502_FIX.md) for captured-response replay, live evidence and diagnostics. Future unexpected failures include a safe category/reference instead of the undifferentiated 502 message. No model/provider/budget change or retry was added.

231 backend tests and four targeted browser checks pass. Fresh live reconstruction returned HTTP 200 with both floors; exact failed-response replay also succeeds. Previous visual fidelity findings remain open. Refresh/reupload after the development server reloads because its session cache is temporary.

## Run and inspect

Run `bash scripts/dev.sh`; open http://127.0.0.1:8000. Upload unchanged `assets/junction-dataset/data/cubicasa5k/colorful-11397.png` or `colorful-1794.png`, then Generate building model. In Drawing view enable Source comparison and toggle spaces/walls/openings/features/unresolved layers. These paths come from actual tessellated IFC meshes, inverse-transformed into the original page, not copied model description polygons. Walls use a section through assumed opening heights; other objects use footprint projection. Inspect missing features, incorrect enclosure and misplaced openings against the original.

The inventory links all interpreted entries to source evidence and exposes unresolved reasons. It does not certify complete coverage. Model view keeps orbit, floor filters, schematic separation, answer highlighting, 10% surrounding opacity, independent assumptions and source clicks. Download/reupload preserves source pages, exact V3 input description, stable IDs, statuses and assumptions. V2 artifacts still reopen.

## Provider configuration

Gemini is the default/final demo provider. Reconstruction alone makes one high-thinking `gemini-3.1-pro-preview` request; override explicitly with `GEMINI_RECONSTRUCTION_MODEL`. Its 150-second timeout and 32,768-output-token budget are design choices measured against the richer inventory; large drawings can still exceed them. Truncated output is an operational error and cannot be cached. There is no automatic fallback or refinement stage.

`GEMINI_MODEL` remains the source-answer model (locally `gemini-flash-latest`); native Decisions, answer/crop budgets and refusal flow are unchanged. `.env.local` and credentials were not edited. `AI_PROVIDER=openai` remains an explicit temporary adapter with equivalent description fields and reconstruction-only time/token budgets. OpenAI V3 is SDK/regression tested, not live-fidelity verified. Health reports the reconstruction model separately.

## Geometry and provenance rules

- Room polygons make floor plates only. Explicit walls/shared boundaries are independent of rooms; invalid rooms cannot suppress valid walls/openings/features. Door leaves, swing arcs and furnishing outlines never automatically create walls.
- Door/window records name an explicit same-floor wall key. Valid gaps create actual IFC void/fill relationships. Invalid/ambiguous hosts stay unresolved, retaining source, stable ID and reason; no nearest-wall attachment.
- Outdoor space footprints do not imply enclosure. Open-edge polylines make flat markers; railings require explicit depicted support. No inferred hidden floors.
- Stairs/furniture/fixtures may be flat schematics when vertical shape is unknown. Stair marks are level symbols, not measured treads/rise or travel direction. Empty feature polygons request an explicit bbox schematic; malformed supplied geometry stays unresolved.
- V3 source boxes may provide context beyond the approximate floor bbox if the same-page regions overlap. Geometry anchors must remain in both floor and source region. Wrong-page/disjoint sources do not acquire invented geometry. V2 keeps its former containment validation.
- Unknown scale is `UNSCALED_DISPLAY_UNIT`, never measured metres. Supported calibration affects plan scale only. All missing vertical dimensions, opening heights/sills, symbol thicknesses and layout offsets remain assumptions.
- Generated IFC always reopens as derived drawing visualization, never as a factual native IFC catalog. Original embedded PNGs are validated by hash/dimensions; manifest, IFC properties, classes and storeys must agree. Original source QA excludes generated properties, geometry and assumed heights. The object index is only a fallible association aid. Unknown/ambiguous source associations retain citations without highlights.
- Every described item survives as reconstructed/schematic/unresolved. The model can still omit a source item completely: a valid inventory does not prove “everything shown” was found. All-unresolved scenes clearly report no 3D geometry and keep source inspection available.

## Verification and known blockers

The final live report and actual IFC/source overlays are recorded in [RECONSTRUCTION_V3_DIAGNOSIS.md](RECONSTRUCTION_V3_DIAGNOSIS.md). Temporary artifacts/scripts are under `/tmp/junction-v3/`; `/final/` contains the final1794 production-path run and the initial rejected11397 request; `/diagnostic/` contains the exact-request successful11397 repeat and latest model; `/pro/` is an earlier controlled model comparison. Do not mix their descriptions or screenshots. No reference answer files were used.

- 194 backend/native-IFC tests passed; all 11 optional Chromium checks passed separately. Doctor passes. Native sample: `assets/junction-dataset/data/ifc_bench/duplex_arc.ifc`.
- Regression coverage includes room/wall independence, outdoor non-enclosure, true hosted gaps, duplicate/conflicting hosts, semantic feature classes, unresolved persistence, V2/V3 provenance and fresh-store reopening, source-only QA, conservative highlights and independent assumptions. A test moves actual IFC placement while holding provenance fixed and confirms the comparison moves.
- Independent read-only code review passed 106 focused checks with no code blockers. Independent visual review reports unresolved acceptance blockers because real extraction results still have fidelity errors. The latest successful two-floor IFC passed real Gemini browser QA, source clicking, orbit, highlight fading and actual-height refusal after reopening; those do not establish complete source fidelity.
- Final 1794 removes the earlier invented bedroom window, but still has a wall through the balcony, unresolved clear living-room/entry gaps, excessive thickness at the kitchen/bath partition and sink/hob misclassification. The earlier 11397 Pro output missed a long interior partition/storage doorway and shortened/shifted some glazing. The latest 11397 repeat generated 89 records across two floors with two explicitly unresolved doors; its exact-response and visual findings are in the diagnosis report. The preceding identical request returned an invalid description, the later captured reproduction isolated and fixed line-shaped boundary citations as documented above; the discarded earlier response itself was not retained.

Do not claim full acceptance until original-coordinate review verifies those behaviors. Avoid hand-correcting acceptance fixtures and calling them live inference. Generic second-pass and upright-view experiments were tested but not adopted: they did not establish a reliable fidelity improvement.

## Workflow and limits

Root owns architecture/contracts/provider/reader/integration; backend planner/implementer owns IFC generation and generator tests; frontend owns UI/browser tests; independent reviewer stays read-only. Continue the AGENTS.md planning/review workflow and communicate any new design constraint before implementing it. No new extraction floor/room/vertex caps were added.

Existing drawing limits: 10 MiB, five pages, 40 MP input, 4096-pixel normalized edge; initial provider images use a 1600-pixel edge. IFC limits: 25 MiB, 4,000 elements, one million triangles; embedded original pages count toward artifact size. Native IFC properties retain 48-value inspector/12-value inference limits with warnings. Session cache is temporary; portable IFC download is the explicit persistence mechanism.

Defer photorealism, detailed stairs/roofs, structural engineering, new formats, Blender/cloud rendering, auth/database and reference-building retrieval. Multi-page/supported calibration flows are regression-tested; new live fidelity evidence uses the two PNG originals. Dataset ground-truth answers stay evaluation-only and were never runtime input.

The native duplex sample license attributes Duplex Apartment - arc to BSI (2020), buildingSMART International, CC-BY-ND-3.0. Dataset/source notes remain in 3D_PLAN.md and supplied license files.
