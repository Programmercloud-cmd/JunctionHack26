Implement the next hackathon iteration around source-first reasoning and coherent building reconstruction. The following changes were discussed in a side conversation and should not be assumed implemented.

Use the established planning, independent plan review, bounded implementation and independent implementation review workflow. Reviewers should directly interact with the browser and compare actual reopened IFC geometry with original drawings. Make focused commits at suitable milestones; do not push.

1. Make reasoning extraction independent of optional 3D generation

The default flow should be:

Upload → preserve original sources → extract and save reasoning JSON
                                              ├─→ Question answering
                                              └─→ Optional 3D generation

Start structured extraction automatically after upload. Save valid interpretation JSON as soon as extraction completes, before IFC generation. QA must be able to use it without a 3D model. Skipping or failing geometry generation must not discard successful extraction.

Make 3D generation an explicit user action. Reuse the existing interpretation and obtain additional geometry only where needed. Keep one shared representation with optional geometry information rather than separate, incompatible pipelines.

To reduce token cost, the no-render path should skip geometry-specific model work and reconstruction review/repair calls. IfcOpenShell generation and Three.js rendering are local and do not themselves consume model tokens.

For drawings, QA and Decisions must continue to inspect original images alongside the fallible JSON. Missing extracted records must not be mistaken for missing source evidence. Questions asked before extraction finishes should remain answerable from the originals.

2. Preserve caching and incremental reuse

Inspect and retain the existing content-based persistence. Reuploading identical bytes, including under another filename, should reuse saved resources without repeating inference.

Persist interpretation JSON independently of rendering. Keep original files, source mappings, successful extraction, geometry and review results through failures and restart. Explicit retries or refinement can make new calls; reopening, orbiting and mode switching must not.

Adding another source to a building should reuse existing extraction rather than process every unchanged file again. Ordinary question answering may still incur token usage; adding answer caching is outside this iteration.

3. Diagnose the colorful-34.png failure

Use the unchanged original:

assets/junction-dataset/data/cubicasa5k/colorful-34.png

It currently reports:

> Source processing failed operationally. Previous usable revision retained; no evidence-quality conclusion was made.

Determine the actual failed stage and exception through controlled live testing. Do not guess whether the cause is Gemini, schema validation, IFC generation or reopening. Retain returned structured descriptions safely for deterministic replay where possible.

Improve stage-specific diagnostics without exposing credentials or raw requests. When no model has ever existed, say that the source was saved but no model was generated; do not imply that a previous usable model was retained.

4. Investigate unnecessary door-count refusal

The application refused a door-count question by demanding a complete door schedule, clearer symbols and comprehensive legends, although door leaves and swing arcs are visible.

Inspect the initial sufficiency decision, draft and post-draft review to determine where that unnecessary requirement arose. Do not assume Decisions alone caused it.

Distinguish counting doors depicted in the supplied plans from establishing every installed door in the actual building. A door schedule is not a universal prerequisite for counting visible symbols.

Return a supported count with source regions when possible. Identify genuinely ambiguous openings individually and explain whether they affect the total. Avoid double-counting a connecting door from its two adjacent spaces. Preserve appropriate uncertainty rather than forcing an exact answer.

This must work from original drawings even when reconstruction fails. Generated IFC object counts must never substitute for factual drawing inspection. Add positive door-count and genuinely ambiguous-opening regression cases; keep evaluation annotations out of runtime context.

5. Provide consistent native IFC floor controls and adjustable cutaway

For duplex_arc.ifc, expose floor selection using supplied storeys and containment relationships. Native IFC should receive the relevant inspection controls already available for generated models.

Replace the binary cutaway with a percentage slider. Define its reference clearly—for example, 0% at the selected storey’s floor level and 100% at full storey height—and make all-floor behavior understandable. Clip geometry rather than shrinking walls or moving openings. Any unsupported reference height remains a display assumption.

6. Assemble drawing-derived floors into one coherent building

For unchanged colorful-11397.png, investigate the lateral offset and the collapse of floors into one plane when vertical separation is disabled.

Separate original page coordinates, building placement and exploded-view offsets. The diagrams’ positions on the sheet must not automatically determine their positions in the building.

Use supported shared features, especially the staircase and exterior boundaries, to register corresponding floors. Preserve their differing footprints, including the larger terrace. Do not independently rescale floors or force equal footprints.

Stacked mode should retain storey elevations; exploded mode should add extra spacing. Where heights are unknown, use explicit display assumptions without presenting them as measured dimensions. Preserve the shared-page scale fix and keep uncertain cross-page scale relationships explicit.

Corresponding stairs should connect the storeys where the source supports that relationship. A simple continuous schematic connection is sufficient; missing rise measurements should not erase clearly depicted connectivity. Preserve supported footprints and label assumed vertical geometry.

7. Diagnose wall shapes and unresolved hosted openings

Inspect the actual description, host associations, transforms and reopened IFC behind messages such as:

> Opening cannot be projected within its explicit host band and original source region.

Determine whether the extraction selected the wrong host, misplaced a wall/opening, misrepresented thickness or introduced inconsistent coordinates. Clear source doorways should prompt correction of the responsible records, not arbitrary attachment to a nearby wall.

Compare the red wall overlays against the actual black wall footprints. The source contains genuinely thick and tapered/angled wall ends; do not assume every unusual shape is erroneous or replace all walls with constant-width rectangles.

Use building-level consistency checks to identify contradictions in walls, openings, storeys and stairs. These checks should guide source inspection and correction, without inventing a “perfect” building from unsupported information.

8. Allow multiple source files for one building

Support uploading several related blueprints together and adding sources to an existing building. Use a suitable kit_institute dataset example if available.

Plans, sections and elevations should contribute their supported information without every view becoming a floor. Preserve file identity, original page coordinates, citations and source-specific authority. Expose conflicting measurements or uncertain alignment.

The user’s selected building and source content should establish grouping; filename similarity can suggest it. Keep this lean: extend the existing building bundle and reasoning representation rather than introducing a new subsystem.

Preserve building-type agnosticism, original labels, neutral concept styling, stable IDs, portable provenance, source-based QA, refusals, conservative highlights and independent assumption controls. Gemini remains the final-demo provider; keep the provider switch and current model default.

Verify the changed flows using colorful-34.png, colorful-11397.png, colorful-1794.png, native duplex IFC and a related non-residential document set. Include live Gemini checks, original-coordinate overlays, actual reopened geometry, restart/reupload reuse and independent browser review. Report remaining fidelity gaps honestly.

Before introducing new constraints, explain what they restrict, why they are needed, whether they are external requirements or design choices, and how they could block valid inputs or the demo. Defer photorealism, detailed roofs/domes, new formats, Blender, cloud rendering and unrelated infrastructure.

9. Turn the right-hand panel into a source-linked QA conversation

Replace the isolated question/result interaction with a lightweight chat scoped to the selected building. Preserve conversation context so follow-up questions such as “What about the upper floor?” can resolve their references.

When ambiguity materially changes the answer, Gemini should ask a brief clarification, preferably with selectable suggestions and a free-text option. For example:

> “Do you mean the ground floor, upper floor, or both?”

Distinguish unclear user intent from insufficient source evidence. Asking for clarification should not appear as a refusal. Avoid unnecessary clarification when a reasonable interpretation can be stated clearly in the answer.

Show meaningful progress and an expandable Evidence and checks view containing:

- Inspected blueprint regions or original IFC records.
- Supported calculations and their inputs.
- A concise explanation of what supports the answer.
- Remaining uncertainty and review outcome.

This should expose useful, evidence-based explanations rather than promise a stream of the model’s private internal reasoning. Do not present unreviewed drafts as final findings.

Citations and object references should connect the conversation to the left-hand viewer. Blueprint references open the original file/page/region; reliable model associations highlight corresponding objects. Respect the selected view and preserve camera controls. If an object mapping is uncertain or 3D is unavailable, the source citation must still work.

Keep original evidence authoritative throughout follow-ups. Earlier assistant messages and extracted JSON are fallible context, not new factual sources. Associate answers with their building revision and preserve access to the evidence used for older answers.

10. Add an editable assumptions and missing-information panel

Provide a clean, source-linked table for reconstruction assumptions and unresolved inputs. Distinguish:

- Information observed in the supplied sources.
- Inferred interpretations.
- Display assumptions.
- Unknown information.
- Values supplied by the user.

Group shared assumptions—such as a floor’s display height—rather than presenting hundreds of duplicate rows. Each editable entry should identify the affected floor/object, property, current value or unknown state, units, and why the value was assumed. Selecting an entry should locate its source region and associated geometry where available.

Allow users to provide missing information or correct an interpretation, with an optional supporting document or source region. For example, they could supply a storey height, a known plan distance for calibration, or clarify a stair connection.

User-provided information must retain its provenance. A supplied height should be labeled “provided by user,” not silently converted into a dimension observed in the blueprint. QA may use it with explicit attribution when appropriate; questions about what the drawing itself establishes must retain that distinction. A known vertical height must not automatically establish horizontal plan scale.

Let users edit several entries and submit them through an explicit Apply and refine action. Do not make model calls on every keystroke. Applying changes should:

1. Validate values, units, scope and revision.
2. Preserve the submitted information with its provenance.
3. Review conflicts with existing sources.
4. Refine affected geometry using the existing bounded workflow.
5. Retain the previous usable revision if the candidate fails.
6. Publish an accepted update without resetting exploration.

Preserve user-provided values and their attribution through saving, export and reopening. This is structured input to deterministic generation—not permission to execute user- or model-generated code.

Verify clarification and follow-up QA without any 3D model, clickable chat evidence in both views, and a user-supplied reconstruction value producing a traceable revision. Unsupported source-height questions must still refuse when the original drawing supplies no height, even if a display assumption or user-provided value is available.


11. Evaluate generalization continuously using previously unseen inputs

Do not optimize the pipeline around a closed list of demo images. Keep known failures as regression tests, and regularly evaluate fresh examples at meaningful implementation milestones—particularly after changes to extraction prompts, schemas, geometry generation or QA.

Vary the inputs across:

- Residential, commercial, institutional and religious buildings.
- Clean drawings, scans, handwritten annotations and sparse plans.
- Rotated diagrams, irregular footprints, multiple floors and multiple related files.
- Dimensioned and unscaled drawings.
- Floor plans, sections, elevations and mixed drawing sets.
- Native IFC and drawing-derived IFC, preserving their different evidence rules.

Select examples from different buildings, not merely different pages or versions of buildings already tested. Maintain a rotating held-out sample. Once a failure informs an implementation change, retain it as a regression case and choose new unseen examples for subsequent generalization checks.

Use the same application pipeline for every case. Avoid filename-specific behavior, hardcoded coordinates, building-specific prompts or manually repaired artifacts presented as successful extraction. Dataset reference answers remain evaluation-only.

Evaluate stages separately:

- Source ingestion and structured extraction.
- Useful QA before or without 3D.
- Grounded answers, appropriate clarification and unnecessary refusals.
- Geometry fidelity, floor relationships, openings and feature coverage.
- Provenance, caching, refinement and recovery from failures.
- Latency and token usage.

Include direct visual comparisons and independent browser inspection. Successful API calls, valid IFC files and higher object counts do not establish fidelity.

Use representative live checks within explicitly communicated budgets rather than rerunning the entire dataset after every edit. Report the selection, failures and limitations so demo-case success cannot conceal broader weaknesses.

The goal is robust handling of arbitrary inputs within the supported formats and documented limits. Complete reconstruction will not always be justified. When information is missing or a view cannot be reconstructed reliably, the pipeline should still preserve usable evidence, answer supported questions, identify unresolved portions and request targeted clarification where useful. It should neither crash generically nor invent a complete building.

12. Add remaining file formats through an independent implementation track

Assign a dedicated subagent an isolated worktree, with agreed interfaces and file ownership, so format support can progress alongside the core work. Integrate through independent review. Coordinate dependency changes with the orchestrator.

Start with SVG:

Original SVG → normalized source image
             → shared reasoning JSON
             → QA and optional 3D

Preserve the original vector file, text, proportions and coordinate mapping. Citations, overlays and source inspection must remain traceable to the supplied drawing. SVG coordinates and document dimensions must not automatically establish physical building scale.

Render SVG into the existing source-preview pipeline rather than embedding raw SVG directly in the browser. Report unsupported rendering features explicitly.

Then extend to DXF, preserving relevant layers, units and source references where available. Assess the actual available DWG conversion path before claiming support; any dependency or availability limitation should remain explicit and should not block SVG or other development.

Use matching SVG/PDF examples from the institute dataset for comparison, plus previously unseen examples. Verify labels, linework, proportions, source coordinates, QA, caching and optional reconstruction—not merely successful file loading.
