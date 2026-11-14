"""Time real Blueprint QA requests on a shared random sample of Junction drawings."""

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from hashlib import file_digest, sha256
import json
from pathlib import Path
from random import Random
import shutil
from statistics import mean, median
from tempfile import TemporaryDirectory
from threading import Lock
from time import monotonic, perf_counter, sleep

from fastapi.testclient import TestClient
from google.genai.errors import APIError
from httpx2 import TransportError

from app.documents import MAX_UPLOAD, DocumentError, DocumentStore
from app.jobs import TERMINAL
from app.main import create_app
from app.providers.gemini import GeminiProvider, configured_number, settings

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATASET = ROOT / "junction-dataset"
MODELS = ("gemini-4-hydrogen", "gemini-4-carbon", "gemini-3.8-flash", "gemini-3.1-pro-preview")
EXTRACTION_MODEL = "gemini-3.8-flash"
SAMPLE_SIZE = 10
SEED = 2026111401
POLL_SECONDS = 0.4
WORKERS = 2
LOCK = Lock()
BENIGN_STATUSES = {"answered", "insufficient", "unclear", "clarification"}


def digest(path):
    with path.open("rb") as file:
        return file_digest(file, "sha256").hexdigest()


def json_digest(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def append(path, row):
    with LOCK, path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(row, ensure_ascii=False) + "\n")


def latest(path, key):
    if not path.exists():
        return {}
    return {key(row): row for line in path.read_text(encoding="utf-8").splitlines() if (row := json.loads(line))}


def sample():
    question_file = DATASET / "questions.jsonl"
    rng = Random(SEED)
    pool, excluded = {}, Counter()
    with question_file.open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            row = json.loads(line)
            path, question = row["path"], row["question"]
            if Path(path).suffix.lower() not in {".pdf", ".png"}:
                excluded["non_pdf_png"] += 1
                continue
            if not isinstance(question, str) or not 1 <= len(question.strip()) <= 2000:
                excluded["invalid_question_length"] += 1
                continue
            if (path, question) in pool:
                excluded["duplicate_question_and_path"] += 1
                continue
            pool[path, question] = {"line": number, "path": path, "question": question, "type": row.get("type")}
    candidates = list(pool.values())
    rng.shuffle(candidates)
    cases, preflight_rejected = [], []
    with TemporaryDirectory(prefix="qa-latency-preflight-") as directory:
        document_store = DocumentStore(Path(directory))
        for row in candidates:
            path = DATASET / row["path"]
            size = path.stat().st_size if path.is_file() else None
            if size is None or size == 0 or size > MAX_UPLOAD:
                preflight_rejected.append({"line": row["line"], "reason": "missing_empty_or_oversize"})
                continue
            try:
                source = document_store.add(path.read_bytes(), path.name)
                if source.kind != "drawing" or not source.pages:
                    preflight_rejected.append({"line": row["line"], "reason": "no_original_pages"})
                    continue
            except DocumentError as error:
                preflight_rejected.append({"line": row["line"], "reason": "document_rejected", "http_status": error.status})
                continue
            order = list(MODELS)
            rng.shuffle(order)
            cases.append({
                **row, "id": f"random-{len(cases)+1:02d}", "source_sha256": digest(path),
                "format": path.suffix.lower()[1:], "pages": len(source.pages), "model_order": order,
            })
            if len(cases) == SAMPLE_SIZE:
                break
    if len(cases) != SAMPLE_SIZE:
        raise RuntimeError("Too few eligible drawings for the requested sample")
    configuration = settings("gemini")
    return {
        "seed": SEED, "question_file_sha256": digest(question_file), "rows_in_initial_pool": len(pool),
        "excluded_before_preflight": dict(excluded), "preflight_rejected": preflight_rejected, "cases": cases,
        "extraction_model": EXTRACTION_MODEL, "decision_model": configuration["decision_model"],
        "qa_total_seconds": configured_number("QA_TOTAL_SECONDS", 180),
        "qa_draft_seconds": configured_number("GEMINI_DRAFT_SECONDS", 90),
        "workers": WORKERS, "poll_seconds": POLL_SECONDS,
        "adapter_sha256": digest(ROOT / "app" / "providers" / "gemini.py"),
    }


class TimingProvider(GeminiProvider):
    def __init__(self, model, revision, pages):
        super().__init__()
        self.model = model
        self.clarification_model = model  # Match the original latency experiment.
        self.expected_revision = revision
        self.expected_pages = pages
        self.context = None
        self.provider_error = None

    def resolve_intent(self, document, question):
        data = document.question_context or {}
        current_pages = [digest(page.path) for page in document.pages]
        prior_turns = len((data.get("conversation_context") or {}).get("messages") or [])
        interpretation = data.get("interpretation")
        verified = (
            document.revision_id == self.expected_revision and document.interpretation_status == "complete"
            and interpretation is not None and not prior_turns and bool(current_pages)
            and current_pages == self.expected_pages
        )
        self.context = {
            "verified": verified, "revision_id": document.revision_id, "page_sha256": current_pages,
            "prior_turns": prior_turns, "interpretation_sha256": json_digest(interpretation),
        }
        if not verified:
            raise RuntimeError("Question did not receive the source revision with fresh conversation")
        return super().resolve_intent(document, question)

    def _generate(self, *args, **kwargs):
        try:
            return super()._generate(*args, **kwargs)
        except (TransportError, APIError) as error:
            self.provider_error = {"type": type(error).__name__, "status": getattr(error, "code", None)}
            raise

    def _decisions(self, *args, **kwargs):
        try:
            return super()._decisions(*args, **kwargs)
        except (TransportError, APIError) as error:
            self.provider_error = {"type": type(error).__name__, "status": getattr(error, "code", None)}
            raise


def extracting_provider():
    provider = GeminiProvider()
    provider.interpretation_model = EXTRACTION_MODEL
    return provider


def wait_job(client, identity, window):
    deadline = monotonic() + window
    while monotonic() < deadline:
        response = client.get(f"/api/jobs/{identity}")
        response.raise_for_status()
        job = response.json()
        if job["status"] in TERMINAL:
            return job
        sleep(POLL_SECONDS)
    response = client.post(f"/api/jobs/{identity}/stop")
    response.raise_for_status()
    return response.json()


def upload(case, origin):
    path = DATASET / case["path"]
    if digest(path) != case["source_sha256"]:
        raise ValueError("Dataset source changed after sampling")
    with TestClient(create_app(storage_root=origin, provider_factory=extracting_provider)) as client:
        with path.open("rb") as file:
            result = client.post("/api/documents", files={"file": (path.name, file)})
        if not result.is_success:
            return {"status": "upload_rejected", "http_status": result.status_code}
        data = result.json()
        identity = data["building_id"]
        window = configured_number("RECONSTRUCTION_JOB_SECONDS", 900) + 20
        jobs = [wait_job(client, row["id"], window) for row in data["extraction_jobs"]]
        for _ in range(1):
            if not jobs or all(job["status"] == "complete" for job in jobs):
                break
            retryable = {"provider_timeout", "provider_quota", "provider_failure", "response_schema", "response_json"}
            if not all(job.get("error_category") in retryable for job in jobs if job["status"] != "complete"):
                break
            retry = client.post(f"/api/buildings/{identity}/extraction", json={"retry": True})
            retry.raise_for_status()
            jobs.extend(wait_job(client, row["id"], window) for row in retry.json()["jobs"])
        response = client.get(f"/api/buildings/{identity}")
        response.raise_for_status()
        current = response.json()
    revision = current["revision_id"]
    folder = origin / "buildings" / identity / "revisions" / revision
    persisted = {name: digest(folder / name) for name in ("description.json", "reasoning.json") if (folder / name).is_file()}
    ready = current["interpretation_status"] == "complete" and len(persisted) == 2
    return {
        "status": "ready" if ready else "extraction_failed", "building_id": identity,
        "revision_id": revision, "saved_sha256": persisted,
        "jobs": [{key: job.get(key) for key in ("status", "error_category", "provider_calls")} for job in jobs],
    }


def clone_source(origin, target, identity):
    shutil.copytree(origin / "buildings" / identity, target / "buildings" / identity,
                    ignore=shutil.ignore_patterns("jobs", "conversation.json"))
    resource = origin / "resources" / identity
    if resource.exists():
        shutil.copytree(resource, target / "resources" / identity)


def ask(case, model, evidence, origin, target, window):
    identity, revision = evidence["building_id"], evidence["revision_id"]
    clone_source(origin, target, identity)
    pages = sorted((origin / "buildings" / identity / "pages").glob("*.png"), key=lambda p: int(p.stem))
    page_sha256 = [digest(path) for path in pages]
    providers = []

    def factory():
        provider = TimingProvider(model, revision, page_sha256)
        providers.append(provider)
        return provider

    app = create_app(storage_root=target, provider_factory=factory)
    with TestClient(app) as client:
        started = perf_counter()
        response = client.post("/api/questions", json={
            "document_id": identity, "revision_id": revision, "question": case["question"],
        })
        if not response.is_success:
            return {"status": "question_rejected", "http_status": response.status_code,
                    "wall_seconds": perf_counter() - started}
        job = wait_job(client, response.json()["id"], window)
        wall = perf_counter() - started
    answer = job.get("answer") or {}
    provider = providers[0] if providers else None
    verified = provider.context if provider else None
    status = answer.get("status") if job["status"] == "complete" else f"question_{job['status']}"
    if job["status"] == "complete" and (answer.get("answered_revision_id") != revision
                                        or not (verified or {}).get("verified")):
        status = "context_mismatch"
    calls = job.get("provider_calls") or []
    return {
        "status": status, "context": verified, "wall_seconds": round(wall, 3),
        "qa_ms": (answer.get("usage") or {}).get("latency_ms"),
        "provider_ms": sum(call["elapsed_ms"] for call in calls if call.get("elapsed_ms") is not None) if calls else None,
        "provider_calls": calls, "provider_error": provider.provider_error if provider else None,
    }


def run_case(case, manifest, cached_uploads, results):
    runtime = HERE / ".runtime"
    runtime.mkdir(exist_ok=True)
    origin = runtime / case["id"] / "upload"
    evidence = cached_uploads.get(case["id"])
    if not evidence:
        try:
            evidence = upload(case, origin)
        except Exception as error:
            evidence = {"status": "upload_harness_error", "error_type": type(error).__name__}
        append(HERE / "uploads.jsonl", {"id": case["id"], **evidence})
        print(case["id"], "upload", evidence["status"], flush=True)
    for model in case["model_order"]:
        if (case["id"], model) in results:
            continue
        result = {"status": evidence["status"]}
        if evidence["status"] == "ready":
            try:
                with TemporaryDirectory(dir=runtime) as folder:
                    result = ask(case, model, evidence, origin, Path(folder), manifest["qa_total_seconds"] + 35)
            except Exception as error:
                result = {"status": "question_harness_error", "error_type": type(error).__name__}
        append(HERE / "results.jsonl", {"id": case["id"], "model": model, **result})
        print(case["id"], model, result["status"], result.get("wall_seconds", ""), flush=True)


def summarize(manifest, results):
    for case in manifest["cases"]:
        contexts = [results.get((case["id"], model), {}).get("context") for model in MODELS]
        if any(context and not context["verified"] for context in contexts):
            raise RuntimeError(f"Invalid saved question context for {case['id']}")
        if len({json_digest(context) for context in contexts if context}) > 1:
            raise RuntimeError(f"Models received differing saved question context for {case['id']}")
    matches = [
        case["id"] for case in manifest["cases"]
        if all(results.get((case["id"], model), {}).get("status") in BENIGN_STATUSES for model in MODELS)
    ]
    lines = [
        "# Blueprint QA latency on 10 random Junction questions", "",
        f"Sample seed {manifest['seed']}. Randomly shuffled {manifest['rows_in_initial_pool']:,} distinct "
        "PDF or PNG question/path pairs from the full dataset. Accepted the first 10 that passed the app's "
        "local input checks. Each model received the same selected questions. IFC questions were left out "
        "because this comparison requires original drawing pages with saved upload interpretation.", "",
        f"The app saved one interpretation per source using {manifest['extraction_model']}. Each timed "
        "run used the original pages and the revision's JSON through the production QA adapters. "
        f"All runs used {manifest['decision_model']} for sufficiency and review. Generation follows the "
        f"app's configured {manifest['qa_total_seconds']:g}s overall QA window and model-specific settings. "
        "The order of models is randomized per question. Up to two question sources run in parallel. "
        "Upload and interpretation time are outside the timing window.", "",
        "Wall time starts immediately before POST /api/questions and ends when a job poll observes a "
        f"terminal result, with {manifest['poll_seconds']:g}s polling. App QA time is the answer's "
        "usage latency. Provider time sums the app's elapsed intervals for generation and Decisions "
        "calls, including input preparation and response handling timed by their existing diagnostics. "
        "Means use completed QA outcomes including evidence abstentions and intent clarifications. "
        "The per-question records include elapsed times for failed attempts. "
        "Every model's initial request in a case had matching original-page and saved-interpretation hashes.", "",
        "| Generation model | Answered | Abstained or clarified | QA failures | Pre-QA failures |"
        " Avg wall, completed | Median wall | Wall range | Avg app QA | Avg provider | Avg wall, all timed attempts |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]

    def average(rows, key, factor=1):
        values = [row[key] * factor for row in rows if row.get(key) is not None]
        return f"{mean(values):.2f} s" if values else "—"

    for model in MODELS:
        rows = [row for (_, selected), row in results.items() if selected == model]
        completed = [row for row in rows if row["status"] in BENIGN_STATUSES]
        times = [row["wall_seconds"] for row in completed]
        med = f"{median(times):.2f} s" if times else "—"
        span = f"{min(times):.2f}–{max(times):.2f} s" if times else "—"
        answered = sum(row["status"] == "answered" for row in completed)
        qa_failures = sum(row["status"] not in BENIGN_STATUSES and row["status"].startswith(("question_", "context_"))
                          for row in rows)
        lines.append(f"| {model} | {answered} | {len(completed)-answered} | {qa_failures} | "
                     f"{len(rows)-len(completed)-qa_failures} | "
                     f"{average(completed, 'wall_seconds')} | {med} | {span} | {average(completed, 'qa_ms', .001)} | "
                     f"{average(completed, 'provider_ms', .001)} | {average(rows, 'wall_seconds')} |")
    lines.extend(["", f"Matched sample contains {len(matches)}/10 questions with completed outcomes for all models.",
                  "", "| Model | Matched avg wall | Matched avg provider | Matched avg generation |"
                  " Matched avg Decisions |",
                  "| --- | ---: | ---: | ---: | ---: |"])

    def average_calls(rows, model):
        milliseconds = [sum(call["elapsed_ms"] or 0 for call in row["provider_calls"] if call["model"] == model)
                        for row in rows]
        return f"{mean(milliseconds)/1000:.2f} s" if milliseconds else "—"

    for model in MODELS:
        common = [results[identity, model] for identity in matches]
        lines.append(f"| {model} | {average(common, 'wall_seconds')} | "
                     f"{average(common, 'provider_ms', .001)} | {average_calls(common, model)} | "
                     f"{average_calls(common, manifest['decision_model'])} |")

    lines.extend(["", "| Case | Model | Outcome | Wall seconds | App QA seconds | Provider seconds | Calls |",
                  "| --- | --- | --- | ---: | ---: | ---: | ---: |"])

    def seconds(value, factor=1):
        return f"{value * factor:.2f}" if value is not None else "—"

    for case in manifest["cases"]:
        for model in MODELS:
            row = results.get((case["id"], model), {})
            lines.append(f"| {case['id']} | {model} | {row.get('status', 'pending')} | "
                         f"{seconds(row.get('wall_seconds'))} | {seconds(row.get('qa_ms'), .001)} | "
                         f"{seconds(row.get('provider_ms'), .001)} | {len(row.get('provider_calls', []))} |")
    failure_rows = [row for row in results.values() if row["status"] not in BENIGN_STATUSES]
    if failure_rows:
        lines.extend(["", "| Case | Model | Failure | Last call | Outcome or HTTP status |",
                      "| --- | --- | --- | --- | --- |"])
        for row in failure_rows:
            call = (row.get("provider_calls") or [{}])[-1]
            error = row.get("provider_error") or {}
            outcome = call.get("outcome") or row.get("http_status") or row.get("error_type") or "—"
            if error.get("status"):
                outcome = f"{outcome} / HTTP {error['status']}"
            lines.append(f"| {row['id']} | {row['model']} | {row['status']} | "
                         f"{call.get('schema', '—')} | {outcome} |")
    (HERE / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    command = parser.add_mutually_exclusive_group()
    command.add_argument("--sample-only", action="store_true")
    command.add_argument("--report-only", action="store_true")
    args = parser.parse_args()
    manifest_path = HERE / "manifest.json"
    if not manifest_path.exists():
        manifest_path.write_text(json.dumps(sample(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if args.sample_only:
        print(Counter((case["format"], case["type"]) for case in manifest["cases"]), flush=True)
        return
    output = HERE / "results.jsonl"
    if not args.report_only:
        if manifest["adapter_sha256"] != digest(ROOT / "app" / "providers" / "gemini.py"):
            raise RuntimeError("The QA adapter changed after sampling")
        uploads = latest(HERE / "uploads.jsonl", lambda row: row["id"])
        results = latest(output, lambda row: (row["id"], row["model"]))
        with ThreadPoolExecutor(max_workers=WORKERS) as executor:
            futures = [executor.submit(run_case, case, manifest, uploads, results) for case in manifest["cases"]]
            for future in as_completed(futures):
                future.result()
    summarize(manifest, latest(output, lambda row: (row["id"], row["model"])))


if __name__ == "__main__":
    main()
