"""Compare the real Blueprint QA routes on the direct benchmark's fixed sample."""

import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from hashlib import file_digest
import json
import math
import os
from pathlib import Path
import re
import shutil
from tempfile import TemporaryDirectory
from threading import Lock
from time import perf_counter, sleep

from fastapi.testclient import TestClient
from google.genai.errors import APIError
from httpx2 import TransportError

from app.jobs import TERMINAL
from app.main import create_app
from app.providers.gemini import GeminiProvider, settings

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DIRECT = HERE.parent / "junction-quantity-27"
DATASET = ROOT / "junction-dataset"
MODELS = ("gemini-3.8-flash", "gemini-3.1-pro-preview", "gemini-4-hydrogen")
CATEGORIES = ("count", "length", "area")
FORMATS = ("pdf", "ifc", "png")
TOKEN_BUDGET = 65536
GENERATION_SECONDS = 180
QA_SECONDS = 600
EXTRACTION_SECONDS = 420
EXTRACTION_MODEL = "gemini-3.1-pro-preview"
RUN_LOCK = Lock()

# Read only explicit results from reviewed prose. Avoid numeric IFC IDs, evidence
# coordinates, dimensions in explanations, and repeated operand lists.
NUMBER = r"(?<![\w#,])[-+]?\d+(?:[.,]\d+)*(?![\w,°º])"
MEASURES = {
    "m": r"(?:m(?!\s*[²2³3])|met(?:er|re)s?)",
    "m2": r"(?:m\s*(?:2|²|\^2)|square\s+met(?:er|re)s?|sq\.?\s*m|qm|quadratmeter)",
    "ft2": r"(?:ft\s*(?:2|²|\^2)|square\s+(?:feet|foot)|sq\.?\s*ft)",
}
COUNT_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}


def digest(path):
    with path.open("rb") as file:
        return file_digest(file, "sha256").hexdigest()


def record(path, result):
    with RUN_LOCK, path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(result, ensure_ascii=False) + "\n")


class BenchmarkProvider(GeminiProvider):
    """Use the production adapter with explicit isolated evaluation allowances."""

    def __init__(self, model, expected_revision=None, expected_kind=None):
        super().__init__()
        self.model = model
        self.clarification_model = model  # Match the original comparison.
        self.expected_revision = expected_revision
        self.expected_kind = expected_kind
        self.context_check = None
        self.provider_error = None

    def _generate(self, *args, **kwargs):
        if kwargs.get("include_qa_context", True):
            kwargs["max_tokens"] = TOKEN_BUDGET
            kwargs["timeout_ms"] = round(GENERATION_SECONDS * 1000)
        try:
            return super()._generate(*args, **kwargs)
        except (TransportError, APIError) as error:
            self._note_error(error)
            raise

    def _decisions(self, *args, **kwargs):
        try:
            return super()._decisions(*args, **kwargs)
        except (TransportError, APIError) as error:
            self._note_error(error)
            raise

    def _note_error(self, error):
        self.provider_error = {"type": type(error).__name__, "code": getattr(error, "code", None)}

    def resolve_intent(self, document, question):
        data = document.question_context or {}
        prior_turns = len((data.get("conversation_context") or {}).get("messages") or [])
        present = data.get("interpretation") is not None
        valid = (
            document.revision_id == self.expected_revision
            and not prior_turns
            and (
                (self.expected_kind == "ifc" and data.get("source_kind") == "native_ifc" and bool(data.get("catalog")))
                or (self.expected_kind == "drawing" and present and document.interpretation_status == "complete")
            )
        )
        self.context_check = {
            "verified": valid, "revision_id": document.revision_id,
            "source_kind": data.get("source_kind"), "has_saved_interpretation": present,
            "prior_turns": prior_turns, "native_catalog_records": len(data.get("catalog") or []),
            "context_utf8_bytes": len(json.dumps(data, ensure_ascii=False).encode()),
        }
        if not valid:
            raise RuntimeError("Unexpected question context")
        return super().resolve_intent(document, question)


def source_path(case):
    path = DATASET / case["source_path"]
    if digest(path) != case["sha256"]:
        raise ValueError(f"Source hash differs for {case['id']}")
    if case["source_origin"] == "rendered from dataset PDF":
        rendered = sorted((DIRECT / "derived").glob(f"{case['id']}-page-*.png"))
        if len(rendered) != 1 or [digest(p) for p in rendered] != case["input_sha256"]:
            raise ValueError(f"Derived PNG differs for {case['id']}")
        return rendered[0]
    return path


def job_wait(client, identity):
    while True:
        response = client.get(f"/api/jobs/{identity}")
        response.raise_for_status()
        job = response.json()
        if job["status"] in TERMINAL:
            return job
        sleep(2)


def app_metadata(job):
    fields = ("id", "status", "phase", "error_stage", "error_category", "provider_calls", "usage")
    return {name: job[name] for name in fields if name in job}


def upload(client, store, path, previous=None):
    started = perf_counter()
    with path.open("rb") as file:
        response = client.post("/api/documents", files={"file": (path.name, file)})
    result = {"http_status": response.status_code, "upload_sha256": digest(path)}
    if not response.is_success:
        detail = response.json().get("detail", "")
        capacity = next((tag for phrase, tag in (
            ("triangle limit", "ifc_triangle_limit"),
            ("element limit", "ifc_element_limit"),
            ("MiB", "file_size_limit"),
        ) if isinstance(detail, str) and phrase in detail), None)
        return {**result, "status": "upload_rejected", "reason": capacity,
                "seconds": round(perf_counter() - started, 3)}
    initial = response.json()
    building = initial["building_id"]
    extraction_jobs = initial["extraction_jobs"]
    if previous:
        response = client.post(f"/api/buildings/{building}/extraction", json={"retry": True})
        response.raise_for_status()
        extraction_jobs = response.json()["jobs"]
    jobs = [job_wait(client, job["id"]) for job in extraction_jobs]
    current = client.get(f"/api/buildings/{building}")
    current.raise_for_status()
    info = current.json()
    revision = info["revision_id"]
    folder = store / "buildings" / building / "revisions" / revision
    files = {name: digest(folder / name) for name in ("description.json", "reasoning.json")
             if (folder / name).is_file()}
    ready = info["interpretation_status"] == "complete" and "reasoning.json" in files and (
        info["kind"] == "ifc" or "description.json" in files
    ) and all(job["status"] == "complete" for job in jobs)
    return {
        **result, "status": "ready" if ready else "extraction_failed",
        "building_id": building, "revision_id": revision, "kind": info["kind"],
        "interpretation_status": info["interpretation_status"], "saved_files_sha256": files,
        "extraction_jobs": [app_metadata(job) for job in jobs], "attempt": 2 if previous else 1,
        "seconds": round(perf_counter() - started, 3),
    }


def copy_evidence(origin, target, building):
    """Clone saved files without allowing question jobs or chats to cross cases."""
    source = origin / "buildings" / building
    destination = target / "buildings" / building
    shutil.copytree(source, destination, copy_function=os.link, ignore=shutil.ignore_patterns("jobs", "conversation.json"))
    (destination / "jobs").mkdir()
    resources = target / "resources"
    resources.mkdir()
    saved = origin / "resources" / building
    if saved.exists():
        shutil.copytree(saved, resources / building, copy_function=os.link)


def parse_number(text):
    if "," in text and "." not in text:
        chunks = text.split(",")
        text = "".join(chunks) if all(len(chunk) == 3 for chunk in chunks[1:]) else text.replace(",", ".")
    return float(text.replace(",", ""))


def score_value(case, answer):
    if answer["status"] != "answered":
        return None, answer["status"]
    unit = case["unit"]
    aliases = ({"meters", "meter", "metres", "metre", "m"} if unit == "m"
               else {"m2", "square metres", "square meters", "m^2"} if unit == "m2"
               else {"count", "objects", "items"} if unit == "count" else {unit})
    checked = {entry["value"] for entry in answer.get("calculation_results", [])
               if type(entry.get("value")) in {int, float}
               and (entry.get("unit") or "count").casefold().replace("²", "2") in aliases}
    if len(checked) == 1:
        return checked.pop(), "validated_calculation"
    # Consider the leading result line before citations, caveats and derivation steps.
    text = answer["answer"].replace("**", "").replace("~", "").strip()
    first = re.split(r"(?<!\d)[.!?](?=\s|$)|(?<=\d)[.!?](?=\s+[A-Z]|$)|\n", text, maxsplit=1)[0]
    if case["type"] == "count":
        # Items after a colon often enumerate supporting rooms. Strip page,
        # storey and room labels before considering the stated count.
        lead = first.split(":", 1)[0]
        lead = re.sub(
            r"\b(?:page|pagina|sivu(?:n|lla)?|floor\s+plan|level|raum|room|locale)\s+#?\d+(?:[.,]\d+)*",
            "", lead, flags=re.I,
        )
        lead = re.sub(r"\b\d+\.\s*(?:OG|UG|EG|piano|sal|kerros|etage)\b", "", lead, flags=re.I)
        lead = re.sub(r"\bGrundriss\s+\d+\b", "Grundriss", lead, flags=re.I)
        list_of_values = re.findall(NUMBER, lead)
        if not list_of_values:
            list_of_values = [COUNT_WORDS[word] for word in re.findall(r"\b[a-z]+\b", lead.casefold())
                              if word in COUNT_WORDS]
        values = {float(value) if isinstance(value, int) else parse_number(value) for value in list_of_values}
    else:
        measure = MEASURES[unit]
        values = {parse_number(value) for value in re.findall(rf"({NUMBER})\s*{measure}(?!\w)", first, re.I)}
        if not values:
            # Permit a clearly unit-tagged answer split across several lines, but
            # require the full reviewed answer to contain only one stated value.
            values = {parse_number(value) for value in re.findall(rf"({NUMBER})[ \t]*{measure}(?!\w)", text, re.I)}
    return (values.pop(), "reviewed_prose") if len(values) == 1 else (None, "unscored_prose")


def correct(case, value):
    if value is None or not math.isfinite(value):
        return False
    reference = case["answer"]
    return value == reference if case["type"] == "count" else abs(value - reference) <= abs(reference) * .02


def ask_case(case, model, evidence, origin, runtime):
    result = {"id": case["id"], "model": model, "correct": False, "value": None}
    if evidence["status"] != "ready":
        return {**result, "status": evidence["status"]}
    building, revision = evidence["building_id"], evidence["revision_id"]
    providers = []

    def provider_factory():
        provider = BenchmarkProvider(model, revision, evidence["kind"])
        providers.append(provider)
        return provider

    with TemporaryDirectory(prefix=case["id"] + "-", dir=runtime) as location:
        store = Path(location)
        copy_evidence(origin, store, building)
        app = create_app(provider_factory=provider_factory, storage_root=store)
        with TestClient(app) as client:
            started = perf_counter()
            response = client.post("/api/questions", json={
                "document_id": building, "revision_id": revision, "question": case["question"],
            })
            if not response.is_success:
                return {**result, "status": "question_rejected", "http_status": response.status_code}
            job = job_wait(client, response.json()["id"])
        result.update(seconds=round(perf_counter() - started, 3), job=app_metadata(job))
        result["context"] = providers[0].context_check if providers else None
        if providers and providers[0].provider_error:
            result["provider_error"] = providers[0].provider_error
        if job["status"] != "complete":
            return {**result, "status": "question_" + job["status"]}
        answer = job["answer"]
        if answer["answered_revision_id"] != revision or not (result["context"] or {}).get("verified"):
            return {**result, "status": "context_mismatch"}
        value, scored_from = score_value(case, answer)
        return {
            **result, "status": answer["status"], "value": value, "scored_from": scored_from,
            "correct": correct(case, value), "gate": (answer.get("gate") or {}).get("decision"),
            "review": answer.get("review_decision"), "review_passes": answer["review_passes"],
            "source_citations": len(answer["evidence"]), "ifc_citations": len(answer["model_evidence"]),
            "usage": answer["usage"], "answered_revision_id": revision,
            "answer": answer["answer"],
        }


def is_transient_qa(row):
    calls = row.get("job", {}).get("provider_calls", [])
    return (
        row["status"] == "question_failed" and row.get("attempt", 1) == 1 and bool(calls)
        and calls[-1]["outcome"] in {"provider_error", "provider_timeout"}
    )


def is_retryable_extraction(row):
    return (
        row["status"] == "extraction_failed" and row.get("attempt", 1) == 1
        and any(job.get("error_category") in {"provider_timeout", "provider_quota", "provider_failure",
                                                "provider_request", "response_schema", "response_json"}
                or any(call.get("outcome") in {"provider_error", "provider_timeout",
                                              "response_schema_rejected", "response_json_rejected"}
                       for call in job.get("provider_calls", []))
                for job in row.get("extraction_jobs", []))
    )


def read_rows(path):
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def summarize(cases, app, direct, metadata):
    formats = {case["id"]: case for case in cases}
    lines = [
        "# Blueprint QA versus direct Gemini", "",
        "The same 27 questions and input-file mappings were used in both runs. "
        "Each model received the exact original question through the app. Direct requests "
        "also included a unit instruction and returned a numeric JSON field. App answers "
        "used a verified calculation or a single unambiguous value in reviewed prose. "
        "Counts exclude ordinal markers. Counts require an exact match and measurements allow 2% relative error.", "",
        "App requests used the upload route, the persisted completed interpretation "
        "revision or native IFC reasoning, and the background Q&A route with a fresh "
        "conversation for each model and question. Extraction used "
        f"{metadata['extraction_model']} for all three models. {metadata['decision_model']} "
        "handled sufficiency and answer review for all three models. Generation calls "
        f"allowed {metadata['generation_tokens']:,} output tokens. App file-size "
        "limits and evidence review remained in effect. App failures, refusals, and "
        "unscorable answers count as zero, as do direct failures. Transient provider "
        "failures may be retried once in a fresh conversation and the latest result is scored. "
        "Upload schema failures may be retried once through the app extraction endpoint. "
        "Model metadata reported 65,536 as the supported output ceiling for all three.", "",
        "| Model | App count | Direct count | App length | Direct length | App area | Direct area | App total | Direct total |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for model in MODELS:
        cells = [model]
        for category in (*CATEGORIES, "all"):
            ids = [i for i, case in formats.items() if category == "all" or case["type"] == category]
            for run in (app, direct):
                count = sum(bool(run.get((i, model), {}).get("correct")) for i in ids)
                populated = sum((i, model) in run for i in ids)
                cells.append(f"{count}/{len(ids)}" if populated == len(ids) else f"{count} correct, {populated}/{len(ids)} recorded")
        lines.append("| " + " | ".join(cells) + " |")
    population = len(cases) * len(MODELS)
    lines += ["", "## Availability", "",
              f"{len(app)}/{population} app slots and {len(direct)}/{population} direct slots have results.",
              "",
              "| Model | App verified evidence context | App answered | IFC/upload rejected | Extraction failed | Question failed | Direct answered |",
              "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for model in MODELS:
        answers = [row for (_, name), row in app.items() if name == model]
        live = sum(bool((r.get("context") or {}).get("verified")) for r in answers)
        solved = sum(r["status"] == "answered" for r in answers)
        rejects = sum(r["status"] == "upload_rejected" for r in answers)
        extracts = sum(r["status"] == "extraction_failed" for r in answers)
        failures = sum(r["status"].startswith("question_") for r in answers)
        direct_solved = sum(r["status"] == "answered" for (_, name), r in direct.items() if name == model)
        lines.append(f"| {model} | {live} | {solved} | {rejects} | {extracts} | {failures} | {direct_solved} |")
    lines += ["", "The app rejected count-ifc-2 at its IFC triangle limit. "
              "It rejected length-ifc-3 at its 25 MiB upload limit. These slots remain "
              "in the comparison denominator. The app uses a richer IFC catalog "
              "and retrieval context than the direct run's compact IFC records. "
              "All accepted IFC uploads failed at question intent resolution. One "
              "representative replay per accepted IFC source independently returned "
              "Gemini HTTP 400 with the app's 2.32, 5.46 or 5.90 MB context. The exact "
              "server-side cause was unavailable. See diagnostic.jsonl for the probes."]
    lines.extend(["", "## Paired outcomes", "",
                  "| Model | Paired | App only correct | Direct only correct | Both correct | Neither correct | App minus direct | Common completed subset (app vs. direct) |",
                  "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |"])
    judged = {"answered", "abstained", "insufficient", "unclear", "clarification"}
    for model in MODELS:
        pairs = [(app[i, model], direct[i, model]) for i in formats
                 if (i, model) in app and (i, model) in direct]
        outcomes = [(bool(left["correct"]), bool(right["correct"])) for left, right in pairs]
        app_only, direct_only = outcomes.count((True, False)), outcomes.count((False, True))
        shared = [pair for pair in pairs if all(row["status"] in judged for row in pair)]
        shared_app = sum(left["correct"] for left, _ in shared)
        shared_direct = sum(right["correct"] for _, right in shared)
        lines.append(f"| {model} | {len(pairs)} | {app_only} | {direct_only} | "
                     f"{outcomes.count((True, True))} | {outcomes.count((False, False))} | "
                     f"{app_only - direct_only:+d} | {shared_app}/{len(shared)} vs. {shared_direct}/{len(shared)} |")
    lines += ["", "The common completed subset includes cases where both runs returned a model "
              "answer or an evidence/intent abstention. Its membership can differ by model."]
    lines.extend(["", "## Correct by format", "", "| Category | Format | Model | App | Direct |",
                  "| --- | --- | --- | ---: | ---: |"])
    for category in CATEGORIES:
        for fmt in FORMATS:
            ids = [i for i, case in formats.items() if (case["type"], case["format"]) == (category, fmt)]
            for model in MODELS:
                scores = [sum(bool(rr.get((i, model), {}).get("correct")) for i in ids) for rr in (app, direct)]
                lines.append(f"| {category} | {fmt.upper()} | {model} | {scores[0]}/3 | {scores[1]}/3 |")
    lines.extend(["", "## Per-question comparison", "",
                  "| Case | Model | App value | App status | Citations | Direct value | Direct status |",
                  "| --- | --- | ---: | --- | ---: | ---: | --- |"])
    for i in formats:
        for model in MODELS:
            left, right = app.get((i, model), {}), direct.get((i, model), {})
            citations = left.get("source_citations", 0) + left.get("ifc_citations", 0)
            lines.append(f"| {i} | {model} | {left.get('value')} | {left.get('status', 'pending')} | "
                         f"{citations} | {right.get('value')} | {right.get('status', 'pending')} |")
    (HERE / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def extracting_provider():
    provider = GeminiProvider()
    provider.interpretation_model = EXTRACTION_MODEL
    return provider


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-only", action="store_true")
    parser.add_argument("--retry-extraction", action="store_true")
    parser.add_argument("--retry-qa", action="store_true")
    parser.add_argument("--skip-retry-source", action="append", default=[],
                        help="Skip retries for a source path after a confirmed deterministic provider rejection.")
    args = parser.parse_args()
    selected = json.loads((DIRECT / "manifest.json").read_text(encoding="utf-8"))
    cases = selected["cases"]
    configuration = settings("gemini")
    metadata = {
        "direct_dataset_sha256": selected["dataset_sha256"], "seed": selected["seed"],
        "models": MODELS, "extraction_model": EXTRACTION_MODEL,
        "decision_model": configuration["decision_model"], "generation_tokens": TOKEN_BUDGET,
        "qa_generation_seconds": GENERATION_SECONDS, "qa_total_seconds": QA_SECONDS,
        "extraction_call_seconds": EXTRACTION_SECONDS,
    }
    manifest_path = HERE / "manifest.json"
    if args.report_only and manifest_path.is_file():
        metadata = json.loads(manifest_path.read_text(encoding="utf-8"))
    output = HERE / "results.jsonl"
    app_results = {(row["id"], row["model"]): row for row in read_rows(output)}
    upload_path = HERE / "uploads.jsonl"
    uploads = {row["path"]: row for row in read_rows(upload_path)}
    if not args.report_only:
        if not configuration["api_key"]:
            parser.error("Gemini credential is required")
        os.environ["RECONSTRUCTION_MAX_TOKENS"] = str(TOKEN_BUDGET)
        os.environ["RECONSTRUCTION_CALL_SECONDS"] = str(EXTRACTION_SECONDS)
        os.environ["QA_TOTAL_SECONDS"] = str(QA_SECONDS)
        manifest_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        runtime = HERE / ".runtime"
        origin = runtime / "extraction"
        origin.mkdir(parents=True, exist_ok=True)
        sources = {}
        for case in cases:
            path = source_path(case)
            sources.setdefault(path, []).append(case)
        app = create_app(storage_root=origin, provider_factory=extracting_provider)
        with TestClient(app) as client, ThreadPoolExecutor(max_workers=2) as extract_pool, ThreadPoolExecutor(max_workers=2) as qa_pool:
            future_uploads = {}
            future_qa = {}

            def schedule(path, result):
                for case in sources[path]:
                    for model in MODELS:
                        row = app_results.get((case["id"], model))
                        retry_extraction = row and args.retry_extraction and row["status"] == "extraction_failed"
                        retry_qa = (row and args.retry_qa and is_transient_qa(row)
                                    and case["source_path"] not in args.skip_retry_source)
                        if row is None or (result["status"] == "ready" and (retry_extraction or retry_qa)):
                            future = qa_pool.submit(ask_case, case, model, result, origin, runtime)
                            future_qa[future] = (case["id"], model), (2 if row else 1)

            for path in sources:
                key = str(path.relative_to(ROOT))
                previous = uploads.get(key)
                if previous and not (args.retry_extraction and is_retryable_extraction(previous)):
                    schedule(path, previous)
                elif previous:
                    future_uploads[extract_pool.submit(upload, client, origin, path, previous)] = path
                else:
                    future_uploads[extract_pool.submit(upload, client, origin, path)] = path
            while future_uploads or future_qa:
                done, _ = wait(set(future_uploads) | set(future_qa), return_when=FIRST_COMPLETED)
                for future in done:
                    if future in future_uploads:
                        path = future_uploads.pop(future)
                        try:
                            result = future.result()
                        except Exception as error:
                            result = {"status": "upload_harness_error", "detail": type(error).__name__}
                        key = str(path.relative_to(ROOT))
                        record(upload_path, {"path": key, **result})
                        print("upload", sources[path][0]["id"], result["status"], flush=True)
                        schedule(path, result)
                    else:
                        key, attempt = future_qa.pop(future)
                        try:
                            row = future.result()
                        except Exception as error:
                            row = {"id": key[0], "model": key[1], "status": "harness_error",
                                   "detail": type(error).__name__, "correct": False, "value": None}
                        row["attempt"] = attempt
                        app_results[key] = row
                        record(output, row)
                        print("question", row["id"], row["model"], row["status"], flush=True)
    case_index = {case["id"]: case for case in cases}
    reviewed = []
    for row in app_results.values():
        if row["status"] == "answered" and row.get("scored_from") != "validated_calculation":
            case = case_index[row["id"]]
            row["value"], row["scored_from"] = score_value(case, row)
            row["correct"] = correct(case, row["value"])
        reviewed.append(row)
    (HERE / "scored-results.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in reviewed), encoding="utf-8",
    )
    direct_results = {(row["id"], row["model"]): row for row in read_rows(DIRECT / "results.jsonl")}
    summarize(cases, app_results, direct_results, metadata)
    print("App results:", len(app_results), "of", len(cases) * len(MODELS), flush=True)


if __name__ == "__main__":
    main()
