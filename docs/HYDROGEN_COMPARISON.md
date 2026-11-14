# Hydrogen model-only reconstruction experiment — 2026-11-14

## Reviewed method

Planner and independent reviewer approved a temporary experiment harness, with no extraction-stage, prompt, schema, generator, frontend, dependency or infrastructure changes. The reviewer independently opened both saved baseline IFCs in Chromium, orbited all three depicted floors, switched floors, inspected original-page overlays and clicked source evidence before reviewing new results.

Baseline files are the final deterministic replay artifacts from the preceding fidelity iteration: `/tmp/junction-fidelity-v4/schematics/11397.ifc` and `1794.ifc`. Copies and their embedded descriptions are preserved separately in `/tmp/junction-hydrogen-20261114-9_yxhyez/baseline/`. Fresh outputs belong under that experiment directory's `hydrogen/` subdirectory. Nothing overwrites the originals or existing scene caches.

The initial experiment changes only `GeminiProvider.reconstruction_model` on each temporary provider instance to `gemini-4-hydrogen`. Temperature 0, HIGH thinking, v1beta structured JSON, the existing wire schema, 150-second request timeout, 32,768 output-token budget and single attempt remain unchanged. No automatic fallback or quality retry. [Google's Hydrogen documentation](https://aistudio.google.com/docs/models/gemini-4-hydrogen) lists image input, structured output and high thinking as supported.

The harness records original file, normalized PNG, actual provider-image, prompt, schema and code hashes plus safe model/usage/status metadata. Credentials and raw requests are not logged or committed. Descriptions and IFCs are local experiment artifacts, not application persistence. Operational API/validation failures must not become source-insufficiency judgments.

This is one fresh sample per case against saved outputs. Historical request settings are not fully recorded; current hashes do not retrospectively establish bit-identical historical requests. Different extractions can reorder description entries, so cross-model comparisons use source regions and semantics rather than matching index-derived GUIDs. IDs must remain stable within each artifact's export/reopen flow.

Adoption requires a useful source-fidelity improvement without material regressions. Object counts and unresolved totals alone cannot establish that. **Do not adopt Hydrogen from this experiment.** The default remains `gemini-3.1-pro-preview`; `GEMINI_RECONSTRUCTION_MODEL` remains configurable. Hydrogen improved several 1794 defects but introduced material regressions, and did not complete 11397 within the tested budgets.

## Results

| Case/configuration | Actual live outcome |
|---|---|
| 1794, initial unchanged configuration | `gemini-4-hydrogen`, STOP, 71.515 s. Valid structured description, deterministic IFC and successful reopening. |
| 11397, initial unchanged configuration | `gemini-4-hydrogen`, MAX_TOKENS, 136.257 s. 25,498 thought + 7,270 candidate tokens exhausted 32,768. Provider correctly rejected incomplete output; no accepted description or IFC. |
| 11397, isolated budget probe | Only `max_output_tokens` increased to 65,536, the documented synchronous maximum. HTTP 504 DEADLINE_EXCEEDED after 150.847 s. No accepted description or IFC. |

The token-budget adjustment was explained before execution and independently reviewed. It was a single diagnosed operational probe, not a quality retry or repair stage. Its separate metadata lives in `hydrogen-budget65536/11397.run.json`. HIGH reasoning and all other settings, including the 150-second timeout, stayed unchanged. No further calls, fallback or larger timeout were introduced. Live API compatibility is established, but API compatibility does not establish useful reconstruction fidelity. Neither failure says the drawing lacks evidence.

## Original-page before/after comparison

The reviewer personally inspected original drawings and actual reopened IFC overlays, and directly used Chromium to orbit, switch floors, inspect assumptions and click source evidence. Baseline browser evidence is in `/tmp/hydrogen-review-baseline/`; fresh 1794 evidence is in `/tmp/hydrogen-review-after1794/`. Root independently inspected original images, description records and actual-IFC overlays under the experiment's `hydrogen/captures/` directory.

1794 wall comparison: [before](/tmp/hydrogen-review-baseline/1794-floor1-walls-overlay.png) · [after](/tmp/junction-hydrogen-20261114-9_yxhyez/hydrogen/captures/1794-floor1-walls.png). Feature comparison: [before](/tmp/hydrogen-review-baseline/1794-floor1-all-overlay.png) · [after](/tmp/junction-hydrogen-20261114-9_yxhyez/hydrogen/captures/1794-floor1-comparison.png). These paths are derived from tessellated IFC meshes, not merely redrawn descriptions.

| Requested issue | Result | Source/description/mesh evidence and remaining cause |
|---|---|---|
| 11397 upper-floor facade | **Uncertain** | No accepted new IFC; comparison unavailable. Existing baseline missing/conflicting facade remains. Operational truncation/deadline is not an extraction-quality verdict. |
| 11397 doors/windows | **Uncertain** | No accepted new description/model to compare with the baseline unresolved or omitted openings. |
| 11397 connectivity and depicted thickness | **Uncertain** | No new reopened geometry. Baseline source-band generator is unchanged. |
| 11397 indoor/outdoor boundaries and furnishings | **Uncertain** | No new accepted output; no claim that Hydrogen fixes or worsens these. |
| 1794 kitchen/bath partition | **Improved** | Baseline wrongly spans x≈.186–.324 with .067-page-height thickness. Hydrogen limits the thick part to the depicted left pier (x≈.181–.226), with a separate thin bathroom top wall at y≈.403. Actual overlay follows the source more closely. Extraction improvement; generator unchanged. |
| 1794 wall crossing balcony | **Improved** | The interior balcony-crossing vertical wall disappears; the right glazed perimeter moves to x≈.824, matching the depicted outer edge. Glazing/parapet construction remains explicitly unresolved; no physical vertical detail is established. Extraction improvement. |
| 1794 sink/hob classification | **Improved** | Left-counter cooktop is now an appliance (source region x=.209–.230, y=.235–.295); lower-counter sink is a sink (x=.242–.278, y=.364–.384). Both match visible source symbols. Extraction improvement. |
| 1794 wall connectivity/openings | **Worse** | `w_bath_bottom` contains just one point. Generator correctly retains an unresolved record instead of inventing a wall; its hosted bathroom door also becomes unresolved. Both were rendered in the baseline and are clearly depicted in the original. Extraction defect causing a visible missing boundary/gap assembly. |
| 1794 depicted thickness | **Improved** | Corrects the oversized horizontal kitchen/bath strip while retaining the thick source pier. This does not establish physical scale or universal thickness accuracy. |
| 1794 indoor/outdoor boundary layout | **Improved** | Balcony is still outdoor and its perimeter follows the source better. Missing bathroom boundary is separately reported above; vertical glazing construction remains unknown. |
| 1794 furnishing coverage | **Uncertain** | Sink/hob semantics improve and wardrobe/counter records are visible, but counts include different segmentation. A bathroom corner symbol is now explicitly unresolved. No defensible overall completeness score follows from 13 rather than 10 feature records. |
| New 1794 floor error | **Worse** | Description adds an empty floor named `w_bath_bottom_fix_error_check` at a narrow bathroom region. It becomes a blank selectable floor/storey in the unchanged viewer. The original depicts only one floor. This is model extraction output, not a newly implemented generation rule. |

The two new 1794 defects are material. All listed differences originate in fresh description content; no generator change was made to create or conceal them. Invalid wall geometry stays unresolved, as intended. The experiment did not alter validation to repair the response or suppress its extra floor.

## Artifacts and verification

- Fresh accepted files: `hydrogen/1794.description.json`, `1794.ifc`, `1794.scene.json`. Original baseline copies and descriptions remain intact. Initial 11397 incomplete provider output is retained privately for diagnosis, never treated as an accepted building description.
- Safe run/configuration/hash metadata: `experiment.json` and per-case `*.run.json`; temporary execution harness `/tmp/hydrogen_model_experiment.py`. No raw requests or credentials were saved. No source/description/IFC data is committed.
- Reopening checks preserve the exact description, original embedded pixels, element IDs within the artifact, assumptions and transforms. Fresh-store 1794 import restores a derived drawing with original source page and relative units. Its QA context contains only source association hints, not generated heights, properties or geometry.
- Independent browser review exercised 1794's real floor selection, including the erroneous empty floor, unresolved annotations, element-source links and assumptions controls. No JavaScript errors. The missing wall/door and bogus floor are extraction regressions despite a successful render.
- Focused regressions: **72 passed** (`test_gemini_schema.py`, `test_provider_selection.py`, `test_ifc_artifact.py`, `test_reconstruction.py`). Protected product-code hashes and original/copied baseline hashes were rechecked unchanged. No application configuration, provider default, prompt, schema, generator or UI edits are part of this experiment. No push or deployment.

This model-only swap is insufficient for adoption on the current evidence. No additional extraction experiment or infrastructure is implemented or proposed as part of this result.
