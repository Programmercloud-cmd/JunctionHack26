"""Count and locate objects in construction blueprints."""

import json
from pathlib import Path

from ._recount import independent_recount
from .models import gemini, kimi, qwen


_PROVIDERS = {"gemini": gemini, "kimi": kimi, "qwen": qwen}


def count_objects(
    image_path: str | Path, prompt: str, provider: str, model: str
) -> tuple[int, list[list[int]]]:
    """Return (count, boxes) after two independent counts and optional adjudication.

    Accepts PNG or JPEG files. Boxes use normalized [xmin, ymin, xmax, ymax]
    coordinates on a 0–1000 scale. Some counted objects may lack a box.
    """
    adapter = _PROVIDERS.get(provider)
    if adapter is None:
        raise ValueError(f"Unknown provider {provider!r}. Choose from {', '.join(_PROVIDERS)}.")
    if not isinstance(model, str) or not model.strip():
        raise ValueError(f"Set a non-empty model ID for provider {provider!r}.")

    path = Path(image_path)
    if path.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
        raise ValueError("The blueprint image must be PNG or JPEG.")

    if provider in {"gemini", "kimi"}:
        from dotenv import load_dotenv

        load_dotenv(Path(__file__).resolve().parents[1] / ".env")

    def call(image, instructions, schema):
        if provider == "gemini":
            answer = adapter.complete(image, instructions, model, schema=schema)
        else:
            instructions += (
                '\nReturn only a JSON object like {"count": 1, "boxes": [[10, 20, 30, 40]]}. '
                'Use a nonnegative integer count and an empty boxes list if nothing can be localized.'
            )
            answer = adapter.complete(image, instructions, model)

        if not answer or not answer.strip():
            raise ValueError(f"{provider}/{model} returned no answer.")
        answer = answer.strip()
        first_line, _, remainder = answer.partition("\n")
        if first_line.lower() in {"```json", "```"} and remainder.endswith("\n```"):
            answer = remainder[:-4].strip()
        result = json.loads(answer)
        if not isinstance(result, dict) or type(result.get("count")) is not int or result["count"] < 0:
            raise ValueError("Expected a nonnegative integer count.")
        boxes = result.get("boxes")
        if not isinstance(boxes, list):
            raise ValueError("Expected a list of boxes.")
        for box in boxes:
            if not (
                isinstance(box, list) and len(box) == 4 and all(type(n) is int for n in box)
                and 0 <= box[0] < box[2] <= 1000 and 0 <= box[1] < box[3] <= 1000
            ):
                raise ValueError(f"Invalid bounding box {box!r}.")
        return result

    result = independent_recount(path, prompt, call)
    return result["count"], result["boxes"]
