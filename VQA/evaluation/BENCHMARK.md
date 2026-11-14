# Blueprint counting benchmark

Run `python -m VQA.evaluation.evaluate_harnesses` from the project directory to
evaluate all five harnesses on 25 held-out questions without arguments. Edit
`evaluate_harnesses.py` to change its settings. The runner writes to
`VQA/benchmark-runs/held-out-25-current/` and resumes completed cases there.

Run `python -m VQA.evaluation.evaluate_models` to compare providers and models
using the public counting API. It shows accuracy, per-question timing, and
median and total latency per model, including failed attempts.

From the directory that contains `VQA`, run:

```bash
python -m VQA.evaluation.benchmark --questions junction-dataset-preview/questions.jsonl --split held-out --harness all --limit 10 --max-calls 0 --output VQA/benchmark-runs/held-out-unfiltered
```

The command is headless. It uses the Gemini credential from the environment or the project's existing local `.env`. It sends the selected raster blueprints to Gemini Hydrogen. Direct count is the default. Use `--harness all` to compare all five or select `current`, `direct`, `inventory-then-count`, `independent-recount`, or `json-based`. Use a fresh output directory for a changed sample or dataset. Reuse the same directory, split, seed, limit, and dataset to resume. The call cap is per invocation. Use `--max-calls 0` to rebuild the report from recorded results without inference.

## Cases and scoring

The default input is `junction-dataset/questions.jsonl`. Eligible rows have `type: count`, a PNG or JPEG file that Pillow verifies, and a nonnegative integer label. The benchmark accepts every question wording, including counts of floors.

SHA-256 groups byte-identical images across questions. The first eight hex digits modulo five assign images to the held-out split when the remainder is zero and to development otherwise. The seeded sample draws rows without replacement from the requested split. Labels are used only for scoring and reporting.

The default dataset has 68,576 eligible development rows across 3,827 images and 16,938 held-out rows across 941 images. The loader excludes 15,281 other task rows and 26,249 count rows with unsupported file types.

Exact integer matches determine the ranking, with failures and missing answers counted as incorrect. Ties use fewer failures or missing answers, then lower median latency. Mean absolute error uses valid answers. Token totals reflect calls whose usage was available. The current VQA adapter does not expose token usage.

## Files

- `counting_harnesses.py` holds the five strategies.
- `benchmark_cases.py` loads and splits the dataset.
- `benchmark.py` runs, persists, and scores the benchmark.
- `benchmark_report.py` renders the self-contained HTML report.
- Each run contains `manifest.json`, `results.jsonl`, `summary.json`, and `report.html`. Reusable JSON inventories live in the run's `inventories/` directory and are keyed by image digest.

The report compares available boxes using greedy one-to-one matching at intersection over union ≥ 0.5. It processes highest IoU pairs first and breaks ties by box order. IoU ≥ 0.8 within a prediction flags potential duplicates. These measurements compare model outputs. JSONL expected counts are the accuracy labels.

## Coverage and verification

The live development pilot reads `junction-dataset-preview/questions.jsonl`. Its output is in `benchmark-runs/live-pilot/`. The live pilot used the old eligibility rule. With the current rule, the preview contains 3,428 eligible development rows and 842 held-out rows. Run the new held-out sample with:

```bash
python -m VQA.evaluation.benchmark --questions junction-dataset-preview/questions.jsonl --split held-out --harness all --limit 10 --max-calls 0 --output VQA/benchmark-runs/held-out-unfiltered
```

Use `--retry-errors` to explicitly retry failed attempts. Successful predictions are reused. The held-out manifest records source hashes for the candidates so changed implementations cannot silently join an existing run.

The mocked smoke test exercised 50 case/harness pairs on the preview held-out sample and verified that a second question on the same image reused its cached inventory. Those results are synthetic and are excluded from model rankings.

The optional IfcOpenShell experiment preserves instance IDs, types, and raster coordinates as IFC properties. It was verified on ten live-extracted instances. It does not generate geometric IFC solids or participate in the benchmark.

```bash
python -m VQA.evaluation.inventory_ifc path/to/inventory.json VQA/benchmark-runs/ifc-experiment
```

### Live development pilot results

All ten case/harness pairs completed using 17 model requests. These development scores use the earlier eligibility rule.

| Harness | Exact matches | Failures | Median seconds | Calls per case |
|---|---:|---:|---:|---:|
| Direct | 1/2 | 0 | 8.9 | 1.0 |
| Current VQA | 1/2 | 0 | 18.4 | 1.0 |
| Inventory then count | 1/2 | 0 | 19.7 | 2.0 |
| Independent recount | 1/2 | 0 | 44.0 | 2.5 |
| JSON-based count | 0/2 | 0 | 38.2 | 2.0 |

The live pilot HTML was rendered in Chrome to verify the shared image framing and box alignment.

### Live held-out results with all count wordings

| Harness | Exact matches | Failures | Median seconds |
|---|---:|---:|---:|
| Independent recount | 10/10 | 0 | 15.52 |
| Current VQA | 9/10 | 0 | 6.91 |
| Inventory then count | 9/10 | 0 | 12.64 |
| Direct | 8/10 | 0 | 4.46 |
| JSON-based count | 7/10 | 0 | 21.28 |

The run completed 50 comparisons using 81 model calls. The ten-question sample contained ten distinct images, so the live JSON strategy recorded extraction costs without any cache hits. Cache reuse was verified in the mocked smoke run. Independent recount led the ten-question run. The sample is too small to establish a broad accuracy advantage.

### Expanded live held-out comparison

The seed-71 sample was extended to 25 questions across 18 images. The first ten
questions and their saved results were reused. The additional 15 questions used
114 model calls. The JSON harness reused its inventory for seven questions.

| Harness | Exact matches | Failures | Median seconds |
|---|---:|---:|---:|
| Direct | 21/25 | 0 | 4.00 |
| Independent recount | 21/25 | 0 | 13.82 |
| Current VQA | 20/25 | 0 | 6.54 |
| Inventory then count | 20/25 | 0 | 12.17 |
| JSON-based count | 11/25 | 0 | 18.68 |

Direct count is the default based on the latency tiebreaker. To rebuild
the archived expanded comparison from the directory containing VQA:

```bash
python -m VQA.evaluation.benchmark --questions junction-dataset-preview/questions.jsonl --split held-out --harness all --limit 25 --max-calls 0 --output VQA/benchmark-runs/held-out-25
```

Evaluation code lives in `VQA/evaluation/`. Existing report URLs remain under `VQA/benchmark-runs/`. For a live run after the move, use a new output directory to record the current source hashes.
