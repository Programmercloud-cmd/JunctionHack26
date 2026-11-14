# Agent handoff — 2026-11-14


## Voice branch update

`feat/voice-interaction` in `/home/jcb/dev/github/JunctionHack26-voice` contains the voice extension over a source-only snapshot of the uncommitted Reconstruction V2 app. Original workspace files were verified unchanged. No commits or pushes. The existing `.venv` is linked for local checks; no secrets, uploads or datasets were copied.

Delivered Gemini Live transcription, building-specific vocabulary/manual terms, visible room aliases, editable explicit-submit questions, ElevenLabs spoken-answer playback and lifecycle-safe cancellation/text fallback. Read [VOICE.md](VOICE.md), [VOICE_CONTRACT.md](VOICE_CONTRACT.md), [VOICE_PLAN.md](VOICE_PLAN.md) and [VOICE_VERIFICATION.md](VOICE_VERIFICATION.md).

Verification: 220 integrated tests plus 2 additional focused browser tests passed. Independent review cleared blockers. Live Google browser transcription → existing grounded Ask → citation passed on a synthetic source and spoken question; no accuracy benchmark claim. ElevenLabs CLI onboarding completed authorization and SDK setup. The SDK adaptation passed 39 focused checks plus independent review; the user-approved live test then passed end-to-end through Google transcription, cited source answering, ElevenLabs MP3 generation and Chromium playback/Stop. Both CLI and app speech returned HTTP 200; no JavaScript errors occurred. George and multilingual_v2 are configured. Both services now have local configuration in ignored `.env.local`; credentials were never printed.

## Spoken-answer formatting update

Speech now has separate `spoken_answer` and `spoken_answer_with_details` fields, prepared deterministically after grounded-answer validation and calculation replacement. Default speech removes recognized coordinate lists, bounding boxes, opaque identifiers and citation annotations; explicit category requests or “Read technical details” retain them. Useful dimensions, uncertainty, every missing-information entry and the next action remain. Full written answers, citations and highlights are unchanged. No additional inference request or dependency was introduced. See [SPOKEN_ANSWERS.md](SPOKEN_ANSWERS.md). Final verification: **286 integrated tests passed**, independent review passed 71 focused checks with no blockers, and live window-answer speech preserved the 1.2 m measurement and missing-width/height qualifiers while all three citations stayed visible. Playback and the technical-details stop behavior passed with no JavaScript errors. See [VOICE_VERIFICATION.md](VOICE_VERIFICATION.md).

## Current state

Reconstruction V2 implements original JPG/PNG/PDF → Gemini building description → deterministic Python/IfcOpenShell → downloadable generated IFC → local Three.js viewer. It covers explicitly depicted floors on one image and across pages. Read [RECONSTRUCTION_V2_PLAN.md](RECONSTRUCTION_V2_PLAN.md), [RECONSTRUCTION_V2_CONTRACT.md](RECONSTRUCTION_V2_CONTRACT.md) and [RECONSTRUCTION_V2_VERIFICATION.md](RECONSTRUCTION_V2_VERIFICATION.md). These supersede the historical single-floor limits. No commits, pushes or deployment.

Run `bash scripts/dev.sh` and open http://127.0.0.1:8001. Dependencies remain pinned; no new services or frontend build. `.venv/bin/python scripts/doctor.py` passes. Ignored `.env.local` already selects Gemini and `gemini-flash-latest`; this work did not alter credentials or model selection. OpenAI remains explicitly selectable; no auto-failover. Final demo uses Gemini plus native Decisions.

## Delivered behavior

- Gemini describes floor regions, original-coordinate room footprints, labels, openings, ordering/orientation and known/unknown measurements. Explicit named axes on the API wire avoid an observed row/column ambiguity; application coordinates stay normalized against the unchanged original page.
- Our Python code constructs IFC4 storeys, room plates, walls and reliably hosted door/window voids/fills. No model-generated Python or IFC text is executed. Invalid/overlapping geometry is omitted transparently, not repaired or promoted to evidence. No arbitrary extraction floor/room/vertex caps; existing resource limits remain.
- Unknown scale uses `IfcContextDependentUnit LENGTHUNIT=UNSCALED_DISPLAY_UNIT`, never measured metres. Supported source-segment calibration is computed with page aspect ratio. Only fully calibrated projects use SI metres; mixed-scale projects are explicitly relative. All extrusion heights/thicknesses/opening vertical dimensions remain display assumptions. Storey elevations are unknown.
- Unknown registration uses a schematic layout. Derived multifloor scenes start visually separated; this is a viewer transform, not a physical elevation. Source regions remain original after rotation, selection and export.
- Each artifact embeds original normalized PNG pages with hashes and a provenance manifest, plus per-element/floor property sets. Downloaded IFC reopens in a fresh session with stable GlobalIds, original pages and assumptions. Recognized malformed/contradictory generated metadata fails closed. This consistency mechanism is not cryptographic authentication of arbitrary third-party IFC.
- Reopened generated IFC is `kind=drawing`, `source_kind=image`, `derived=true`, `catalog_complete=false`, with inferred geometry. QA still inspects original drawings. Generated properties, inventory and assumptions cannot enter native IFC count/property shortcuts. Genuine supplied IFC retains its semantic catalog and source evidence.
- All-page model is cached once. Floor controls, orbit/zoom, source clicks, validated answer highlights, 10% surroundings, independent assumption control and generated-IFC download are integrated. Uncertain mappings retain citations with no invented highlight.

## Live verification

No current Gemini 400 reproduced in the initial actual SDK transport probes or new structured-generation runs. Safe metadata/hashes were captured, not credentials or request bodies. Historical `maxItems` compatibility evidence is in [GEMINI_FIX.md](GEMINI_FIX.md); the current implementation was tested again live rather than assumed compatible.

Only reconstruction now uses medium reasoning, after a controlled comparison increased valid multi-floor footprint coverage. Answer/crop/gate settings are unchanged. Existing 8,192-token/45-second/one-attempt budgets remain; truncated responses are operational errors and cannot be cached.

Final live upload → reconstruction → cited answer/highlight → actual-height refusal → download → fresh-store reopen passed:

| Unchanged original | Floors | Rendered room footprints | Rendered objects | Reconstruction |
|---|---:|---:|---:|---:|
| `colorful-1794.png` | 1 | 6 | 43 | 35.03 s |
| `colorful-11397.png` | 2 | 6 + 5 | 69 | 32.92 s |

Both files are in `assets/junction-dataset/data/cubicasa5k/`. 11397 is the original upside-down image with two side-by-side diagrams; no user editing/cropping was applied. Its final model explicitly reports two overlapping footprints and three openings omitted. These are interpreted model counts, not source facts or accuracy benchmarks. Both live height questions returned insufficient and no highlights. A supported second-floor question returned an original-region citation and matching highlight before and after standalone IFC reopening.

Portable artifacts, safe wire metadata and live reports are under `/tmp/junction-live-v2-final/`; they are temporary local verification files, not committed dataset outputs. Intermediate low-reasoning runs are under `/tmp/junction-live-v2/`; do not confuse them with final coverage. The verification document records browser checks separately from fixture tests.

## Tests and review

- 167 backend/native-IFC tests passed; 9 optional real-browser tests passed separately (176 total). Native sample: `assets/junction-dataset/data/ifc_bench/duplex_arc.ifc`.
- Separate final live Chromium acceptance reopened the real 69-object IFC, orbited both floors, called real Gemini, highlighted the second-floor source match with 0.1 surroundings, clicked its mesh/source region, and refused actual height. No JavaScript errors. Screenshots are under `/tmp/junction-live-v2-final/`.
- Browser regressions use explicitly injected providers, including calibrated/unscaled multi-panel/multi-page generated IFC round trips. They verify UI behavior, not live model quality.
- Generator/artifact tests use real IfcOpenShell creation, void geometry, serialization and tessellation. Fresh-store tests remove the original session before reopening, validate exact source pixels/IDs, and exercise provenance corruption and derived-only QA routing.
- Independent read-only review found and cleared mismatched opening source regions and actual IFC storey/manifest disagreement. Pset/manifest agreement, element type, source floor region and actual containment are now validated. Final reasoning-only change was independently reviewed. No outstanding code blockers.
- Development roles: root owns contracts/environment/provider/integration; backend planner/implementer owns generation/artifact regressions; frontend owns UI/browser tests; separate reviewer remains read-only. Continue bounded ownership under AGENTS.md.

## Remaining limits

Models remain approximate. Gemini may omit/misread boundaries, labels or measurements; valid polygons and a sufficient gate do not establish correctness. Ambiguous source mappings deliberately stay unhighlighted. Medium reasoning costs time and can approach the existing timeout on harder drawings; source QA remains available after reconstruction errors. Download/reopen avoids repeating successful reconstruction.

Drawing limits remain 10 MiB / 5 pages / 40 MP input / 4096-pixel normalized edge; model input views use 1600-pixel edge with a source crop retry for unclear QA. IFC limits remain 25 MiB / 4,000 elements / one million triangles. Embedded source PNGs count toward the artifact size limit. Native properties retain the existing 48-value inspector / 12-value inference bounds with omission warnings. There is no reference-building retrieval or durability beyond the explicit portable download.

Multi-page PDFs, supported calibration and mixed-scale handling are regression-tested; new live Gemini acceptance uses the two PNGs above. The temporary OpenAI V2 adapter is SDK-mocked, not newly live-tested. Keep unseen floors, detailed stairs/roofs, engineering calculations, DXF/SVG/DWG, photorealism, Blender/cloud rendering, auth and database deferred.

## Dataset provenance

The native duplex sample's LICENSE.md attributes Duplex Apartment - arc to BSI (2020), buildingSMART International, under CC-BY-ND-3.0. Historical dataset/source notes remain in 3D_PLAN.md and the supplied dataset license. Ground-truth question/answer files are evaluation-only and never runtime context. No dataset file or generated model was added by this work to tracked source.
