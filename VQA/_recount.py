"""Independent counting passes and disagreement resolution."""

import json

from .models.gemini import _RESPONSE_SCHEMA

COORDINATES = "Use [xmin, ymin, xmax, ymax] integer coordinates normalized to 0–1000."
RECOUNT_SCHEMA = {
    "type": "object",
    "properties": {
        "count": {"type": "integer", "minimum": 0},
        "boxes": _RESPONSE_SCHEMA["properties"]["boxes"],
    },
    "required": ["count", "boxes"],
}


def independent_recount(image, question, call):
    print(f"using harness independent recount.", end="\r")
    schema = RECOUNT_SCHEMA
    prompt = (
        f"Count the matching objects. Provide one box per locatable object.\n"
        f"{COORDINATES}\nQuestion: {question}"
    )
    first = call(image, "Inspect the plan by sweeping left to right.\n" + prompt, schema)
    print(f"first prompt done                   ", end="\n")
    second = call(image, "Inspect the plan room by room.\n" + prompt, schema)
    print(f"second prompt done, counts: {first['count']}, {second['count']}", end="\n")
    passes = [first, second]
    if first["count"] == second["count"]:
        return {**first, "source": "first pass (counts agreed)", "passes": passes}
    
    resolved = call(
        image,
        f"{prompt}\nResolve the disagreement by inspecting the blueprint. "
        f"Previous independent proposals: {json.dumps(passes)}",
        schema,
    )
    print(f"resolved call done", end="\n")
    return {**resolved, "source": "adjudication", "passes": passes}

