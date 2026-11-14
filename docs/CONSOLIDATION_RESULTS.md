# Consolidation verification

Consolidation on `blueprint-qa-isolated`; final workflow checks are recorded below. The reviewed scope is [CONSOLIDATION_PLAN.md](CONSOLIDATION_PLAN.md). No provider/model or execution-budget increase, automatic fallback, new format or rendering feature was introduced. Results below distinguish retained-response diagnosis, deterministic replay, synthetic tests and fresh live calls. Original sources and previous usable revisions remain preserved.

## Exact reported failures

| Report | Confirmed cause | Change and limits |
|---|---|---|
| 34, `793854acf67f4221a0e5e0f4a37e810f` | All26 serialized records decode and validate. The patch fails only `operations[7].evidence`: its top and bottom are equal. A boundary record may cite a line; operation evidence requires positive area. | Explicit shared prompt/schema guidance distinguishes the two contracts. The unchanged historical response still fails correctly. No automatic padding, fabricated source evidence or weakened validation. Historical aggregate usage21,442input/18,333output; job duration94.5s, not measured per-call latency. |
| 11397, `d7e1cba092f442d5b0821374e73a6f03` | Review hit `MAX_TOKENS`. Saved diagnostic incorrectly contains the preceding successful patch because response state was not cleared before the failed call. Historic112,927input/59,406output is multi-call aggregate; missing review-specific thought/text split cannot be recovered. | Stage-bound per-call diagnostics and private non-thought response capture; explicit review-phase mapping; private candidate retained before review, never published as an accepted replacement. Reconstruction request no longer repeats QA-oriented context containing the same description. Original images, current/previous overlays/descriptions, source warnings and user attribution remain. Exact exhaustion mechanism beyondMAX_TOKENS is unproven. |
| 3181, `c2b56109169044fda5b53fdc1a1c16f8` | Correction changed walls not authorized by the cited issue's explicit opening IDs. Strict target guard correctly rejected the patch atomically. A separate review diagnosis of unclosed feature polygons was wrong: six valid polygons exceeded their own source boxes by0.012–0.0335saved-source pixels after coordinate rounding. | Explicit issue-target guidance, unchanged authorization checks. Feature-only half-source-pixel containment tolerance, preserving source boxes/points. Page/floor/topology, walls/openings/hosts and citation validation stay strict. Accepted rounding is disclosed in portable notes; beyond-tolerance geometry remains unresolved. |

The half-pixel allowance is an application design choice for raster precision, not a physical tolerance or external requirement. It applies only to feature geometry versus its own citation, using the saved normalized source PNG dimensions. It could admit a subpixel discrepancy within a raster sample. Unknown/invalid dimensions use the previous strict comparison; there is no snapping or bbox expansion.

## Deterministic and automated evidence

- Exact3181 saved-description replay, with zero provider calls: six previously unresolved fixtures/furnishings now render; existing rendered geometry, IDs, exact description and source references are unchanged. Seven unresolved openings remain. Independent reopening confirmed these results. Artifact: `/tmp/consolidation3181-geometry-t7m30xc1/replay/`.
- Independent11397 exact saved-patch replay produced93elements and changed3records, with no additions/removals and no active-store mutation. Artifact: `/tmp/consolidation11397-exact-review-input/`. This is geometry replay, not a successful historical review.
- Focused regressions include zero-area operation evidence, precise feature tolerance boundaries, strict floor/topology/host/target checks, stale-response attribution, partial response privacy, missing SDK metadata, request-context preservation, private candidate retention and restart/publication safety.
- Backend checkpoint after compatibility fixes:536 passed,25 optional skipped. Independent precision/coherence checks:68 passed. Independent wire/diagnostic checks:44 passed. Browser suite:24 passed. Final live workflow outcomes are recorded below.

## Fresh workflow ledger

Live acceptance uses unchanged colorful34,11397,1794 and fresh non-residential `wikimedia/22921604.jpg`. Each must undergo fresh upload/extraction, three source-only QA submissions, optional geometry/review, direct browser/source-overlay inspection, one attributed input with source-only refusal, and available export/reimport/restart/reupload checks. Missing geometry is recorded as unavailable, never filled with old demo artifacts.34contains real height annotations; refusal checks use absent foundation depth rather than falsely assuming all heights are missing.

Private live stage artifacts and per-call metadata will be recorded under `/tmp/junction-consolidation/`. Structured output and QA responses are private; no credentials, raw provider requests or dataset reference answers are committed. Individual outcomes and independent browser findings follow; unavailable stages are not counted as passed.

## Controlled live review and fresh-run findings

The exact saved11397 candidate received one new live review, without re-extraction/publication:53.15s, same `gemini-3.1-pro-preview`, high thinking,16,384output allowance and120s deadline. Response finishedSTOP with36,832input,1,608candidate and6,383thought tokens (7,991output total), reporting5issues and candidate_supported=true. This establishes this request's compatibility; it does not prove the old failure's precise cause or universal reliability. Private report:`/tmp/junction-consolidation/controlled11397/report.json`.

Fresh11397 source extraction returned a malformed floor right coordinate (`4989473684210526`) and was correctly rejected (`87ff1a8f71834473845af008299a88b4`). The custom Point/Box API schema lacked numeric0–1bounds already required locally. A canonical-schema bound was added, then a controlled live A/B found that this bounded Gemini request returned HTTP400 while the identical request without minimum/maximum completedSTOP (1.14s versus6.38s). Gemini now omits those numeric wire constraints; canonical/OpenAI schemas and strict local validation retain them. The saved malformed response remains invalid, without rescaling or an inferred decimal. Original-only outdoor-space questions and foundation-depth refusal worked despite extraction failure. The initial driver reached explicit geometry prematurely, causing the existing flow to retry source extraction; that second call saved a valid interpretation before enrichment was stopped. This is recorded as an implicit retry, not hidden or called fresh geometry success. The valid saved interpretation is reused; no third extraction is planned. The driver now stops before geometry when extraction is incomplete.

Fresh34 interpretation and three original-only questions completed. Source locations were supported, but extra compass terms west/northwest were not established; shared grounding guidance now distinguishes image positions from actual cardinal orientation. Its geometry response (`64f422475c5e4543a9b32f28eb9610d3`) completedSTOP but omitted record from all21operations. Usage12,686input /4,654candidate /22,108thought tokens;143.912s call. Local application rejected it, retaining interpretation. The wire schema made record optional; it now requires record on the wire, with null reserved for removals. No missing records are synthesized.

Opt-in browser suite:24passed in131.75s. Independent initial real-browser checks confirm original previews and pinned citations, with no JSerrors; these do not establish final3Dfidelity.


## Compatibility correction and retained partial results

The numeric-bounds A/B used the same full BuildingDescription schema, model, high reasoning setting, short synthetic prompt and token allowance; only numeric minimum/maximum changed. It proves compatibility for that request, not a universal absence of Gemini numeric-bound support. The full schema had failed fresh1794/non-residential extraction before any model response. Both failures remain recorded; their explicitly requested post-fix retries reuse the original uploads. No image change, model fallback, local coordinate relaxation or budget increase was used.

34's post-fix enrichment returned complete records and generated a preview, but its review (`aefa139c5d9c40279667ac764afcdd81`) cited two zero-height regions. Local replay isolates exactly issues[2].source and issues[3].source. Review prompt/schema now request genuine surrounding positive-area citations. The saved invalid review remains rejected; no citation padding occurs. A later user-input review completed structurally but declined the candidate, preserving the prior preview and saving the submitted value separately.

11397's retained interpretation generated a sparse preview; review completed, but correction returned no material change and was rejected. This is a recoverable partial result, not completed fidelity. A later explicitly attributed display_height=1.4 relative-unit refinement passed live review. The value is a visualization input, not a measured height; unchanged horizontal geometry, IDs, source references, transforms and relative units were verified.

Independent browser checks on34/11397 exercised orbit, floor controls, source overlays, actual mesh clicks, revision-pinned source navigation and refinement controls without console errors.34 has13 rendered rooms,9 rendered walls and2 stairs, with16 unresolved records and no modeled openings.11397 has sparse exterior walls, rooms and stairs; interior walls/openings are missing and both outdoor polygons remain unresolved. These are substantial fidelity gaps.

Portable checks on both actual exported IFCs passed: exact original source bytes, manifest descriptions, stable IDs, source references, assumptions and attributed values survive import, restart and identical IFC reupload. Source-coordinate round-trip error stayed below2.3e-16. The import tests forbade provider creation and made zero inference calls.34's rejected input is retained in its original bundle/candidate audit, not falsely exported as an accepted active value.

Independent deterministic analysis of the rejected34 input found no new plan-geometry regression: all40 IDs/renderability states and XY vertices survived. The review rejected pre-existing gaps and gave inaccurate causal explanations. Several walls/rooms cross strict floor bounds by less than a pixel; six wall records contain multi-point paths unsupported by the straight-wall generator. These limits were not silently relaxed. The job and private candidate IFC retain the attributed input, while the active model correctly remains the prior revision. This is a conservative false rejection, not proof that the requested display-height change was invalid.

1794's corrected-schema extraction reached the existing300s timeout (304.98s measured), reference`8429996653bc401bb2314ce5189639d4`. No provider response or token metadata was available; aggregate zeros are not evidence of zero charged tokens. No blind retry or budget increase followed. Original-only supported QA, follow-up and foundation-depth refusal subsequently completed. Fresh saved interpretation,3D, scoped input and IFC export remain unavailable for this case; the acceptance matrix must not call it a complete workflow.

The rotated unseen church plan `wikimedia/17451275.jpg` completed fresh extraction and one source-label question after the compatibility fix. This was a held-out source workflow check, not a3D or whole-building fidelity test.

Source QA was independently reviewed through Chromium, including every1794 and non-residential citation. Original region positions and revision pinning were correct. The held-out church's printed North/South Aisle labels are preserved as source labels; they are not inferred compass orientation. Historical34 answers retain unsupported compass embellishments; a fresh post-fix answer used page-relative positions. All four requested plans returned appropriate source-only foundation-depth refusals, and11397 additionally refused actual ceiling height after its accepted display-height refinement. No highlights were invented where geometry was unavailable.

34's rejected input remains durable but the exact submitted value is not displayed in current assumptions/job details. This is an unresolved UI visibility limitation, not data loss or an accepted update.11397's accepted user value is visible in the assumptions panel with correct provenance.

Independent browser review of non-residential preview `7d0b68d3ff024feba03810195d2f6eed` verified orbit, floor control, actual canvas picking, pinned evidence links and actual-IFC source overlays without JavaScript errors. The preview has3 room areas,16 rendered walls,12 schematic piers and3 schematic stairs;26 records are unresolved (19 windows,6 doors and entrance steps). Openings lack usable wall hosts. The upper-left spiral stair is absent from extraction; the three captured spiral symbols use generic straight tread schematics. No residential furnishings were proposed. This is a source-linked partial visualization, not faithful complete church geometry.

Non-residential geometry enrichment and first review both completed, but correction was rejected atomically (`de914c918618436fa647d6a1e0d118ff`): a floor-metadata replacement changed nested identity order/length. The original preview remained current. Provider calls took183.55s/42.09s/235.87s (enrichment/review/correction); all completedSTOP. Correction output was structurally parsed but failed application validation, so it was not accepted. Post-model source QA still answered from the original plan.


## Final acceptance status

| Case | Fresh interpretation and source-only QA | Optional geometry/review | Attributed input | Portability and restart |
|---|---|---|---|---|
| 34 | Interpretation saved; supported answer, follow-up and refusal checked. Initial compass embellishments remain in historical messages; post-fix answer uses image-relative positions. | Partial preview retained after zero-area review rejection; source-linked browser inspection passed, substantial omissions remain. | Input saved privately; conservative review rejected publication, previous geometry unchanged. Exact rejected value is not shown in current assumptions. | Actual IFC export/reimport/restart and original reupload passed with no inference. |
| 11397 | First response rejected for malformed coordinate; explicitly documented second extraction saved interpretation. Supported answers/follow-up/refusals passed. | Sparse preview retained after no-material-change correction; source-linked browser inspection passed. | Relative display height accepted after live review; original-only actual height still refuses. XY/IDs/source/scale unchanged. | Actual IFC export/reimport/restart and original reupload passed with no inference. |
| 1794 | Schema400 corrected; subsequent extraction timed out without response. Original-only supported answer/follow-up/refusal passed despite pending interpretation. | Unavailable: no fresh interpretation/model. No blind retry or older artifact substituted. | Unavailable: no interpreted floor scope. | Original bundle/chat/reupload/restart preserved with no new extraction job. No IFC export available. |
| Non-residential22921604 | Initial schema400; corrected request saved interpretation. Supported answer/follow-up/refusal passed. | Partial preview retained after invalid floor-metadata correction. Browser orbit/source/overlay check passed; all openings unresolved and a spiral stair omitted. | Relative display height accepted after live review; XY/IDs/source/units unchanged and source-only refusal preserved. | Actual IFC export/reimport/restart and original reupload passed with no inference. |

The non-residential correction's first operation attempted a supported floor-bbox expansion but explicitly emptied16 boundaries,25 openings,3 rooms and16 features. Local replay reproduced the exact rejection with the original document unchanged. Existing floor-metadata membership/order/identity regression tests cover this class. It is patch-contract noncompliance, not a new provider-schema or generator failure.

Final accepted non-residential revision is `8cb0f5019c9d4e77829f4752704f1244`;11397 is `ba99c0701fb54727bf63608cb6c349ec`;34 retains `5245972351244fe2bb79fc23b036372a`. All are derived visualization, never authoritative IFC evidence. The church's final export preserved60 IDs and its attributed value with exact original bytes and zero source-transform round-trip error.34/11397 export results remain as described above.

The real verification server was stopped and restarted after all jobs finished. Identical original reuploads for all four cases preserved revision IDs, chat counts, existing IFC hashes and job-file lists, and returned no new extraction jobs. Rejected34 input remains in its job and private candidate after restart. No failed extraction was automatically retried by reupload. Independent per-artifact import tests used a forbidden provider factory and made zero calls.

Validation:536 backend tests passed,25 optional skipped;24 opt-in browser tests passed; doctor passed. Independent code/schema tests passed44/44; independent reviewers directly used Chromium for QA citations, orbit, floor controls, mesh picking, source overlays and assumption attribution. No raw requests, credentials, uploaded originals or reference answers are committed. Live-call/private-browser artifacts remain under `/tmp/junction-consolidation/` and `/tmp/reviewer-consolidation-browser/`; durable application bundles are in `.runtime/consolidation-verification`.

Final non-residential browser verification after restart confirmed the accepted user value, unchanged60 IDs/XY/topology/source associations, actual pier-to-original clicking and source-only refusal. Saved supported answers did not return highlight IDs, so live answer-driven fading was **not demonstrated** in this fresh case. Existing browser regressions exercise highlighting/fading; those are not a substitute for a live mapping claim. No matches or highlights were synthesized to manufacture acceptance.

**Full four-case acceptance is not met:**1794 lacks a fresh interpretation and downstream geometry/input/export. The other models remain substantially incomplete, and34's refinement review was conservatively wrong. The completed work improves diagnostics, API compatibility, provenance safety and recoverability; it does not establish reconstruction accuracy. No further retry, limit increase, new model, prompt repair loop or infrastructure was added to manufacture passing results.

## Live stage metrics

Times below sum completed provider-call elapsed time, excluding queue wait. Input/output counts use SDK-reported aggregates. A dash means no elapsed-call metadata was available; missing token metadata and zeros from timeout aggregates are shown as unknown. Failed/cached/controlled runs are not merged into a successful fresh run.

| Case | Stage | Outcome | Active calls (s) | Input tokens | Output tokens |
|---|---|---|---:|---:|---:|
| 34 | extraction-0 | complete | 36.72 | 1902 | 5896 |
| 34 | geometry-retry1 | failed | 300.11 | 27909 | 55873 |
| 34 | geometry | failed | 143.91 | 12686 | 26762 |
| 34 | qa-followup-before3d | complete / answered | 18.54 | 55414 | 1227 |
| 34 | qa-refusal-after-input | complete / insufficient | 14.47 | 101654 | 696 |
| 34 | qa-refusal-before3d | complete / insufficient | 17.86 | 60182 | 804 |
| 34 | qa-supported-before3d | complete / answered | 20.44 | 50749 | 1270 |
| 34 | qa-supported-with3d | complete / answered | 26.81 | 96848 | 2043 |
| 34 | refinement | needs_attention | 56.96 | 25808 | 8460 |
| 11397 | extraction-0 | failed | 11.24 | 1909 | 1057 |
| 11397 | geometry-retry1 | failed | 198.77 | 41063 | 34180 |
| 11397 | geometry | stopped | 28.38 | unknown | unknown |
| 11397 | qa-actual-height-after-input | complete / insufficient | 14.23 | 79516 | 991 |
| 11397 | qa-followup-before3d | complete / answered | 16.47 | 16056 | 1031 |
| 11397 | qa-refusal-after-input | complete / insufficient | 14.96 | 75521 | 909 |
| 11397 | qa-refusal-before3d | complete / insufficient | 13.51 | 20246 | 829 |
| 11397 | qa-supported-before3d | complete / answered | 23.69 | 11049 | 1733 |
| 11397 | qa-supported-with3d | complete / answered | 21.08 | 70431 | 1451 |
| 11397 | refinement | complete | 79.80 | 17789 | 12523 |
| 1794 | extraction-0 | failed | 2.96 | unknown | unknown |
| 1794 | extraction-retry1-0 | failed | 304.98 | unknown | unknown |
| 1794 | qa-followup-before3d | complete / answered | 20.46 | 15219 | 1300 |
| 1794 | qa-refusal-before3d | complete / insufficient | 19.52 | 19955 | 885 |
| 1794 | qa-supported-before3d | complete / answered | 15.80 | 11131 | 833 |
| nonresidential | extraction-0 | failed | 7.17 | unknown | unknown |
| nonresidential | extraction-retry1-0 | complete | 15.50 | 1909 | 711 |
| nonresidential | geometry | failed | 461.51 | 56776 | 93787 |
| nonresidential | qa-followup-before3d | complete / answered | 36.47 | 20008 | 2392 |
| nonresidential | qa-refusal-after-input | complete / insufficient | 22.61 | 138723 | 982 |
| nonresidential | qa-refusal-before3d | complete / insufficient | 16.73 | 25222 | 834 |
| nonresidential | qa-supported-before3d | complete / answered | 31.19 | 14915 | 1489 |
| nonresidential | qa-supported-with3d | complete / answered | 29.11 | 133866 | 1509 |
| nonresidential | refinement | complete | 47.77 | 35914 | 7357 |
| unseen-17451275 | extraction-0 | complete | 31.39 | 1922 | 4851 |
| unseen-17451275 | qa-supported | complete / answered | 22.85 | 47317 | 1020 |
