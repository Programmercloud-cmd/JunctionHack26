"""Count and locate objects in construction blueprints."""

import json
from pathlib import Path

from .models import gemini, kimi, qwen


_PROVIDERS = {"gemini": gemini, "kimi": kimi, "qwen": qwen}
_PROMPT = """Inspect the entire construction blueprint and locate every distinct object
that matches the counting question. Return one tight bounding box per object.
For windows, check every exterior wall and distinguish window symbols from
doors and other openings. Count each matching object only once.

Return a JSON object of the form {"boxes": [[xmin, ymin, xmax, ymax], ...]}.
Use integer coordinates from 0 to 1000, normalized independently by the image
width and height, with the origin at the top left. Use an empty list if there
are no matching objects.

Counting question: """


def count_objects(
    image_path: str | Path, prompt: str, provider: str, model: str
) -> tuple[int, list[list[int]]]:
    """Return (count, boxes) for a PNG or JPEG blueprint.

    Each box is [xmin, ymin, xmax, ymax] in normalized 0–1000 coordinates.
    The count is the number of boxes. The provider must be gemini, kimi,
    or qwen, and the model is a model ID or, for local Qwen, a checkpoint path.
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

    answer = adapter.complete(path, _PROMPT + prompt, model)
    if not answer:
        raise ValueError(f"{provider}/{model} returned no answer.")
    answer = answer.strip()
    first_line, _, remainder = answer.partition("\n")
    if first_line.lower() in {"```json", "```"} and remainder.endswith("\n```"):
        answer = remainder[:-4].strip()

    result = json.loads(answer)
    if not isinstance(result, dict) or not isinstance(result.get("boxes"), list):
        raise ValueError("Expected a JSON object containing a list of boxes.")

    boxes = result["boxes"]
    for box in boxes:
        if not isinstance(box, list) or len(box) != 4 or any(type(n) is not int for n in box):
            raise ValueError(f"Expected four integer coordinates per box, got {box!r}.")
        xmin, ymin, xmax, ymax = box
        if not (0 <= xmin < xmax <= 1000 and 0 <= ymin < ymax <= 1000):
            raise ValueError(f"Invalid bounding box {box!r}.")

    return len(boxes), boxes
