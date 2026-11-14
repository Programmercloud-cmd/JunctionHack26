"""Run the 25-question held-out benchmark with settings defined here."""

import sys
from pathlib import Path


VQA_DIR = Path(__file__).resolve().parents[1]
QUESTIONS_FILE = VQA_DIR.parent / "junction-dataset-preview" / "questions.jsonl"
OUTPUT_DIR = VQA_DIR / "benchmark-runs" / "held-out-4-current"
QUESTION_COUNT = 4
SEED = 72

if not __package__:
    sys.path.insert(0, str(VQA_DIR.parent))

from VQA.evaluation import benchmark


def main() -> None:
    benchmark.main([
        "--questions", str(QUESTIONS_FILE),
        "--output", str(OUTPUT_DIR),
        "--split", "held-out",
        "--harness", "all",
        "--limit", str(QUESTION_COUNT),
        "--seed", str(SEED),
        "--max-calls", str(9 * QUESTION_COUNT),
    ])


if __name__ == "__main__":
    main()
