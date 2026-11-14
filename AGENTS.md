# Blueprint QA — hackathon instructions

## Scope
Build a local, lean application: upload JPG/PNG/PDF/SVG/DXF or IFC, ask a construction-plan question, inspect evidence and an interactive Three.js model. Current scope includes explicitly depicted floors via building description → deterministic IfcOpenShell generation → derived IFC → viewer. Read docs/RECONSTRUCTION_V3_PLAN.md and docs/RECONSTRUCTION_V3_CONTRACT.md. V3 uses explicit physical walls, wall-hosted openings, indoor/outdoor spaces, schematic stairs/furnishings/fixtures, source-linked unresolved records and actual-IFC source comparison. Room polygons must never imply enclosure. Defer unseen/invented floors, DWG without a validated converter, Blender/cloud rendering, per-user accounts, database and multi-agent runtime.

The active product specification is docs/PRODUCT_SPEC.md, with independently reviewed checkpoints in docs/PRODUCT_PLAN.md. It adds local filesystem bundles, background reconstruction reviews, reviewed QA and the existing concept renderer; these are now authorized scope. Keep the configurable reconstruction model default; Hydrogen was not adopted.

Current source-first scope is docs/SOURCE_FIRST_SPEC.md with reviewed docs/SOURCE_FIRST_PLAN.md and implemented docs/SOURCE_FIRST_CONTRACT.md. Upload saves originals and extracts interpretation; 3D is explicit. Related drawing sources share revision-pinned provenance, source-linked chat and attributed batch user inputs. Keep native IFC separate from grouped drawing sources until mixed evidence validation exists. Read docs/SOURCE_FIRST_VERIFICATION.md for actual live results and remaining fidelity gaps. Focused commits are authorized; do not push.

Public Verda deployment is authorized through Sunday2026-11-15: one CPU VM, persistent filesystem storage, Gemini and nine cached examples. Read docs/PUBLIC_DEMO_PLAN.md and docs/VERDA_DEPLOYMENT_PLAN.md. Public visitors may inspect exact pinned examples; a shared access code gates uploads, paid QA and other private actions. Shared example source/model revisions remain read-only; authenticated QA remains available against originals. Code holders share one privileged workspace, not isolated accounts. No automatic deletion/top-ups, no GPU, no push. Chat UI is integrated; read docs/CHAT_UI_CONTRACT.md before changing action routing.

## Workflow
- Before introducing self-imposed constraints, explicitly communicate what they restrict, why they are needed, whether they are an external requirement or our design choice, and how they might block valid inputs or the demo. Prefer the smallest justified set for this hackathon. Do not silently introduce arbitrary caps or turn this into a blanket approval bureaucracy.
- Read docs/PLAN.md, docs/CONTRACT.md and docs/HANDOFF.md before changing behavior.
- Setup: `bash scripts/bootstrap.sh`. Run: `bash scripts/dev.sh`. Check: `bash scripts/test.sh`. Diagnose: `.venv/bin/python scripts/doctor.py`. Make targets are optional aliases when make is installed.
- Python 3.12+, FastAPI, plain HTML/CSS/JS, server-side Gemini (final demo) or explicit temporary OpenAI adapter. `AI_PROVIDER=gemini|openai`; default Gemini, never auto-failover. One process; no frontend build tool.
- Dependencies live in requirements.in; requirements.txt is the reproducible resolved lock. Coordinate dependency changes with the orchestrator.
- Use `.venv/bin/python`; do not modify system Python. Local sandbox may fail with bwrap: use approved escalated calls if required.
- Never print or commit `.env*` secrets, uploads, provider request bodies, or dataset answers. `.env.example` contains placeholders only.
- Use injected fake providers for deterministic tests. Never present fixture answers as real inference. API failures are operational errors, not evidence-insufficiency judgments.

## Product invariants
- Remain building-type agnostic: preserve original space labels and meaningful non-residential features. Unknown use gets neutral concept styling and explicit schematic fallbacks, never automatic residential furnishing. Separate floor plans from sections, elevations and site plans; unsupported views/features remain source-linked unresolved records without invented floors. Detailed domes/roofs are out of scope.
- Concept styling/proposals never enter reasoning evidence, source counts or IFC exports. Inspection/concept use the same saved revision. Original sources and usable revisions survive operational failure, stop and restart.
- One overall source-sufficiency gate: sufficient / insufficient / unclear. Inspect original source material, not only a model summary.
- Allow derivations with supported inputs. No invented dimensions as facts; no model confidence advertised as accuracy.
- Unclear gets at most one targeted additional inspection; unresolved stays unclear.
- Drawing answers cite normalized page/region evidence; IFC answers cite inspected GlobalId/property records. Unknown source references fail validation. Unreliable object mappings retain source evidence without highlighting.
- Genuine source IFC counts use the complete semantic catalog, including geometry-less objects. Generated IFC is always drawing-derived, including after reopening: restore original pages, inferred status and assumptions; never run native factual IFC shortcuts on it. Unknown scale uses an explicit context-dependent display unit, not measured metres. Supported calibration does not make assumed heights or generated geometry factual evidence.
- Missing information is scoped to inspected material. Similar-building ideas/defaults are explicitly proposals; never factual evidence about this building.
- Ground-truth questions.jsonl is evaluation-only, never runtime context.
- Gate sufficiency does not establish answer correctness. Check references and calculations; test confident failures too.

## Collaboration
The root agent is the orchestrator and owns architecture, contracts, environment and integration. Delegate bounded tasks to a planner, an independent plan reviewer, backend/frontend implementers, and an independent implementation reviewer. Reviewers must not review their own implementation as the independent review.

1. **Plan:** The planner proposes the smallest hackathon-sized implementation, explicit exclusions, file ownership, dependencies and testable acceptance criteria.
2. **Plan review loop:** The plan reviewer identifies blocking gaps, unnecessary scope and missing checks. The planner revises the plan and responds to each finding; the reviewer checks the revision. Allow at most two review rounds, then the orchestrator resolves remaining disagreements using evidence or scope reduction. Begin dependent implementation only after planning blockers are resolved. Do not reopen settled scope without new evidence or a user-requested change.
3. **Implementation:** Assign backend/frontend work with clear file ownership and a shared contract. Implementers edit only assigned paths, communicate contract changes first, and do not revert another agent's changes. Parallelize independent tasks; coordinate dependencies through the orchestrator.
4. **Implementation review loop:** A read-only reviewer reports actionable findings with file locations, reproduction evidence where possible, and whether each finding blocks acceptance. Route findings to the responsible implementer, apply fixes, run relevant checks, and re-review the affected behavior. Repeat for unresolved blockers; keep optional improvements deferred unless needed for the agreed scope. If a blocker cannot be resolved, report it explicitly rather than declaring completion.
5. **Integration and completion:** The orchestrator verifies the integrated user flow against the acceptance criteria. Stop when those criteria are met, required checks pass, and no blocking findings remain. Agent agreement alone is not evidence of correctness. Record unresolved limitations and verification gaps in the handoff.

Keep review rounds focused on changed behavior and outstanding findings. No commits, pushes or deployment unless requested.

## Definition of done
Working image/PDF upload and source preview, question/answer flow, explicit insufficient/unclear states, visible citations, bounded provider calls, credential-safe errors, useful tests, documented setup and limitations. Live provider claims require a successful live run; otherwise clearly report unverified integration.
