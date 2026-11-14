# V3 diagnosis and fidelity verification

## Confirmed baseline failures

The unchanged originals were compared with the matching final V2 IFC/scene, not merely an earlier description or screenshot. The final V2 description itself was not saved; the separate medium-reasoning description belongs to a different run and was not treated as its generator input.

For 11397, actual V2 IFC and scene contain 11 spaces, 57 walls, 1 door, 0 windows and no furnishing/stair entities. Every retained polygon edge generates a wall. That encloses terraces/balconies, turns arbitrary space-partition edges into walls, and duplicates physical shared boundaries. Actual diagonal walls were verified on outdoor outlines; a door-leaf origin for those particular diagonals was not established. 1794 also has invented walls across open circulation and parallel room-boundary walls that can leave a door passage blocked despite cutting one host.

V3 therefore separates room plates from explicit shared physical boundaries and associates openings with boundary keys rather than room-edge indices. Outdoor/open/railing types and schematic feature types are explicit. Validation failures preserve source-linked unresolved objects instead of silently disappearing. Exact V3 generator input is embedded in the IFC manifest; original images remain the only factual drawing source.

## Controlled live tests

Configured Flash was tested on unchanged 11397 with the new structured schema:

| Configuration | Observed result |
|---|---|
| Existing 45-second deadline, 8,192-token budget | HTTP 504 deadline expired after 43.58 s; no accepted result |
| Reconstruction timeout 90 s only | MAX_TOKENS after 48.87 s; 7,167 response + 1,011 thinking tokens; partial output rejected |
| 90 s / 16,384 tokens | STOP after 48.51 s; two floor descriptions; 8,191 response + 469 thinking tokens |

No schema 400 reproduced in these V3 requests. SDK transport metadata/hashes were captured safely; no credentials or request bodies were printed or committed. Only reconstruction settings changed. Answer/crop/Decisions retain their original settings and provider behavior. The temporary OpenAI reconstruction adapter has the same richer schema/budgets and actual-SDK strict-schema regression checks; its V3 live fidelity is not claimed.

The direct V3 description produces some correct outdoor boundaries, hosted openings and flat feature schematics, but independent original-coordinate comparison found major unaccounted doors, facade glazing and furnishings. Successful API completion/valid IFC is insufficient evidence of source fidelity.

A controlled generic coverage-refinement call supplied original pages plus the explicitly fallible candidate. It returned more features (75.15 s on 11397), but visual review found remaining missing openings/chairs and new incorrect wall/cabinet placement. This was tested as a possible plan revision, not silently added to production or accepted as a completeness guarantee.

An automatic upright-floor-view experiment used only Gemini-detected regions/orientations, with deterministic inverse mapping to original coordinates. It also returned sparse coverage (47.08 s). It is not being added to production: no additional source-coordinate processing path is justified by that result.

A controlled same-source/model-schema comparison with `gemini-3.1-pro-preview` high thinking succeeded on 11397 (85.91 s,18,025 output tokens) and 1794 (42.11 s,8,195 output tokens). This produced substantially richer furnishing/opening coverage, including individual chairs and stair/fixture schematics. It exceeded16,384 output tokens on the two-floor source. Production therefore uses one Pro/high reconstruction request,150 seconds/32,768 tokens, explicitly configurable by `GEMINI_RECONSTRUCTION_MODEL`; QA/Decisions settings are unchanged. These budgets are design choices, not external source limits or fidelity guarantees. The direct Pro artifacts are under `/tmp/junction-v3/pro/`.

A final generic prompt refinement added wall-bend/jamb/glazing/fixture-symbol checks, without image-specific coordinates, manual corrections, additional production calls or reference answers. The fresh production1794 request succeeded in 45.13 s. The fresh11397 request was rejected after 84.64 s as an invalid description; the app saved no model. An exact-request repetition with response capture succeeded; the earlier invalid-description cause was not reproduced and its response had not been retained. This is not evidence of a schema 400 or proof that intermittent validation failures are fixed. `/tmp/junction-v3/final/` denotes this final API run, distinct from earlier controlled artifacts.

## Reviewable fidelity and remaining safeguards

The source comparison uses actual reopened IFC meshes inverse-transformed through stored floor matrices. Wall layers are horizontal sections at an assumed display height, so lintels cannot conceal a generated door gap. Other physical objects use footprint projections. Unresolved source boxes have a different style and no fabricated footprint. A regression moves actual IFC geometry while keeping description/source metadata fixed and verifies the overlay moves; another checks a real hosted void gap at the section plane.

An evidence-region bug was also identified: a correct entry gap/host was rejected solely because its contextual source box extended 0.005 beyond the approximate floor region. V3 now permits positive-area evidence overlap with the assigned floor while retaining unchanged original boxes; actual geometry anchors/segments must remain inside both floor and citation. Wrong-page/disjoint regions and wrong hosts remain unresolved. V2 reads retain their existing containment behavior.

All heights/vertical opening positions/flat symbol thicknesses remain assumptions. A stair symbol's marks are not a measured tread count or rise. Unknown scale still uses an explicit context-dependent IFC display unit. Generated IFC cannot enter native factual count/property QA, including after portable reopening. The comparison is a tool for human fidelity review, not proof that the model found every meaningful source feature.

## Actual final1794 fidelity audit

The exact description embedded in its IFC agrees with the generated geometry. Independent reviewer reproduced the causes from both, rather than attributing every error to assembly:

- The previously invented north-bedroom window is gone; open K/OH/ET circulation remains open.
- `wall_2` is described at original x=.794,y=.025→.811. This creates an opaque wall through the balcony interior instead of the depicted eastward step. This is an extraction error, not automatic room enclosure.
- `wall_7` is described at y=.344 with a thickness segment ending y=.411, including the kitchen counter depth. The excessive wall follows that mistaken supplied axis/width.
- The living-room window at x=.781 does not reach its host axis x=.794, and the entry at y=.797 does not reach host y=.811. They remain individually source-linked unresolved; relaxing host checks would create arbitrary attachments.
- The description swaps the sink/hob categories at the two kitchen positions. The generated IFC preserves those incorrect interpretations.

These block full fidelity acceptance. Screenshots: `/tmp/junction-v3/final/1794-floor1-comparison.png` and `1794-floor1-model.png`. No manually corrected version is substituted for the live result.

## Functional verification separate from fidelity

194 backend/native-IFC tests and 11 opt-in Chromium tests passed. An independent read-only reviewer passed 106 focused checks. A subsequent 19-test Gemini check additionally verifies the actual request URLs keep Pro reconstruction separate from the configured answer model.

Final 1794 live source QA answered a supported room question with one citation and one validated highlight; the actual-height question returned insufficient with no highlights. Its IFC reopened in a fresh store with the same IDs, 34 meshes, original page and relative units.

A real browser run reopened the earlier successful live Pro11397 IFC: two floors, orbit, cached viewer identity, one live floor-specific validated highlight, 0.1 surrounding opacity, pointer selection/source click, independent assumptions, and live actual-height refusal all passed with no JavaScript errors. This establishes UI/source-QA behavior, **not** that the later11397 extraction succeeded or that the earlier artifact has complete source fidelity.

## Exact-request11397 repeat

The production provider request was repeated unchanged with safe metadata and response capture. Both request hashes were `333c99a7be85dab665f8f8af7e2a745c3b68d85d7cc8c13cf7656c3e99a7dbe6`; the repeat returned STOP, a valid BuildingDescription and 19,116 output tokens in 92.10 s. Schema hash `2c898b316ab1701f6535b3705224e27ae21698798c9fb6131527ed684bb7461a`. No source edits, coordinate patches or fixture answers were introduced. The difference is provider output, not a request/schema fix.

Deterministic generation and reopening of that exact response produced 89 records across both floors:2outdoor,11room,22wall,5open_edge,12door,9window,2stairs,15furniture,10fixture,1other. Two door host/endpoint inconsistencies remain explicitly unresolved; counts are generated inventory, not verified source counts. Original response, exact description, IFC and scene are under `/tmp/junction-v3/diagnostic/`. This is the latest successful current-production 11397 result, not the earlier `/pro/` artifact. Intermittent description validation remains a demo risk: failures are operational, source QA stays available, and retry is explicit rather than an automatic extra call.

### Latest11397 visual and browser result

Original-coordinate comparison of the latest repeat restores the long first-floor partition, stops the stair surround before the entrance hall, records storage, retains six chairs and an L-shaped kitchen, renders outdoor edges without automatic room enclosure, and moves the upper bedroom divider closer to the depicted step.

Full fidelity remains blocked by two clearly depicted doorways that are unresolved and therefore not cut, absent upper-floor east glazing alongside the stairs, an upper terrace-side facade approximately 0.017 original-page height above the depicted axis, and full-height cabinet-front/shower-divider interpretations where structural walls are not established. The first-floor lower east window is broadly plausible in the latest result; do not repeat the earlier claim that it is truncated. Independent review distinguishes these extraction defects from the intentionally conservative host validation.

Screenshots: `/tmp/junction-v3/diagnostic/11397-floor1-comparison.png`, `11397-floor2-comparison.png` and corresponding `-model.png` files. Both source originals were inspected directly without manual input edits.

The latest 89-record artifact also passed a separate real Chromium run using real Gemini QA after portable reopening: two floors, orbit, cached viewer reuse, one supported floor-specific highlight, 0.1 background opacity, actual pointer/source selection, independent assumption toggle, actual-height refusal and zero JavaScript errors. This supersedes the earlier Pro browser check for current successful behavior; it does not erase the earlier invalid-description failure or remaining visual blockers.

## Acceptance conclusion

Implementation mechanics, source-only factual QA, portable provenance and focused regression/browser checks pass. Both unchanged originals have successful live Gemini outputs. **Complete faithful reconstruction is not accepted:** the final visual audits still find missed/misplaced openings and incorrectly interpreted boundaries/features, and one identical 11397 request produced an invalid description. Do not present this as certified completeness or a solved model-fidelity problem. The overlay and stored exact description now make those failures directly inspectable.

Final independent review of the latest 89-record IFC found no remaining reviewed code blocker and accepted the functional/provenance path. It explicitly did not accept full visual fidelity: the upper-floor dashed shower separator (`w24`) and stair-outline boundary (`w25`) are interpreted as full-height walls, unresolved door gaps remain closed, and glazing coverage is incomplete. Independent actual-geometry audit plots are `/tmp/reviewer-v3-diagnostic-11397-{structures,features,spaces}.png`. These findings must not be “fixed” by weakening host/source validation or treating generated inventory as factual source evidence.

## Subsequent captured 502 repair

The user-reported11397 failure was subsequently reproduced with the original image: successful Gemini STOP/valid JSON, followed by five zero-area boundary-line source validation errors. This class is now fixed through boundary-only line citations and explicit selection padding, with original physical-source validation preserved. See [RECONSTRUCTION_502_FIX.md](RECONSTRUCTION_502_FIX.md) for exact-response replay and fresh live verification. The earlier visual fidelity findings remain separate.
