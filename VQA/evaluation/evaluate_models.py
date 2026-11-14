"""Evaluate vision models on randomly selected image-based counting questions."""

import json
import random
import sys
from pathlib import Path
from statistics import median
from textwrap import fill
from time import perf_counter

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from VQA.api import count_objects
from VQA.test import IMAGE_SUFFIXES, QUESTIONS_FILE
from VQA.visualization import draw_bounding_boxes


MODELS = {
    "gemini-3.5-flash": "gemini",
    "gemini-4-hydrogen": "gemini",
    "gemini-4-carbon": "gemini",
    "kimi-k3-1-pro": "kimi",
    "unsloth/Qwen3-VL-4B-Instruct-bnb-4bit": "qwen",
}
QUESTION_COUNT = 3


def main() -> None:
    from matplotlib import pyplot as plt
    from PIL import Image

    with QUESTIONS_FILE.open(encoding="utf-8") as source:
        rows = (json.loads(line) for line in source if line.strip())
        eligible = [
            row for row in rows
            if row.get("type") == "count" and Path(row["path"]).suffix.lower() in IMAGE_SUFFIXES
        ]
    if len(eligible) < QUESTION_COUNT:
        raise ValueError(f"Need {QUESTION_COUNT} image-based counting questions in {QUESTIONS_FILE}.")
    questions = random.sample(eligible, QUESTION_COUNT)

    correct = dict.fromkeys(MODELS, 0)
    errors = dict.fromkeys(MODELS, 0)
    timings = {model: [] for model in MODELS}
    for index, row in enumerate(questions, 1):
        question = row["question"]
        ground_truth = row["answer"]
        image_path = QUESTIONS_FILE.parent / row["path"]
        print(f"\n{index}. {question}\nGround truth: {ground_truth}", flush=True)

        with Image.open(image_path) as source:
            original = source.convert("RGB")
        figure, grid = plt.subplots(2, 3, figsize=(16, 9), layout="constrained")
        axes = grid.flat
        figure.suptitle(fill(question, width=100))
        axes[0].imshow(original)
        axes[0].set_title(f"Original · Ground truth: {ground_truth}")
        for axis in axes:
            axis.set_axis_off()

        for axis, (model, provider) in zip(axes[1:], MODELS.items()):
            label = model.rsplit("/", 1)[-1]
            started = perf_counter()
            try:
                answer, boxes = count_objects(image_path, question, provider, model)
            except Exception as error:
                elapsed = perf_counter() - started
                timings[model].append(elapsed)
                errors[model] += 1
                print(f"  {model}: error after {elapsed:.2f} s ({error})", flush=True)
                axis.set_title(f"{label} · Error · {elapsed:.2f} s")
                continue

            elapsed = perf_counter() - started
            timings[model].append(elapsed)
            matches = answer == ground_truth
            correct[model] += matches
            status = "correct" if matches else "incorrect"
            print(f"  {model}: {answer} ({status}) · {elapsed:.2f} s", flush=True)
            axis.imshow(draw_bounding_boxes(original, boxes))
            axis.set_title(f"{label} · {answer} ({status}) · {elapsed:.2f} s")

    print("\nExact count accuracy and latency (all attempts)")
    for model in MODELS:
        total = len(questions)
        durations = timings[model]
        print(
            f"  {model}: {correct[model]}/{total} correct, {errors[model]} errors"
            f" · {median(durations):.2f} s median · {sum(durations):.2f} s total"
        )
    plt.show()


if __name__ == "__main__":
    main()
