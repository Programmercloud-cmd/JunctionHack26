# Reconstruction V2 verification — 2026-11-14

The implementation follows the independently reviewed [plan](RECONSTRUCTION_V2_PLAN.md) and [contract](RECONSTRUCTION_V2_CONTRACT.md). Planner/backend, frontend and a separate read-only reviewer had bounded ownership; root handled contracts/provider/integration. No commits, pushes or deployment.

## Current Gemini compatibility diagnosis

Started by exercising the actual existing SDK transport against unchanged original 1794 and 11397, and structured answering. Captured only endpoint/configuration metadata, schema sizes/hashes, body hashes and statuses; no credentials, headers or request bodies were printed or committed. All current structured calls succeeded: no remaining HTTP 400 reproduced. The old single-floor extraction rejected 11397 semantically (`single_floor=false`), not at the API layer. Historical controlled 400 reproduction/fix is documented separately in [GEMINI_FIX.md](GEMINI_FIX.md); that historical result was not used as a substitute for current live calls.

The new BuildingDescription schema also succeeded live. Named coordinate objects (`x`,`y`; `left`,`top`,`right`,`bottom`) replaced ambiguous coordinate arrays on the model wire after inspecting a live axis-order error on 11397. Canonical application/source coordinates remain normalized original-page arrays. There is no heuristic axis swap, rotation of source pixels, or manual crop. The SDK tests exercise actual request serialization, but compatibility claims here come from real Google requests.

Gemini uses `response_json_schema` with the existing Gemini-only `maxItems` removal. Local answer/reference validation remains strict. Extraction has no arbitrary floor/room/vertex count caps. Existing upload/IFC/resource and generation budgets remain. The two normal providers share the building-description schema; OpenAI compatibility is SDK-mocked, not newly live-verified in this extension.

## Controlled quality comparison

One unchanged 11397/image/schema/prompt comparison changed only reconstruction reasoning. Low reasoning produced both floors but retained 6 of 12 proposed rooms after invalid/overlap filtering (17.55 s); medium retained 12 of 12 (42.37 s). Reconstruction now requests medium. Answer/crop/Decisions settings remain unchanged; 8,192 output tokens, 45-second request timeout and one attempt remain. Runtime partial warnings still apply. Valid polygons and fewer omissions do not prove geometric accuracy. The measured medium call has limited timeout margin; cached IFC can be downloaded/reopened without re-extraction.

## Live acceptance

Final full API flows passed with medium reasoning: 1794 produced one floor / 6 room footprints / 43 rendered objects in 35.03 s; 11397 produced two floors / 6 + 5 room footprints / 69 rendered objects in 32.92 s. The latter explicitly omitted two overlapping footprints and three ambiguously mapped openings. Both supported questions returned citations and highlights; both actual-height questions returned insufficient with no highlights. Fresh-store reopening restored exact source pages, stable IDs and all meshes (43 / 69). A second-floor question after reopening again returned a citation and the same validated highlight. Neither file was edited. These are demonstration results, not accuracy measurements. Inputs are the unchanged repository files under `assets/junction-dataset/data/cubicasa5k/`:

- 1794 SHA256: `c9547f7c5374a2a26670175fa4825c5d9dc535e8ccb7c8405a04cacbcb99b204`.
- 11397 SHA256: `e40c1b2314ae3a21e2e9fedab0222efe24fbd61c40fff805c6a17bf431472859`.

## Regression and review coverage

- 167 deterministic/native-IFC checks passed; 9 optional browser checks passed separately. The native sample is `assets/junction-dataset/data/ifc_bench/duplex_arc.ifc`.
- Actual IfcOpenShell creation, serialization, reopening and tessellation; opening void/fill geometry; calibrated nonsquare-page/rotation transforms; mixed/unknown units; partial omission and stable IDs.
- Multiple source panels/pages, original coordinates after transforms, floor filters, display-only explosion, stable cache, independent assumptions/highlights and 0.1 background opacity.
- Standalone fresh-store reopening after original files/session disappear restores exact normalized PNG bytes/hash, stable GlobalIds, assumptions and derived status. Wrong/missing manifest, page hashes, source records, units, types, storey membership and contradictory per-element metadata fail closed.
- Reopened derived IFC cannot enter native counts/property QA, even with a stale document tag. Original source pages are required; geometry dimensions/assumptions stay out of factual context. Native IFC behavior remains unchanged.
- Independent reviewer reproduced and cleared both blockers: unrelated opening source region and manifest/storey mismatch. The final reasoning-only change passed independent scoped review and SDK check.

Reproduce local checks:

```sh
IFC_SAMPLE="$PWD/assets/junction-dataset/data/ifc_bench/duplex_arc.ifc" bash scripts/test.sh
RUN_BROWSER_TESTS=1 PLAYWRIGHT_BROWSERS_PATH=/tmp/junction-playwright bash scripts/test.sh tests/test_browser.py tests/test_browser_3d.py tests/test_browser_v2.py
.venv/bin/python scripts/doctor.py
```

Browser fixtures are explicitly injected; they are not live model inference. Separate live browser evidence is recorded below. No dataset ground-truth answer files enter runtime or prompts. Multi-page PDF and calibrated/mixed scale are regression-tested; the real Gemini acceptance inputs here are the two unchanged PNGs.

Final local run artifacts and safe wire metadata: `/tmp/junction-live-v2-final/`. The original-session stores were closed before standalone reopening.

## Final live browser verification

Chromium reopened the final 69-object 11397 IFC in a new server session with the real Gemini provider. Orbit changed the camera; both floors appeared in schematic separated display; a second-floor question produced one validated highlight while all other objects faded to 0.1. A real pointer click on the highlighted mesh opened its inspector and unchanged original page region. Assumption/highlight controls remained independent. A subsequent actual-height question was refused with no highlights, and the same cached viewer/model was retained. No JavaScript errors.

Screenshots: `/tmp/junction-live-v2-final/model.png`, `highlight.png`, `source.png`. These final screenshots use actual Gemini-generated geometry and live Gemini answers, unlike the injected regression fixtures. All owned test servers were stopped after verification.
