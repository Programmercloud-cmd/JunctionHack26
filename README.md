# Blueprint QA

Junction hackathon prototype: upload JPG/PNG/PDF/SVG/DXF drawings or a native IFC and ask reviewed questions with original evidence. Drawing uploads save source interpretation automatically; an orbitable Three.js model is an explicit optional step. Related drawings can share a building, and source-linked conversations and attributed user inputs persist locally. Inspection and concept modes share the same geometry; decorative proposals remain separate from evidence. Unknown scale stays unscaled.

## Quick start

Requires Python 3.12+, curl and system Cairo for SVG/DXF preview rendering. No Node, database or cloud setup.

```sh
bash scripts/bootstrap.sh
# Add GEMINI_API_KEY to .env.local using your editor; do not overwrite existing keys.
# Optional model overrides are listed in .env.example.
bash scripts/dev.sh
```

Open http://127.0.0.1:8000. Uploads, previews and IFC import/viewing work without a key. Credentials stay on the server. Questions send source images or extracted IFC records to the explicitly selected provider. Image reconstruction also requires that provider. Three.js is pinned locally; there is no rendering service or CDN dependency.

## Try the two demo flows

1. Upload `duplex_arc.ifc` from the dataset's `ifc_bench` folder. Drag to orbit, scroll to zoom. Ask **How many windows are in this IFC model?** Supported source objects highlight while other elements fade to 10% opacity. Click a highlighted object or its evidence row to inspect its GlobalId, STEP reference and properties. Rooms mean supplied IFC spaces. Select supplied storeys and adjust the cutaway percentage; geometry is clipped, never shrunk.
2. Upload unchanged `colorful-1794.png` or `colorful-11397.png`. Source interpretation starts automatically and is saved before any IFC work; questions inspect original drawings even without a model. Select **Generate 3D** to enrich missing geometry and build/reopen a derived IFC. Multiple files can be uploaded together or appended to the selected building. Sections/elevations remain evidence; possible repeated floor views do not automatically create storeys. Use the conversation's citations to locate the original file/page, and inspect **Assumptions and missing inputs** before applying supplied values. User heights never establish horizontal scale or become dimensions observed in the blueprint.

Use **Saved buildings** to reopen without inference, including after restart. Repeat uploads are recognized by content. Explicit refinement starts a new job; asking questions never reconstructs the model. See [source-first verification](docs/SOURCE_FIRST_VERIFICATION.md) and [the API contract](docs/SOURCE_FIRST_CONTRACT.md) for tested flows and remaining limitations. Genuine native IFC currently stays a separate building; mixed native/drawing grouping is explicitly rejected. DWG requires a converter that is not available here.

**Source comparison** overlays the actual reopened IFC footprints, wall sections and openings on the original page. Toggle layers to check missing features, invented walls and displaced openings. The interpreted inventory links every generated or unresolved record to its source; it is not a claim that every source feature was found. Stairs, furnishings and fixtures use simple schematic geometry. Terraces/balconies are outdoor spaces; room polygons never create walls.

Furniture and fixtures use raised schematic blocks, tops and basin symbols with labeled assumed heights. Supported stair relationships can form continuous schematic connections; unknown rise remains an explicit display assumption. Orbit toward an overhead view to inspect features hidden behind walls. Click a **?** marker to inspect an unresolved source region; these annotations are separate from model geometry and answer highlights. A floor badge means a precise location is unavailable. See [the fidelity results](docs/SCHEMATIC_FIDELITY_RESULTS.md) for known extraction errors.

**Highlight answer** and **Show assumptions** are independent controls. A scene is cached once for all pages; asking questions only updates highlights. Download its generated IFC and upload it in a fresh session: stable object IDs, original source PNGs, assumptions and provenance travel with the file. Unmapped answers keep their source evidence and do not invent a 3D selection.

## Switch providers

Set one variable in `.env.local` and restart the server:

```dotenv
# Temporary development (OpenAI Responses API)
AI_PROVIDER=openai
OPENAI_MODEL=gpt-6.1-sol
# OPENAI_API_KEY must already be set locally.
```

```dotenv
# Final sponsor demo (default if AI_PROVIDER is absent)
AI_PROVIDER=gemini
# GEMINI_API_KEY must be set locally and have access to the configured reconstruction, answer and Decisions models.
```

There is no automatic fallback. The UI identifies the active pipeline. OpenAI uses the same image-capable model for one structured sufficiency judgment and answer generation; the gate returns `confidence: null`. This is a development substitute for Gemini Decisions, not an equivalent calibrated decision model. OpenAI does document a separate Decisions endpoint, but this temporary adapter deliberately avoids a second model/access dependency. The original-source requirement, one-crop retry, citations and calculation checks are shared. Both pipelines can be confidently wrong; evaluate them separately before the Gemini demo. A Codex app login is not used: this adapter uses `OPENAI_API_KEY` with the Responses API.

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

Historical Gemini compatibility diagnosis is in [GEMINI_FIX.md](docs/GEMINI_FIX.md). The reconstruction default remains `gemini-3.1-pro-preview`; Hydrogen was not adopted. Default configurable design budgets are 300 seconds/65,536 output tokens per reconstruction or patch, 120 seconds/16,384 tokens per reconstruction review, 900 seconds per background job and two patch attempts. QA has a 180-second total budget, 45-second calls, at most two support reviews and one meaningful correction. Budget exhaustion is operational, not proof of missing evidence. See `.env.example` and [the reviewed plan](docs/PRODUCT_PLAN.md).

The API wire schema and necessary local validation remain separate. Invalid/ambiguous geometry stays as a source-linked unresolved record; an all-unresolved result explicitly says no 3D geometry was reconstructed. Valid walls/features do not depend on room polygons surviving. Source-based answers remain available.
- Related JPG/PNG/PDF/SVG/DXF sources can be uploaded together or appended. Existing per-file drawing limits remain 10 MiB and, for PDF, five pages; oversized PDFs are rejected, not silently truncated. These are not whole-building page limits.
- Uncompressed IFC STEP up to 25 MiB, 4,000 render-catalog elements and one million triangles. GlobalIds and source units are preserved; native world geometry is in metres. The shared reasoning catalog retains relevant geometry-less semantic records and original properties/relationships. Question retrieval reports coverage and omitted values. Native evidence citations open the complete pinned original record, beyond the legacy scene-property summary.
- For genuinely supplied IFC only, exact English whole-model count questions use deterministic catalog counts after the same sufficiency gate. Qualified/floor-specific questions use the normal gated source-answer path. Intent resolution can request clarification before the evidence gate when user intent is materially ambiguous. Counts describe the uploaded model, not physical-building completeness.
- The selected gate evaluates whether the inspected source supports the question: sufficient, insufficient or unclear. One additional inspection is allowed for unclear results.
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

## Model-quality experiment

Use the same document/question pairs for ordinary Gemini and the gated pipeline. Measure answer coverage, error among answered questions, unsupported answers, unnecessary abstention, latency and token usage. Include deliberately incomplete and ambiguous drawings, as well as sparse JPGs with answerable questions. Split by drawing/building rather than translations or file formats. Keep reference answers out of runtime context.

API references: [Decisions](https://aistudio.google.com/docs/decisions-api), [models](https://aistudio.google.com/docs/models). The Decisions SDK requires google-genai 3.2 or later; this environment pins the installed version. Model names are configurable because account access can differ.

OpenAI references: [structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs), [model catalog](https://developers.openai.com/api/docs/models), [native Decisions (not used by this temporary adapter)](https://developers.openai.com/api/docs/guides/decisions).

## Separate VQA experiment

The upstream VQA experiment is preserved in `VQA/`. Its [original upstream documentation](VQA/README.md) is retained verbatim and includes historical `backend/` paths; use the instructions above for this application. The experiment is not wired into the application provider pipeline.
