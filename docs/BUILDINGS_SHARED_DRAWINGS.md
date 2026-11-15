# Buildings, drawings and chats

This user-requested product change supersedes the earlier Project/File navigation in PROJECTS_AND_MARKS.md and DRAWING_FILE_NAVIGATION.md. The existing Project concept is renamed **Building** in the UI; there is no additional hierarchy level.

Each Building overview contains **Drawings**, **Chats** and an obvious **Upload drawings** button. Uploading additional drawings joins that Building's shared source group. All of its chats can inspect that group; the displayed drawing is a view selection rather than the chat's evidence boundary. Uploads retain the source-first interpretation/cache workflow; 3D generation remains explicit. Existing source revisions and usable models survive an append, with stale geometry disclosed through the existing status.

The visualizer composer has no Attach drawings button. Drag-and-drop remains available and captures the current Building as its target. The Drawings tab expands a file picker downward; large previous/next chevrons remain above/below the drawing. These controls change only the visible source file/page. They preserve the active chat, draft and shared source-group identity and request no inference. Multipage PDFs remain one file entry with separate page controls.

## Existing saved groups

The user explicitly chose **separate Building entries for the old groups**. Independently uploaded groups must not be silently combined. Their original group identities, model revisions, annotations, conversation owners, session IDs and exact historical citations remain intact. The migration changes organization/presentation metadata only. Old chats with no source group retain an explicit empty/general Building rather than inheriting arbitrary drawings.

Identical original bytes do not authorize silently adopting another Building's appended source set. New shared drawing groups must be independently owned while reusing immutable original resources and successful interpretation caches where possible. An older bundle referenced by several owners must remain safe to inspect; appending must not unexpectedly change a sibling Building.

Genuine native IFC stays a separate Building/evidence context until mixed-evidence support exists. A mixed native-IFC/drawing batch must fail before publishing mixed membership. Drawing-derived IFC retains its original drawing authority and recoverable source provenance.

## Acceptance

- An empty Building uploads an image and PDF into one group; a later upload appends to it. Two independent chats both inspect all current originals.
- Picker/arrows preserve the chat, draft and group. PDF page navigation remains distinct; failed/canceled loads retain the previous visible source.
- Overview and visualizer drops target the captured Building. Access restrictions and pinned examples stay enforced; uploads never request 3D automatically.
- Old separate groups appear as separate Building entries, with stable sessions, source/model/annotation identities and historical revision links through reload, rename, delete and Undo.
- Reusing an original in a new Building cannot borrow or mutate another group's sources/history. Concurrent first uploads cannot establish competing groups for one Building.
- Native IFC remains separate. Tests use injected providers; no fixture is represented as live inference.

Implementation ownership follows the reviewed plan: backend owns scope/group/upload/session resolution, frontend owns presentation and view-only source navigation, and an independent reviewer checks changed behavior. Final API details and verification results are recorded below after integration.

## Reviewed storage and API contract

Independent plan review cleared the frontend plan and backend contract on November 15 before implementation. Existing `/api/projects` records remain internal chat/task owners. The flat Building list uses `building_scopes` from `/api/buildings`; this does not add another UI screen or parent entity.

Each scope DTO supplies `id` (a presentation key), `owner_project_id`, `scope_id`, `name`, nullable `source_group_id`, `building_ids` (zero or one group), `active_building_id`, `kind`, `read_only`, `upload_allowed` and `upload_reason`. Requests to `/api/chat` keep the actual owner project ID and the selected session ID. A card's presentation key is not a conversation owner.

Scope routes are based at `/api/projects/{owner}/scopes/{scope}`:

| Action | Route |
| --- | --- |
| Rename entry | `PATCH` base, `{name}` |
| Delete / Undo | `DELETE` base / `POST .../restore` |
| Shared upload, first or later batch | `POST .../sources`, multipart files |
| List / create chats | `GET` / `POST .../chats` |

Existing session routes retain original ownership and IDs. Stored session `building_id` remains unchanged; `effective_building_id` separately resolves the intentionally established shared group for source-free chats. Each new turn records the actual inspected document/revision. An old source-free chat cannot silently inherit the owner's unrelated active file, and a stale submission after upload fails before inference.

Shared-group initialization and its owner pointer/membership are serialized under the store lock. Extraction starts after releasing that lock. The first original's content hash and resource IDs retain their original meaning even when the new group has an independent namespace. Existing per-source caches remain reusable; another group's appended sources, model and history are not imported through deduplication.

Scoped rename, deletion and Undo update organization metadata only. Legacy source-group entries filter sessions by their stored source binding. Source-free sessions retain the explicit shared/General entry. Retained/deleted owners count when detecting old shared aliases: appending is refused with a concrete explanation if it would also change another owner's group. Inspection, history and QA remain available, and a new Building can upload an independent copy through the ordinary Upload drawings flow.

## Implementation and verification

The backend and frontend implementations were independently reviewed. The reviewer passed 23 current backend/access checks and 17 Chromium checks, with no remaining acceptance blockers. Backend implementation checks additionally passed 111 scope, ownership, voice, annotation, source/job, bundle and format regressions. The new five-case real-HTTP browser suite covers shared initial upload, later append, empty-chat continuity, captured destinations, separate legacy entries, scoped rename/delete/Undo and alias guards. Navigation checks cover unchanged session/draft/attached marks, PDF pages, delayed replies, native/pinned entries and failed/canceled loads.

Review found and fixed two preservation bugs: the old membership-removal API now rejects removal of a primary shared group instead of breaking its pointer, and an explicitly saved General entry remains restorable after its last source-free chat is deleted. Neither fix rebases annotations or rewrites stored session owners/history.

An isolated copy of the saved demo workspace supplied actual originals and a previously generated model for browser verification. Overview upload, a fresh independently owned two-source group, two chats seeing all sources, same-chat arrows/draft, mobile fit and reopening the saved model passed with zero script errors. All 124 pre-existing source/model/history/resource files remained byte-identical; only organization metadata and new verification records changed. The original workspace was untouched. Extraction was explicitly disabled in this private transport check and the provider factory rejected inference; it is not a live inference result. Results/screenshots: `/tmp/junction-buildings-verification/checks/`.

The peer-review access policy and rendering/review loop were not changed. Final frozen-suite and deployment results are recorded in the deployment handoff.
