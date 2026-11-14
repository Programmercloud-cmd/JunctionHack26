"""Load benchmark rows and deterministically split by source image."""

import hashlib
import json
from collections import Counter
from pathlib import Path

from PIL import Image


def load_cases(questions_file: Path):
    cases = {"dev": [], "held-out": []}
    exclusions = Counter()
    images = {}
    with questions_file.open(encoding="utf-8") as source:
        for number, line in enumerate(source, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            question = row["question"].strip()
            path = questions_file.parent / row["path"]
            if row["type"] != "count":
                exclusions["other task type"] += 1
            elif path.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
                exclusions["unsupported file type"] += 1
            elif not path.is_file():
                exclusions["missing image"] += 1
            elif type(row["answer"]) is not int or row["answer"] < 0:
                exclusions["invalid count label"] += 1
            else:
                canonical = path.resolve()
                if canonical not in images:
                    try:
                        with Image.open(canonical) as image:
                            valid = image.format in {"PNG", "JPEG"}
                            image.verify()
                    except (OSError, SyntaxError):
                        valid = False
                    images[canonical] = None
                    if valid:
                        with canonical.open("rb") as raster:
                            images[canonical] = hashlib.file_digest(raster, "sha256").hexdigest()
                digest = images[canonical]
                if digest is None:
                    exclusions["invalid raster image"] += 1
                    continue
                split = "held-out" if int(digest[:8], 16) % 5 == 0 else "dev"
                cases[split].append({
                    "id": number, "split": split, "image": str(canonical),
                    "digest": digest, "question": question, "expected": row["answer"],
                })
    return cases, dict(exclusions)
