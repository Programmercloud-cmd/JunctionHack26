"""Paired direct-vision benchmark for Junction quantity questions."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from hashlib import file_digest, sha256
import json
from math import isfinite
from pathlib import Path
from random import Random
from statistics import median
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from time import perf_counter

from dotenv import load_dotenv
from google import genai
from google.genai import types

from app.documents import DocumentError, DocumentStore
from app.ifc_reasoning import extract_native_reasoning
from app.providers.gemini import image_bytes, settings

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATASET = ROOT / "junction-dataset"
MODELS = ("gemini-3.8-flash", "gemini-3.1-pro-preview", "gemini-4-hydrogen")
TRANSPORT_FAILURES = {
    "ConnectError", "ConnectTimeout", "ReadError", "ReadTimeout",
    "RemoteProtocolError", "WriteError", "WriteTimeout",
}
CATEGORIES = ("count", "length", "area")
FORMATS = ("pdf", "ifc", "png")
SCHEMA = {
    "type": "object",
    "properties": {"value": {"type": ["number", "null"]}},
    "required": ["value"],
}


def digest(path):
    with path.open("rb") as file:
        return file_digest(file, "sha256").hexdigest()


def source_for(case, fmt):
    source = Path(case["path"])
    if source.suffix == f".{fmt}":
        return source, "dataset"
    if source.suffix != ".pdf":
        return None
    if case["type"] == "area" and fmt == "png":
        companion = source.with_suffix(".png")
        if (DATASET / companion).is_file():
            return companion, "dataset PNG counterpart"
    if case["type"] == "length":
        if fmt == "png":
            return source, "rendered from dataset PDF"
        if fmt == "ifc" and source.parent.name == "ifc_models":
            parent = source.with_name(source.stem.rsplit("_", 1)[0] + ".ifc")
            if (DATASET / parent).is_file():
                return parent, "parent IFC of dataset floor plan"
    return None


def sample(seed):
    questions = DATASET / "questions.jsonl"
    pools = {(category, fmt): [] for category in CATEGORIES for fmt in FORMATS}
    with questions.open(encoding="utf-8") as file:
        for line, text in enumerate(file, 1):
            row = json.loads(text)
            if row["type"] not in CATEGORIES:
                continue
            for fmt in FORMATS:
                if source := source_for(row, fmt):
                    path, origin = source
                    pools[row["type"], fmt].append((line, row, path, origin))
    rng = Random(seed)
    cases, used = [], set()
    for (category, fmt), pool in pools.items():
        # Keep each original question/path pair at most once in the sample.
        eligible = list({(row["path"], row["question"]): (line, row, path, origin)
                         for line, row, path, origin in pool
                         if (row["path"], row["question"]) not in used}.values())
        for index, (line, row, path, origin) in enumerate(rng.sample(eligible, 3), 1):
            used.add((row["path"], row["question"]))
            cases.append({
                "id": f"{category}-{fmt}-{index}", "line": line, **row,
                "format": fmt, "source_path": path.as_posix(), "source_origin": origin,
                "sha256": digest(DATASET / path),
            })
    return {"seed": seed, "dataset_sha256": digest(questions),
            "pool_sizes": {f"{key[0]}-{key[1]}": len(pool) for key, pool in pools.items()},
            "cases": cases}


def read_ifc(path):
    return extract_native_reasoning(
        path.read_bytes(), SimpleNamespace(derived=False, elements=[], warnings=[]),
    )


def ifc_evidence(native, category):
    relevant = {"length": "IfcWall", "area": "IfcSpace"}.get(category)
    records = []
    for row in native["objects"]:
        if relevant and relevant not in row["type_groups"] and row["ifc_type"] != "IfcBuildingStorey":
            continue
        values = {
            name: [value["value"], value["unit"]]
            for name, value in row["values"].items()
            if value["value"] is not None and isinstance(value["value"], (str, int, float))
            and name not in {"Name", "GlobalId"}
            and (not relevant or any(field in name.casefold() for field in
                 ("length", "area", "number", "longname", "width", "height")))
        }
        if category == "count":
            values = {name: value for name, value in values.items()
                      if name in {"PredefinedType", "ObjectType", "LongName"}}
        records.append([row["id"], row["ifc_type"], row["name"], row["storey_id"], values])
    return json.dumps({
        "format": "IFC semantic records",
        "record_columns": ["global_id", "ifc_type", "name", "storey_global_id", "properties"],
        "property_columns": ["value", "unit"],
        "project_units": native["units"],
        "records": records,
    }, ensure_ascii=False, separators=(",", ":"))


def prepare(cases):
    inputs, ifc_cache = {}, {}
    with TemporaryDirectory() as directory:
        store = DocumentStore(Path(directory))
        try:
            for case in cases:
                path = DATASET / case["source_path"]
                if digest(path) != case["sha256"]:
                    raise ValueError(f"Source changed for {case['id']}")
                try:
                    if case["format"] == "ifc":
                        if path not in ifc_cache:
                            ifc_cache[path] = read_ifc(path)
                        evidence = ifc_evidence(ifc_cache[path], case["type"])
                        case["input_sha256"] = sha256(evidence.encode()).hexdigest()
                        case["input_bytes"] = len(evidence.encode())
                        inputs[case["id"]] = [types.Part.from_text(text=evidence)]
                        print("Prepared", case["id"], case["input_bytes"], flush=True)
                        continue
                    document = store.add(path.read_bytes(), path.name)
                    pages = [image_bytes(page.image()) for page in document.pages]
                    case["input_sha256"] = [sha256(png).hexdigest() for png in pages]
                    case["input_bytes"] = sum(map(len, pages))
                    if case["source_origin"] == "rendered from dataset PDF":
                        target = HERE / "derived"
                        target.mkdir(exist_ok=True)
                        for index, png in enumerate(pages, 1):
                            (target / f"{case['id']}-page-{index}.png").write_bytes(png)
                    inputs[case["id"]] = [
                        types.Part.from_bytes(data=png, mime_type="image/png") for png in pages
                    ]
                except (DocumentError, RuntimeError, ValueError) as error:
                    inputs[case["id"]] = error.message if isinstance(error, DocumentError) else type(error).__name__
                print("Prepared", case["id"], case.get("input_bytes", "source error"), flush=True)
        finally:
            store.close()
    return inputs


def evaluate(client, model, case, parts, attempt, token_budget):
    started = perf_counter()
    result = {"id": case["id"], "model": model, "attempt": attempt, "max_output_tokens": token_budget,
              "status": "error", "value": None}
    try:
        if isinstance(parts, str):
            result.update(status="source_error", detail=parts)
            return result
        prompt = (
            ("Answer the quantity question using the supplied IFC semantic records. " if case["format"] == "ifc"
             else "Answer the quantity question using the supplied drawing pages. ") +
            "For measurements, use dimensions or a supported scale. "
            "Return one numeric value in the requested unit, or null if the drawing "
            "does not establish an answer.\n"
            f"Question: {case['question']}\nRequested unit: {case['unit']}"
        )
        response = client.models.generate_content(
            model=model, contents=[types.Content(role="user", parts=[
                types.Part.from_text(text=prompt), *parts,
            ])],
            config=types.GenerateContentConfig(
                temperature=0, max_output_tokens=token_budget,
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
        if result["finish_reason"] == "FinishReason.MAX_TOKENS":
            result["status"] = "token_limit"
            return result
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
    for result in results:
        if result["status"] == "invalid_output" and result.get("finish_reason") == "FinishReason.MAX_TOKENS":
            result["status"] = "token_limit"
    rows = {case["id"]: case for case in manifest["cases"]}
    summary = [
        "# Junction quantity benchmark", "",
        f"Seed {manifest['seed']}. Three questions per category and input format drawn "
        "from the full Junction dataset, without reusing exact question/path pairs.", "",
        "The dataset has no PNG length or area questions and no IFC length questions. "
        "PNG areas use matched dataset PNGs, PNG lengths use rendered PDF pages, "
        "and IFC lengths use the parent IFC files from which the question PDFs were drawn.", "",
        "All models received identical inputs for each question. PDF and PNG inputs use "
        "app-normalized raster pages resized with the Gemini image helper. IFC inputs "
        "use compact IFC text records with entity types and storey IDs. Length and area "
        "inputs focus on wall and space properties respectively. These records come "
        "from the app's IFC parser, with geometry tessellation disabled. No reference "
        "answers or precomputed aggregates are included in requests. "
        "This measures direct model answers, before the app's sufficiency and answer review. "
        "Counts must match exactly. Lengths and areas allow 2% relative error. "
        "A zero reference requires zero. Abstentions and errors earn no credit. "
        "Transient transport errors were eligible for one retry with identical request "
        "settings and lower concurrency.", "",
        "| Model | Count | Length | Area | Total | Answered | Median request time |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    budget_retries = sum(r.get("max_output_tokens", 8192) > 8192 for r in results)
    if budget_retries:
        summary[6] += (
            f" Reran {budget_retries} 8,192-token exhaustions at a shared 65,536-token "
            "ceiling. Cases that finished within 8,192 tokens kept their existing results. "
            "Scores and latencies use the last attempt for each pair."
        )
    for model in models:
        items = [result for result in results if result["model"] == model]
        scores = [sum(r["correct"] for r in items if rows[r["id"]]["type"] == category)
                  for category in CATEGORIES]
        timings = [r["seconds"] for r in items if r["status"] in {"answered", "abstained", "invalid_output", "token_limit"}]
        timing = f"{median(timings):.2f} s" if timings else "—"
        answered = sum(r["status"] == "answered" for r in items)
        counts = " | ".join(f"{score}/9" for score in scores)
        summary.append(f"| {model} | {counts} | {sum(scores)}/27 | {answered}/27 | {timing} |")
    summary += ["", "## Correct by category and format", "",
                "| Category | Input format | " + " | ".join(models) + " |",
                "| --- | --- |" + " ---: |" * len(models)]
    for category in CATEGORIES:
        for fmt in FORMATS:
            scores = [sum(r["correct"] for r in results if r["model"] == model
                          and rows[r["id"]]["type"] == category and rows[r["id"]]["format"] == fmt)
                      for model in models]
            summary.append(f"| {category} | {fmt.upper()} | " + " | ".join(f"{score}/3" for score in scores) + " |")
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
    parser.add_argument("--seed", type=int, default=20261115)
    parser.add_argument("--sample-only", action="store_true")
    parser.add_argument("--retry-transport", action="store_true")
    parser.add_argument("--retry-token-limit", action="store_true")
    args = parser.parse_args()
    manifest_path = HERE / "manifest.json"
    results_path = HERE / "results.jsonl"
    results = {}
    attempts_by_budget = {}
    resume = args.retry_transport or args.retry_token_limit
    if resume:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for line in results_path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            key = row["id"], row["model"]
            results[key] = row
            budget = row.get("max_output_tokens", 8192)
            attempts_by_budget[key, budget] = attempts_by_budget.get((key, budget), 0) + 1
    else:
        manifest = sample(args.seed)
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.sample_only:
        return
    load_dotenv(ROOT / ".env", override=False)
    config = settings("gemini")
    if not config["api_key"]:
        parser.error("A Gemini API key is required.")
    pending = []
    for case in manifest["cases"]:
        for model in MODELS:
            row = results.get((case["id"], model))
            if row is None:
                pending.append((case, model, 1, 8192))
                continue
            attempt = row.get("attempt", 1)
            budget = row.get("max_output_tokens", 8192)
            transport_retry = (args.retry_transport and row.get("detail") in TRANSPORT_FAILURES
                               and attempts_by_budget.get(((case["id"], model), budget), 0) == 1)
            if transport_retry:
                pending.append((case, model, attempt + 1, budget))
            elif (args.retry_token_limit and row.get("finish_reason") == "FinishReason.MAX_TOKENS"
                  and budget < 65536):
                pending.append((case, model, attempt + 1, 65536))
    pending_ids = {case["id"] for case, _, _, _ in pending}
    sources = [case for case in manifest["cases"] if case["id"] in pending_ids]
    prior_hashes = {case["id"]: case.get("input_sha256") for case in sources}
    inputs = prepare(sources)
    for case in sources:
        prior_hash = prior_hashes[case["id"]]
        if prior_hash and prior_hash != case.get("input_sha256"):
            raise ValueError(f"Input changed for {case['id']}")
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    workers = 3 if resume else 9
    mode = "a" if resume else "w"
    with genai.Client(api_key=config["api_key"], http_options={
        "api_version": "v1beta", "timeout": 180000, "retry_options": {"attempts": 1},
    }) as client, ThreadPoolExecutor(max_workers=workers) as executor, results_path.open(mode, encoding="utf-8") as file:
        futures = [executor.submit(evaluate, client, model, case, inputs[case["id"]], attempt, budget)
                   for case, model, attempt, budget in pending]
        for future in as_completed(futures):
            result = future.result()
            results[result["id"], result["model"]] = result
            file.write(json.dumps(result) + "\n")
            file.flush()
            print(result["id"], result["model"], result["status"], result.get("detail", ""), flush=True)
    ordered = [results[case["id"], model] for case in manifest["cases"] for model in MODELS]
    report(manifest, MODELS, ordered)


if __name__ == "__main__":
    main()
