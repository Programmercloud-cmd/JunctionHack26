# First slice

Current drawing reconstruction is specified in [RECONSTRUCTION_V3_PLAN.md](RECONSTRUCTION_V3_PLAN.md) and [RECONSTRUCTION_V3_CONTRACT.md](RECONSTRUCTION_V3_CONTRACT.md). These supersede historical single-floor/relative-only restrictions; core evidence and provider invariants remain.

Historical initial slice. The user's later 3D request is implemented under [3D_PLAN.md](3D_PLAN.md) and [3D_CONTRACT.md](3D_CONTRACT.md); those supersede the CAD/3D exclusions below. Core provider and evidence rules remain in force.

Local-first single-process app. JPG/PNG and small PDFs are mandatory. FastAPI serves static UI and API. Render PDF pages with PDFium and send the rendered source images to Gemini/Decisions; always identify inspected pages. Persist bounded uploads only in ignored local runtime storage. No reference-building retrieval, CAD, 3D, auth, streaming, hosting or infrastructure expansion.

Authorized development exception: select the temporary OpenAI Responses adapter via AI_PROVIDER=openai while Gemini access is pending. It uses one structured sufficiency classification without a confidence score. The final sponsor demo uses AI_PROVIDER=gemini and native Gemini Decisions. All evidence and retry rules are shared; no automatic failover.

1. Bootstrap environment and establish API contract.
2. Independent plan/reliability review.
3. Backend: upload normalization, provenance, Gemini provider adapter, one sufficiency decision, one bounded unclear inspection, evidence-linked structured answers.
4. Frontend: source viewer, upload, ask, status, result/citation highlighting and clear operational errors.
5. Integration and independent implementation review; meaningful tests for unsupported answers, unclear handling, missing credentials, bad uploads, citation bounds and API failures.
6. Document and run the local workflow; live Gemini smoke test only when a Gemini credential is configured. No substitute provider without agreement.

The initial evidence gate is an experiment, not a correctness guarantee. Evaluate against standard Gemini using coverage, error among answered questions, unsupported answers, unnecessary abstention, latency and usage. Synthetic fixtures verify control flow, not model quality.
