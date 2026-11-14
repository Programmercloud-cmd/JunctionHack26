# Blueprint questions

Ask a question about one PNG, JPEG, PDF, or IFC file. The backend returns JSON with the answer, units, and source evidence.

## Run locally

```bash
python -m pip install -r backend/requirements.txt
```

For Gemini and Verda, copy `backend/api_key.example.json` to `backend/api_key.json` and fill in the `gemini` and `verda` entries for the providers you use. Git ignores the local file. `GEMINI_API_KEY` and `VERDA_INFERENCE_API_KEY` take precedence over the file.

### Count objects in one file

Set `QUESTION_INDEX` in `backend/count_objects.py` to select a row from the count questions in `junction-dataset-preview/questions.jsonl`. The index starts at zero and follows the dataset order after filtering for `"type": "count"`. Select a question with a PNG or PDF. Set `PROVIDER` to `"gemini"`, `"kimi"`, or `"qwen"`. With `MODEL = None`, the script uses [Gemini 3.5 Flash-Lite](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite) for Gemini and the configured defaults for Kimi and Qwen. Set `MODEL` to a model ID to override that choice.

```bash
python backend/count_objects.py
```

The script prints one integer on success, opens a Matplotlib figure with the question, correct answer, model answer, and model name, and writes `reasoning.txt` in the current directory. Without an interactive display, it saves the figure to `count_result.png`. On inference failure it exits with a nonzero status, leaves stdout empty, and records the error in `reasoning.txt`.

### Gemini (default)

Set `GEMINI_API_KEY` or use the `gemini` entry in `backend/api_key.json`. The legacy `backend/.gemini_api_key` file still works as a fallback. The answer CLI defaults to [Gemini 4 Carbon](https://aistudio.google.com/docs/models/gemini-4-carbon) (`gemini-4-carbon`).

```bash
python backend/answer_blueprint.py --provider gemini \
  junction-dataset-preview/data/cubicasa5k/colorful-11397.png \
  -q "How many windows are shown?" --type count
```

### Kimi on Verda

Enable `kimi-k3-1-pro` in your Verda project and set `VERDA_INFERENCE_API_KEY` or use the `verda` entry in `backend/api_key.json`. The adapter uses `https://inference.verda.com/v1`. [Verda quickstart](https://docs.verda.com/inference/quickstart/)

If the runner reports a Cloudflare access page or error 1010, Verda's edge is rejecting the request before inference. Send Verda support the timestamp and Ray ID when shown. The runner stops the batch on this error.

```bash
python backend/answer_blueprint.py --provider kimi \
  junction-dataset-preview/data/cubicasa5k/colorful-11397.png \
  -q "How many windows are shown?" --type count
```

### Local Qwen

Qwen runs inside the Python process on an NVIDIA GPU. First install a CUDA-enabled PyTorch build and its matching torchvision build, then install the optional Qwen dependencies. [PyTorch installation guide](https://pytorch.org/get-started/locally/)

```bash
python -m pip install -r backend/requirements-qwen.txt
python backend/test.py --provider qwen --category count
```

Run the backend with the same Python interpreter where you installed the Qwen dependencies. For an existing workspace environment at `backend/.qwen-cache/venv`, use:

```bash
backend/.qwen-cache/venv/bin/python backend/test.py --provider qwen --category count
```

The default is a [4-bit Qwen3-VL-4B checkpoint](https://huggingface.co/unsloth/Qwen3-VL-4B-Instruct-bnb-4bit) of roughly 3.5 GB. It leaves GPU memory for image processing on 8 GB cards. The first run downloads missing files into the ignored `backend/.qwen-cache/` directory. Later runs reuse the files, and a batch loads the model once. Qwen requires no inference server or provider API key.

Set `QWEN_CACHE_DIR` to choose a different cache, or `QWEN_LOCAL_FILES_ONLY=1` to require cached weights. Use `--model` or `QWEN_MODEL` with a Qwen3-VL Hugging Face model ID or a local checkpoint directory. For a fine-tuned model, use the directory containing the merged safetensors checkpoint and processor files. If GPU memory is tight, close other GPU applications or use a smaller Qwen3-VL checkpoint.

If the initial Hugging Face transfer stalls, rerun the command with `HF_HUB_DISABLE_XET=1` to use the HTTPS downloader.

### Debugging and input limits

`python backend/test.py` runs Gemini, Kimi, and Qwen on the same cases and saves separate reports under `output/blueprint-debug-*/{gemini,kimi,qwen}/index.html`. A provider failure stays in its own report and the other providers still run. Live requests to Gemini and Kimi may incur charges.

Edit `PROVIDER` and the `MODELS` mapping in `backend/test.py` to change the defaults. A `None` model entry uses that provider's default. Select one provider to use a CLI `--model` override.

Both commands support `--model` as an override for the selected provider. For example:

```bash
python backend/test.py --provider qwen --model /path/to/local/qwen-checkpoint --category count
python -m unittest discover -s tests
```

Omit `--category` to run all examples. The runner prints the provider, model, and report path, and saves plots under `output/`. The unit tests use mocks and do not send API requests.

Gemini receives the original PDF. Kimi and Qwen receive numbered PNG renders of every page and an excerpt of the extracted text, while all extracted lines remain available for local citation checks. Drawings and combined generated images are limited to 14 MB before provider-specific processing. PDF rendering for Kimi and Qwen is limited to eight pages per request. Verda may impose a lower image limit. Split larger PDFs or use Gemini's native PDF path. IFC files stay local with every provider.

## Where to look

| Path | Responsibility |
| --- | --- |
| `backend/answering.py` | Validates inputs and routes questions by file format. |
| `backend/providers.py` | Selects the provider, captures debug traces, and validates structured responses. |
| `backend/gemini.py`, `backend/openai_compatible.py`, `backend/qwen.py` | Run Gemini and Kimi requests or Qwen inference on the local GPU. |
| `backend/evidence/` | Extracts and checks drawing evidence, reads PDF text, and executes IFC queries locally. |
| `backend/question_types/` | Holds instructions and evidence rules for lengths, areas, counts, and other questions. |
| `backend/visualizations.py`, `backend/overlays.py` | Produce the Matplotlib summaries and numbered evidence overlays. |
| `backend/debug/` | Holds sample questions and builds the terminal and HTML debug reports. |

For drawings, the selected provider returns observations and Python validates the evidence and computes numeric answers. For IFC, the provider returns a query and Python applies it to the local model. Debug plots and overlays are generated from the result after the answer is assembled.
