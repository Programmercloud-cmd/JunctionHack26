# API contract v1

Current drawing reconstruction is specified in [RECONSTRUCTION_V2_PLAN.md](RECONSTRUCTION_V2_PLAN.md) and [RECONSTRUCTION_V2_CONTRACT.md](RECONSTRUCTION_V2_CONTRACT.md). These supersede historical single-floor/relative-only restrictions; core evidence and provider invariants remain.

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
`bbox` is [left,top,right,bottom], normalized 0–1 in the original displayed page. Validate positive area and page existence. Proposal if present: `{text, basis:"explicit_assumption|reference",reference:null|string}`. No invented reference buildings. Model-generated evidence is an aid to inspection, not a verified detection guarantee. Scores are model signals, not probabilities of factual correctness. `gate.confidence` is nullable: OpenAI's temporary structured classification returns null instead of inventing a confidence score.

Provider selection: `AI_PROVIDER=gemini|openai`, default gemini. Health additionally returns `provider`, `provider_label`, `credential_env`, `gate_kind` (`gemini_decisions|structured_classification`). For OpenAI, `decision_model` is the same configured `OPENAI_MODEL` used to generate the three-way classification. Missing/invalid configuration fails explicitly; no automatic fallback. The final demo must select Gemini.

## Provider orchestration
One overall Decisions choice on source pages + question. `unclear` allows one bounded targeted second inspection (a real crop/higher-resolution source view), then rerun the same gate with expanded evidence. Do not re-ask identical input and call it inspection. Standard Gemini explains limitations or generates a structured answer against original sources; never turn a negative gate into a factual answer. A positive gate does not force an answer when generation reveals missing evidence. Answer citations must validate; absent/invalid evidence cannot be silently accepted. Operational errors never silently fall back to a different gate/provider. No hidden live mocks or fixtures.

Provider documentation verified 2026-11-14: https://aistudio.google.com/docs/decisions-api ; Python SDK requires >=3.2 for Decisions. REST endpoint https://generativelanguage.googleapis.com/v1beta/decisions. Latest selected stable answer model: gemini-3.8-flash, configurable. SDK/REST details must be verified, not invented.

Implementation bound: at most two gate calls, one crop-selection call and one answer/explanation call. The crop is appended to the original pages with its original coordinates; it is not a separate source. The answer generator may downgrade a sufficient gate, never promote an insufficient/unclear gate. Arithmetic uses a small internal schema (sum, product, difference, quotient with source-indexed operands); code computes the value. Operand interpretation and unit compatibility still require human inspection. No claim of geometric or semantic verification is implied.


## Optional voice interaction

[VOICE_CONTRACT.md](VOICE_CONTRACT.md) defines Gemini Live transcription, document-specific vocabulary and ElevenLabs speech. Voice adapts text input/output; the existing Ask/evidence contract is unchanged.

`/api/ask` additionally returns optional `spoken_answer` and `spoken_answer_with_details` presentation strings. They are derived after answer validation; original `answer`, evidence and highlights remain unchanged. Explicit null indicates unavailable speech preparation.
