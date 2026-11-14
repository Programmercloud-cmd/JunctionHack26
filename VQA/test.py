"""Run a random image-based counting question."""

import json
import random
import sys
from pathlib import Path
from textwrap import fill

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from VQA.api import count_objects

#VLM = ["kimi", "kimi-k3-1-pro"]
#VLM = ["qwen", "unsloth/Qwen3-VL-4B-Instruct-bnb-4bit"]
VLM = ["gemini", "gemini-4-carbon"]

ID = 200

QUESTIONS_FILE = Path(__file__).resolve().parents[1] / "junction-dataset" / "questions.jsonl"
[PROVIDER, MODEL] = VLM
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}


def main() -> None:
    candidates = []
    with QUESTIONS_FILE.open(encoding="utf-8") as source:
        for line in source:
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("type") == "count" and Path(row["path"]).suffix.lower() in IMAGE_SUFFIXES:
                candidates.append(row)
    if not candidates:
        raise ValueError(f"No PNG or JPEG counting questions found in {QUESTIONS_FILE}.")

    from matplotlib import pyplot as plt
    from PIL import Image

    from VQA.visualization import draw_bounding_boxes

    selected = candidates[ID]
    image_path = QUESTIONS_FILE.parent / selected["path"]
    question = selected["question"]
    ground_truth = selected["answer"]
    print(f"Question: {question}", flush=True)
    print(f"Ground truth: {ground_truth}", flush=True)
    count, boxes = count_objects(image_path, question, PROVIDER, MODEL)
    print(f"Model answer: {count}", flush=True)

    with Image.open(image_path) as source:
        original = source.convert("RGB")
    annotated = draw_bounding_boxes(original, boxes)

    figure, (left, right) = plt.subplots(1, 2, figsize=(14, 8), layout="constrained")
    figure.suptitle(fill(question, width=100))
    left.imshow(original)
    left.set_title(f"Original · Ground truth: {ground_truth}")
    right.imshow(annotated)
    right.set_title(f"Model boxes · Model answer: {count}")
    left.set_axis_off()
    right.set_axis_off()
    plt.show()


if __name__ == "__main__":
    main()
