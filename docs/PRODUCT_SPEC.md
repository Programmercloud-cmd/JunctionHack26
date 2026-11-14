/goal Implement and integrate the product described below: progressive, source-grounded building reconstruction; JSON-mediated building reasoning; reviewed Q&A; persistent building bundles; and the existing browser-based concept presentation layer.

Work autonomously through planning, independent plan review, bounded implementation, integration, live verification and independent implementation review. Continue beyond planning until the agreed acceptance flows work or a concrete external blocker prevents further progress.

I will be offline. Resolve routine implementation decisions using the repository instructions, existing architecture and your judgment. Communicate assumptions and tradeoffs in progress updates without turning them into approval requests. Preserve existing working behavior and keep the implementation appropriate for this hackathon.

PRODUCT CONCEPT

The product uses two source-grounded review loops: one progressively improves the building model; the other checks answers before publishing them. Both preserve original evidence, explicit uncertainty and traceable revisions.

A saved building can be reopened immediately. New drawings run through background reconstruction; questions reuse the available model and evidence.

Users can switch between:
- Inspection mode: source-associated geometry, evidence, assumptions, unresolved issues and answer highlights.
- Concept mode: an architectural presentation of the same building, with clearly distinguished styling and decorative proposals.

The core experience is:

Upload or open a building, explore its 3D interpretation, and ask questions whose answers link back to the supplied evidence.

All supported inputs expose structured building context for reasoning, while the evidence rules depend on where the information came from.

INPUT PATHS AND JSON-MEDIATED BUILDING REASONING

Implement a structured reasoning interface for genuine IFC files, drawings/PDFs and our drawing-generated IFCs.

JSON makes the information usable for Gemini and deterministic code. It must preserve provenance rather than become an unqualified replacement for the source.

Inspect and reuse existing extraction, description, source-context and artifact functionality before adding new mappings. Do not duplicate capabilities that already exist.

1. Genuine uploaded IFC → reasoning JSON

Use IfcOpenShell to extract a semantic building representation containing:
- Stable IFC GlobalIds, entity types and names.
- Storeys and supported containment relationships.
- Available properties, quantities and units.
- Opening/host and space-boundary relationships where supplied.
- Relevant geometry summaries and deterministic calculations.
- Provenance for each value: supplied property or calculated result.
- Calculation methods and contributing records where relevant.
- Extraction coverage, missing data and unresolved relationships.

Include relevant geometry-less entities in the semantic catalog. Rendering availability must not determine which records can support factual answers.

Preserve references to the original IFC records. Do not invent drawing pages, citation boxes or relationships that the IFC does not provide.

Native IFC facts describe the supplied model, not guaranteed as-built reality.

Do not require Gemini to read raw IFC text or reconstruct an existing IFC. IfcOpenShell performs extraction and supported geometry operations.

2. Drawing/PDF → interpretation JSON plus original evidence

Reuse the building description and source mappings, exposing them through the shared reasoning interface.

Gemini must retain access to original pages and relevant regions. Extracted JSON is a fallible interpretation, not a replacement for the drawing.

Keep observed information, inferred interpretations and display assumptions distinct. Generated dimensions and decorative proposals must not enter factual QA as evidence.

3. Drawing-generated IFC → restored drawing context

When reopening our generated IFC, restore its embedded description, original pages, source mappings and assumptions.

Do not treat generated properties or geometry as authoritative native-IFC evidence merely because the file format is IFC.

Recover the embedded exact description where available instead of unnecessarily reconstructing it from the generated geometry.

4. Shared reasoning interface

Define a common interface for objects, relationships, evidence references, units, provenance and coverage while retaining source-specific detail.

The native-IFC extraction schema and drawing-description schema may remain different.

Do not perform a lossy conversion of arbitrary IFC geometry into simple room polygons and wall segments just to reuse BuildingDescription.

Use common stable object references to connect reasoning records, source evidence and viewer selection.

5. Use this context throughout Q&A

Retrieve question-relevant structured records for the sufficiency gate, reasoning model and post-draft review.

For native IFC:
- Code selects relevant original records.
- Code performs supported counts and calculations.
- Gemini interprets the question and explains results.
- Answers cite the contributing original IFC records and properties.

For drawings:
- Supply the structured interpretation alongside original visual evidence.
- The reviewer must not assess an answer solely against extraction JSON or the answer model’s explanation.

Validate that retrieved context covers the question’s scope. A selected subset must not be mistaken for a complete building-wide inventory.

Unsupported or incomplete calculations must expose their missing inputs and coverage limitations rather than silently returning a complete-looking total.

Preserve source-linked highlighting through shared stable IDs. Uncertain associations retain citations without invented highlights.

BUILDING-MODEL REVIEW LOOP

The building-model loop produces an interactive preview, then improves it through targeted revisions.

For drawings, the pipeline is:

Original drawing
→ building-description JSON
→ deterministic IFC generation
→ reopened geometry
→ interactive model

Genuine uploaded IFCs use direct extraction and rendering. Do not route them through drawing reconstruction or automatically rewrite their original contents.

A reconstruction reviewer examines the original drawing, description and actual generated geometry together. JSON-only review could overlook generator errors or approve a plausible interpretation that does not match the source.

1. Generate the first description and preview.

The implementer describes depicted floors, spaces, walls, openings and meaningful features, retaining source regions and uncertainty.

Deterministic code generates and reopens the IFC. After local validation, publish the first usable model as:

“Preview · review in progress.”

Do not wait for the complete refinement loop before making a usable preview available.

2. Review against the original.

Supply full-page context, relevant crops, the description and original-coordinate overlays derived from the actual reopened IFC.

Check:
- Missing meaningful features.
- Invented walls or floors.
- Wall connectivity and relative thickness.
- Opening placement, width and wall associations.
- Indoor/outdoor boundaries and incorrect enclosure.
- Furnishing and fixture coverage.
- Unsupported dimensions and other assumptions.

The reviewer must examine actual generated geometry, not only the description or attractive concept styling.

3. Return actionable feedback.

Each issue identifies:
- The affected object or original source region.
- The discrepancy.
- Supporting source evidence.
- The proposed inspection or correction.
- Any uncertainty that prevents a confident correction.

For example:

“This boundary crosses the depicted balcony opening. Reinspect this source region and revise the boundary’s classification or extent.”

Distinguish extraction, generation and display problems. If the JSON is correct but the generator renders it incorrectly, do not distort the description to compensate.

4. Apply targeted corrections.

Patch the affected description records while preserving unrelated objects and their identities.

Unsupported or ambiguous interpretations remain unresolved. Do not casually rewrite the entire building on each iteration.

Runtime models propose description corrections. They must not generate or execute Python, raw IFC text or application-code patches.

5. Validate the candidate revision.

Regenerate and reopen the IFC, then check both the requested correction and possible regressions elsewhere.

Review what disappeared as well as what improved. A repair to a balcony must not silently remove a bathroom wall or door.

Keep the previous usable revision if generation fails or a clear regression is found.

6. Publish the update without disrupting exploration.

Prepare replacement geometry offscreen and swap the complete revision into the viewer. Do not expose a partially replaced scene.

Preserve:
- Camera position and orbit target; no automatic fit.
- Selected floor and floor separation where the floor still exists.
- Inspection/concept mode.
- Cutaway and assumption controls.
- Selected object when its identity survives.
- Stable concept decoration placements where supporting geometry is unchanged.

Revalidate answer highlights against the new revision.

If an object is removed or becomes unresolved, explain the change and retain its source evidence. Do not silently select an unrelated replacement.

If the footprint changes substantially, offer “Fit updated model” instead of moving the camera automatically.

STABLE IDENTITIES AND COORDINATES

Object identities must survive insertion and reordering.

Persistent object IDs must map consistently to IFC GlobalIds. List positions cannot serve as enduring identities.

Preserve existing imported artifact IDs and compatibility. New objects receive new IDs; deleted objects must not have their IDs reassigned to unrelated features.

Source-to-display frames must remain stable during ordinary refinement. Changing a floor’s bounding box must not recenter or rescale existing geometry.

Preserve the shared-page scale fix:
- Uncalibrated diagrams on the same page retain their relative drawn proportions.
- This does not establish physical scale or prove that independently resized diagrams use equal drawing scales.
- Relationships across different pages remain schematic unless supported.
- Supported physical calibration remains intact.

Supported calibration or orientation corrections require an explicit transform update.

Use building/revision identifiers on reconstruction updates and QA requests. Reject stale patches and stale asynchronous updates rather than allowing an older job to overwrite a newer revision.

RECONSTRUCTION STOPPING BEHAVIOR

The loop stops when:
- There are no actionable supported corrections.
- Repeated attempts make no material progress.
- The user stops the job.
- An explicitly configured execution budget is reached.

Preserve the best available revision and remaining issues.

Reviewer agreement does not justify a “verified accurate” badge. Unresolved disagreements remain visible.

A model can be available with unresolved issues. Availability and completeness are separate states.

Q&A REVIEW LOOP

The Q&A loop inspects evidence, drafts internally and reviews the answer before publication.

1. Establish the evidence context.

Capture the question and current building revision.

Retrieve relevant reasoning JSON and original evidence through the shared interface.

Keep the input distinction:
- Genuine uploaded IFC: use its actual records, relationships and supported geometry calculations.
- Image/PDF: inspect original pages alongside the structured interpretation.
- Drawing-generated IFC: continue using the original drawing as evidence, including after reopening.

Drawing-generated geometry and concept decorations do not establish factual dimensions.

2. Check evidence sufficiency.

Retain the existing Decisions gate:
- Sufficient: proceed to drafting.
- Insufficient: explain what is missing from the inspected material.
- Unclear: perform the permitted targeted inspection or request clarification; unresolved uncertainty remains explicit.

Missing information is scoped to the inspected material, not asserted to be absent everywhere.

3. Generate an internal draft.

Gemini supplies:
- The proposed answer.
- Source citations.
- Relevant calculation inputs and derivations.
- Explicit limitations.

The draft is not yet presented as the final answer.

4. Run deterministic validation.

Check source references, units and calculations.

Code performs supported native-IFC counts and geometry operations using the actual records, including relevant objects without renderable geometry.

Do not ask the model to replace deterministic counting or arithmetic where the required records and inputs are available.

5. Review the draft against the evidence.

Decisions receives:
- The user’s question.
- The draft answer.
- The original evidence or faithful extracted native-IFC records.
- Relevant structured context with provenance and coverage.
- Calculation results and relevant validation findings.

For drawings, include the necessary original visual evidence. Do not supply only the reconstruction JSON or the answer model’s explanation.

Ask one overall question:

“Does the inspected original evidence support this draft’s answer to the user’s question, including its factual claims and derivations, without treating assumptions as facts?”

Route the result:
- Supported: publish after local validation passes.
- Contradicted: reinspect the evidence and revise.
- Unsupported by inspected evidence: seek missing evidence if available; otherwise explain the limitation.
- Unclear: inspect further or return explicit uncertainty.

Do not introduce a large set of independent model vetoes. Add targeted diagnostic checks only where demonstrated failure modes justify them.

6. Revise through meaningful progress.

Each retry must:
- Inspect additional evidence.
- Correct a calculation.
- Repair a citation.
- Remove an unsupported claim.
- Or narrow the answer appropriately.

Rephrasing the same unsupported assertion until it receives approval is not progress.

Decisions provides a routing judgment, not a written critique. The reasoning model identifies the correction using original evidence and concrete validation failures.

A wrong room count can be corrected. An actual ceiling height absent from the supplied material cannot be recovered through repeated reasoning.

7. Publish with validated associations.

Show the answer, citations, limitations and reliably associated highlights.

Uncertain object mappings retain source evidence without invented highlights. A missing highlight must not suppress an otherwise supported textual answer.

If reconstruction changed during the request, revalidate highlight associations against the displayed revision. Original source citations remain available even if an earlier object mapping no longer works.

During Q&A, show progress such as:
- “Inspecting source.”
- “Checking answer.”

The model remains usable while the answer is prepared. Questions do not automatically trigger reconstruction.

SHARED EVIDENCE BOUNDARIES

- Original IFC records support answers about the supplied model; they are not proof of as-built reality.
- Drawing-derived IFC remains an interpretation, including after export and reopening.
- Unknown scale stays explicitly unscaled.
- Extrusion heights, decorative materials and proposed furnishings remain assumptions.
- Actual-height questions still refuse when the original source supplies no height.
- Concept additions never become factual evidence merely because they are visible.
- API failures are operational errors, not evidence-quality judgments.
- Missing information is scoped to the inspected material.
- Optional similar-building ideas remain explicitly hypothetical proposals.
- A reviewer’s approval is corroboration, not proof of correctness.
- Model confidence must not be presented as measured accuracy on this dataset.
- Dataset ground-truth answers remain evaluation-only and never become runtime context.

INTEGRATE THE EXISTING CONCEPT PRESENTATION

Inspect:

/home/jcb/dev/github/JunctionHack26-concept

Read its docs/CONCEPT_VISUALIZATION.md, inspect the implementation, verification artifacts and actual git state.

Reuse its existing Three.js concept layer. Keep the simpler inspection mode as the evidence-oriented view.

Do not build a replacement concept renderer or add Blender, remote rendering, new rendering services or downloaded asset libraries for this goal.

The concept worktree reportedly contains:
- Architectural materials.
- Procedural furnishings and planting.
- Glazing.
- Lighting and shadows.
- Cutaway/full-wall controls.
- Floor selection.
- Cached orbit interaction.

Its prior verification is useful context, not proof that it works with the current main-thread implementation.

Identify the presentation-specific changes and integrate them carefully. Do not replace newer reconstruction, provenance, scaling, opening, schematic geometry or QA fixes with the concept worktree’s older baseline.

Preserve unrelated work and inspect uncommitted changes before integrating anything.

Maintain these boundaries:
- Inspection and concept consume the same building revision and object mapping.
- Concept styling and decorative proposals never enter factual QA context, source object counts, evidence citations or exported IFC.
- Source-associated furnishings and newly proposed decorations are visibly distinguishable.
- Selecting a proposal identifies it as a proposal.
- Generic semantic categories must not silently imply unsupported specificity. An unspecified appliance must not automatically become a hob.
- Inspect rotated and irregular footprints. Avoid decorative geometry extending outside its supported footprint because of world-axis bounding-box placement.
- If precise styling is unavailable, use an explicit schematic fallback.
- Preserve camera, controls, floor selection, cutaway, assumptions and stable decorative placements across model revisions, not only across mode switches.
- Rebuild affected presentation assets offscreen and publish revisions atomically.
- Dispose replaced resources without invalidating shared geometry.
- Check performance on available hardware and report software-rendering limitations honestly.
- Inspection must remain usable.

Blender remains a possible future consumer of the same saved geometry and source mappings. It is outside this implementation goal.

PERSISTENCE AND BACKGROUND PROCESSING

Implement the smallest local persistence mechanism sufficient for the product.

A filesystem artifact store and a lightweight job runner are acceptable. A database, distributed queue or general-purpose agent framework is not required.

Store complete, versioned building bundles containing:
- Original source files and normalized pages.
- Exact building descriptions or native IFC extraction records.
- Reasoning JSON with provenance and coverage information.
- IFC artifacts.
- Browser geometry.
- Stable object mappings and source-coordinate transforms.
- Assumptions and unresolved issues.
- Review findings and revision status.
- Pipeline, prompt and model configuration.

Recognize repeat uploads by content identity rather than filename.

Reopening a saved building must survive application restart without reconstruction. Camera movement, mode changes and questions must not regenerate geometry.

Improved pipelines create explicit new revisions instead of silently overwriting the previous usable result.

A failed background job must not destroy a usable building bundle. Report failure separately from model completeness and source sufficiency.

IMPLEMENTATION SEQUENCE

First inspect the current repository and concept worktree, then produce a small implementation plan and shared contracts.

Use the established planning and independent review workflow. Obtain independent plan review before dependent implementation.

Use staged checkpoints:

1. Integrate the concept view while preserving current inspection and QA.
2. Establish persistent bundles, stable identities and revision-safe viewer updates.
3. Implement or extend native IFC extraction into the shared reasoning interface, preserving drawing-specific evidence behavior.
4. Implement background reconstruction with first-preview publication, source/geometry review and targeted description patches.
5. Add post-draft Q&A review and corrective iteration using the structured reasoning context while retaining the existing sufficiency gate and deterministic validation.
6. Verify the integrated flows with real artifacts and live Gemini, resolve blocking review findings, and document remaining limitations.

Parallelize only tasks with clear file ownership and settled interfaces.

Development subagents are for implementation and review. The application itself does not need a general-purpose multi-agent runtime.

PROVIDER AND EXECUTION POLICY

Gemini remains the final-demo provider.

Preserve the explicit provider switch and current reconstruction-model default. The Hydrogen experiment was not adopted. Do not reopen model selection as part of this goal without concrete evidence that it blocks implementation.

Use existing credentials for live tests necessary to establish compatibility and acceptance. Do not print secrets or raw sensitive requests.

Background reconstruction need not inherit a synchronous HTTP request deadline.

Inspect existing limits and choose explicit, configurable execution budgets appropriate to background reconstruction and interactive QA.

Before introducing or changing a self-imposed constraint, communicate:
- What it restricts.
- Why it is needed.
- Whether it is an external requirement or our design choice.
- How it could block a valid input or the demo.

This requires communication, not a blanket approval process.

Do not silently introduce arbitrary feature, floor, room or vertex caps.

Avoid unlimited retry loops. Track material progress, repeated feedback and candidate revisions.

Budget exhaustion, API failure and evidence insufficiency remain distinct outcomes. Exhaustion means processing stopped; it does not prove information is absent.

Keep local semantic/geometric validation separate from the API schema where appropriate. A successful schema response is not evidence of reconstruction fidelity.

VERIFICATION AND ACCEPTANCE

Use unchanged:
- assets/junction-dataset/data/cubicasa5k/colorful-11397.png
- assets/junction-dataset/data/cubicasa5k/colorful-1794.png

Use a genuine supplied IFC for native-IFC extraction and QA regression.

Reuse saved descriptions for deterministic work. Make fresh Gemini calls where extraction or review behavior itself must be tested.

The independent reviewer must directly interact with the browser and inspect original-source overlays, rather than relying only on implementer summaries.

Demonstrate:
- A first usable model appears while review continues in the background.
- A source-backed correction produces an updated model without resetting the camera, floor, mode or controls.
- Inserting or reordering description objects does not change unrelated IDs.
- Failed or clearly regressive candidates do not replace a usable revision.
- No invented floors or factual dimensions appear through refinement.
- Original source evidence remains inspectable in inspection and concept modes.
- Saved buildings reopen after application restart without an extraction call.
- Concept proposals remain separate from factual evidence and IFC export.
- A genuine uploaded IFC is extracted into reasoning JSON with original-record provenance.
- A supported native-IFC question is answered through the JSON-mediated reasoning path with original GlobalId/property citations and deterministic calculations where appropriate.
- Relevant geometry-less IFC entities remain available to reasoning.
- Incomplete extraction or retrieval does not produce a falsely complete count or total.
- Drawing-derived IFCs still restore original drawing evidence and never acquire native factual shortcuts.
- A supported drawing question returns citations and reliably associated highlights.
- An unsupported actual-height question refuses despite visible extrusions.
- Q&A handles a model revision arriving while an answer is being prepared.
- The post-draft reviewer can trigger a meaningful correction or preserve an explicit unresolved result without simply retrying until approval.

Use injected fake providers for deterministic failure and concurrency tests, and clearly identify them as fixtures.

Do not present synthetic corrections or fixture answers as successful live inference.

Compare live before/after geometry against the original drawings. Review omissions and regressions as well as improvements.

Compare the reviewed-QA pipeline against the current pipeline on:
- Supported questions.
- Unsupported questions.
- Confidently wrong draft answers.
- Cases where unnecessary abstention is a risk.

Report:
- Error rate among answered questions.
- Answer coverage.
- Unnecessary refusals.
- Latency.
- Cost or provider usage where available.

Do not manufacture accuracy percentages from a small demonstration sample or treat model confidence as measured accuracy.

If a live loop fails to improve a case, preserve that finding and the earlier usable artifact. Do not hide regressions, hand-edit acceptance inputs or claim full fidelity from passing tests alone.

The first acceptance milestone is concrete:

Correct a known reconstruction error, detect an introduced regression, publish a revision without moving the camera, preserve source links through reopening, answer supported drawing and native-IFC questions with appropriate citations/highlights, and refuse an unsupported actual-height question.

The desired improvement is better source fidelity and more dependable answers—not simply agreement between model calls.

COMMITS, REVIEW AND HANDOFF

Create focused commits at suitable verified milestones, as already requested.

Do not push, deploy or alter unrelated worktrees beyond the integration needed for this task. Do not purchase services or provision paid infrastructure.

Run relevant checks after each meaningful change and complete the integrated regression suite at the end.

Route blocking independent-review findings to the responsible implementer, fix them and re-review the affected behavior.

Finish with:
- The implemented flows and their verification evidence.
- Commit identifiers.
- Exact launch instructions and saved demo-building locations.
- A short reproducible demo sequence.
- Live-provider results separated from fixture-based tests.
- Known fidelity gaps, operational limits and unresolved blockers.
- Updated handoff documentation for subsequent agents.

Do not declare completion merely because the architecture exists, agents agree or mocked tests pass. Establish the working integrated experience and report any acceptance criteria that remain unmet.