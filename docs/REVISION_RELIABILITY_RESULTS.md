# Revision and refinement reliability verification

Work on `blueprint-qa-isolated`, with local focused commits and no push. Scope and independent review decisions are in [REVISION_RELIABILITY_PLAN.md](REVISION_RELIABILITY_PLAN.md). Verification demonstrates3181 host recovery and34/11397 attributed-height recovery. **Church batch recovery remains incomplete**; strict geometry checks retain its usable partial model. Complete reconstruction fidelity is not established.

## Implementation and evidence boundaries

- Floor metadata has a dedicated typed patch path. Historical destructive whole-floor payloads still reject; metadata edits cannot rewrite nested inventories.
- Recoverable local application errors return safe actionable feedback within the existing correction budget. Additional exact targets require a separately source-grounded authorization decision; proximity and dependency do not grant authority. All ordinary validation and candidate review still run afterward.
- Candidate reviews distinguish requested-change support, new regressions, source conflicts and pre-existing findings. Fresh reviews must explicitly assess `unresolved_delta`; old ambiguous responses are retained but never retroactively accepted. False model decisions are never flipped to true locally.
- Private parsed review responses are saved before local publication gating. Prior findings retain their provenance. Deduplication ignores only the application's repeated provenance prefix, not substantive uncertainty.
- Rejected proposals/candidates retain original sources and the previous usable revision. UI displays recovery decisions and submitted values without implying application. Authorization source links pin the event's own revision.

No provider/model changes, fallback, increased processing budgets, new formats or rendering infrastructure. Existing two correction proposals and overall deadline remain. The UI session's additive intent router is independently owned and coordinates through `/tmp/junction-ui-coordination.md`; it does not replace these pipelines.

## Deterministic and mocked checks

Original3181 unauthorized-target and church destructive-floor responses still reject atomically. Dedicated synthetic regressions cover metadata omission/null/conflict semantics; exact grants and cross-floor/source rejection; tamper-resistant authority; feedback and repeated/no-op stopping; source/identity/XY/height delta checks; conservative prior finding carry; missing/false/ambiguous assessment rejection; and revision-pinned UI evidence.

Browser-inclusive checkpoint after delta-assessment clarification: **644 passed, 1 skipped** in200.92s. Environment doctor passed. The subsequent target-review prompt/payload clarification passed80 focused provider/reliability tests; independent review checks are recorded below. Synthetic tests prove contracts, not live model fidelity.

## Live refinement recovery

Saved immutable descriptions and unchanged originals were reused. These are live candidate reviews, not fresh extraction. Initial34 and11397 reviews returned validSTOP structured responses, supported the requested delta and reported no source conflicts/new regressions, but listed old findings under ambiguous `unresolved`; strict local gating rejected them. Those failures remain saved.

After the required `unresolved_delta` clarification, new live reviews accepted both changes:

| Case | Accepted revision | Review input/output tokens | Active review time | Checks |
|---|---|---:|---:|---|
|34 | `31ca73cc67334b4d99bcba3cded553db` |36,213 /2,585 |33.87s | Attributed1.4relative display height; existing omissions retained. |
|11397 | `d9bf2487d5584894a7854024bd04911c` |29,884 /2,468 |22.07s | Attributed1.6relative display height; existing omissions retained. |

Both preserve stable IDs, exact source references, horizontal geometry, source/display transforms and relative units. Subsequent live source-only foundation-depth questions returned `insufficient`, despite visible extrusions. Source annotations on34 remain facts where actually supplied; this is not a blanket claim that all heights are absent.

Export/reimport, process-lifespan restart and identicalIFC reupload passed for both accepted revisions and the retained3181/church baselines, with **zero provider calls**. Exact original bytes, description, stable IDs, source references, assumptions and attributed values survived. GeneratedIFC reopened as drawing-derived, not native factualIFC. Maximum source-coordinate round-trip error was2.22e-16.

##3181 scope-recovery experiment

The first controlled job replayed the exact historical review and rejected patch, then used live Gemini for correction and target review. The corrector requested12exact additional targets. All12 were denied because the review prompt unconditionally forbade neighboring objects while its payload described the old scope as `listed_existing_ids_only`. The final opening was also called unrequested despite appearing in the explicit request list. The previous revision remained untouched.

This is a confirmed prompt/payload contradiction, not evidence insufficiency. Independently approved clarification distinguishes existing authority from proposed additional authority only in target review. Unrequested/unknown/cross-floor/unsupported targets remain invalid. Historical denials remain immutable. A separate controlled experiment reused the retained live proposal and original review, then obtained fresh live scope and candidate decisions. All12explicit requests were approved after source inspection; the candidate was accepted. Target review took46.12s and candidate review41.30s, bothSTOP. Independent browser/source/IFC review verified nine actual opening-host/void-fill relationships. Seven previously unresolved openings now render; seven fragmented wall IDs were explicitly consolidated, all seven room records/meshes remained unchanged, and six schematic features render. No unrelated correction regression was found. The unchanged bedroom-crossing partition and coarse bathroom/sauna segmentation remain fidelity defects, despite zero unresolved records. The accepted model subsequently passed a live attributed1.4relative-height refinement, source-only foundation refusal, supported QA/follow-up and export/reopen/restart. The initial failed job and denials remain unchanged.

## Church metadata recovery and correct geometry rejection

The first controlled church job replayed the original review and destructive floor replacement, then made one live correction call. Gemini used the new metadata-only bbox operation and separately proposed37nested edits. The metadata contract recovered; the complete geometry batch was rejected because three previously renderable walls lost geometry:

- One replacement polygon extended above the unchanged floor source bounds by about4.94source pixels.
- Another replacement polygon self-intersected.
- A new stair enclosure ambiguously overlapped an unchanged wall over about41.2source pixels.

Actual reopenedIFC confirmed all three losses. These are correct local rejections, not transform bugs; no polygon repair, invented padding, automatic authority or bypass was introduced. The run had exhausted its existing proposals and retained the previous model.

An explicitly offline, unpublished control applied only the saved live metadata operation. It restored the depicted entrance stair, increasing renderable objects34→35 with no losses. All60nested records, IDs, existing meshes, original-page projections and stored frames remained unchanged. This isolates the metadata fix but **does not establish successful live batch recovery**. The full rejected batch also had35meshes overall: aggregate counts would have hidden the losses.

## Unseen blueprint and remaining acceptance

Fresh unchanged `cubicasa5k/high_quality_architectural-10262.png` was selected; it had not been used in prior live verification. Source extraction completed, two supported original-label/loft questions answered with page-region evidence, and a source-only foundation-depth question refused before3D. Geometry review accepted two corrections within the existing budget, retaining findings. A live attributed1.4relative-height change then passed with unchanged IDs/source/XY/transforms and another source-only refusal. Export/reopen/restart passed without inference. Independent browser/IFC review found a material fidelity gap: TUVAN YLÄOSA is rendered as a filled indoor room surface although it denotes upper/open volume. This remains unresolved in interpretation even though no scene records are marked unresolved.

Independent reviewers directly used the browser on retained3181/church: orbit, floor controls, mesh selection, source links and overlays worked withoutJavaScript errors. They observed unresolved openings and an erroneous bedroom-crossing wall on3181, and unresolved hosts/spiral-stair omissions in the church. These gaps are not called fixed. Independent direct-browser review of accepted34,11397,3181 and unseen10262 completed: orbit, floor controls, actual mesh selection, overlays and pinned source links worked without JavaScript errors. User heights were visibly attributed, and source-only refusal responses retained their pinned revisions.11397 also refused an original-only actual clear-ceiling-height question after its1.6relative display input. These checks establish workflow behavior, not full fidelity.

1794's prior extraction timeout is separate; no new1794 inference or limit increase was performed in this pass.

Private diagnostics, response bodies and generated artifacts remain outside commits under `/tmp/revision-reliability/` and ignored `.runtime/revision-reliability*`. No credentials, raw provider requests, uploads or dataset reference answers are committed.


## Final bounded church correction experiment

The correction loop now returns completed, same-ID renderable→unresolved losses as actionable feedback only when an existing proposal remains. Mixed missing-object/frame failures, provider/reopen failures and initial enrichment/refinement paths retain their terminal behavior. Private rejected artifacts, strict authority and all candidate guards remain; no extra attempt or silent partial application is introduced. Independent19recovery tests verified this branch; a legacy fake-provider signature was updated to accept the existing feedback keyword.

A fresh live church review/correction run reused its original saved description, with no provider replay or re-extraction. Its first proposal lost seven previously renderable objects. Exact local feedback reached the second allowed proposal, which reduced losses to three but still failed. Both candidates were retained privately, no new geometry revision published, and the usable baseline survived. Aggregate usage was92,482input and92,202output tokens. This is demonstrated bounded recovery feedback and correct rejection, **not successful church geometry recovery**. No further blind retry was made. Its separately accepted attributed height and source-only refusals still pass.

The preserved gallery church example therefore remains partial. The metadata-only offline control proves that the requested bbox operation itself can restore the entrance stair without unrelated changes; it does not justify publishing either invalid complete proposal.
