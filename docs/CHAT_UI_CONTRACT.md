# Chat actions and workspace contract

Corrective branch `feat/chat-ui-corrections`, worktree `/tmp/junction-chat-ui-corrections`, starts at integrated main `9a001f3` and incorporates main's reviewed `37c4dd1` as `fe44534`. The original `feat/chat-first-ui` commits through `9b20a0b` were already integrated. Coordination lives at `/tmp/junction-ui-coordination.md`. This additive boundary never replaces extraction, QA, refinement, persistence or reconstruction. Main session owns those pipelines and public-access enforcement. The reopened user requirements supersede the earlier chat-only controls restriction and prior acceptance.

## Request and result

`POST /api/chat/actions` takes `{message,request_id,document_id:null|string,revision_id:null|string,workspace:{geometry_revision_id:null|string,view_mode:"chat|source|model|concept",selected_ids:[],focused_id:null|string,camera:null|object,tour:{ids:[],index:-1,running:false},navigation_epoch:0,highlighting:true,answer_highlighting:true,show_assumptions:false,floor_id:null|string,exploded:false,cutaway:100}}`.

Capture and deep-copy workspace synchronously at submit; pause timer before awaiting. Also capture the document visit epoch and QA reply/clarification context. A request does not accept client object names, source boxes or screenshots as evidence. `revision_id` means current interpretation; `geometry_revision_id` means displayed saved geometry. Camera uses viewer `getCameraState()`; damping is not a navigation epoch change. User submissions, compact navigation and manual viewer interaction invalidate older navigation effects, **not factual question execution**. Polls and expected reconstruction swaps do not falsely invalidate their pending action.

Validate all echoed identities before dispatch. Factual questions execute once against their captured document/revision/reference despite orbit, zoom, pan, source/model switches or a later selection. Mixed batches dispatch captured questions independently and suppress stale navigation only. A different document visit (including A → B → A) rejects undispatched work; already submitted jobs remain persisted in their captured building and cannot populate another building's view. Persistent mutations retain captured base revisions and final server validation; camera movement never rebases them. Visibility/theme controls preserve the tour and do not invalidate navigation. QA completion cannot change the camera, tab or selection.

Response echoes `request_id,document_id,revision_id,geometry_revision_id,navigation_epoch` and adds `{status:"ready|clarification",actions:[],message,clarification:null|{message,suggestions:[]},usage:{}}`. Message is a deterministic operation summary; factual output only comes from reviewed QA. Clarification concerns intent, never the evidence-sufficiency gate. Operational errors retain existing safe HTTP detail format; 409 means stale context. One selected-provider structured call, existing timeout/output budget, no retry/fallback. Known compact actions execute locally without interpretation.

Provider transport uses `WireChatIntent`: one action-type enum with nullable typed fields. Null fields are removed before strict operation-specific validation; unrelated non-null fields fail rather than being silently discarded. This avoids the broad-union branch ambiguity observed in live Gemini source navigation without changing the public action contract or provider implementation.

## Typed actions

Every action has a literal `type`. Optional keys below default to null/empty. Unknown types/keys and invalid references fail validation.

| Type | Fields / behavior |
|---|---|
| `show_model` | Reuse cached scene or await existing reconstruction; preserve active tour. |
| `select` | `selector:{target:"focused|selection|all|named",kind:null|string,label:null|string,floor:null|string,ids:[]}`, server outputs `ids`, `unresolved_ids`, `deferred` (bool). Empty scene permits only semantic deferred selector; resolve after actual geometry arrives. No fabricated IDs. |
| `show_source` | No selector/page opens the first supplied **whole original page** at captured interpretation revision, with `bbox:null` and no object. Explicit `page` validates against that revision. Explicit object `selector` opens exact saved evidence at captured geometry revision. Native object source opens record inspector; native whole-source requests offer original-record guidance. |
| `close_workspace` | Retain model/camera/tour paused. |
| `set_camera` | `preset:"top|fit|isometric"`; preserve selections. |
| `tour` | `command:"start|pause|resume|next|previous"`; start uses navigation selected IDs, excludes unrenderable records. End stops without cycling. |
| `set_visibility` | `target:"answer_highlights|navigation_highlights|assumptions"`, `enabled:boolean`. Independent state. |
| `set_view` | `mode:"model|concept|source"`. |
| `set_floor` | `floor_id` resolved server-side, null means all; model may propose `label`. |
| `set_separation` | `enabled:boolean`. |
| `set_cutaway` | `percent:number` in existing 0–100 domain. |
| `set_theme` | `theme:"light|dark|system"`. Exact Chronicle tokens. |
| `question` | `question:string`, `revision_id`, `navigation_reference:null|{object_id,source,source_revision_id}`; original message preserved. A general `all`/kind selector is question scope, not a demand to resolve one object or count modeled IDs. For a focused/named singular question append a deterministic clearly labeled navigation reference to existing question text and pin its source revision. Do not introduce an AskRequest field or model-authored factual paraphrase. Respect its existing text length bound. |
| `refine` | `edits` is existing UserEdit batch, `supporting_source_ids:[]`; server validates with existing prepare_inputs without publication. Final execution sends existing RefinementRequest with current captured base. |
| `reconstruct` | `mode:"refine|reconstruct"`; reuse existing job route. |
| `list_saved` | Show saved choices in chat. |
| `open_saved` | `building_id` validated against saved catalog; model may propose `label`. |
| `attach_sources` / `new_upload` | Native file chooser from compact chat control. Existing upload/append routes. |
| `download_ifc` | Existing saved artifact URL; derived provenance unchanged. |
| `download_source` | `source_id` validated; ambiguity asks which source. |
| `retry_extraction` / `refresh` | Existing endpoints. |
| `stop_job` | `job_id` validated against selected building; ambiguity asks which job. |
| `inspect_assumptions` / `inspect_inventory` | Source-linked rows in chat, not a settings panel; no mesh for unresolved records. |
| `set_comparison` | `enabled:boolean`, optional `layer:"spaces|walls|openings|features|unresolved"`, optional `opacity` in the existing 10–90 percent control range; uses the existing actual-IFC source overlay. |
| `help` | Compact examples and available operations in chat. |

Model selectors resolve exact saved IDs/labels/kinds/floors in code. Duplicate labels clarify. Saved modeled-window selection reports coverage as modeled records, not all real/source windows. Source boxes are copied unchanged; never synthesized tighter boxes. Focused removed objects retain old source evidence, but persistent edits must target current surviving identities. No nearest-object or list-index substitution.

Persistent numeric edits must be explicitly attributed to an adjacent quantity/unit pair in the submitted message (digits and common English number words are supported). Calibration requires explicit normalized original-page endpoints; the navigation catalog cannot establish them. Unsupported phrasing clarifies. Any supplied edit source must exactly match a scoped saved source region. Existing attributed-input validation and review remain the final mutation authority.

Execute actions in order, stopping dependent actions on failure. A deferred selector waits for the explicitly requested reconstruction, then resolves using actual new scene records and checks the request/document/navigation epoch. Partial preview and failed review are reported honestly; no automatic extra reconstruction loop. Revision replacements use existing atomic viewer swap; revalidate tour IDs and pause/report lost targets. Source mode retains ordered IDs/index and model camera so back/next advances exactly once.

Question actions are independent of navigation dependencies as described above; the original ordering rule applies to dependent navigation/mutation actions. General factual QA always uses the existing source pipeline, not inventory/mesh counts. Source navigation, public browsing and QA never implicitly reconstruct.

## Viewer interface

`getCameraState()` / `setCameraState(snapshot)`; `frameIds(ids,{topDown:false}) -> {framed_ids,unavailable_ids}`; `focusObject(id) -> {focused_id,orientation:"geometry|uncertain|unavailable",note}`; `setTheme("light|dark")`. Existing select, setHighlights, setHighlightsEnabled, setShowAssumptions, setFloorFilter, setExploded, setMode and cutaway methods remain. Geometry covariance can establish a window axis; it does not establish exterior side. Ambiguous axes use a labeled approximate oblique camera. Z-up orbit remains; top-down respects the existing numerical polar epsilon.

`setSelectionHighlightEnabled(boolean)` hides clicked-object selection appearance in both inspection/concept without clearing its ID or evidence; answer highlights and assumption overlays remain independent. `clearSelection()` clears only the focused viewer identity/appearance; selecting a new group also clears the old inspector while retaining the new group IDs. Assumption tint reuses existing fields. A markers identify stored assumed properties on selected/highlighted geometry; they never create source matches. Unresolved ? markers retain their existing source-only semantics.

Client-only direct controls use `browse_source{page?,source_revision_id?}`, `switch_model` and `return_selection`. They do not call Gemini. `switch_model` only reuses a saved scene; absence shows an explicit Build model action using the existing pipeline. `return_selection` explicitly frames current IDs; ordinary tab switches preserve camera/tour position. `chatUI.inspection()` returns a copied selected record, floor, units, source revision and removed status (or non-factual proposal/host). `chatUI.sourceView()` returns the active pinned page catalog/revision/page. `blueprint:workspace` notifies the read-only controls module; it does not introduce another state owner.

Cache supplied page catalogs by revision during a document visit. If an old citation lacks a locally known catalog, open only its exact cited page and derive image dimensions from the successful original-image read; do not borrow current filenames/coordinates. Preload before committing a source switch; failed reads retain the previous view. The Blueprints tab browses current originals; the page chooser follows the active source revision. Comparisons from another geometry revision are hidden rather than overlaid on older evidence. Explicitly enabling comparison first opens a stored original page pinned to the model revision, preserving the current page/region only when it belongs to that revision. A failed matching-page load retains the previous view and does not enable a mismatched overlay.

## Presentation and compatibility

Navigation turns/progress are ephemeral UI records retained across server conversation refresh, separate from persisted factual conversation. Answers are rendered once with citations and expandable existing checks. Saved building/job state remains backend-owned. Recovery events and submitted values are not evidence of publication: preserve labels and event.base_revision_id source pins. Failed/stopped/needs_attention outcomes retain usable models and original sources.

Persistent compact controls expose view/page navigation, current selection, theme and independent toggles. A selected-evidence summary remains outside chat scrolling and independent of overlays: presence, representation, property origins, object/floor assumptions, pinned user inputs and exact Show in original links. Current assumption rows are attached only when their data revision matches the selected record; older floors retain captured units. Supported presence/registration cannot establish height or vertical placement. The legend distinguishes observation, interpretation, derivation, user-provided values, display assumptions, unresolved values and non-factual proposals.

Intent failures emit one credential-safe diagnostic with an application-generated reference, stage, exception class, schema-known validation paths/types, and numeric HTTP status when available. Unknown field names, messages, request IDs, request/response bodies and source text are excluded. The generic operational response carries that reference; no automatic retry, fallback, budget increase or evidence conclusion is added. Public paid-action gates, immutable example pins and access-code/no-replay behavior are unchanged.

Chronicle tokens originate at `https://github.com/Programmercloud-cmd/AI_Chronicle_UI/blob/main/src/web/styles/global.css`, blob `4396f7a3594369ea3a38c6c0ebdb620496f9703c`: light background/surface/text/muted/line/accent/focus `#fbfaf8/#ffffff/#241f1a/#716a62/#ded9d2/#b95318/#1769aa`; dark `#121110/#191816/#eeeae4/#aaa39a/#403c37/#ef8a4c/#75bfff`.

Verification must distinguish explicit deterministic fixtures, actual imported artifacts/backend responses, and new live-provider runs. No fixture fallback in production. The current matrix is in CHAT_UI_CORRECTION_PLAN.md and its outcomes are in CHAT_UI_CORRECTION_VERIFICATION.md; CHAT_UI_PLAN.md is the historical initial plan.

Main reliability session agreed the additive routing and ownership on 2026-11-14 in the coordination record. All request/action IDs and finite camera/control values are validated against saved revisions; providers close in finally. Mutation actions use their captured base without silently rebasing subsequent edits. Main-owned recovery fields retain event-specific source revisions and submitted-versus-accepted attribution.
