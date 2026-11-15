# Concrete

Junction hackathon prototype: upload JPG/PNG/PDF/SVG/DXF drawings or a native IFC and ask reviewed questions with original evidence. Drawing uploads save source interpretation automatically; an orbitable Three.js model is an explicit optional step. Related drawings can share a building, and source-linked conversations and attributed user inputs persist locally. Inspection and concept modes share the same geometry; decorative proposals remain separate from evidence. Unknown scale stays unscaled.

## Quick start

Requires Python 3.12+, curl and system Cairo for SVG/DXF preview rendering. No Node, database or cloud setup.

```sh
bash scripts/bootstrap.sh
# Add GEMINI_API_KEY to .env.local using your editor; do not overwrite existing keys.
# Optional model overrides are listed in .env.example.
bash scripts/dev.sh
```

Open http://127.0.0.1:8000. Uploads, previews and IFC import/viewing work without a key. Credentials stay on the server. Questions send source images or extracted IFC records to Gemini. Source interpretation and image reconstruction also use Gemini. Three.js is pinned locally; there is no rendering service or CDN dependency.

## Try the two demo flows

1. Upload `duplex_arc.ifc` from the dataset's `ifc_bench` folder. Drag to orbit, scroll to zoom. Ask **How many windows are in this IFC model?** Supported source objects highlight while other elements fade to 10% opacity. Click a highlighted object or its evidence row to inspect its GlobalId, STEP reference and properties. Rooms mean supplied IFC spaces. Select supplied storeys and adjust the cutaway percentage; geometry is clipped, never shrunk.
2. Upload unchanged `colorful-1794.png` or `colorful-11397.png`. Source interpretation starts automatically and is saved before any IFC work; questions inspect original drawings even without a model. Select **Generate 3D** to enrich missing geometry and build/reopen a derived IFC. Sections/elevations remain evidence; possible repeated floor views do not automatically create storeys. Use the conversation's citations to locate the original file/page, and inspect **Assumptions and missing inputs** before applying supplied values. User heights never establish horizontal scale or become dimensions observed in the blueprint.

Select a file from **Home** to reopen it without inference, including after restart. Repeat uploads are recognized by content. Explicit refinement starts a new job; asking questions never reconstructs the model. See [source-first verification](docs/SOURCE_FIRST_VERIFICATION.md) and [the API contract](docs/SOURCE_FIRST_CONTRACT.md) for tested flows and remaining limitations. Genuine native IFC currently stays a separate building; mixed native/drawing grouping is explicitly rejected. DWG requires a converter that is not available here.

**Concrete** opens on the project list, with previews and editable project names. Clicking a project opens its overview: **Files** above **Chats**, a rounded read-only chat preview in the middle, and Active tasks on the right. Upload/drop files here, then open a file or choose **New chat**. Each chat belongs to that project and its explicitly selected file; empty-project chats have no inherited source. Click a chat name to resume it, its eye icon to preview it, the pencil to rename it, or the red trash icon to delete it. Last-active date/time appears on each row. The home icon beside the theme selector returns to all projects. There is no chat input on the project list or in the preview. Existing saved entries and older conversations are retained. A multi-page PDF stays one file; related drawing attachments share their source group, while native IFC stays separate.

Click the hammer circle at the top left of the drawing/model viewer to expand its tool palette. **Point**, **Draw** and **Measure** add user marks; measurement values and labels appear in a second row when needed. **Eraser** removes whole marks; the arrow icons **Undo** and **Redo** restore drawing/erasing actions. Undo history resets on reload, file switch or source/model revision replacement. Click an active tool again to restore camera controls and drawing scrolling. The tag icon lists saved marks; choosing one highlights its drawing, with a separate option to attach it to your next message. The fullscreen icon sits in the viewer's top-right corner. See [projects and marks](docs/PROJECTS_AND_MARKS.md) for persistence and verification details.

The viewer's slim top bar contains **Drawings**, **3D Model** and **Concept**. The Files icon opens saved downloads and Import; the View icon below it holds source/page, fit and overlay controls. The arrow at the chat/viewer boundary opens supplied-value corrections and the evidence legend. Component details can collapse to their label and stay collapsed until manually reopened. Project rows have a red delete icon with Undo; deleting a project retains its saved chats, originals and models.

Rendering uses one Hydrogen creator followed by two independent reviews running in parallel: three calls per valid full round. Both reviewers must support the same generated IFC before it is published; both must also be satisfied to finish. Otherwise combined feedback goes into the next creation round. Stop retains original sources and the last usable published model. See the [render contract](docs/AGENTIC_CHAT_CONTRACT.md#rendering).

Drag files onto a project row to add them directly, or open its Files page and use the drop area. Multiple files become separate entries in that project. Existing format/access checks and upload deduplication also apply to dropped files.

**Source comparison** overlays the actual reopened IFC footprints, wall sections and openings on the original page. Toggle layers to check missing features, invented walls and displaced openings. The interpreted inventory links every generated or unresolved record to its source; it is not a claim that every source feature was found. Stairs, furnishings and fixtures use simple schematic geometry. Terraces/balconies are outdoor spaces; room polygons never create walls.

Furniture and fixtures use raised schematic blocks, tops and basin symbols with labeled assumed heights. Supported stair relationships can form continuous schematic connections; unknown rise remains an explicit display assumption. Orbit toward an overhead view to inspect features hidden behind walls. Click a **?** marker to inspect an unresolved source region; these annotations are separate from model geometry and answer highlights. A floor badge means a precise location is unavailable. See [the fidelity results](docs/SCHEMATIC_FIDELITY_RESULTS.md) for known extraction errors.

**Highlight answer** and **Show assumptions** are independent controls. A scene is cached once for all pages; asking questions only updates highlights. Download its generated IFC and upload it in a fresh session: stable object IDs, original source PNGs, assumptions and provenance travel with the file. Unmapped answers keep their source evidence and do not invent a 3D selection.

## Gemini setup

Set `GEMINI_API_KEY` in `.env.local` and restart the server. Agentic chat routes the original message to conversation, basic technical QA, advanced technical QA, rendering, or UI interaction. Conversation/basic QA default to Gemini 3.8 Flash; advanced QA defaults to Hydrogen. `GEMINI_BASIC_MODEL`, `GEMINI_ADVANCED_MODEL`, `GEMINI_ROUTER_MODEL` and `GEMINI_UI_MODEL` configure them independently. Technical workers inspect original evidence directly, with no Decisions sufficiency preflight; Decisions remains factual support review. Both technical workers and normal conversation can call the shared UI capability. Existing model overrides in `.env.local` take precedence. The app uses Gemini regardless of any existing `AI_PROVIDER` setting.

Chat rendering and **Build model** use two independent Hydrogen instances (`GEMINI_RENDER_MODEL`). Both must be satisfied with the same reopened IFC candidate before completion. Rendering has no total deadline, iteration limit, or cost cap: use **Stop** to interrupt it. Operational failures retry visibly while preserving saved sources and the last usable model. Legacy reconstruction routes retain their separate model and budgets. See [the agentic chat contract](docs/AGENTIC_CHAT_CONTRACT.md).

Use **Point**, **Draw**, or **Measure** in the drawing/model workspace to attach a mark to a message. Enter measurement values and units explicitly; they remain user-provided. A blueprint measurement with an explicitly selected floor can calibrate generation. Model marks stay attached to their saved object and revision through camera/floor view changes. Original files remain unchanged; marks are saved locally and are not included in portable IFC downloads.

```sh
.venv/bin/python scripts/doctor.py
bash scripts/test.sh
```

Optional browser checks (real local HTTP flow with a clearly injected test provider, no Google calls):

```sh
.venv/bin/python -m pip install -r requirements-browser.txt
.venv/bin/python -m playwright install chromium
RUN_BROWSER_TESTS=1 bash scripts/test.sh tests/test_browser.py tests/test_browser_3d.py tests/test_browser_v2.py tests/test_browser_v3.py
# Optional actual-dataset import validation:
IFC_SAMPLE=/path/to/duplex_arc.ifc bash scripts/test.sh tests/test_ifc_import.py
```

Browser tests skip by default. They cover both 3D acceptance flows plus PDF/citation navigation, replacement, insufficient/unclear/error states, mobile layout, busy-state locking, and preview without credentials. The real IFC browser case requires the local duplex sample; provider calls in browser tests are explicitly injected fixtures.

The bootstrap creates a local `.venv` and installs pinned `requirements.txt`. On hosts lacking ensurepip, it bootstraps pip from the official PyPA endpoint. Never install into system Python. `requirements.in` records direct dependencies; regenerate the lock in a clean project environment after intentional dependency updates.

## Scope and behavior

Historical Gemini compatibility diagnosis is in [GEMINI_FIX.md](docs/GEMINI_FIX.md). Existing per-call transport/output settings remain 300 seconds/65,536 output tokens per reconstruction or patch and 120 seconds/16,384 tokens per render review. The legacy reconstruction route additionally has a 900-second job budget and two patch attempts; these limits do not apply to the agentic render loop. QA has a 180-second total budget, 90 seconds per Gemini draft or correction, at most two support reviews and one correction. Budget exhaustion is operational, not proof of missing evidence. See `.env.example` and [the agentic contract](docs/AGENTIC_CHAT_CONTRACT.md).

The API wire schema and necessary local validation remain separate. Invalid/ambiguous geometry stays as a source-linked unresolved record; an all-unresolved result explicitly says no 3D geometry was reconstructed. Valid walls/features do not depend on room polygons surviving. Source-based answers remain available.
- Related JPG/PNG/PDF/SVG/DXF sources can be uploaded together or appended. Existing per-file drawing limits remain 10 MiB and, for PDF, five pages; oversized PDFs are rejected, not silently truncated. These are not whole-building page limits.
- Uncompressed IFC STEP up to 25 MiB, 4,000 render-catalog elements and one million triangles. GlobalIds and source units are preserved; native world geometry is in metres. The shared reasoning catalog retains relevant geometry-less semantic records and original properties/relationships. Question retrieval reports coverage and omitted values. Native evidence citations open the complete pinned original record, beyond the legacy scene-property summary.
- For genuinely supplied IFC only, whole-model counts use deterministic original semantic catalog calculations. Counts describe the uploaded model, not physical-building completeness.
- The selected technical worker inspects evidence and answers, clarifies, or reports insufficient/unclear support. There is no separate sufficiency preflight on `/api/chat`; legacy direct QA compatibility retains its earlier contract.
- Draft answers and refusals receive one overall post-draft support review plus deterministic reference/calculation checks. A meaningful correction may inspect new evidence, repair a bound calculation/citation or narrow unsupported claims. Reviewer agreement is not proof of correctness. See [live QA results](docs/QA_REVIEW_VERIFICATION.md).
- Building use is not assumed residential. Preserve source labels and meaningful non-residential features; concept mode uses neutral fallbacks for uncertain uses. Unsupported sections, elevations and site plans remain source-linked unresolved views without placeholder floors.
- Missing scale/dimensions remain unknown. Assumptions are labeled proposals, never facts about the uploaded building. Similar-building retrieval is deferred.
- Drawing reconstruction describes explicitly depicted floors, indoor/outdoor footprints, independent physical walls/shared boundaries, hosted doors/windows, stairs, furnishings and fixtures. Every description entry survives as reconstructed, schematic or unresolved; model omissions remain possible and need source comparison. There are no extraction floor/room/vertex caps. Existing upload, IFC and provider budgets still apply. Unknown scale uses IFC `UNSCALED_DISPLAY_UNIT`, never metres; an explicitly cited physical dimension can calibrate footprints. Heights/thicknesses and missing vertical opening dimensions remain display assumptions. Unsupported alignment remains schematic. Generated IFC preserves explicit storey elevations (display assumptions when unknown); exploded view adds separate viewer spacing.
- Generated IFC is derived visualization, never authoritative evidence—even after reopening. It embeds original normalized source PNGs and a validated provenance manifest, including the exact description used by the generator. V5 also preserves original source files when available; legacy artifacts may retain only normalized source pages, without recoverable original bytes. Missing originals are never fabricated. QA inspects those originals; generated inventory, dimensions and assumed heights do not enter factual context. Invalid or contradictory recognizable generated metadata is rejected rather than reclassified as supplied IFC. This is consistency validation, not cryptographic authenticity.
- API/configuration errors are displayed as operational errors, never as evidence insufficiency. No hidden fixture mode or provider fallback.

This is a local hackathon app, not a production service. Bind to loopback. It has no authentication or durable database. Runtime files are ignored by Git. See the API contract for exact source handling and limits.

Uploads are normalized to PNG with a maximum 4096-pixel edge (input images over 40 megapixels are rejected). Versioned bundles persist under `.runtime/buildings` or `BLUEPRINT_STORAGE_ROOT/buildings`: originals, pages, exact descriptions/native records, reasoning, IFC, viewer geometry, identities/frames and review/job metadata. A single application process owns the store. Restart marks unfinished jobs interrupted and reopens saved models without inference. Initial provider images use a 1600-pixel edge; fine text can remain unreadable. Neither normalization nor server arithmetic guarantees correct source interpretation.

## For subsequent agents

Read [AGENTS.md](AGENTS.md), [the active source-first specification](docs/SOURCE_FIRST_SPEC.md), [reviewed plan](docs/SOURCE_FIRST_PLAN.md), [API contract](docs/SOURCE_FIRST_CONTRACT.md), and [handoff](docs/HANDOFF.md). Root owns contracts/environment/integration; bounded implementers and independent reviewers follow the established workflow. Tests use injected providers and are not a model-quality evaluation. DWG without a validated converter, photorealism, Blender/MCP and cloud/HPC rendering remain deferred. SVG and DXF previews are supported with the documented limitations.

## Counting benchmark

With the app's Gemini credential configured and the full Junction dataset in `junction-dataset/`, run from the repository root:

```sh
PYTHONPATH=. .venv/bin/python evaluation/counting/benchmark.py
```

The default run samples three PDF and three PNG counting questions and scores exact matches. Add `--type length` or `--type area` to sample six original PDFs of that question type and score answers within 2% of the reference after unit conversion. The dataset has no PNG rows for those two types. IFC area rows are outside this drawing-interpretation workflow.

The benchmark uploads the originals to an isolated app store, waits for interpretation, and runs chat routing and QA. The terminal shows model-call progress, separate upload and question timings, and scores. The run directory printed at startup contains the sample manifest and per-case results.

For the two-call experiment, add `--pipeline interpretation-only`. It samples ten questions per group (PDF count, PNG count, PDF length, and PDF area). Gemini 4 Hydrogen builds a question-independent interpretation from each original drawing, then receives the saved `interpretations.json` and exact question to produce a structured numeric answer. The second call uses the JSON as its evidence. This mode skips chat routing, intent resolution, Gemini Decisions, and answer review. Its run directory includes `results.html` with a combined counting score and per-case results.

## Voice interaction

The microphone icon beside the prompt starts muted. Click to start dictating and click again to stop, then review and edit the transcript before sending. Enable **Read answers aloud** beside the microphone to hear new answers via ElevenLabs. See [voice setup](docs/VOICE.md).

Peer-review access for the separate agentic deployment: `bash scripts/peer-review-access.sh status`. The one-time Helsinki window and immediate code restoration command are documented in [AGENTIC_DEPLOYMENT.md](docs/AGENTIC_DEPLOYMENT.md#peer-review-access-window).
