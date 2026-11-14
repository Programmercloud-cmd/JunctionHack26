"""Paired direct-vision benchmark for Junction quantity questions."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from hashlib import file_digest
import json
from math import isfinite
from pathlib import Path
from random import Random
from statistics import median
from tempfile import TemporaryDirectory
from time import perf_counter

from dotenv import load_dotenv
from google import genai
from google.genai import types

from app.documents import DocumentError, DocumentStore
from app.providers.gemini import image_bytes, settings

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATASET = ROOT / "junction-dataset"
CATEGORIES = ("count", "length", "area")
SCHEMA = {
    "type": "object",
    "properties": {"value": {"type": ["number", "null"]}},
    "required": ["value"],
}


def digest(path):
    with path.open("rb") as file:
        return file_digest(file, "sha256").hexdigest()


def sample(seed):
    questions = DATASET / "questions.jsonl"
    pools = {category: [] for category in CATEGORIES}
    with questions.open(encoding="utf-8") as file:
        for line, text in enumerate(file, 1):
            row = json.loads(text)
            if row["type"] in pools:
                pools[row["type"]].append({"line": line, **row})
    rng = Random(seed)
    cases = []
    for category, pool in pools.items():
        for index, row in enumerate(rng.sample(pool, 4), 1):
            cases.append({
                "id": f"{category}-{index}", **row,
                "sha256": digest(DATASET / row["path"]),
            })
    return {"seed": seed, "dataset_sha256": digest(questions),
            "pool_sizes": {key: len(pool) for key, pool in pools.items()}, "cases": cases}


def prepare(cases):
    inputs = {}
    with TemporaryDirectory() as directory:
        store = DocumentStore(Path(directory))
        try:
            for case in cases:
                path = DATASET / case["path"]
                if digest(path) != case["sha256"]:
                    raise ValueError(f"Source changed for {case['id']}")
                try:
                    document = store.add(path.read_bytes(), path.name)
                    if not document.pages:
                        inputs[case["id"]] = "Source has no drawable pages"
                    else:
                        inputs[case["id"]] = [
                            types.Part.from_bytes(data=image_bytes(page.image()), mime_type="image/png")
                            for page in document.pages
                        ]
                except DocumentError as error:
                    inputs[case["id"]] = error.message
        finally:
            store.close()
    return inputs


def evaluate(client, model, case, pages):
    started = perf_counter()
    result = {"id": case["id"], "model": model, "status": "error", "value": None}
    try:
        if isinstance(pages, str):
            result.update(status="source_error", detail=pages)
            return result
        prompt = (
            "Answer the quantity question using the supplied drawing pages. "
            "For measurements, use dimensions or a supported scale. "
            "Return one numeric value in the requested unit, or null if the drawing "
            "does not establish an answer.\n"
            f"Question: {case['question']}\nRequested unit: {case['unit']}"
        )
        response = client.models.generate_content(
            model=model, contents=[types.Content(role="user", parts=[
                types.Part.from_text(text=prompt), *pages,
            ])],
            config=types.GenerateContentConfig(
                temperature=0, max_output_tokens=8192,
                response_mime_type="application/json", response_json_schema=SCHEMA,
            ),
        )
        result["model_version"] = response.model_version
        result["finish_reason"] = str(response.candidates[0].finish_reason) if response.candidates else None
        usage = response.usage_metadata
        if usage:
            result["tokens"] = {
                "input": usage.prompt_token_count, "output": usage.candidates_token_count,
                "thinking": usage.thoughts_token_count,
            }
        value = json.loads(response.text or "")["value"]
        if value is None:
            result["status"] = "abstained"
        elif type(value) in (int, float) and isfinite(value):
            result.update(status="answered", value=value)
        else:
            result["status"] = "invalid_output"
    except genai.errors.APIError as error:
        result.update(status="api_error", detail=f"{error.code} {error.status}")
    except (ValueError, KeyError, TypeError):
        result["status"] = "invalid_output"
    except Exception as error:
        result["detail"] = type(error).__name__
    finally:
        result["seconds"] = round(perf_counter() - started, 3)
        value, expected = result["value"], case["answer"]
        result["correct"] = value is not None and (
            value == expected if case["type"] == "count"
            else abs(value - expected) <= abs(expected) * 0.02
        )
    return result


def report(manifest, models, results):
    rows = {case["id"]: case for case in manifest["cases"]}
    summary = [
        "# Junction quantity benchmark", "",
        f"Seed {manifest['seed']}. Four questions per category sampled uniformly from the "
        "full Junction question file, without replacement within each category.", "",
        "Both models received the same drawing pages, question and requested unit. "
        "App-normalized images were resized using its Gemini image helper. "
        "This measures direct model answers, before the app's sufficiency and answer review. "
        "Counts must match exactly. Lengths and areas allow 2% relative error. "
        "A zero reference requires zero. Abstentions and errors earn no credit.", "",
        "| Model | Count | Length | Area | Total | Answered | Median request time |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for model in models:
        items = [result for result in results if result["model"] == model]
        scores = [sum(r["correct"] for r in items if rows[r["id"]]["type"] == category)
                  for category in CATEGORIES]
        timings = [r["seconds"] for r in items if r["status"] in {"answered", "abstained", "invalid_output"}]
        timing = f"{median(timings):.2f} s" if timings else "—"
        answered = sum(r["status"] == "answered" for r in items)
        counts = " | ".join(f"{score}/4" for score in scores)
        summary.append(f"| {model} | {counts} | {sum(scores)}/12 | {answered}/12 | {timing} |")
    summary += ["", "## Per-question results", "",
                "| Case | Unit | Reference | Model | Prediction | Status | Correct | Seconds |",
                "| --- | --- | ---: | --- | ---: | --- | --- | ---: |"]
    for result in results:
        case = rows[result["id"]]
        value = result["value"] if result["value"] is not None else "—"
        status = result["status"] + (f" ({result['detail']})" if result.get("detail") else "")
        summary.append(
            f"| {case['id']} | {case['unit']} | {case['answer']} | {result['model']} | "
            f"{value} | {status} | {'yes' if result['correct'] else 'no'} | {result['seconds']:.2f} |"
        )
    summary += ["", "See manifest.json for the sampled questions, source paths and hashes, "
                "and results.jsonl for per-call model versions, token counts and finish reasons.", ""]
    (HERE / "report.md").write_text("\n".join(summary), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=20261114)
    parser.add_argument("--sample-only", action="store_true")
    args = parser.parse_args()
    manifest = sample(args.seed)
    (HERE / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.sample_only:
        return
    load_dotenv(ROOT / ".env", override=False)
    config = settings("gemini")
    models = tuple(dict.fromkeys((config["model"], config["reconstruction_model"])))
    if not config["api_key"] or len(models) != 2:
        parser.error("Two distinct Gemini model IDs and a Gemini API key are required.")
    inputs = prepare(manifest["cases"])
    results = []
    with genai.Client(api_key=config["api_key"], http_options={
        "api_version": "v1beta", "timeout": 120000, "retry_options": {"attempts": 1},
    }) as client, ThreadPoolExecutor(max_workers=4) as executor, (HERE / "results.jsonl").open("w", encoding="utf-8") as file:
        futures = [executor.submit(evaluate, client, model, case, inputs[case["id"]])
                   for case in manifest["cases"] for model in models]
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            file.write(json.dumps(result) + "\n")
            file.flush()
            print(result["id"], result["model"], result["status"], result.get("detail", ""), flush=True)
    order = {case["id"]: index for index, case in enumerate(manifest["cases"])}
    results.sort(key=lambda result: (order[result["id"]], models.index(result["model"])))
    report(manifest, models, results)


if __name__ == "__main__":
    main()
