# Blueprint QA

Junction hackathon prototype: upload an IFC or floor-plan JPG/PNG/PDF, orbit a source-linked Three.js model, and ask questions with evidence or an explicit limitation. Supplied IFC geometry is extracted. Drawing reconstructions become downloadable, source-linked IFC; unknown scale is explicitly unscaled.

## Quick start

Requires Python 3.12+ and curl. No Node, database or cloud setup.

```sh
bash scripts/bootstrap.sh
# Add GEMINI_API_KEY to .env.local using your editor; do not overwrite existing keys.
# Optional model overrides are listed in .env.example.
bash scripts/dev.sh
```

Open http://127.0.0.1:8000. Uploads, previews and IFC import/viewing work without a key. Credentials stay on the server. Questions send source images or extracted IFC records to the explicitly selected provider. Image reconstruction also requires that provider. Three.js is pinned locally; there is no rendering service or CDN dependency.

## Try the two demo flows

1. Upload `duplex_arc.ifc` from the dataset's `ifc_bench` folder. Drag to orbit, scroll to zoom. Ask **How many windows are in this IFC model?** The complete source catalog contains 24 windows. They highlight while other elements fade to 10% opacity. Click a highlighted object or its evidence row to inspect its GlobalId, STEP reference and properties. Rooms mean IFC spaces (21 in this model).
2. Upload unchanged `colorful-1794.png` or `colorful-11397.png` from `assets/junction-dataset/data/cubicasa5k`. Click **Generate building model**. Gemini describes every explicitly depicted floor across all pages; deterministic Python/IfcOpenShell creates the IFC and local Three.js renders it. The upside-down, side-by-side diagrams in 11397 require no manual editing. Use the floor selector and separate-floor display; click an object to inspect its original page region. Ask a floor-specific room question, requesting its full room region. Only reliable source-region/name associations highlight. Actual ceiling height remains unknown unless the original source supplies it.

**Source comparison** overlays the actual reopened IFC footprints, wall sections and openings on the original page. Toggle layers to check missing features, invented walls and displaced openings. The interpreted inventory links every generated or unresolved record to its source; it is not a claim that every source feature was found. Stairs, furnishings and fixtures use simple schematic geometry. Terraces/balconies are outdoor spaces; room polygons never create walls.

Furniture and fixtures use raised schematic blocks, tops and basin symbols with labeled assumed heights. Stair marks remain level symbols, not measured steps or rise. Orbit toward an overhead view to inspect features hidden behind walls. Click a **?** marker to inspect an unresolved source region; these annotations are separate from model geometry and answer highlights. A floor badge means a precise location is unavailable. See [the fidelity results](docs/SCHEMATIC_FIDELITY_RESULTS.md) for known extraction errors.

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

Historical Gemini compatibility diagnosis is in [GEMINI_FIX.md](docs/GEMINI_FIX.md); V3 live experiments and fidelity findings are in [RECONSTRUCTION_V3_DIAGNOSIS.md](docs/RECONSTRUCTION_V3_DIAGNOSIS.md). Reconstruction uses one `gemini-3.1-pro-preview` call with high thinking, a 150-second deadline and a 32,768-token output budget. Set `GEMINI_RECONSTRUCTION_MODEL` to select another supported model explicitly. `GEMINI_MODEL` still selects source answering; Decisions keeps its existing model and settings. These reconstruction budgets are design choices for the richer inventory, not completeness guarantees. Truncated responses fail explicitly and are never cached.

The API wire schema and necessary local validation remain separate. Invalid/ambiguous geometry stays as a source-linked unresolved record; an all-unresolved result explicitly says no 3D geometry was reconstructed. Valid walls/features do not depend on room polygons surviving. Source-based answers remain available.
- One document at a time: JPG/PNG or PDF up to 10 MiB and five pages. Oversized PDFs are rejected, not silently truncated.
- Uncompressed IFC STEP up to 25 MiB, 4,000 elements and one million triangles. GlobalIds and source units are preserved; world geometry is in metres. Geometry failures retain source records and count membership. Inspector properties are bounded to 48 primitive values per object; inference sees the first 12 with explicit omission warnings.
- For genuinely supplied IFC only, exact English whole-model count questions use deterministic catalog counts after the same sufficiency gate. Qualified/floor-specific questions use the normal gated source-answer path; no extra intent model. Counts describe the uploaded model, not physical-building completeness.
- The selected gate evaluates whether the inspected source supports the question: sufficient, insufficient or unclear. One additional inspection is allowed for unclear results.
- The selected model generates structured answers and source references. A sufficiency score does not prove the answer is correct. References are model-proposed regions for human verification.
- Missing scale/dimensions remain unknown. Assumptions are labeled proposals, never facts about the uploaded building. Similar-building retrieval is deferred.
- Drawing reconstruction describes explicitly depicted floors, indoor/outdoor footprints, independent physical walls/shared boundaries, hosted doors/windows, stairs, furnishings and fixtures. Every description entry survives as reconstructed, schematic or unresolved; model omissions remain possible and need source comparison. There are no extraction floor/room/vertex caps. Existing upload, IFC and provider budgets still apply. Unknown scale uses IFC `UNSCALED_DISPLAY_UNIT`, never metres; an explicitly cited physical dimension can calibrate footprints. Heights/thicknesses and missing vertical opening dimensions remain display assumptions. Unsupported alignment is schematic; vertical separation is only a viewer effect.
- Generated IFC is derived visualization, never authoritative evidence—even after reopening. It embeds original normalized source PNGs and a validated provenance manifest, including the exact V3 description used by the generator. QA inspects those originals; generated inventory, dimensions and assumed heights do not enter factual context. Invalid or contradictory recognizable generated metadata is rejected rather than reclassified as supplied IFC. This is consistency validation, not cryptographic authenticity.
- API/configuration errors are displayed as operational errors, never as evidence insufficiency. No hidden fixture mode or provider fallback.

This is a local hackathon app, not a production service. Bind to loopback. It has no authentication or durable database. Runtime files are ignored by Git. See the API contract for exact source handling and limits.

Uploads are normalized to PNG with a maximum 4096-pixel edge (input images over 40 megapixels are rejected). Each server session holds at most 20 documents in a temporary directory under `.runtime`; normal shutdown removes that session. Restarting clears the document index. Initial model views are resized to 1600 pixels; a targeted retry uses a crop from the stored higher-resolution page. Fine text can still be unreadable. Server arithmetic verifies the operation, not the model's interpretation of operands or units.

## For subsequent agents

Read [AGENTS.md](AGENTS.md), [reconstruction plan](docs/RECONSTRUCTION_V3_PLAN.md), [reconstruction contract](docs/RECONSTRUCTION_V3_CONTRACT.md), [base API contract](docs/CONTRACT.md), and [handoff](docs/HANDOFF.md). Root owns contracts/environment/integration; backend and frontend owners work in separate paths; an independent reviewer checks reliability and scope. Tests use injected providers and are not a model-quality evaluation. DXF/SVG/DWG, photorealism, Blender/MCP and cloud/HPC rendering remain deferred.

## Model-quality experiment

Use the same document/question pairs for ordinary Gemini and the gated pipeline. Measure answer coverage, error among answered questions, unsupported answers, unnecessary abstention, latency and token usage. Include deliberately incomplete and ambiguous drawings, as well as sparse JPGs with answerable questions. Split by drawing/building rather than translations or file formats. Keep reference answers out of runtime context.

API references: [Decisions](https://aistudio.google.com/docs/decisions-api), [models](https://aistudio.google.com/docs/models). The Decisions SDK requires google-genai 3.2 or later; this environment pins the installed version. Model names are configurable because account access can differ.

OpenAI references: [structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs), [model catalog](https://developers.openai.com/api/docs/models), [native Decisions (not used by this temporary adapter)](https://developers.openai.com/api/docs/guides/decisions).
