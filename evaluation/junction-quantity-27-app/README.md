# Blueprint QA app benchmark

The app run uses the fixed 27-case manifest from the adjacent direct benchmark. Generate the direct manifest and its rendered PNGs before starting this runner.

From the repository root, run:

```sh
PYTHONPATH=. .venv/bin/python evaluation/junction-quantity-27-app/benchmark.py
```

The runner uses the real ASGI upload, job, and question routes in an isolated store. It submits questions only after verifying the saved interpretation or native IFC reasoning. Each case and model uses the same saved revision with an empty conversation. The live run requires the app's usual Gemini credential and does not use a running development server. The runner reads reference answers only for local scoring.

`results.jsonl` is the append-only request log. `scored-results.jsonl` contains one final row per model and question, with locale-aware parsing of reviewed prose. `uploads.jsonl` tracks saved revision hashes and terminal upload interpretation jobs. `diagnostic.jsonl`, when present, records separate provider rejection probes. `--report-only` regenerates the comparison from existing evidence without API requests. Results, uploads, and the isolated store are ignored by Git.

The live run used one retry for transient request failures and one retry for selected upload interpretation schema failures. The repeat HTTP 400 probes identified a deterministic failure at intent resolution for each accepted IFC, so these sources were excluded from bulk retries.
