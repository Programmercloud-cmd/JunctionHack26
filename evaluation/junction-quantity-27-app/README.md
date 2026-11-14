# Historical Blueprint QA app evaluation

This archive contains the completed 27-case comparison. The current counting benchmark is documented in the [project README](../../README.md#counting-benchmark).

The archived run used the real ASGI upload, job, and question routes in an isolated store. It submitted questions only after verifying the saved interpretation or native IFC reasoning. Each case and model uses the same saved revision with an empty conversation. The live run used the app's usual Gemini credential and did not use a running development server. The archived run read reference answers only for local scoring.

`results.jsonl` is the append-only request log. `scored-results.jsonl` contains one final row per model and question, with locale-aware parsing of reviewed prose. `uploads.jsonl` tracks saved revision hashes and terminal upload interpretation jobs. `diagnostic.jsonl`, when present, records separate provider rejection probes. Results, uploads, and the isolated store are ignored by Git.

The live run used one retry for transient request failures and one retry for selected upload interpretation schema failures. The repeat HTTP 400 probes identified a deterministic failure at intent resolution for each accepted IFC, so these sources were excluded from bulk retries.
