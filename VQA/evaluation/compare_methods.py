"""Compare the public VQA API and the app Q&A service on four held-out images."""

import argparse
import hashlib
import json
import re
from html import escape
from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory
from time import perf_counter

from dotenv import load_dotenv

from VQA.api import count_objects
from app.documents import DocumentStore
from app.provider import create_provider, settings
from app.service import ask

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "VQA" / "benchmark-runs"
MANIFEST = RUNS / "held-out-4-current" / "manifest.json"
METHODS = ("VQA API", "App Q&A")
NUMBER_WORDS = "zero one two three four five six seven eight nine ten eleven twelve".split()
NUMBER = r"[0-9]+|" + "|".join(NUMBER_WORDS)


def load_cases():
    cases = json.loads(MANIFEST.read_text(encoding="utf-8"))["sample"]
    if len(cases) != 4 or len({case["id"] for case in cases}) != 4:
        raise ValueError("Expected four distinct questions in the held-out manifest.")
    for case in cases:
        # Archived manifests can contain paths from a different checkout.
        relative = str(case["image"]).replace("\\", "/").split("junction-dataset-preview/", 1)[1]
        path = ROOT / "junction-dataset-preview" / relative
        with path.open("rb") as source:
            if hashlib.file_digest(source, "sha256").hexdigest() != case["digest"]:
                raise ValueError(f"Image digest differs from manifest for case {case['id']}.")
        case["image"] = path
    return cases


def app_count(answer):
    if answer.status != "answered":
        return None
    counts = [
        item["value"] for item in answer.calculation_results
        if item.get("operation") == "count" and type(item.get("value")) is int
    ]
    if counts:
        return counts[0] if len(set(counts)) == 1 else None

    # Score an explicit count in the first sentence. Leave ambiguous prose for inspection.
    first = re.split(r"(?<!\d)[.!?](?=\s|$)|\n", answer.answer.replace("*", ""), maxsplit=1)[0]
    matches = re.findall(rf"(?<![\w.,+-])(?:{NUMBER})(?!\w|[.,][0-9])", first.casefold())
    if len(matches) != 1:
        return None
    value = matches[0]
    return int(value) if value.isdecimal() else NUMBER_WORDS.index(value)


def run_vqa(path, question):
    result = count_objects(path, question)
    count = result.count if result.status == "ok" else None
    return result.status, count, result.detail or ""


def run_app(path, question, store):
    document = store.add(path.read_bytes(), path.name)
    provider = create_provider()
    try:
        answer = ask(document, question, provider)
    finally:
        provider.close()
    count = app_count(answer)
    status = "unscored prose" if answer.status == "answered" and count is None else answer.status
    return status, count, answer.answer


def measure(run, *args):
    started = perf_counter()
    try:
        status, count, detail = run(*args)
    except Exception as error:
        status, count, detail = "error", None, type(error).__name__
    return status, count, detail, perf_counter() - started


def write_report(output, cases, results, app_config):
    def row(*cells):
        return "<tr>" + "".join(f"<td>{escape(str(cell))}</td>" for cell in cells) + "</tr>"

    totals = {}
    summary = []
    details = []
    for method in METHODS:
        measured = results[method]
        totals[method] = sum(count == case["expected"] for case, (_, count, _, _) in zip(cases, measured))
        summary.append(row(method, f"{totals[method]}/{len(cases)}",
                           sum(count is None for _, count, _, _ in measured),
                           f"{median(seconds for _, _, _, seconds in measured):.2f}"))
        for case, (status, count, detail, seconds) in zip(cases, measured):
            details.append(row(case["id"], case["question"], case["expected"], method,
                               count if count is not None else "—", status,
                               "Yes" if count == case["expected"] else "No", f"{seconds:.2f}", detail))
    best = max(totals.values())
    leaders = [method for method, total in totals.items() if total == best]
    outcome = f"{leaders[0]} scored more exact matches." if len(leaders) == 1 else "The methods tied on exact matches."
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(f"""<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Counting methods comparison</title>
<style>
body {{ font: 16px system-ui, sans-serif; margin: 2rem auto; padding: 0 1rem; max-width: 80rem; color: #18221e; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border-bottom: 1px solid #d1d9d5; padding: .6rem; text-align: left; vertical-align: top; }}
th {{ background: #edf3ef; }}
.scroll {{ overflow-x: auto; }}
</style>
<h1>Counting methods comparison</h1>
<p>{escape(outcome)}</p>
<p>Four archived held-out raster questions. The app used {escape(app_config)}.
Exact matches use the dataset integer. Missing and unscored counts earn no credit.
For app prose, the scorer reads a single integer or number word from the first sentence.
The per-question table retains the full answer for inspection.</p>
<p>Elapsed time includes the standalone API call or the app document load and Q&amp;A service call.</p>
<table>
<thead><tr><th>Method</th><th>Exact matches</th><th>No scored count</th><th>Median seconds</th></tr></thead>
<tbody>{''.join(summary)}</tbody>
</table>
<h2>Question results</h2>
<div class="scroll"><table>
<thead><tr><th>Case</th><th>Question</th><th>Expected</th><th>Method</th><th>Count</th>
<th>Status</th><th>Exact</th><th>Seconds</th><th>Answer or detail</th></tr></thead>
<tbody>{''.join(details)}</tbody>
</table></div>
</html>
""", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=RUNS / "compare-methods" / "summary.html")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env", override=False)
    config = settings()
    cases = load_cases()
    results = {method: [] for method in METHODS}
    with TemporaryDirectory() as directory:
        store = DocumentStore(Path(directory))
        try:
            for case in cases:
                path, question = case["image"], case["question"]
                for method, run, extra in ((METHODS[0], run_vqa, ()), (METHODS[1], run_app, (store,))):
                    result = measure(run, path, question, *extra)
                    results[method].append(result)
                    print(f"Case {case['id']} | {method} | {result[0]} | {result[3]:.2f} s", flush=True)
        finally:
            store.close()
    write_report(args.output, cases, results, f"{config['label']} / {config['model']}")
    print(args.output.resolve())


if __name__ == "__main__":
    main()
