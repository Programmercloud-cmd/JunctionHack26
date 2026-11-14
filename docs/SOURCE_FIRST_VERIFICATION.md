# Source-first verification — 2026-11-14

**Implemented and independently reviewed, with partial reconstruction fidelity.** This records actual source-first, geometry, provenance and failure-recovery checks. It does not claim arbitrary-building reconstruction completeness. Passing tests, successful provider calls, valid IFC files and object counts do not establish source fidelity. The reconstruction default remains configurable `gemini-3.1-pro-preview`; no provider/model substitution or automatic failover was adopted.

## Completed automated and independent checks

| Check | Recorded result | Meaning and limits |
|---|---|---|
| Backend suite | 496 passed, 25 skipped | Final root-run suite (38.05 s). Skipped cases are not counted as verified. Deterministic provider fixtures test contracts/control flow, not live inference quality. |
| Browser suite, separate run | 24 passed (133.26 s) | Includes source-only chat/clarification, explicit model action, user-height refinement, source-only height refusal, citations, persisted conversation/reupload, floor controls and viewer state. Fixture answers remain explicitly synthetic. |
| Doctor | Passed | Local environment/configuration diagnostic, not proof of provider access or geometry accuracy. |
| Format adapter focused review | 23 tests passed | SVG/DXF mapping, resource isolation, metadata and rendering regressions reviewed independently. See `SOURCE_FORMATS.md`; adapter success alone does not verify integrated QA/3D. |
| Focused provenance re-review | 29 tests passed | Independent reviewer verified source-only stripping without saved-data mutation and numeric source review before publication/rejection recovery. |

Legacy diagnostics were isolated from automatic upload extraction by creating their source through the store. The secret/source canary checks remain intact. True defects were fixed: legacy provider failures were incorrectly categorized as description failures, and geometry errors were logged twice. Failure phases now distinguish provider, returned-description validation, generation and reopening through one sanitization boundary.

Backend coverage includes incremental/cross-building reuse, stale revision protection, source-local/canonical page agreement, successful JSON retention after geometry failure, typed patch identity/provenance checks, user-input conflicts, source-only drawing reasoning and native semantic evidence. Browser checks also caught and fixed an enqueue-response race that could erase the next question typed while the preceding request was accepted.

## Live Gemini evidence recorded so far

Inputs used the application pipeline and unchanged originals. No evaluation answer file was runtime context, no source description was manually repaired to manufacture a successful extraction, and old baseline artifacts remain preserved.

| Case / stage | Time | Input / output tokens | Observed result |
|---|---:|---:|---|
| `colorful-34.png`, source-only extraction after coordinate-prompt correction | 22.058 s | 2,273 / 2,959 | Valid normalized interpretation saved without requiring 3D. |
| Same source, drawing QA | 53.569 s | 40,404 / 4,642 | Supported depicted upper-floor door-count answer with six original source citations. This is a source-scoped result, not a count of every installed door. |
| Religious example `14661814`, source-only extraction | 7.015 s | 2,174 / 352 | Successful source-only interpretation; no 3D claim. |
| Same religious example, QA | 20.135 s | 12,328 / 1,399 | Supported answer with four original-source citations; before optional 3D. |
| Institute related set, three sources | See retained run metadata | See retained run metadata | Independent extractions succeeded; first combined interpretation exposed alternate-floor labeling duplication described below. |

The earlier unchanged colorful-34 source-only checkpoint returned bbox coordinates on a 0–1000 grid and failed strict validation. The exact captured response replay produced 28 source/measurement-region validation errors. Extraction/enrichment prompts now explicitly require normalized decimals in `[0,1]`, with 0.5 representing halfway across a page; there is no silent coordinate division. The later successful row above is a genuine new live run.

The initial door-refusal trace was inspected across all relevant stages: both initial/additional sufficiency gates returned unclear, the draft introduced schedule/clearer-callout requirements, and post-draft review accepted that refusal. The correction applies depicted-door scope to gate, draft and review. Positive and individually ambiguous-opening regressions remain separate from live count evidence.

The institute set initially created separate interpretations for labels `Erdgeschoss` and `Grundriss Erdgeschoss`. A generic word-contained-label or shared-supported-level rule now retains possible alternate views as source-linked unresolved records and observations rather than extra storeys. Cached source interpretations were replayed through that merger without new extraction. Combined-source live QA passed; institute geometry was not verified. This is deterministic source integration, not a manual edit of returned descriptions, and it does not prove two views are geometrically equivalent.

## colorful-11397 enrichment schema diagnosis

The first explicit enrichment request was rejected by Gemini with HTTP 400 before output tokens were produced. The stage was `geometry_enrichment`; no returned interpretation/patch JSON was available. The previous usable baseline was retained. This was an operational request failure, not a source-sufficiency conclusion.

Controlled probes isolated the submitted record-schema structure:

| Probe schema | HTTP result |
|---|---:|
| Exact combined typed `RecordPatch` record schema | 400 |
| Floor-only record schema | 200 |
| Non-floor-only record schema | 200 |
| Generic record object | 200 |
| Merged-properties record object | 400 |

The generic-object probe was API-compatible but **not usable in production**: actual enrichment returned empty `record: {}` values, which strict local validation correctly rejected. The final Gemini transport uses a JSON-encoded string for each complete typed patch record. The exact record schemas are supplied as generation guidance; decoded values still pass the unchanged collection-specific Pydantic schema and source/identity/provenance validation. OpenAI retains its typed transport. A live string-record probe produced a nonempty valid record, then real religious and 11397 enrichment produced validated patches without HTTP 400. No automatic provider/model fallback was introduced.

The valid 11397 response then exposed a local patch-order defect: its floor metadata contained an unchanged nested inventory except for the same stair connection explicitly declared by a separate feature replacement. The floor guard rejected that redundant copy. The narrow fix checks nested identity/order/length and accepts only exact base/current/explicitly declared replacement copies, then discards the nested copy in favor of staged records. Only separately validated object operations apply geometry changes. Seventeen focused tests cover both orders, unrelated mutations and atomic rejection when a separate operation has invalid evidence. The exact saved live response was replayed against its exact base revision, with no new extraction/enrichment call. Subsequent source review remains live.

A separate source-cache defect was found with fresh DXF: upload preflight and publication normalized the same file twice, yielding different preview hashes. Normalization now happens once per cached resource. Restart may recover only exact hash-matching pinned pixels from the original building page; arbitrary changed pixels are rejected. The verification cache was repaired using those exact published pixels, without altering source bytes or the returned interpretation. Independent reproduction verified recovery and rejection if both copies are corrupt.

## Preserved evidence locations

- `/tmp/sourcefirst-live-checkpoint`: initial live checkpoint, including retained `annotated34-returned.json` for strict replay.
- `/tmp/sourcefirst-live-retry`: normalized-coordinate retry and subsequent live records.
- `/tmp/sourcefirst-schema-probe`: controlled wire-schema probe results.
- `.runtime/sourcefirst-demo-v2`: earlier diagnostic/live checkpoint; the consolidated final store is `.runtime/sourcefirst-final-verification`. Baseline artifacts remain preserved separately.
- `/tmp/junction-formats-verification`: original format comparison/rendering artifacts described in `SOURCE_FORMATS.md`.

These are local verification artifacts, not committed fixture answers or a promise of permanent external availability. Raw provider requests and credentials are excluded from logs and documentation. Structured responses are retained privately where available.

## Additional live and browser checks

| Case | Observed result and limitations |
|---|---|
| Religious `wikimedia/14661814.svg` | Live geometry and bounded review completed in 280.31 s, 78,666 input / 50,915 output tokens. Retained a derived IFC; a later correction candidate failed source review and did not replace it. Independent Chromium orbit, source click, overlay and neutral concept checks passed. Major straight walls and piers are represented; small circular columns, curved apse/chapel boundaries and interior details remain omitted. This is partial coverage, not full reconstruction. |
| Institute SVG + matching PDF + east–west section | Cached replay merged three successful source interpretations without constructing a provider. One floor remains; possible alternate plan and section remain source-linked views, not extra storeys. Live source-only view-identification QA completed in 32.95 s with 109,625 / 1,270 tokens and two citations. No institute 3D fidelity claim. |
| Fresh Swiss dwelling `site120_bldg55_floor209.dxf` | Source extraction succeeded in 25.08 s with 2,345 / 3,382 tokens. Source-only printed-area QA succeeded in 28.06 s with 35,691 / 777 tokens and one citation. Optional geometry reached Gemini's output limit after 349.61 s (16,654 / 65,522 tokens): no model was generated, saved JSON and originals remain usable. Expanded failed-job details now show the sanitized token-limit reason. No DXF geometry-fidelity claim. |
| Fresh commercial `Crema_Cafe/Models/pdfs/A-101 - Elevations v3.pdf` | Unchanged wide-format source, no manual crop/rotation. Extraction took 91.79 s, 2,283 / 9,782 tokens; retained eight unresolved elevation views and zero floors. Source-only view QA took 46.71 s, 16,247 / 4,171 tokens, with original citations. No invented floor model. |
| Native duplex IFC | Independent actual-browser floor selection and 0/50/100% cutaway passed using four supplied storeys at elevations −1.25, 0, 3.1 and 6; clipping changes neither vertices nor openings. Uncontained objects remain identified. |
| Retained 1794 | Actual original-coordinate overlay and browser controls inspected; prior known extraction errors remain. This is a regression comparison, not fresh extraction. |
| 11397 source-only height QA | Despite visible saved extrusions, live original-only question returned insufficient in 20.88 s (115,976 / 957 tokens), with no invented citations or highlights. |

These samples span residential, institutional, religious and commercial buildings and original raster/vector/native sources. This is not broad dataset accuracy measurement. Cases that exposed changes are now regression cases; the fresh café trial was selected after the source-schema/cache changes. No dataset reference answers were runtime context. Tests with injected providers are distinguished from these live calls.

## Final 11397 coherence, attributed height and portability

The exact retained 11397 enrichment response produced accepted revision `b7e743c4a62d449a809ac4116059b9d4`. Its normal live source-review/correction workflow took 116.35 s and used 121,217 input / 17,903 output tokens, excluding the earlier enrichment call. Source review accepted the registered/stair-connected IFC; a later correction returned a missing typed record and was rejected. The job therefore ends **failed**, with a usable accepted model retained. This is not a fully successful correction run and does not fix all opening omissions. Reviewer-generated proposed windows on the left wall were not accepted or added.

Independent direct IFC and Chromium checks found:

- Actual supplied generated storey elevations are 0 and 1.2 **relative display units**, not measured heights. Stacked mode preserves those elevations; exploded mode adds spacing.
- Source and building transforms remain separate. Supported exterior anchors align floors, their shared-page linear scale is unchanged, and the larger ground terrace stays larger (2.22 versus 1.04 display-length outdoor depth in this reconstruction).
- The lower schematic stair mesh spans 0–1.22 and reaches the upper level. Rise and other missing vertical dimensions remain display assumptions.
- Actual reopened IFC source overlays align with both original diagrams; embedded description equals the accepted saved description. This checks coordinate fidelity, not complete semantic extraction.
- Orbit, both floor selections, stacked/exploded switching, room selection and revision-pinned original evidence worked without JavaScript errors. Camera orientation is retained; tiny damping drift is not a camera reset.

Export/reimport into a fresh store and restart/reupload preserved all 85 stable element IDs, original page, inferred origin and assumptions. Unknown units remain context-dependent relative units. Source→building→source round-trip maximum error was `2.22e-16`. The imported legacy baseline embeds its normalized source page, not recoverable original PNG file bytes; v5 preserves that limitation without inventing source identity. The exported IFC SHA256 is `5b0c598dfe912d05263410a048ea22c3170a1ed86186e241cd79f5c390a06691`. This portable-artifact check made zero provider calls.

On saved 1794, one explicitly supplied **3 m user value** produced accepted revision `bd98f00829914c72b49c82028a62b96e`. Refinement took 74.82 s, 31,706 / 10,854 tokens; the original-drawing-only height question then took 22.07 s, 59,941 / 998 tokens and correctly returned insufficient. All object IDs, XY vertex signatures and source transforms were unchanged; units remain relative. Wall display height changed from 1.2 to 1.38461538 under the disclosed unscaled display convention. Reopened IFC retained the original page and user-provided attribution. Independent Chromium inspection found no errors. No new extraction occurred.

After restart, the fresh SVG and DXF originals uploaded under changed filenames reused their completed interpretations with no extraction jobs. The institute merger reused all three cached source interpretations. A separate attempted PNG cache check was actually a first upload (the baseline had been imported from IFC); it was stopped and archived, not counted as zero-call reuse or successful extraction.

Final independent implementation review cleared the floor-patch order fix, source-pixel recovery and safe diagnostic display. Backend suite: **496 passed, 25 skipped**; opt-in Chromium suite: **24 passed**; doctor and diff checks passed. These tests exercise mechanics with injected providers. Live claims above come from actual Gemini runs, not fixtures.

## Saved local demo and remaining limits

The consolidated verification store is `.runtime/sourcefirst-final-verification`. It contains accepted 11397 and attributed-height 1794 revisions, native duplex, source-only colorful34, institutional sources, religious partial model, DXF source-only evidence and the unsupported café elevation sheet. Original baseline stores remain untouched. While the verification server is running, open `http://127.0.0.1:8769`; do not start another process against this storage root. After stopping that server, use:

```sh
BLUEPRINT_STORAGE_ROOT=.runtime/sourcefirst-final-verification PORT=8000 bash scripts/dev.sh
```

Private evidence: `/tmp/reviewer-11397-accepted/`, `/tmp/reviewer-11397-final-browser/`, `/tmp/sourcefirst-portable-check.json`, `/tmp/sourcefirst-live1794-height/`, `/tmp/reviewer-religious-live/`, `/tmp/sourcefirst-live-cache-reopen.json`, and immutable job/revision metadata in the verification stores. Source responses are private artifacts; no raw requests, credentials or dataset answers are committed.

Remaining geometry errors are not hidden by test totals: 11397 still has incomplete/misassociated openings and retained detail/label issues; 1794 retains prior source-extraction errors; religious circular columns, curves and interior details remain incomplete; DXF optional geometry exhausted output tokens. The scene inventory only accounts for interpreted records, not every meaningful feature in the source. Source-only QA remains available in all those cases, and unsupported elevation views do not become floors.

Mixed genuine native IFC plus drawing grouping is explicitly unsupported and rejected before publication; native IFC remains a separate supplied-record building. DWG is unsupported because no validated local conversion path was found. Unknown source geometry and scale remain unresolved or explicitly schematic. User-supplied physical heights preserve attribution and do not calibrate XY; unscaled vertical presentation uses the disclosed display conversion. Source-only extraction can omit semantic records; factual questions still inspect the originals.
