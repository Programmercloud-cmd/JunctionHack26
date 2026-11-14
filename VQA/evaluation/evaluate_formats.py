"""Compare PDF and IFC counting harnesses on a reproducible held-out sample."""

import hashlib
import json
import random
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path
from statistics import median
from time import perf_counter

from .benchmark import write_json
from .format_report import write_report


VQA_DIR = Path(__file__).resolve().parents[1]
QUESTIONS = VQA_DIR.parent / "junction-dataset" / "questions.jsonl"
OUTPUT = VQA_DIR / "benchmark-runs" / "format-evaluation-25-visual-zero"
CASES_PER_FORMAT = 25
SEED = 71
HELD_OUT_BUCKETS = {1, 3}
WORKERS = 4
HARNESSES = {
    "pdf": ("pdf-native", "pdf-rendered"),
    "ifc": ("ifc-direct", "ifc-lookup"),
}


def load_sample():
    hashes = {}
    counts = Counter()
    held_out = {kind: [] for kind in HARNESSES}
    with QUESTIONS.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            path = (QUESTIONS.parent / row["path"]).resolve()
            kind = path.suffix.lower().lstrip(".")
            if row["type"] != "count" or kind not in HARNESSES:
                continue
            if path not in hashes:
                if path.is_file():
                    with path.open("rb") as stream:
                        hashes[path] = hashlib.file_digest(stream, "sha256").hexdigest()
                else:
                    hashes[path] = None
            digest = hashes[path]
            if digest is None:
                counts[kind, "missing"] += 1
                continue
            split = "held-out" if int(digest[:8], 16) % 5 in HELD_OUT_BUCKETS else "dev"
            counts[kind, split] += 1
            if split == "held-out":
                held_out[kind].append({
                    "id": line_number, "path": str(path), "digest": digest,
                    "question": row["question"], "expected": row["answer"],
                })
    rng = random.Random(SEED)
    sample = {}
    for kind, rows in held_out.items():
        chosen = []
        seen = set()
        for row in rng.sample(rows, len(rows)):
            if row["digest"] in seen:
                continue
            chosen.append(row)
            seen.add(row["digest"])
            if len(chosen) == CASES_PER_FORMAT:
                break
        if len(chosen) < CASES_PER_FORMAT:
            selected = {row["id"] for row in chosen}
            remaining = [row for row in rows if row["id"] not in selected]
            chosen.extend(rng.sample(remaining, CASES_PER_FORMAT - len(chosen)))
        sample[kind] = chosen
    return sample, {
        kind: {split: counts[kind, split] for split in ("dev", "held-out", "missing")}
        for kind in HARNESSES
    }


def summarize(rows):
    summaries = {}
    for kind, names in HARNESSES.items():
        scores = []
        for name in names:
            items = [row for row in rows if row["harness"] == name]
            complete = sum(
                item["status"] == "ok" and not item["gaps"]
                and (bool(item["evidence"]) or item["verified_zero"])
                for item in items
            )
            invalid = sum(item["status"] == "ok" and bool(item.get("invalid_evidence")) for item in items)
            scores.append({
                "harness": name,
                "cases": len(items),
                "exact": sum(item["status"] == "ok" and item["count"] == item["expected"] for item in items),
                "failures": sum(item["status"] != "ok" for item in items),
                "unsupported": sum(item["status"] == "unsupported" for item in items),
                "verified_zeros": sum(
                    item["status"] == "ok" and item["count"] == 0 and item["verified_zero"]
                    for item in items
                ),
                "visual_zeros": sum(
                    item["status"] == "ok" and item["count"] == 0
                    and any(record["kind"] == "pdf_visual_zero" for record in item["evidence"])
                    for item in items
                ),
                "evidence_complete": complete,
                "evidence_invalid": invalid,
                "invalid_evidence_attempts": sum(bool(item.get("invalid_evidence")) for item in items),
                "median_seconds": round(median(item["seconds"] for item in items), 3),
                "eligible": 2 * complete >= len(items) and invalid == 0,
            })
        summaries[kind] = sorted(scores, key=lambda row: (
            not row["eligible"], -row["exact"], row["failures"], row["median_seconds"],
        ))
    return summaries


def main():
    from VQA.evaluation.format_harnesses import count_with_harness

    sample, counts = load_sample()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    manifest = {"model": "gemini-4-hydrogen", "split": "held-out", "seed": SEED,
                "held_out_buckets": sorted(HELD_OUT_BUCKETS),
                "sample": sample, "dataset_counts": counts}
    manifest_path = OUTPUT / "manifest.json"
    if manifest_path.exists() and json.loads(manifest_path.read_text()) != manifest:
        raise ValueError("Saved evaluation settings differ. Choose another OUTPUT directory.")
    write_json(manifest_path, manifest)
    log = OUTPUT / "results.jsonl"
    rows = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    done = {(row["id"], row["harness"]) for row in rows}
    def evaluate(kind, case, harness):
        started = perf_counter()
        result = count_with_harness(Path(case["path"]), case["question"], harness)
        return {**case, **asdict(result), "format": kind, "harness": harness,
                "seconds": perf_counter() - started}

    with log.open("a", encoding="utf-8") as stream, ThreadPoolExecutor(max_workers=WORKERS) as executor:
        pending = [
            executor.submit(evaluate, kind, case, harness)
            for kind, cases in sample.items() for case in cases for harness in HARNESSES[kind]
            if (case["id"], harness) not in done
        ]
        for future in as_completed(pending):
            row = future.result()
            rows.append(row)
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            stream.flush()
            print(f"{row['format']} row {row['id']} {row['harness']}: {row['status']} ({row['seconds']:.2f} s)", flush=True)
    rows.sort(key=lambda row: (row["format"], row["id"], row["harness"]))
    summary = summarize(rows)
    write_json(OUTPUT / "summary.json", summary)
    write_report(OUTPUT / "report.html", rows, summary)
    for kind, scores in summary.items():
        print(kind, json.dumps(scores))


if __name__ == "__main__":
    main()
