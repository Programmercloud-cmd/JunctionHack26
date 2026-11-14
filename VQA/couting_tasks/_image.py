"""Count objects in raster images with independent recount."""

import json

from ._recount import independent_recount
from ._result import CountResult, InvalidEvidence, valid_box
from .models import gemini


def count_image(path, question):
    def call(image, prompt, schema):
        answer = gemini.complete(image, prompt, gemini.MODEL, schema=schema)
        if not answer or not answer.strip():
            raise ValueError("Gemini returned no structured answer.")
        answer = answer.strip()
        first_line, _, remainder = answer.partition("\n")
        if first_line.lower() in {"```json", "```"} and remainder.endswith("\n```"):
            answer = remainder[:-4].strip()
        result = json.loads(answer)
        if not isinstance(result, dict) or type(result.get("count")) is not int or result["count"] < 0:
            raise ValueError("Expected a nonnegative integer count.")
        if not isinstance(result.get("boxes"), list) or not all(valid_box(box) for box in result["boxes"]):
            raise InvalidEvidence("Gemini proposed an invalid image bounding box.")
        return result

    result = independent_recount(path, question, call)
    count = result["count"]
    boxes = list({tuple(box): box for box in result["boxes"]}.values())
    if len(boxes) > count:
        raise InvalidEvidence("The image response has more distinct boxes than counted occurrences.")
    gaps = [f"{count - len(boxes)} counted occurrence(s) lack a box."] if len(boxes) < count else []
    if count == 0:
        gaps.append("The source does not independently verify this visual zero.")
    evidence = [
        {"kind": "image", "occurrence_id": number, "box": box}
        for number, box in enumerate(boxes, 1)
    ]
    return CountResult(count=count, boxes=boxes, evidence=evidence, gaps=gaps, detail=result["source"])
