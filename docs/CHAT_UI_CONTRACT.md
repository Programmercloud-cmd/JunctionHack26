# Chat actions and workspace contract

UI branch `feat/chat-first-ui`, worktree `/tmp/junction-chat-ui`, base `fdfd4e3`. Coordination lives at `/tmp/junction-ui-coordination.md`. This additive boundary never replaces extraction, QA, refinement, persistence or reconstruction. Main session owns those pipelines.

## Request and result

`POST /api/chat/actions` takes `{message,request_id,document_id:null|string,revision_id:null|string,workspace:{geometry_revision_id:null|string,view_mode:"chat|source|model|concept",selected_ids:[],focused_id:null|string,camera:null|object,tour:{ids:[],index:-1,running:false},navigation_epoch:0,highlighting:true,answer_highlighting:true,show_assumptions:false,floor_id:null|string,exploded:false,cutaway:100}}`.

Capture and deep-copy workspace synchronously at submit; pause timer before awaiting. A request does not accept client object names, source boxes or screenshots as evidence. `revision_id` means current interpretation; `geometry_revision_id` means displayed saved geometry. Camera uses viewer `getCameraState()`; damping is not a navigation epoch change. User submissions, compact navigation and manual viewer interaction invalidate older navigation responses. Polls and expected reconstruction swaps do not falsely invalidate their pending action.

Response echoes `request_id,document_id,revision_id,geometry_revision_id,navigation_epoch` and adds `{status:"ready|clarification",actions:[],message,clarification:null|{message,suggestions:[]},usage:{}}`. Message is a deterministic operation summary; factual output only comes from reviewed QA. Clarification concerns intent, never the evidence-sufficiency gate. Operational errors retain existing safe HTTP detail format; 409 means stale context. One selected-provider structured call, existing timeout/output budget, no retry/fallback. Known compact actions execute locally without interpretation.

## Typed actions

Every action has a literal `type`. Optional keys below default to null/empty. Unknown types/keys and invalid references fail validation.

| Type | Fields / behavior |
|---|---|
| `show_model` | Reuse cached scene or await existing reconstruction; preserve active tour. |
| `select` | `selector:{target:"focused|selection|all|named",kind:null|string,label:null|string,floor:null|string,ids:[]}`, server outputs `ids`, `unresolved_ids`, `deferred` (bool). Empty scene permits only semantic deferred selector; resolve after actual geometry arrives. No fabricated IDs. |
| `show_source` | Same optional `selector`; output `object_id`, `source`, `source_revision_id` from saved revision. Optional explicit `page` for whole original page. Focused references use captured geometry revision. Native source opens record inspector. |
| `close_workspace` | Retain model/camera/tour paused. |
| `set_camera` | `preset:"top|fit|isometric"`; preserve selections. |
| `tour` | `command:"start|pause|resume|next|previous"`; start uses navigation selected IDs, excludes unrenderable records. End stops without cycling. |
| `set_visibility` | `target:"answer_highlights|navigation_highlights|assumptions"`, `enabled:boolean`. Independent state. |
| `set_view` | `mode:"model|concept|source"`. |
| `set_floor` | `floor_id` resolved server-side, null means all; model may propose `label`. |
| `set_separation` | `enabled:boolean`. |
| `set_cutaway` | `percent:number` in existing 0–100 domain. |
| `set_theme` | `theme:"light|dark|system"`. Exact Chronicle tokens. |
| `question` | `question:string`, `revision_id`, `navigation_reference:null|{object_id,source,source_revision_id}`; original message preserved. For a focused question append deterministic clearly labeled navigation reference to existing question text and pin its source revision. Do not introduce an AskRequest field or model-authored factual paraphrase. Respect its existing text length bound. |
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
| `set_comparison` | `enabled:boolean`, optional `layer:"spaces|walls|openings|features|unresolved"`; toggles existing actual-IFC source overlay. |
| `help` | Compact examples and available operations in chat. |

Model selectors resolve exact saved IDs/labels/kinds/floors in code. Duplicate labels clarify. Saved modeled-window selection reports coverage as modeled records, not all real/source windows. Source boxes are copied unchanged; never synthesized tighter boxes. Focused removed objects retain old source evidence, but persistent edits must target current surviving identities. No nearest-object or list-index substitution.

Execute actions in order, stopping dependent actions on failure. A deferred selector waits for the explicitly requested reconstruction, then resolves using actual new scene records and checks the request/document/navigation epoch. Partial preview and failed review are reported honestly; no automatic extra reconstruction loop. Revision replacements use existing atomic viewer swap; revalidate tour IDs and pause/report lost targets. Source mode retains ordered IDs/index and model camera so back/next advances exactly once.

## Viewer interface

`getCameraState()` / `setCameraState(snapshot)`; `frameIds(ids,{topDown:false}) -> {framed_ids,unavailable_ids}`; `focusObject(id) -> {focused_id,orientation:"geometry|uncertain|unavailable",note}`; `setTheme("light|dark")`. Existing select, setHighlights, setHighlightsEnabled, setShowAssumptions, setFloorFilter, setExploded, setMode and cutaway methods remain. Geometry covariance can establish a window axis; it does not establish exterior side. Ambiguous axes use a labeled approximate oblique camera. Z-up orbit remains; top-down respects the existing numerical polar epsilon.

## Presentation and compatibility

Navigation turns/progress are ephemeral UI records retained across server conversation refresh, separate from persisted factual conversation. Answers are rendered once with citations and expandable existing checks. Saved building/job state remains backend-owned. Recovery events and submitted values are not evidence of publication: preserve labels and event.base_revision_id source pins. Failed/stopped/needs_attention outcomes retain usable models and original sources.

Chronicle tokens originate at `https://github.com/Programmercloud-cmd/AI_Chronicle_UI/blob/main/src/web/styles/global.css`, blob `4396f7a3594369ea3a38c6c0ebdb620496f9703c`: light background/surface/text/muted/line/accent/focus `#fbfaf8/#ffffff/#241f1a/#716a62/#ded9d2/#b95318/#1769aa`; dark `#121110/#191816/#eeeae4/#aaa39a/#403c37/#ef8a4c/#75bfff`.

Verification must distinguish explicit deterministic fixtures, actual imported artifacts/backend responses, and new live-provider runs. No fixture fallback in production. Full matrix in CHAT_UI_PLAN.md.

Main reliability session agreed the additive routing and ownership on 2026-11-14 in the coordination record. All request/action IDs and finite camera/control values are validated against saved revisions; providers close in finally. Mutation actions use their captured base without silently rebasing subsequent edits. Main-owned recovery fields retain event-specific source revisions and submitted-versus-accepted attribution.
