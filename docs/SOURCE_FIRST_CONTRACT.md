# Source-first contract

Implemented checkpoint, 2026-11-14. This extends `CONTRACT.md`, `PRODUCT_PLAN.md` and the reviewed `SOURCE_FIRST_PLAN.md`; final acceptance is tracked separately in `SOURCE_FIRST_VERIFICATION.md`. JSON uses snake_case. The configurable reconstruction default remains `gemini-3.1-pro-preview`; the app uses Gemini for inference.

## Sources, identities and revisions

The building ID remains the SHA-256 identity of its initial upload. Each source has its own SHA-256 `source_id`, independent of filename. Original bytes and normalized pages are preserved in filesystem resources; filenames can be aliases. A revision pins its source membership, source-local page mappings, interpretation, identity/frame registries, user inputs and available geometry. A building retains its identity when sources are appended.

Each public page has `page`, `source_id`, `source_page`, `source_filename`, `width`, `height` and `image_url`. `page` is the append-only building page number; `source_page` is the page/layout within that file. Regions use normalized decimal fractions from 0 to 1 in the original displayed page. Pixels, percentages and 0–1000 integer coordinates are rejected, not silently divided. Referenced `page`, `source_id` and `source_page` must agree. Existing page-only references resolve against their pinned revision.

Resources store successful independent per-source interpretations. A cache merge remaps every local page reference into the selected building and assigns building-specific stable IDs. Adding B does not re-extract A. Reopening, renamed byte-identical uploads, orbiting and mode switching do not invoke inference. Failed/interrupted extraction requires explicit retry. Ordinary questions are not answer-cached. Complete retained legacy descriptions are reused; missing new cache fields do not themselves require another inference call.

Possible repeated floor views are conservative: normalized word-contained labels (for example `Erdgeschoss` and `Grundriss Erdgeschoss`) or the same explicitly supported order retain the incoming diagram as a source-linked unresolved alternate view and preserve its semantic observations. This avoids silently creating another storey; it does not establish equivalence or fuse their geometry. Uncertain alignment and differing measurements remain attributed.

**Grouping limitation:** genuine native IFC must be opened as a separate building. Grouping it with another source/native IFC is rejected before publishing a mixed bundle. This is a lean implementation limitation: the current combined drawing pipeline does not supply a complete mixed native-record catalog. Drawing-derived IFC retains drawing authority and can contribute recoverable embedded original sources. Native IFC still uses its complete supplied semantic catalog, including geometry-less records; generated IFC never becomes factual native evidence.

## Public document and job state

Public documents retain prior fields and add `sources`, `interpretation_status`, `geometry_status` and `geometry_revision_id`. `interpretation_status` is `pending`, `partial` or `complete`. Geometry is `not_requested`, `available` or `stale`. `has_scene` means a saved scene exists, not that every source feature has geometry or the model is accurate. After source changes, a retained scene can belong to `geometry_revision_id` rather than the current interpretation revision; it must not be presented as regenerated geometry.

Job kinds are `extraction`, `reconstruction`, `question` and `refinement`. Statuses are `queued`, `running`, `complete`, `needs_attention`, `failed`, `budget_exhausted`, `stopped` and `interrupted`. Jobs include identity, building/base/current revision, phase, message, timestamps, issues and attempts; usage and operation-specific results appear when available. Failure fields include `error_stage`, `error_category`, `diagnostic_id`, safe `diagnostic_message` and `has_previous_model`. A failure with no usable model says sources were saved and no usable model was generated. Valid saved interpretation survives geometry failure.

Returned structured responses may be retained privately for replay; raw provider requests, credentials and exception bodies are not logged or exposed. Stop prevents late publication; an in-flight call may finish. Revision compare-and-swap, guarded publication and per-source merging prevent a late extraction/geometry result from dropping appended sources or user inputs. Restart marks unfinished jobs interrupted while preserving sources and accepted revisions.

## HTTP endpoints

| Method and path | Request / result |
|---|---|
| `POST /api/documents` | Multipart legacy `file` and/or repeated `files`. Returns public document plus `is_new_upload`, `added_source_ids`, `extraction_jobs`. New uncached drawing sources automatically queue interpretation; no automatic 3D. |
| `POST /api/buildings/{id}/sources` | Same multipart fields, append to selected building; same result shape. |
| `GET /api/buildings` | `{buildings:[public_document]}`. |
| `GET /api/buildings/{id}` | Public document plus persisted `jobs`, newest first. |
| `POST /api/buildings/{id}/extraction` | `{source_ids?:[id], retry:true}`; HTTP 202 `{jobs:[job]}`. Successful existing interpretation is reused; failed/interrupted sources can retry. |
| `POST /api/buildings/{id}/reconstruction` | `{base_revision_id?, mode:"refine"|"reconstruct"}`; HTTP 202 job. Explicit geometry generation/refinement. |
| `GET /api/jobs/{id}` | Persisted job and final `answer` for completed questions. |
| `POST /api/jobs/{id}/stop` | Updated stop status. |
| `GET /api/buildings/{id}/revisions/{revision}/pages/{page}` | Exact revision-pinned normalized PNG. A page added later is unavailable in an older revision. |
| `GET /api/documents/{id}/pages/{page}` | Compatibility current-page PNG route. |
| `GET /api/buildings/{id}/sources/{source_id}/original` | Preserved original bytes as attachment; no raw SVG is embedded in the browser. |
| `GET /api/buildings/{id}/revisions/{revision}/evidence/{object_id}` | Original native IFC record and coverage for the pinned revision; rejects drawing-derived factual shortcuts. |
| `GET /api/documents/{id}/scene` | Saved scene; 404 if none. |
| `POST /api/documents/{id}/scene` | Compatibility explicit synchronous generation with `{page:1}`; uses the job workflow and reuses an existing scene. The page argument does not restrict whole-building generation. |
| `GET /api/documents/{id}/model.ifc` | Saved IFC download; 404 before generation. |
| `GET /api/buildings/{id}/conversation` | `{conversation_id:id,messages:[...]}`. |
| `POST /api/questions` | `AskRequest`; HTTP 202 revision-pinned question job. |
| `POST /api/ask` | Compatibility synchronous `AskRequest` → final `Answer`; also persists turns. |
| `GET /api/buildings/{id}/assumptions` | `{building_id,revision_id,rows,editable_properties}`. |
| `POST /api/buildings/{id}/refinements` | Batch request below; HTTP 202 job. |

Expanded failed-job details show only the existing sanitized `diagnostic_message`, escaped as text; raw provider errors and requests are never displayed. Operational failures are not source-insufficiency judgments. Stale revision submissions return 409. Unknown source references and invalid typed edits are rejected. `/api/health` reports provider/model configuration and existing per-file limits, not successful provider access.

## Shared interpretation and optional geometry

`BuildingDescription` remains the shared representation: floors, semantic records, observations, unresolved views and optional geometry. Empty geometric arrays do not make the original evidence unavailable. Sections/elevations can supply source-linked observations and dimensions without becoming floors. Reasoning objects and floor context derive from saved interpretation even when no scene exists.

`extract_interpretation(document, include_geometry=False)` requests source-linked semantics/observations without exhaustive geometry tracing. Each successful result is validated and saved before any generator call. QA can inspect original pages before extraction completes and after reconstruction fails; missing JSON records never establish absent source features.

Explicit generation reuses saved interpretation and requests missing geometry/registration/stair relationships through `enrich_geometry(document) -> DescriptionPatch`. Application validation remains collection-specific and strict. Gemini's wire encodes each complete patch record as a JSON string (or null for removal): the combined typed union was rejected by the endpoint, while generic objects produced empty records. Decoded record objects still pass local typed `DescriptionPatch` validation. This adaptation does not permit executable code, unknown fields, arbitrary identity changes or invented user provenance. See the verification report for controlled probes and actual live outcomes.

Typed patches preserve existing persistent IDs and require original source evidence. A floor metadata replacement cannot execute implicit nested edits. Its nested copies must preserve base/current ID order and length and exactly match base/current records or separately declared same-floor, same-collection replacements. The floor operation retains staged nested arrays; every separate edit still passes normal source, identity, review and provenance checks. Any invalid operation rejects the entire candidate.

Gemini enrichment uses the same missing-geometry requests as local detection. A valid wall segment does not require an optional footprint; already complete geometry is reused. Missing registration applies to non-reference floors only. These requests guide targeted enrichment, not source completeness judgments. Deterministic IFC generation, reopening and original-coordinate overlays support source review. Existing usable geometry is retained on invalid/rejected replacements. A first model can be published as preview while review runs; preview status is not a fidelity guarantee. Concept styling never enters source counts, QA evidence or IFC facts.

## Conversation and reviewed answers

`AskRequest` contains `document_id`, `question` and optional `revision_id`, `request_id`, `conversation_id`, `reply_to`, `clarification_response`. `conversation_id` is the selected building ID. Async repeated `request_id` reuses its question job. History comes from the server's saved building conversation; client-supplied assistant assertions are not accepted as evidence.

Messages carry `id`, `role`, `revision_id`, `timestamp`, optional job/request/reply references, and either user `question` or assistant `answer`. Clarification replies reference an existing assistant clarification in that building. Earlier answers help resolve phrases such as “the upper floor” but remain fallible context, never additional factual sources.

Intent resolution is separate from source sufficiency. A clarification returns:

```json
{"status":"clarification","answer":"Which floor?","clarification":{"message":"Which floor?","suggestions":["Ground floor","Upper floor","Both"],"free_text_allowed":true},"gate":null,"inspection_passes":0}
```

It has no evidence refusal or reviewed factual draft. Ordinary answers retain `answered|insufficient|unclear`, the three-way sufficiency gate, bounded additional inspection and post-draft review. Answers include `answered_revision_id`, `display_revision_id`, validated original-page `evidence` or native `model_evidence`, conservative `highlight_ids`, `support_summary`, review metadata, and `calculation_results` with source-bound inputs/results. Rejected drafts do not become findings. Chat citations work without 3D and open the exact answered source revision; unreliable geometry associations omit highlights.

Door questions distinguish depicted symbols from all installed building doors. A schedule is not universally required for visible leaves/swings/jambs. Ambiguous openings should be identified individually and connecting doors counted once. Gate, draft and review all apply these rules; generated object totals cannot replace original drawing inspection.

For `sources_only` reasoning, nested `user_provided` calibration/registration/stair connection fields are stripped from the serialized interpretation copy and supplied-value records are omitted. Saved data remains unchanged. Permitted `sources_and_user` answers expose relevant inputs separately, cite `user_value_evidence` IDs and receive server-added `user_value_attributions`; original-source questions cannot silently adopt them.

## Editable inputs and provenance

Assumption rows expose `id`, `scope`, `property`, `label`, `value`, `unit`, `provenance`, `reason`, optional `source`, and `editable`. Provenance distinguishes observed information, inferred interpretations, display assumptions, unknowns and user-provided values. Shared floor assumptions are grouped; source observations are retained separately.

The batch payload is:

```json
{"base_revision_id":"...","edits":[{"property":"floor_height","scope":{"floor_id":"..."},"value":3.4,"unit":"m","reason":"Provided by user"}],"supporting_source_ids":[]}
```

Each edit may also cite `source:{page,bbox,source_id?,source_page?}`. Supporting files must already belong to the building. Implemented properties are:

| Property | Value and scope |
|---|---|
| `floor_height` | Finite positive number; floor scope; `m`, `mm`, `cm`, `ft` or `in`. |
| `display_height` | Positive number; floor scope; physical units above or explicit `relative` display units. |
| `calibration` | `{length:number,segment:[[x,y],[x,y]]}` with distinct normalized endpoints, physical unit and a source region on the selected floor's page. |
| `stair_connection` | Selected stair object/floor; `{target_floor_id,target_feature_id?}` referencing another known floor and optionally its stair. |
| `interpretation_correction` | Nonempty text describing a scoped correction; reviewed through a typed data patch. |

Apply validates the full batch before mutation. Inputs retain their IDs, scope, units, source support, submission/base revision and `user_provided` provenance. Observed source heights are not rewritten as user values. Known source calibration/height conflicts, including section observations with uncertain scope, retain both source facts and submitted inputs and return `needs_attention` without replacing the usable revision. Equivalent calibration is compared using original-page aspect and physical unit conversion.

Numeric changes to an existing scene generate/reopen locally, run loss checks and use one existing original-source/actual-geometry review before publication. The reviewer receives user values separately and must distinguish their authority from source observations. Source-only numeric input persistence does not automatically request 3D. Interpretation corrections invoke the bounded typed-patch workflow. Editing/keystrokes make no model calls. Failed/stopped/rejected candidates retain submitted inputs in the persisted job and preserve the prior usable revision.

A supplied vertical height never establishes XY scale. With unknown horizontal calibration, physical height remains attributed in its original unit; vertical presentation uses the disclosed display convention `1 m = 1.2/2.6 relative units`. The scene stays unscaled. This is a display choice, not an inferred building measurement.

## Geometry, formats and portability

Original-page coordinates, building registration/elevation and viewer-only exploded spacing remain separate. Supported shared-page registration can use relative units without asserting metres. Stacked mode retains generated storey elevations; exploded mode adds spacing. Continuous schematic stairs preserve supported footprints/connectivity with assumed vertical geometry identified. Optional wall footprints preserve supported tapered/angled shapes; explicit hosts remain required for openings.

Native floors come from supplied IFC storeys and containment. Cutaway is a percentage clipping control: 0% is the floor reference and 100% the full reference height. All-floor mode uses each storey's own reference; missing heights and uncontained geometry use displayed fallback references. Clipping does not shrink walls or move openings. Camera, floor/mode selection and assumptions controls survive accepted updates where identities remain valid.

SVG and DXF use the existing normalized-image pipeline, with preserved original bytes, vector/layout metadata and coordinate mappings. Declared document units alone do not establish physical building scale. Unsupported rendering features are reported; external resources are not fetched. DWG is unavailable because no validated converter path exists. See `SOURCE_FORMATS.md` for adapter details.

Portable artifact v5 adds available original source bytes/hashes, mappings, source interpretations and user inputs; V2–V4 remain readable. Legacy derived artifacts may contain only embedded normalized pages with null source IDs and no recoverable original file bytes. Those pages remain authoritative supplied image evidence; absent original files are never fabricated. Upgrading such an artifact to v5 does not recover missing originals. Original pages and derived status are restored on import. Existing per-file/source normalization and artifact-size limits remain explicit; the PDF five-page bound is not a cumulative building-page or DXF-layout bound. An over-capacity portable export must fail explicitly while preserving the local bundle. Large multi-source exports and complex vector semantics are not guaranteed complete reconstruction.
