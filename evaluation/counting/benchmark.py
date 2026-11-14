"""Evaluate Blueprint QA or two-call interpretation-only answers on the Junction dataset."""
import argparse
import base64
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from hashlib import sha256
from html import escape
import json
import math
import os
from pathlib import Path
import random
import re
from tempfile import TemporaryDirectory
from threading import Lock
from time import monotonic, sleep
from typing import Literal
from uuid import uuid4

from fastapi.testclient import TestClient
from pydantic import StrictFloat, StrictInt, model_validator

from app.building import BuildingDescription
from app.documents import DocumentStore
from app.jobs import TERMINAL, pipeline_config
from app.main import create_app
from app.providers.gemini import INTERPRETATION_INSTRUCTIONS, GeminiProvider, configured_number, image_bytes, settings
from app.reasoning import without_user_provided
from app.schemas import StrictModel


HERE = Path(__file__).resolve().parent
DATASET = HERE.parents[1] / "junction-dataset"
SAMPLE_SIZES = {"count": {"pdf": 3, "png": 3}, "length": {"pdf": 6}, "area": {"pdf": 6}}
OUTPUT_LOCK = Lock()
UPLOAD_LOCK = Lock()
COUNT_WORDS = dict(zip(
    "zero one two three four five six seven eight nine ten eleven twelve".split(),
    range(13),
))
FRENCH_COUNTS = dict(zip(
    "zéro un deux trois quatre cinq six sept huit neuf dix onze douze treize quatorze quinze seize".split(),
    range(17),
))
FRENCH_COUNTS["une"] = 1
COUNT_WORDS.update(FRENCH_COUNTS)
NUMBER = re.compile(
    r"(?<![\w+#.,\-–—])(?:[0-9]+(?:,[0-9]{3})*|"
    + "|".join(COUNT_WORDS) + r")(?![\w°º\-–—]|[.,]\d)"
)
LENGTH_UNITS = {
    "m": 1, "metre": 1, "metres": 1, "meter": 1, "meters": 1, "mètre": 1, "mètres": 1,
    "metri": 1, "metros": 1, "meteren": 1, "metern": 1, "cm": 0.01, "mm": 0.001,
    "ft": 0.3048, "foot": 0.3048, "feet": 0.3048, "inch": 0.0254, "inches": 0.0254,
}
AREA_UNITS = {
    "m2": 1, "square metres": 1, "square meters": 1, "quadratmeter": 1,
    "mètres carrés": 1, "metros cuadrados": 1, "metri quadrati": 1,
    "vierkante meter": 1, "kvadratmeter": 1, "cm2": 0.0001, "mm2": 0.000001,
    "ft2": 0.3048 ** 2, "sq ft": 0.3048 ** 2, "square feet": 0.3048 ** 2,
    "square foot": 0.3048 ** 2, "in2": 0.0254 ** 2,
}
MEASURE_UNITS = {"length": LENGTH_UNITS, "area": AREA_UNITS}
MEASUREMENT = re.compile(
    r"(?<![\w.,+\-])(-?\d+(?:[.,' ]\d+)*?)\s*("
    + "|".join(map(re.escape, sorted(AREA_UNITS.keys() | LENGTH_UNITS.keys(), key=len, reverse=True)))
    + r")(?![\w^])"
)
RELATIVE_TOLERANCE = 0.02


class BenchmarkFailure(Exception):
    """Safe local validation or workflow failure."""


def require(condition, message):
    if not condition:
        raise BenchmarkFailure(message)


def digest(data):
    return sha256(data).hexdigest()


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def append_jsonl(path, data):
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(data, ensure_ascii=False) + "\n")


def sample(seed, question_type="count", per_format=None):
    sizes = {fmt: per_format or size for fmt, size in SAMPLE_SIZES[question_type].items()}
    pool = {format_: [] for format_ in sizes}
    entries = DATASET / "questions.jsonl"
    with entries.open(encoding="utf-8") as stream:
        for row_number, line in enumerate(stream, 1):
            row = json.loads(line)
            format_ = Path(row["path"]).suffix.lower().lstrip(".")
            if row["type"] == question_type and format_ in pool and (DATASET / row["path"]).is_file():
                if question_type != "count" and row["unit"] not in MEASURE_UNITS[question_type]:
                    continue
                pool[format_].append({
                    "row_number": row_number, "source": row["path"],
                    "question": row["question"], "reference": row["answer"], "format": format_,
                })
                if question_type != "count":
                    pool[format_][-1]["unit"] = row["unit"]
    rng = random.Random(seed)
    cases = []
    for format_, size in sizes.items():
        require(len(pool[format_]) >= size, f"Not enough {format_.upper()} rows for {question_type}")
        for index, row in enumerate(rng.sample(pool[format_], size), 1):
            cases.append({
                "case": f"{format_}-{index}", **row,
                "source_sha256": digest((DATASET / row["source"]).read_bytes()),
            })
    return {
        "seed": seed, "dataset_sha256": digest(entries.read_bytes()),
        "eligible_rows": {format_: len(rows) for format_, rows in pool.items()},
        "cases": cases,
    }


def count_from_answer(answer):
    if not answer:
        return None
    # Accept a single count in the leading assertion. Do not search supporting lists,
    # floor numbers, ranges, or estimated values for convenient matches.
    text = answer.replace("**", "").strip().casefold()
    if text.startswith(("answer:", "count:", "total:")):
        text = text.split(":", 1)[1].lstrip()
    text = re.sub(r"\([^()]*\)", "", text)
    if re.match(r"^[^:;,.!?\n\d]{1,40}:\s*\d", text):
        text = text.split(":", 1)[1].lstrip()
    leading = re.split(r"\n|[.!?](?=\s|$)|[:;]", text, maxsplit=1)[0]
    if re.search(r"\b(?:about|roughly|approximately|around|at least|at most|between|up to|maybe|possibly|unknown|not known|not clear|unclear|more than|fewer than|or|environ|approximativement|au moins|au plus|entre|ou|plus de|moins de)\b|[~±]|\d\s*[-–—]\s*\d", leading):
        return None
    # Reject partial matches in compound French numerals, including the tens
    # after a conjunction as in « vingt et un ».
    if re.search(r"\b(?:vingts?|trente|quarante|cinquante|soixante|cents?|mille|millions?)\b", leading):
        return None
    numbers = [match.group() for match in NUMBER.finditer(leading)
               if match.group() not in {"un", "une"} or (
                   not re.match(r"\s+total\b", leading[match.end():])
                   and (match.start() == 0 or re.search(r"\bil y a\s*$", leading[:match.start()]))
               )]
    if not numbers and re.match(r"^(?:there (?:is|are) no|no) \w+", leading):
        return 0
    if len(numbers) != 1:
        return None
    value = numbers[0]
    if value in COUNT_WORDS:
        return COUNT_WORDS[value]
    return int(value.replace(",", ""))


def decimal_value(text):
    """Parse locale decimal and grouped digits, rejecting ambiguous separators."""
    if not re.fullmatch(r"-?\d+(?:[.,]\d+)?|-?\d{1,3}(?:[ ']\d{3})+(?:[.,]\d+)?|-?\d{1,3}(?:,\d{3})+\.\d+|-?\d{1,3}(?:\.\d{3})+,\d+", text):
        return None
    if re.fullmatch(r"-?[1-9]\d{0,2}[.,]\d{3}", text):
        return None
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "")
        else:
            text = text.replace(",", "")
    number = float(text.replace(" ", "").replace("'", "").replace(",", "."))
    return number if math.isfinite(number) and number >= 0 else None


def measurement_from_answer(answer, question_type, target_unit):
    text = answer.replace("**", "").casefold().strip().replace("’", "'")
    text = re.sub(r"\b(mm|cm|m|ft|in)\s*(?:\^\s*2|²)\b", r"\g<1>2", text)
    text = re.sub(r"\bsq\.?\s+(?:ft|m)\b", lambda match: match.group().split()[-1] + "2", text)
    text = re.sub(r"\b(?:ca|approx|env)\.(?=\s*\d)", "approximately", text)
    leading = re.split(r"\n|[.!?](?=\s|$)|;", text, maxsplit=1)[0]
    if re.search(r"\b(?:between|at least|at most|up to|more than|less than|under|over|or|entre|jusqu'à|au moins|au plus|ou|zwischen|mindestens|höchstens|oder|tussen|minstens|maximaal)\b|[<>±]|\d\s*[-–—]\s*\d|\b(?:to|à|bis|tot)\s+\d", leading):
        return None
    matches = list(MEASUREMENT.finditer(leading))
    units = MEASURE_UNITS[question_type]
    if len(matches) != 1 or matches[0].group(2) not in units:
        return None
    match = matches[0]
    if re.match(r"\s*[-–—]\s*\d", leading[match.end():]):
        return None
    text_value, unit = match.groups()
    value = decimal_value(text_value)
    if value is None:
        return None
    return value * (units[unit] / units[target_unit])


class ObservedProvider(GeminiProvider):
    def __init__(self, state):
        super().__init__()
        self.state = state
        # Examine only evidence hashes/types on the actual SDK calls. Requests still
        # go through GeminiProvider and its configured clients and validation.
        generate = self.client.models.generate_content
        decisions = self.client.decisions.create

        def checked_generate(*args, **kwargs):
            if self.state["phase"] == "qa":
                parts = kwargs["contents"]
                texts = [part.text for part in parts if part.text is not None]
                images = [part.inline_data.data for part in parts if part.inline_data is not None]
                self.verify_wire(texts, images)
            return generate(*args, **kwargs)

        def checked_decisions(*args, **kwargs):
            if self.state["phase"] == "qa":
                contents = kwargs["input"]
                texts = [item["text"] for item in contents if item["type"] == "text"]
                images = [base64.b64decode(item["data"]) for item in contents if item["type"] == "image"]
                self.verify_wire(texts, images)
            return decisions(*args, **kwargs)

        self.client.models.generate_content = checked_generate
        self.client.decisions.create = checked_decisions

    def verify_wire(self, texts, images):
        try:
            context = json.loads(texts[1])
            require(context["revision_id"] == self.state["revision"], "QA wire revision does not match saved interpretation")
            expected = self.state["interpretation"]
            if context.get("evidence_scope") == "sources_only":
                expected = without_user_provided(expected)
            require(context["interpretation"] == expected, "QA wire input does not contain saved interpretation")
            require([digest(data) for data in images[:len(self.state["pages"])]] == self.state["pages"],
                    "QA wire pages do not match the saved original-source pages")
        except (BenchmarkFailure, KeyError, IndexError, ValueError, TypeError):
            self.state["context_failed"] = True
            raise
        self.state["verified_qa_calls"] += 1

    def report_call(self, record):
        row = {
            "case": self.state["case"], "pipeline": self.state["phase"],
            **{key: record[key] for key in ("call_id", "schema", "stage", "model", "elapsed_ms", "outcome", "http_status")},
        }
        if row["stage"] == "provider":
            row["stage"] = "Chat routing" if row["pipeline"] == "chat" else row["schema"]
        with OUTPUT_LOCK:
            append_jsonl(self.state["calls_path"], row)
            print(f"{row['case']} | {row['pipeline']} | {row['stage']} ({row['schema']}) | "
                  f"{row['model']} | {row['elapsed_ms'] / 1000:.3f}s | {row['outcome']}", flush=True)

    def observed_call(self, function, *args, **kwargs):
        previous = len(getattr(self, "provider_calls", ()))
        print(f"{self.state['case']} | {self.state['phase']} | starting {function.__name__.lstrip('_')} call", flush=True)
        try:
            return function(*args, **kwargs)
        finally:
            for record in getattr(self, "provider_calls", ())[previous:]:
                self.report_call(record)

    def _generate(self, *args, **kwargs):
        return self.observed_call(super()._generate, *args, **kwargs)

    def _decisions(self, *args, **kwargs):
        return self.observed_call(super()._decisions, *args, **kwargs)


def wait_job(client, identity, seconds):
    deadline = monotonic() + seconds
    while monotonic() < deadline:
        response = client.get(f"/api/jobs/{identity}")
        response.raise_for_status()
        job = response.json()
        if job["status"] in TERMINAL:
            return job
        sleep(0.35)
    raise BenchmarkFailure("Job did not reach a terminal state within its configured window")


def save_call_ids(result, outcome, phase):
    result[f"{phase}_call_ids"] = [call["call_id"] for call in outcome.get("provider_calls", [])]


def upload(client, store, case, result, state):
    path = DATASET / case["source"]
    data = path.read_bytes()
    require(digest(data) == case["source_sha256"], "Source changed after the manifest was created")
    started = monotonic()
    try:
        # PDFium is process-wide and expects serialized page rendering.
        with UPLOAD_LOCK:
            started = monotonic()
            response = client.post("/api/documents", files={"file": (path.name, data)})
        response.raise_for_status()
        info = response.json()
        identity = info["building_id"]
        require(len(info["extraction_jobs"]) == 1, "Fresh upload did not start exactly one interpretation job")
        job = wait_job(client, info["extraction_jobs"][0]["id"], pipeline_config()["job_seconds"] + 15)
        save_call_ids(result, job, "upload")
        require(job["status"] == "complete", "Interpretation " + job["status"] + ": " + str(job.get("error_category") or job["phase"]))
        revision = job["revision_id"]
        saved = store / "buildings" / identity / "revisions" / revision / "description.json"
        require(saved.is_file(), "Completed upload did not save interpretation JSON")
        interpretation = json.loads(saved.read_bytes())
        result["upload_seconds"] = round(monotonic() - started, 3)
    finally:
        if result["upload_seconds"] is None:
            result["upload_failure_seconds"] = round(monotonic() - started, 3)

    response = client.get(f"/api/buildings/{identity}")
    response.raise_for_status()
    descriptor = response.json()
    require(descriptor["revision_id"] == revision and descriptor["interpretation_status"] == "complete",
            "Active interpretation revision is not the completed revision")
    bundle = client.app.state.documents.revision(identity, revision)
    response = client.get(f"/api/buildings/{identity}/sources/{identity}/original")
    response.raise_for_status()
    require(digest(response.content) == case["source_sha256"], "Saved original file differs from uploaded file")
    pages = []
    for page in bundle.pages:
        response = client.get(f"/api/buildings/{identity}/revisions/{revision}/pages/{page.number}")
        response.raise_for_status()
        require(response.content == page.path.read_bytes(), "Served page differs from the saved render")
        with page.image() as image:
            pages.append(digest(image_bytes(image)))
    require(bool(pages), "Saved revision has no pages")
    response = client.get(f"/api/buildings/{identity}/conversation")
    response.raise_for_status()
    require(response.json()["messages"] == [], "Case conversation was not empty before chat")
    state.update(revision=revision, interpretation=interpretation, pages=pages)
    result.update(revision=revision, interpretation_sha256=digest(saved.read_bytes()), qa_page_sha256=pages)
    return identity


def ask(client, identity, question, result, state, question_type):
    started = monotonic()
    request_id = uuid4().hex
    revision = state["revision"]
    try:
        state["phase"] = "chat"
        route = client.post("/api/chat/actions", json={
            "message": question, "request_id": request_id, "document_id": identity,
            "revision_id": revision, "workspace": {},
        })
        route.raise_for_status()
        plan = route.json()
        require((plan.get("request_id"), plan.get("document_id"), plan.get("revision_id"),
                 plan.get("geometry_revision_id"), plan.get("navigation_epoch")) ==
                (request_id, identity, revision, None, 0), "Chat routing changed the request or pinned workspace identity")
        if plan["status"] == "clarification":
            result.update(answer=(plan.get("clarification") or {}).get("message") or plan.get("message"), outcome="abstention")
            return
        actions = [action for action in plan.get("actions", []) if action["type"] == "question"]
        require(plan["status"] == "ready" and len(actions) == 1, "Chat did not return a factual question action")
        action = actions[0]
        require(action["revision_id"] == revision, "Chat question action changed the pinned revision")
        require(not action.get("navigation_reference"), "Chat action added a navigation reference to the exact question")
        if action["question"] != question:
            result["routed_question"] = action["question"]

        state["phase"] = "qa"
        response = client.post("/api/questions", json={
            "document_id": identity, "revision_id": revision, "request_id": request_id,
            "question": question, "conversation_id": identity, "reply_to": None, "clarification_response": None,
        })
        response.raise_for_status()
        job = wait_job(client, response.json()["id"], configured_number("QA_TOTAL_SECONDS", 180) + 15)
        save_call_ids(result, job, "qa")
        if job["status"] != "complete":
            result["answer"] = job.get("message")
            raise BenchmarkFailure("Question did not complete: " + job["status"])
        answer = job["answer"]
        result["answer"] = answer["answer"]
        result["answer_status"] = answer["status"]
        require(answer["answered_revision_id"] == revision, "Answer does not use the pinned interpretation revision")
        require(job["question"].strip() == question.strip(), "Saved question differs from dataset wording")
        require(not state["context_failed"] and state["verified_qa_calls"] == len(result["qa_call_ids"]) > 0,
                "Could not verify saved interpretation and rendered pages on every QA model call")
        if answer["status"] != "answered":
            result["outcome"] = "abstention"
        else:
            if question_type == "count":
                value = count_from_answer(answer["answer"])
                if value is not None:
                    result.update(count=value, outcome="correct" if value == result["reference"] else "incorrect")
            else:
                value = measurement_from_answer(answer["answer"], question_type, result["unit"])
                if value is not None:
                    error = abs(value - result["reference"])
                    limit = abs(result["reference"]) * RELATIVE_TOLERANCE
                    correct = error <= limit or math.isclose(error, limit, rel_tol=1e-12)
                    result.update(measurement=value, outcome="correct" if correct else "incorrect")
            if value is None:
                result["outcome"] = "unscorable"
    finally:
        result["question_seconds"] = round(monotonic() - started, 3)


def timing(value):
    return f"{value:.3f}s" if value is not None else "n/a"


def run_case(case, run_path, question_type="count"):
    state = {
        "case": case["case"], "phase": "upload", "calls_path": run_path / "model-calls.jsonl",
        "context_failed": False, "verified_qa_calls": 0,
    }
    result = {
        "case": case["case"], "format": case["format"], "row_number": case["row_number"],
        "reference": case["reference"], "answer": None, "outcome": "operational_failure",
        "upload_seconds": None, "question_seconds": None, "upload_call_ids": [], "qa_call_ids": [],
    }
    if question_type == "count":
        result["count"] = None
    else:
        result.update(unit=case["unit"], measurement=None)
    try:
        with TemporaryDirectory(prefix=case["case"] + "-", dir=run_path) as directory:
            # Only the label and verification state are captured by the factory.
            # The dataset row/answer are used outside the app for submission and scoring.
            with TestClient(create_app(storage_root=directory, provider_factory=lambda: ObservedProvider(state))) as client:
                identity = upload(client, Path(directory), case, result, state)
                ask(client, identity, case["question"], result, state, question_type)
    except BenchmarkFailure as error:
        result["failure"] = str(error)
    except Exception as error:
        result["failure"] = type(error).__name__
        if response := getattr(error, "response", None):
            result["http_status"] = response.status_code
            if state["phase"] == "chat":
                try:
                    payload = response.json()
                except ValueError:
                    payload = {}
                detail = payload.get("detail") if isinstance(payload, dict) else None
                if isinstance(detail, str):
                    result["answer"] = detail
    result["last_phase"] = state["phase"]
    result["verified_qa_calls"] = state["verified_qa_calls"]
    result["context_check_failed"] = state["context_failed"]
    score_detail = f"count: {result['count']}" if question_type == "count" else f"measurement: {result['measurement']} {result['unit']}"
    with OUTPUT_LOCK:
        append_jsonl(run_path / "results.jsonl", result)
        print(
            f"{case['case']} | ground truth: {result['reference']}{' ' + result['unit'] if 'unit' in result else ''} | {score_detail} | {result['outcome']}\n"
            f"User-visible answer: {result['answer'] if result['answer'] is not None else '(none)'}\n"
            f"Upload to saved JSON: {timing(result['upload_seconds'])} | "
            f"Question to terminal: {timing(result['question_seconds'])}"
            + (f" | Upload to failure: {timing(result['upload_failure_seconds'])}" if "upload_failure_seconds" in result else "")
            + (f" | {result['failure']}" if "failure" in result else ""), flush=True,
        )
    return result


def summarize(run_path, manifest, results, question_type="count"):
    expected_cases = {case["case"] for case in manifest["cases"]}
    require(len(results) == len(expected_cases) and {row["case"] for row in results} == expected_cases, "Missing or duplicate case results")
    with (run_path / "model-calls.jsonl").open(encoding="utf-8") as stream:
        calls = [json.loads(line) for line in stream]
    call_ids = {row["call_id"] for row in calls}
    require(len(call_ids) == len(calls) and {row["case"] for row in calls} <= expected_cases, "Model call log has duplicates or unknown cases")
    for result in results:
        for phase in ("upload", "qa"):
            saved = result[f"{phase}_call_ids"]
            logged = [row["call_id"] for row in calls if row["case"] == result["case"] and row["pipeline"] == phase]
            if saved:
                require(logged == saved, "Immediate and persisted model-call logs differ")
        if result["outcome"] != "operational_failure":
            require(result["upload_seconds"] is not None and result["question_seconds"] is not None, "Missing timings")
            require(any(row["case"] == result["case"] and row["pipeline"] == "chat" for row in calls), "Missing chat routing call")
    sizes = dict(Counter(case["format"] for case in manifest["cases"]))
    scores = {format_: sum(r["outcome"] == "correct" and r["format"] == format_ for r in results) for format_ in sizes}
    counts = Counter(r["outcome"] for r in results)
    summary = {"score": counts["correct"], "out_of": len(expected_cases), "format_scores": scores,
               "format_out_of": next(iter(sizes.values())), "outcomes": dict(sorted(counts.items())), "model_calls": len(calls)}
    if question_type != "count":
        summary.update(question_type=question_type, relative_tolerance=RELATIVE_TOLERANCE)
    write_json(run_path / "summary.json", summary)
    format_scores = " | ".join(f"{fmt.upper()} {scores[fmt]}/{size}" for fmt, size in sizes.items())
    print(f"Total {summary['score']}/{summary['out_of']} | {format_scores} | {len(calls)} model calls", flush=True)
    print(json.dumps(summary["outcomes"], ensure_ascii=False), flush=True)


HYDROGEN = "gemini-4-hydrogen"
QUANTITY_INVENTORY = """
This interpretation will be read without the page images. For each floor, preserve
a source-linked inventory of distinctly visible rooms, fixtures, doors and windows,
using separate records for distinct instances and preserving room identifiers in
labels or notes. In observations, save labeled net areas and dimension callouts
with the corresponding room or segment identifier and explicit units. Record
readable wall lengths and any scale-based estimates of individual wall runs when
the visible geometry and scale support them. Distinguish observed values from
estimates. Never guess missing dimensions or counts.
"""
QUANTITY_ANSWER_INSTRUCTIONS = """
Answer the exact question using only the supplied interpretation JSON. Assume the
original referenced file contains the information needed, but the supplied
interpretation may have omitted it. Apply the requested scope and exclusions, and
perform any arithmetic supported by the interpretation. For a count return a
nonnegative integer and unit "count". For lengths use m, cm, mm or ft. For areas
use m2, cm2, mm2 or ft2. For quantities that cannot be determined from the JSON
return null for both value and unit. Do not invent missing quantities. Return only
the structured result with a brief explanation.
"""


class QuantityAnswer(StrictModel):
    value: StrictInt | StrictFloat | None
    unit: Literal["count", "m", "cm", "mm", "ft", "m2", "cm2", "mm2", "ft2"] | None
    explanation: str

    @model_validator(mode="after")
    def validate_quantity(self):
        if (self.value is None) != (self.unit is None):
            raise ValueError("Value and unit must both be present or both be null")
        if self.value is not None and (not math.isfinite(self.value) or self.value < 0):
            raise ValueError("Quantity must be nonnegative and finite")
        if self.unit == "count" and type(self.value) is not int:
            raise ValueError("A count must be an integer")
        return self


def quantity_score(answer, case):
    if answer.value is None:
        return None, "abstention"
    kind = case["question_type"]
    if kind == "count":
        require(answer.unit == "count", "Structured answer has the wrong quantity type")
        return answer.value, "correct" if answer.value == case["reference"] else "incorrect"
    units = MEASURE_UNITS[kind]
    require(answer.unit in units, "Structured answer has the wrong quantity type")
    value = answer.value * units[answer.unit] / units[case["unit"]]
    error = abs(value - case["reference"])
    limit = abs(case["reference"]) * RELATIVE_TOLERANCE
    correct = error <= limit or math.isclose(error, limit, rel_tol=1e-12)
    return value, "correct" if correct else "incorrect"


def interpretation_case(case, run_path):
    case_path = run_path / case["case"]
    case_path.mkdir()
    state = {"case": case["case"], "phase": "interpretation", "calls_path": run_path / "model-calls.jsonl"}
    result = {"case": case["case"], "outcome": "operational_failure", "answer": None,
              "scored_value": None, "interpretation_seconds": None, "answer_seconds": None}
    provider = None
    try:
        path = DATASET / case["source"]
        data = path.read_bytes()
        require(digest(data) == case["source_sha256"], "Source changed after sampling")
        with TemporaryDirectory(prefix="junction-interpretation-") as directory:
            store = DocumentStore(Path(directory))
            try:
                with UPLOAD_LOCK:
                    document = store.add(data, path.name)
                provider = ObservedProvider(state)
                started = monotonic()
                try:
                    interpretation = provider._generate(
                        document, "Interpret the supplied original sources.",
                        INTERPRETATION_INSTRUCTIONS + QUANTITY_INVENTORY, BuildingDescription,
                        model=HYDROGEN, include_qa_context=False, thinking_level="high",
                        max_tokens=configured_number("RECONSTRUCTION_MAX_TOKENS", 65536, integer=True),
                        timeout_ms=round(configured_number("RECONSTRUCTION_CALL_SECONDS", 300) * 1000),
                    )
                finally:
                    result["interpretation_seconds"] = round(monotonic() - started, 3)
                saved = case_path / "interpretations.json"
                write_json(saved, interpretation.model_dump(mode="json"))
            finally:
                store.close()
        state["phase"] = "answer"
        # The second call receives only the exact question plus saved interpretation.
        source = replace(document, pages=[], question_context={"interpretation": json.loads(saved.read_text())})
        started = monotonic()
        try:
            answer = provider._generate(
                source, case["question"], QUANTITY_ANSWER_INSTRUCTIONS, QuantityAnswer,
                model=HYDROGEN, max_tokens=65536,
                timeout_ms=round(configured_number("RECONSTRUCTION_CALL_SECONDS", 300) * 1000),
            )
        finally:
            result["answer_seconds"] = round(monotonic() - started, 3)
        result["answer"] = answer.model_dump(mode="json")
        result["scored_value"], result["outcome"] = quantity_score(answer, case)
    except BenchmarkFailure as error:
        result["failure"] = str(error)
    except Exception as error:
        result["failure"] = type(error).__name__
    finally:
        if provider is not None:
            result["call_ids"] = [record["call_id"] for record in getattr(provider, "provider_calls", ())]
            provider.close()
        else:
            result["call_ids"] = []
    result["last_phase"] = state["phase"]
    with OUTPUT_LOCK:
        append_jsonl(run_path / "results.jsonl", result)
    print(f"{case['case']} | {result['outcome']} | reference {case['reference']} | "
          f"scored {result['scored_value']} | interpretation {timing(result['interpretation_seconds'])} | "
          f"answer {timing(result['answer_seconds'])}"
          + (f" | {result['failure']}" if "failure" in result else ""), flush=True)
    return result


def write_interpretation_report(run_path, manifest, results):
    calls = [json.loads(line) for line in (run_path / "model-calls.jsonl").read_text().splitlines()]
    require(len(results) == len(manifest["cases"]), "Missing case results")
    require(Counter(call["call_id"] for call in calls) == Counter(identity for r in results for identity in r["call_ids"]),
            "Model call log is incomplete")
    rows = []
    groups = {}
    for case, result in zip(manifest["cases"], results, strict=True):
        require(case["case"] == result["case"], "Mismatched case result")
        stages = [call["pipeline"] for call in calls if call["case"] == case["case"]]
        require(stages in ([], ["interpretation"], ["interpretation", "answer"]), "Unexpected model stage")
        require(result["outcome"] == "operational_failure" or len(stages) == 2, "Scored case lacks two calls")
        group = groups.setdefault((case["question_type"], case["format"]), Counter())
        group["total"] += 1
        group[result["outcome"]] += 1
        answer = result["answer"]
        unit = case.get("unit", "count")
        numeric = "—" if result["scored_value"] is None else f"{result['scored_value']:g} {unit}"
        cells = (case["case"], case["source"], case["question"], f"{case['reference']} {unit}", numeric,
                 result["outcome"].replace("_", " "), timing(result["interpretation_seconds"]),
                 timing(result["answer_seconds"]), json.dumps(answer, ensure_ascii=False) if answer else result.get("failure", "—"))
        rows.append("<tr>" + "".join(f"<td>{escape(value)}</td>" for value in cells) + "</tr>")
    correct = sum(result["outcome"] == "correct" for result in results)
    summary = {"correct": correct, "total": len(results), "model_calls": len(calls),
               "outcomes": dict(Counter(r["outcome"] for r in results))}
    write_json(run_path / "summary.json", summary)
    count_groups = [group for (kind, _), group in groups.items() if kind == "count"]
    count_correct = sum(group["correct"] for group in count_groups)
    count_total = sum(group["total"] for group in count_groups)
    count_rows = "".join(
        f"<tr><td>{fmt.upper()}</td><td>{group['correct']}/{group['total']}</td></tr>"
        for (kind, fmt), group in groups.items() if kind == "count"
    )
    report = run_path / "results.html"
    report.write_text(f"""<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Junction interpretation-only benchmark</title>
<style>
body {{font:16px/1.5 system-ui,sans-serif;color:#182821;background:#f3f7f4;margin:0}}
main {{max-width:90rem;margin:auto;padding:2rem 1.5rem}} .scroll {{overflow:auto}}
table {{border-collapse:collapse;background:white;width:100%}}
th,td {{border-bottom:1px solid #d7e3dc;text-align:left;padding:.7rem;vertical-align:top;overflow-wrap:anywhere}}
th {{background:#deebe2;white-space:nowrap}} td:nth-child(2) {{max-width:16rem}}
td:nth-child(3),td:last-child {{min-width:14rem}}
</style>
<main><h1>Junction interpretation-only benchmark</h1>
<p><strong>{correct}/{len(results)} correct</strong> · {len(calls)} Hydrogen calls · seed {manifest['seed']}</p>
<p>Hydrogen first interprets the file without the question. A second Hydrogen call receives the exact question and saved JSON only.
Counts require exact matches. Lengths and areas allow 2% relative error after conversion. Times include each model call and local response validation.</p>
<h2>Count questions</h2>
<table><thead><tr><th>File format</th><th>Correct</th></tr></thead>
<tbody>{count_rows}<tr><th>Total</th><td><strong>{count_correct}/{count_total} questions correct</strong></td></tr></tbody></table>
<h2>Case results</h2>
<div class="scroll"><table><thead><tr><th>Case</th><th>Original file</th><th>Question</th><th>Reference</th><th>Scored value</th><th>Outcome</th><th>Interpretation</th><th>Answer</th><th>Structured response</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>
<p><a href="manifest.json">Manifest</a> · <a href="results.jsonl">Results</a> · <a href="model-calls.jsonl">Model call log</a></p>
</main></html>
""", encoding="utf-8")
    print(f"Total {correct}/{len(results)} | {len(calls)} model calls | report: {report}", flush=True)


def run_interpretation_only(seed, per_format=10):
    cases = []
    samples = {kind: sample(seed, kind, per_format=per_format) for kind in SAMPLE_SIZES}
    for kind, group in samples.items():
        cases.extend({**case, "case": f"{kind}-{case['case']}", "question_type": kind} for case in group["cases"])
    manifest = {"seed": seed, "dataset_sha256": samples["count"]["dataset_sha256"],
                "eligible_rows": {kind: group["eligible_rows"] for kind, group in samples.items()},
                "pipeline": "interpretation-only", "model": HYDROGEN, "cases": cases}
    run_path = HERE / "runs" / f"interpretation-only-{seed}-{uuid4().hex[:8]}"
    run_path.mkdir(parents=True)
    write_json(run_path / "manifest.json", manifest)
    (run_path / "model-calls.jsonl").touch()
    print(f"INTERPRETATION ONLY | {len(cases)} cases | seed {seed} | artifacts: {run_path}", flush=True)
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda case: interpretation_case(case, run_path), cases))
    write_interpretation_report(run_path, manifest, results)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=None, help="Override the randomly generated, recorded seed.")
    parser.add_argument("--type", choices=SAMPLE_SIZES, help="Webapp question type (default: count).")
    parser.add_argument("--pipeline", choices=("webapp", "interpretation-only"), default="webapp",
                        help="Use the webapp or run ten cases per supported group with two Hydrogen calls each.")
    parser.add_argument("--per-format", type=int, help="Override sample size for each supported source format.")
    args = parser.parse_args()
    if args.per_format is not None and args.per_format < 1:
        parser.error("--per-format must be positive.")
    seed = args.seed if args.seed is not None else random.SystemRandom().getrandbits(64)
    config = settings()
    if not config["api_key"]:
        parser.error("Configure the app's usual Gemini credential before running.")
    if args.pipeline == "interpretation-only":
        if args.type is not None:
            parser.error("--type only applies to webapp runs.")
        run_interpretation_only(seed, args.per_format or 10)
        return
    args.type = args.type or "count"
    if os.getenv("BLUEPRINT_PUBLIC_DEMO", "0") != "0":
        parser.error("Run the benchmark with the app's local access configuration.")

    manifest = sample(seed, args.type, args.per_format)
    if args.type != "count":
        manifest.update(question_type=args.type, relative_tolerance=RELATIVE_TOLERANCE)
    manifest["models"] = {key: config[key] for key in ("model", "interpretation_model", "clarification_model", "decision_model")}
    prefix = "" if args.type == "count" else f"{args.type}-"
    run_path = HERE / "runs" / f"{prefix}{seed}-{uuid4().hex[:8]}"
    run_path.mkdir(parents=True)
    write_json(run_path / "manifest.json", manifest)
    (run_path / "model-calls.jsonl").touch()
    print(f"{args.type.upper()} | {len(manifest['cases'])} cases | seed {seed} | artifacts: {run_path}", flush=True)
    cases = manifest["cases"]
    if args.type == "count":
        pdfs, pngs = ([case for case in cases if case["format"] == fmt] for fmt in ("pdf", "png"))
        cases = [case for pair in zip(pdfs, pngs) for case in pair]
    with ThreadPoolExecutor(max_workers=2) as executor:
        jobs = [executor.submit(run_case, case, run_path, args.type) for case in cases]
        results = [job.result() for job in as_completed(jobs)]
    summarize(run_path, manifest, results, args.type)


if __name__ == "__main__":
    main()
