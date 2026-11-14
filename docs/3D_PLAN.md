# Lean 3D extension — reviewed implementation plan

Current drawing reconstruction is specified in [RECONSTRUCTION_V2_PLAN.md](RECONSTRUCTION_V2_PLAN.md) and [RECONSTRUCTION_V2_CONTRACT.md](RECONSTRUCTION_V2_CONTRACT.md). These supersede historical single-floor/relative-only restrictions; core evidence and provider invariants remain.

User-authorized scope supersedes the earlier no-3D constraint. Keep the existing local Python/plain-JS app and evidence gate. Add a browser Three.js viewer, native IFC import, then one-page approximate image reconstruction. No remote rendering, Blender, cloud, DXF/SVG/DWG, photorealism or inferred multiple storeys.

## Deliver in this order

1. Import and display one actual IFC (`ifc_bench/duplex_arc.ifc` is the first candidate). Read model geometry and properties with IfcOpenShell; preserve GlobalIds.
2. Answer explicit English whole-model IFC element-count questions through strict pattern matching + deterministic selection + the existing gate. Highlight selected elements, fade others to 0.1 opacity, click through to IFC source facts. No extra intent-model call or storey filters.
3. Generate an approximate single-floor scene from one selected image/PDF page. Store it once; reuse it across questions. Every object links to a region of the original page. Mark missing scale and assumed dimensions.
4. Connect existing image answers only where their evidence maps to scene objects reliably. Unmapped answers continue to show source-region evidence with no invented selection.

## Shared scene contract (root owns final Pydantic types)

`Scene {version:1, document_id, source_kind:"ifc"|"image", units:"m"|"relative", up_axis:"z", source_page:int|null, elements:SceneElement[], warnings:string[], catalog_complete:bool}`.

`SceneElement {id, kind:"room"|"wall"|"door"|"window"|"other", name, ifc_type:string|null, storey_id:string|null, source:SourceRef, properties:Property[], assumptions:Assumption[], geometry:Geometry|null}`.

- `SourceRef` is a tagged union: `{kind:"ifc",global_id,step_id}` or `{kind:"image",page,bbox:[left,top,right,bottom]}`. IFC facts are evidence from the supplied model, not evidence that it matches the built building. Source references never point to generated renders.
- `Property {name,value,unit:string|null,origin:"source"|"derived"}`. Keep only useful bounded primitive fields (IFC class/name/storey, supplied dimensions and selected quantities/property sets); preserve original names/units. Don't promote raw IFC lengths to metres without unit conversion or multiply already metre-based mesh coordinates again.
- `Assumption {property,value,unit,reason}` records invented dimensions separately. Source geometry and inferred image geometry must not share a blanket "verified" label. Image horizontal locations are model interpretations linked to pixels; vertical dimensions are explicit assumptions.
- `Geometry` is a small tagged union: `mesh {positions:number[],indices:int[]}`, `box {center:[x,y,z],size:[x,y,z],rotation_z:number}`, or `floor {polygon:[[x,y],...],elevation:number}`. Fixed-size arrays may need lists with length validators for SDK structured-output compatibility. All coordinates must be finite; indices in range; dimensions positive; polygon vertex counts bounded.
- IFC element IDs are the unchanged GlobalId; metadata includes STEP IDs. Reject duplicate/missing GlobalIds on selectable relevant elements rather than inventing identity. Image IDs are assigned by server in a document/page namespace and retained with the cached scene.
- Keep elements with source metadata but failed/missing geometry as `geometry:null` plus warnings. Deterministic counts operate on the complete catalog, never only on meshes. Highlighting such IDs shows their source record even if no object can be rendered.

Server uses IFC world-coordinate geometry in metres with Z-up, matching the viewer camera up vector. Image reconstruction uses relative coordinates with a fixed documented image-to-ground mapping; do not label relative scene dimensions as metres. Centering/zoom is a viewer transform and must not change source dimensions.

## Minimal API additions

- Existing upload accepts `.ifc` (actual parsed content, not extension alone). Document metadata gains `kind:"drawing"|"ifc"`; IFC has `pages:[]` and a ready scene. Existing drawing responses remain compatible. Root chooses a separate bounded IFC upload allowance (suggest 25 MiB); retain drawing limits.
- `GET /api/documents/{id}/scene`: cached scene; 404 if none has been generated.
- `POST /api/documents/{id}/scene` with `{page:1}`: one reconstruction request for a selected drawing page; returns cached result on repeat. IFC never calls a model to regenerate imported geometry. Only one selected page scene per document in this slice; do not silently replace it.
- Answers gain `highlight_ids:string[]` (default empty) and `model_evidence` for native IFC facts, while existing image `evidence` remains unchanged. Server validates every highlight against the scene and corresponding source evidence. A textual answer cannot manufacture a valid object mapping merely by naming a known ID.
- The viewer uses cached scene data; question requests update highlighting only. Distinct controls: "Highlight answer" and "Show assumptions". Clicking an image object opens its page/box; clicking an IFC object opens its GlobalId/class/name/properties.

## Native IFC counts: narrow and deterministic

Allow deterministic `count` of rooms/spaces, walls, doors, windows across the uploaded model only. A strict pattern accepts questions such as "How many windows are in this IFC model?" Other questions use the normal gated provider path. Compound filters, physical-building completeness claims, material/condition qualifiers, spatial relations and floor-specific questions never get simplified into this shortcut. Do not silently simplify "fire doors" into "doors".

Code selects exact catalog IDs using IFC types (including relevant subclasses). Run the existing overall sufficiency gate on the original question and source-derived catalog records/coverage metadata. It receives actual source facts, not merely the proposed answer. Negative or unclear gates retain their meaning; absence of a floor plan image must not make native IFC metadata unusable. IFC unclear requests focused clarification; image crop inspection is not applicable.

Only a sufficient gate plus a supported, validated intent produces a deterministic response such as "24 windows are recorded in the uploaded IFC." Include the matched GlobalIds as evidence/highlights. A zero count needs evidence that the relevant catalog was completely inspected; it cannot cite nonexistent elements. Unknown property questions return a scoped limitation, never fabricated IFC values. Geometry tessellation failures do not affect catalog counts, but catalog parsing/truncation does.

## Image reconstruction and safe matching

One provider extraction call describes visible room polygons on a single floor, up to 30 rooms. Server derives approximate boundary boxes and source regions from these polygons; openings are deferred. Validate geometry and object count limits before caching. Root uses the existing selected provider, preserves operational-error behavior, and explicitly prevents this assumed scene from entering factual-answer evidence.

Initially use conservative room matching: a same-page source-region match must uniquely identify the room (IoU >= 0.5), include its normalized name, and have area < 0.8 of the page. No generic room token or incidental overlap qualifies. If that cannot be established, return `highlight_ids:[]` and show the original source evidence. No extra matching-model call.

Image scenes always retain a persistent "Approximate · unscaled" badge in this slice, even if dimensions are printed. Wall height/thickness have rendering defaults in relative units, each visible under assumptions. Questions about actual heights still run against the original plan and remain unanswerable when unsupported. Rendered appearance is never new evidence.

## Bounded ownership and checks

- IFC agent: `app/ifc_import.py`, `tests/test_ifc_import.py`; read bytes -> complete catalog + meshes, stable IDs, units and transform; no provider/UI edits. Enforce limits before expensive geometry (suggest <=4,000 relevant elements and <=1,000,000 triangles; fail oversized imports explicitly).
- Viewer agent: `app/static/viewer.js` and coordinated UI additions; pinned local Three.js modules, orbit/selection/fading, object inspector and assumptions controls. No CDN dependence for the demo.
- Root: shared schema, document/route integration, both provider paths, image reconstruction, intent/gate orchestration and highlight validation.
- Independent reviewer: check plan before implementation and source-to-answer-to-highlight invariants after integration.

Acceptance: actual duplex IFC opens; expected counts are independently checked from the source; IDs survive import; arbitrary unknown IDs cannot highlight; zero counts and geometry-less elements behave honestly; IFC units/placements are correct; one sparse JPG generates an explicitly unscaled scene once; invented heights never answer factual questions; unmappable image evidence remains 2D-only; existing upload/gate/refusal/browser tests still pass.

Documentation consulted: IfcOpenShell geometry processing and unit utilities (`docs.ifcopenshell.org/ifcopenshell-python/geometry_processing.html`, `docs.ifcopenshell.org/autoapi/ifcopenshell/util/unit/index.html`). Verify behavior against the installed version before implementation.
