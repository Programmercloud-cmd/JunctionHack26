"""Run the Hydrogen counting benchmark and resume completed cases from JSONL."""

import argparse
import hashlib
import json
import random
from pathlib import Path
from statistics import median, quantiles
from time import perf_counter

from .benchmark_cases import load_cases
from .counting_harnesses import HARNESSES, MODEL, extract, load_key
from .benchmark_report import write_report


def write_json(path, data):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def valid_box(box):
    return (
        isinstance(box, list) and len(box) == 4
        and all(type(value) is int for value in box)
        and 0 <= box[0] < box[2] <= 1000 and 0 <= box[1] < box[3] <= 1000
    )


def valid_inventory(objects):
    return isinstance(objects, list) and all(
        isinstance(item, dict) and item.get("id") == index
        and isinstance(item.get("type"), str) and item["type"].strip()
        and valid_box(item.get("box"))
        for index, item in enumerate(objects, 1)
    )


class Benchmark:
    def __init__(self, output):
        self.output = output
        self.inventory_dir = output / "inventories"
        self.inventory_dir.mkdir(exist_ok=True)
        self.details = []

    def call(self, image, prompt, schema):
        from google import genai
        from google.genai import types

        contents = [prompt]
        if image is not None:
            from mimetypes import guess_type
            contents.insert(0, types.Part.from_bytes(data=image.read_bytes(), mime_type=guess_type(image)[0]))
        config = types.GenerateContentConfig(
            response_mime_type="application/json", response_json_schema=schema,
            media_resolution=types.MediaResolution.MEDIA_RESOLUTION_HIGH if image is not None else None,
        )
        start = perf_counter()
        detail = {"kind": "answer", "tokens": None}
        self.details.append(detail)
        try:
            options = types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=1), timeout=120000)
            with genai.Client(api_key=load_key(), vertexai=False, http_options=options) as client:
                response = client.models.generate_content(model=MODEL, contents=contents, config=config)
            if response.usage_metadata:
                detail["tokens"] = response.usage_metadata.total_token_count
            return json.loads(response.text)
        finally:
            detail["seconds"] = perf_counter() - start

    def inventory(self, image, call):
        path = self.inventory_dir / f"{self.digest}.json"
        if path.is_file():
            objects = json.loads(path.read_text(encoding="utf-8"))
            if not valid_inventory(objects):
                raise ValueError(f"Invalid cached inventory at {path}")
            self.cache_hit = True
            return objects
        start_index = len(self.details)
        try:
            objects = extract(call, image)
            if not valid_inventory(objects):
                raise ValueError("Extraction returned an invalid object inventory.")
            write_json(path, objects)
            return objects
        finally:
            for detail in self.details[start_index:]:
                detail["kind"] = "extraction"

    def run(self, name, case):
        self.details = []
        self.digest = case["digest"]
        self.cache_hit = False
        result = {**case, "harness": name, "model": MODEL, "count": None}
        start = perf_counter()
        try:
            if name == "current":
                self.details.append({"kind": "baseline", "tokens": None})
            prediction = HARNESSES[name](Path(case["image"]), case["question"], self.call, self.inventory)
            if type(prediction.get("count")) is not int or prediction["count"] < 0:
                raise ValueError("Prediction must be a nonnegative integer.")
            result.update(prediction)
        except Exception as error:
            result["error"] = f"{type(error).__name__}: {error}"
        elapsed = perf_counter() - start
        if name == "current":
            self.details[0]["seconds"] = elapsed
        return {
            **result, "seconds": elapsed, "calls": self.details,
            "inventory_cache_hit": self.cache_hit,
        }


def summarize(results, cases, names):
    summary = []
    for name in names:
        rows = [row for row in results if row["harness"] == name]
        valid = [row for row in rows if row["count"] is not None and "error" not in row]
        durations = [row["seconds"] for row in rows]
        calls = [call for row in rows for call in row["calls"]]
        tokens = [call["tokens"] for call in calls if call["tokens"] is not None]
        extractions = [call for call in calls if call["kind"] == "extraction"]
        cache_answers = [row for row in rows if row["inventory_cache_hit"]]
        summary.append({
            "harness": name, "cases": cases, "completed": len(rows),
            "correct": sum(row["count"] == row["expected"] for row in valid),
            "failures_or_missing": cases - len(valid),
            "mae": sum(abs(row["count"] - row["expected"]) for row in valid) / len(valid) if valid else None,
            "median_seconds": median(durations) if durations else None,
            "p95_seconds": quantiles(durations, n=100, method="inclusive")[94] if len(durations) > 1 else next(iter(durations), None),
            "calls_per_completed_case": len(calls) / len(rows) if rows else None,
            "reported_tokens": sum(tokens) if tokens else None,
            "calls_with_tokens": len(tokens),
            "extraction_calls": len(extractions),
            "extraction_seconds": sum(call["seconds"] for call in extractions),
            "extraction_reported_tokens": sum(call["tokens"] or 0 for call in extractions),
            "cached_answers": len(cache_answers),
            "cached_answer_seconds": sum(row["seconds"] for row in cache_answers),
            "cached_answer_reported_tokens": sum(call["tokens"] or 0 for row in cache_answers for call in row["calls"]),
        })
    return sorted(summary, key=lambda row: (
        -row["correct"], row["failures_or_missing"],
        row["median_seconds"] if row["median_seconds"] is not None else float("inf"),
    ))


def main(argv=None):
    package = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions", type=Path, default=package.parent / "junction-dataset" / "questions.jsonl")
    parser.add_argument("--output", type=Path, default=package / "benchmark-runs" / "pilot")
    parser.add_argument("--split", choices=("dev", "held-out"), default="dev")
    parser.add_argument("--harness", choices=(*HARNESSES, "all"), default="direct")
    parser.add_argument("--limit", type=int, required=True)
    parser.add_argument("--seed", type=int, default=71)
    parser.add_argument("--max-calls", type=int, required=True, help="Maximum new model requests for this invocation.")
    parser.add_argument("--retry-errors", action="store_true", help="Retry cases whose last attempt failed.")
    args = parser.parse_args(argv)
    output = args.output.resolve()
    if not output.is_relative_to(package) or args.limit < 1 or args.max_calls < 0:
        parser.error("Choose an output under VQA, a positive limit, and a nonnegative call budget.")
    splits, exclusions = load_cases(args.questions)
    candidates = splits[args.split]
    if args.limit > len(candidates):
        parser.error(f"Only {len(candidates)} cases in {args.split}.")
    sample = random.Random(args.seed).sample(candidates, args.limit)
    settings = {
        "split": args.split, "seed": args.seed, "model": MODEL,
        "questions": str(args.questions.resolve()), "split_counts": {k: len(v) for k, v in splits.items()},
        "exclusions": exclusions, "sample": sample,
    }
    output.mkdir(parents=True, exist_ok=True)
    manifest = output / "manifest.json"
    previous_settings = json.loads(manifest.read_text(encoding="utf-8")) if manifest.exists() else None
    if args.split == "held-out":
        source_files = ("evaluation/counting_harnesses.py", "_recount.py", "evaluation/_single_pass.py", "models/gemini.py")
        settings["candidate_versions"] = {
            name: hashlib.sha256((package / name).read_bytes()).hexdigest() for name in source_files
        }
        if previous_settings and args.max_calls == 0:
            # Offline report regeneration can read historic runs without mixing candidates.
            settings["candidate_versions"] = previous_settings["candidate_versions"]
    if previous_settings is not None and previous_settings != settings:
        parser.error("Settings differ from the existing run. Choose another output directory.")
    write_json(manifest, settings)

    names = list(HARNESSES) if args.harness == "all" else [args.harness]
    log = output / "results.jsonl"
    attempts = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []
    latest = {(row["id"], row["harness"]): row for row in attempts}
    runner = Benchmark(output)
    remaining = args.max_calls
    worst_case_calls = dict(zip(HARNESSES, (1, 1, 2, 3, 2)))
    with log.open("a", encoding="utf-8") as stream:
        for case in sample:
            for name in names:
                key = (case["id"], name)
                previous = latest.get(key)
                if previous and ("error" not in previous or not args.retry_errors):
                    continue
                call_limit = worst_case_calls[name]
                if name == "json-based" and (runner.inventory_dir / f"{case['digest']}.json").is_file():
                    call_limit = 1
                if remaining < call_limit:
                    continue
                row = runner.run(name, case)
                remaining -= len(row["calls"])
                latest[key] = row
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                stream.flush()
                print(f"{case['id']} {name}: {row.get('error') or row['count']}", flush=True)
    results = list(latest.values())
    reported_names = [name for name in HARNESSES if name in names or any(row["harness"] == name for row in results)]
    summary = summarize(results, len(sample), reported_names)
    write_json(output / "summary.json", summary)
    write_report(output / "report.html", sample, results, summary)
    print(output / "report.html")


if __name__ == "__main__":
    main()
