# API contract v1

## Progressive product extension

The active scope and shared contracts are [PRODUCT_SPEC.md](PRODUCT_SPEC.md) and [PRODUCT_PLAN.md](PRODUCT_PLAN.md). Existing source/scene/download routes remain compatible; `/api/ask` remains a synchronous reviewed-answer route. The browser uses these additions:

- Upload returns `building_id`, `revision_id`, monotonic `revision_number`, `review_status`, `has_scene`, `unresolved_views` and `is_new_upload`. Building identity is a SHA-256 of original uploaded bytes. Only genuinely new drawing uploads automatically start a job in the UI; reopening/reuploading does not start inference.
- `GET /api/buildings` returns `{buildings:[document_public]}`. `GET /api/buildings/{id}` returns that public record plus saved jobs, newest first.
- `POST /api/buildings/{id}/reconstruction` accepts `{base_revision_id,mode:"refine"|"reconstruct"}` and returns a job with HTTP202. Genuine native IFC is never automatically reconstructed. Existing usable models require local/source replacement checks before publication; fresh supported sources publish an early preview.
- `POST /api/questions` accepts `{document_id,question,revision_id?,request_id?}` and returns HTTP202 with a revision-pinned job. `GET /api/jobs/{id}` reports persisted progress and, after successful QA, `answer`. `POST /api/jobs/{id}/stop` prevents late publication; an in-flight provider call may still finish.
- Jobs distinguish queued/running/complete/needs_attention/failed/budget_exhausted/stopped/interrupted. API or schema failures never become source insufficiency. A failed correction leaves the usable revision intact.
- `GET /api/buildings/{id}/revisions/{revision}/evidence/{object_id}` returns a faithful native IFC record plus coverage for that exact saved revision, including non-rendered semantic records. Drawing-derived IFC is rejected on this native evidence path and continues to use original page regions.
- Answers add `building_id`, `answered_revision_id`, `display_revision_id`, support-review metadata and source-bound calculation results. Highlights are revalidated after concurrent reconstruction; original citations survive missing mappings.
- Portable artifact v4 preserves exact description, server-owned identities/tombstones and source frames. V2/V3 remain readable. Ordinary bbox changes cannot move frames; supported calibration/orientation changes require explicit evidence-backed updates. Concept proposals never enter these artifacts or reasoning records.

Below is the historical initial API contract; the extension above supersedes temporary-session and pre-review behavior.

Current drawing reconstruction is specified in [RECONSTRUCTION_V3_PLAN.md](RECONSTRUCTION_V3_PLAN.md) and [RECONSTRUCTION_V3_CONTRACT.md](RECONSTRUCTION_V3_CONTRACT.md). These supersede historical single-floor/relative-only restrictions; core evidence and provider invariants remain.

Root owns this contract; agents coordinate before changes. JSON uses snake_case.

The implemented 3D extension is specified in [3D_CONTRACT.md](3D_CONTRACT.md). Upload also accepts uncompressed IFC up to25MiB, with `kind` and `scene_url` fields; health adds `max_ifc_mb:25`. Answers add `highlight_ids` and `model_evidence`; IFC uses source records rather than page images. Existing drawing fields below remain compatible.

## Endpoints
- `GET /api/health`: `{status:"ok",provider_ready:bool,model:str,decision_model:str,limits:{max_upload_mb:10,max_pages:5}}`. Readiness means credentials/config exist, not verified provider access. No secrets.
- `POST /api/documents` multipart `file` (JPG/PNG/PDF, max 10 MiB, max 5 pages; reject larger documents rather than silently truncate). Returns `{document_id,filename,pages:[{page:1,width,height,image_url}],warnings:[]}`. Images are re-encoded PNG, PDF pages rendered. Opaque server-generated IDs; no filesystem paths.
- `GET /api/documents/{id}/pages/{page}` returns preview PNG.
- `POST /api/ask` JSON `{document_id,question}`. Question trimmed, 1–2000 chars. Returns Answer below.
- Standard errors: `{detail:"safe actionable message"}`; validation errors may be FastAPI detail arrays. API failures are 502/503, not insufficiency. Missing documents 404.

## Answer
```
{
  "status": "answered|insufficient|unclear",
  "answer": "human readable factual answer or scoped limitation",
  "evidence": [{"page":1,"bbox":[0.1,0.2,0.4,0.5],"label":"Bedroom label","observation":"MH annotation"}],
  "missing_information": ["Ceiling height"],
  "next_action": "Upload a section drawing with height dimensions.",
  "proposal": null,
  "inspected_pages": [1],
  "gate": {"decision":"sufficient|insufficient|unclear","confidence":0.8},
  "inspection_passes": 1,
  "usage": {"input_tokens":0,"output_tokens":0,"latency_ms":0}
}
```
`bbox` is [left,top,right,bottom], normalized 0–1 in the original displayed page. Validate positive area and page existence. Proposal if present: `{text, basis:"explicit_assumption|reference",reference:null|string}`. No invented reference buildings. Model-generated evidence is an aid to inspection, not a verified detection guarantee. Scores are model signals, not probabilities of factual correctness. `gate.confidence` is nullable.

Health reports `provider` (`gemini`), `provider_label` (`Gemini`), `credential_env` (`GEMINI_API_KEY`), and `gate_kind` (`gemini_decisions`). The model fields report the configured model per stage. `model` is for answers, `interpretation_model` is for upload interpretation, `clarification_model` is for question intent, `reconstruction_model` is for explicit 3D reconstruction, and `decision_model` is for evidence sufficiency and answer review.

## Provider orchestration
One overall Decisions choice on source pages + question. `unclear` allows one bounded targeted second inspection (a real crop/higher-resolution source view), then rerun the same gate with expanded evidence. Do not re-ask identical input and call it inspection. Standard Gemini explains limitations or generates a structured answer against original sources; never turn a negative gate into a factual answer. A positive gate does not force an answer when generation reveals missing evidence. Answer citations must validate; absent/invalid evidence cannot be silently accepted. Operational errors never silently fall back to a different gate/provider. No hidden live mocks or fixtures.

Provider documentation verified 2026-11-14: https://aistudio.google.com/docs/decisions-api ; Python SDK requires >=3.2 for Decisions. REST endpoint https://generativelanguage.googleapis.com/v1beta/decisions. SDK/REST details must be verified, not invented.

Implementation bound: at most two gate calls, one crop-selection call and one answer/explanation call. The crop is appended to the original pages with its original coordinates; it is not a separate source. The answer generator may downgrade a sufficient gate, never promote an insufficient/unclear gate. Arithmetic uses a small internal schema (sum, product, difference, quotient with source-indexed operands); code computes the value. Operand interpretation and unit compatibility still require human inspection. No claim of geometric or semantic verification is implied.
