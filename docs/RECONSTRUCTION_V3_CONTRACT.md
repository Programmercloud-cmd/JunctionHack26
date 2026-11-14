# Reconstruction V3 contract (reviewed)

Root owns shared schema/API/provider and import integration. V3 replaces room-edge enclosure generation with an explicit physical-boundary description. Original-page coordinates, source-only QA, unknown scale and V2 portable imports remain compatible.

## Description

Keep BuildingDescription(floors, limitations) and existing floor source/order/orientation/calibration fields. RoomDescription adds environment indoor|outdoor|unknown; its polygon creates only an IfcSpace footprint, never walls. Add floor.boundaries, floor.features and floor.unresolved. No list caps.

BoundaryDescription: key:str (unique within floor), kind wall|railing|open_edge, label, segment:list[Point], source:PageRegion, thickness_segment:list[Point] (empty if unknown), basis observed|inferred, note. Walls and railings require two segment endpoints; open_edge additionally accepts a continuous polyline rendered as flat strips, never an enclosure. Physical wall records describe one shared wall axis spanning any explicitly hosted gaps; each shared physical boundary is listed once. Thin door leaves, arcs, furniture and annotations are not walls. Explicit railings/open edges never become full-height walls.

OpeningDescription replaces host_room/host_edge with host_wall:str|null (boundary key); retain kind, label, segment, source, basis, note. Segment endpoints identify the actual gap on the wall, not a drawn door leaf or swing arc. Unknown host stays null and yields an unresolved record, never arbitrary attachment. No valid host depends on a room polygon surviving.

FeatureDescription: kind stairs|table|chair|cabinet|bed|sofa|sink|toilet|shower|bath|appliance|other, label, polygon:list[Point], source:PageRegion, basis, note. Every meaningful depicted feature is included, with simple footprint symbols sufficient; no vertical dimension is required. Generic other+label covers features outside the named categories. UnresolvedDescription: label, category:str, source:PageRegion, reason. Use for ambiguous classification or unlocatable geometry; annotations are excluded. Group inseparable repeated symbols explicitly when individual extents cannot be resolved.

## Scene and IFC

SceneElement adds representation reconstructed|schematic|unresolved, semantic_type:str, environment indoor|outdoor|unknown. Extend kind to room/outdoor/wall/railing/open_edge/door/window/stairs/furniture/fixture/other. Unresolved elements have geometry=None but retain stable GlobalId, source, label and note reason. Every described entry must appear as rendered/schematic/unresolved, including validation omissions. Stable namespace keys must not renumber after omission. No silent omission counter as the only record.

Generated spaces are thin plates. Explicit walls use depicted thickness where a valid original segment establishes it, otherwise labeled display width. Openings create actual IfcOpeningElement void/fill relationships; host geometry is checked in aspect-correct coordinates. Reject incompatible/overlapping host associations to unresolved records. Never close a room edge to create a host. Features may be flat schematic IFC solids/symbols; any thickness, height, tread motif or vertical offset is a display assumption. No engineering/step-count claims.

New artifacts use manifest version3/marker v3 and embed the exact BuildingDescription plus all original normalized PNGs and per-element metadata. Reader accepts version2 artifacts without silently reclassifying them as native IFC. Version3 validates new semantic/status fields against per-element Psets, actual IFC classes/storeys and source regions. Unresolved entries use geometry-less semantic entities; all-unresolved scenes are allowed but explicitly state that no 3D geometry was reconstructed; the original source and unresolved inventory remain available. Native IFC import unchanged.

## Comparison UI

Root provides Scene.comparison: list[PlanComparison] computed after actual IFC tessellation. Each entry: element_id, floor_id, page, layer spaces|walls|openings|features|unresolved, polygons:list[list[list[float]]], lines:list[list[list[float]]], method:str, cut_height:float|null. Coordinates are normalized ORIGINAL page. They are inverse-transformed from actual meshes using stored SceneFloor.transform, without viewer explosion offsets. Walls use a horizontal cross-section through the assumed opening height (explicitly labeled display section), other elements use actual footprint projection. Unresolved entries carry no fabricated paths; UI uses element.source.bbox as a visibly different unresolved marker. Recompute on reopening; do not trust stale saved overlay paths.

Frontend adds a comparison control in the original drawing view, layer toggles and overlay opacity. Original orientation remains unchanged. Separate floor/page filtering, source-linked semantic/status counts and unresolved feature list make missing/incorrect features reviewable. Mesh highlights and assumption controls remain independent. Image-answer association may include new valid feature kinds, but unresolved or unrenderable entries cannot receive invented 3D highlights. Original source citations remain available.

## Budget and acceptance

Existing upload/IFC safeguards remain; no new floor/room/feature caps. Larger explicit inventories may exceed the current reconstruction token/time budget; measure live and change reconstruction-only settings if required, after communicating the tradeoff. No changes to gate/answer budgets or automatic provider fallback.

Acceptance requires visual original-coordinate comparison of both unchanged11397 floors and1794, explicit audit of outdoor boundaries, physical shared walls, every clear opening, stairs and furnishing/fixture coverage, plus live source QA/highlights/refusal and portable reopening. Passing mesh validation alone is not fidelity evidence. Record residual unresolved features/omissions honestly.

## Review resolutions
Duplicate boundary keys never resolve by first/last wins: all conflicting records and dependent openings remain unresolved. Invalid item geometry never invents an exact source region: retain a valid explicit item region, otherwise use the valid floor region and label it unlocalized; invalid floor/page references fail. An empty mesh set is a source inventory result, not a successful 3D reconstruction. The frontend uses safe empty bounds and a clear no-geometry notice.

## Final implementation settings

Reconstruction alone uses one Gemini `gemini-3.1-pro-preview` high-thinking request (explicit `GEMINI_RECONSTRUCTION_MODEL` override), 150 seconds and 32,768 output tokens. These are measured hackathon design choices; larger inventories can still fail, and API success is not fidelity acceptance. Answer/crop retain 45 seconds/8,192 tokens; Decisions is unchanged. Temporary OpenAI uses the same reconstruction-only time/token budgets. No automatic fallback, refinement call, manual source edits or new image-processing stage was added.

V3 permits a contextual evidence box to extend beyond its approximate floor region when the same-page boxes overlap with positive area. Actual geometry anchors remain inside both the floor and source region; no source box is silently rewritten. Disjoint/wrong-page regions remain unresolved. V2 portable imports retain their prior containment check.

Room interiors with positive overlap remain unresolved rather than being silently repaired; independent walls/openings/features survive. Empty feature polygons explicitly request a bbox schematic, while malformed supplied polygons remain unresolved. Display stair bands are level symbol marks, never measured tread counts, rise or travel direction.

## Boundary-line citation repair

BoundaryDescription.source now uses BoundaryRegion: area or normalized positive-length line. Other PageRegion/QA contracts remain strict. A line citation must contain the actual boundary segment before the generator adds one-original-page-pixel selection padding to the zero dimension; physical geometry and thickness validation use original coordinates. Original line bounds remain embedded in the exact description; the padded SourceRef carries a selection-only note. Inconsistent associations remain unresolved. See RECONSTRUCTION_502_FIX.md.

## Shared uncalibrated page scale

Uncalibrated floor transforms use a page-derived factor `10/max(page.width/page.height,1)` rather than independently normalizing each floor bbox. Floor boxes affect centering only. This preserves drawn proportions among uncalibrated diagrams on one page; it does not prove physical scale or equal drawing scales, especially for independently resized diagrams. Separate page frames remain schematic. Supported physical calibration is unchanged. New `page_extent` assumptions disclose the convention; the UI checks those markers before making the claim. Existing artifacts retain stored transforms and original IDs; no automatic migration. See FLOOR_SCALE_FIX.md.

## Depicted wall bands and schematic visibility

A supplied boundary segment is a reference line, not necessarily a centerline. A valid perpendicular thickness segment establishes signed face offsets in the aspect-correct source plane. Validate contact before display rotation; extrude between those faces. This retains depicted relative widths at unknown scale. Missing/invalid widths keep explicit display defaults. Supported band contacts form junctions without endpoint snapping or filling positive gaps.

Opening range and normal-offset checks use the same source plane and named host. Gap endpoints retain their longitudinal positions. Void and fill are centered normally within the supported band (or assumed default band), with an explicit placement assumption; voids cut the full band. A previously accepted opening outside the actual supported band is not grandfathered in.

Feature footprints and source classifications remain fallible drawing interpretations. Raised schematics improve visibility without establishing vertical measurements. Relative to the existing assumed wall height H, display heights are table .30H; chair/bed .20H; sofa/sink/toilet .25H; cabinet .50H; appliance .40H; shower/bath/stairs/other .10H. Motifs and dimensions are portable assumptions. Support symbols do not establish leg counts; chair facing and stair ascent/rise/travel direction are not inferred. New geometry must remain inside the existing footprint.

Unresolved canvas annotations are HTML source links, not IFC geometry or answer highlights. Precise source regions use the stored source transform; coarse/unlocalized records use a labeled floor badge. Annotation screen positions may be separated for legibility without changing source coordinates or exported geometry. A more elevated derived-model camera exposes interiors; native IFC camera behavior is unchanged. See SCHEMATIC_FIDELITY_PLAN.md and SCHEMATIC_FIDELITY_RESULTS.md.
