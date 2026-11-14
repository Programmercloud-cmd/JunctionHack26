"""Five counting strategies for the Hydrogen benchmark."""

import json
import os
from pathlib import Path

from ._single_pass import count_objects
from VQA.models.gemini import _RESPONSE_SCHEMA
from VQA._recount import independent_recount as recount


MODEL = "gemini-4-hydrogen"
BOXES = _RESPONSE_SCHEMA["properties"]["boxes"]
BOX = BOXES["items"]
INTEGER = {"type": "integer", "minimum": 0}
IDS = {"type": "array", "items": {"type": "integer"}}
COORDINATES = "Use [xmin, ymin, xmax, ymax] integer coordinates normalized to 0–1000."


def object_schema(**fields):
    return {"type": "object", "properties": fields, "required": list(fields)}


INVENTORY = object_schema(objects={
    "type": "array",
    "items": object_schema(type={"type": "string"}, box=BOX),
})


def load_key():
    from dotenv import dotenv_values

    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        key = dotenv_values(Path(__file__).resolve().parents[2] / ".env").get("GEMINI_API_KEY")
    if not key:
        raise ValueError("Set GEMINI_API_KEY.")
    return key


def current(image, question, call, inventory):
    count, boxes = count_objects(image, question, "gemini", MODEL)
    return {"count": count, "boxes": boxes}


def direct(image, question, call, inventory):
    count = call(image, f"Answer the count question with one integer.\n{question}", INTEGER)
    return {"count": count}


def extract(call, image, question=None):
    task = (
        f"Inventory all visible candidates relevant to this question.\n{question}"
        if question else
        "Inventory visible architectural elements and fixtures across this blueprint. "
        "Use specific object types and list each distinct visible occurrence once."
    )
    objects = call(image, f"{task}\n{COORDINATES}", INVENTORY)["objects"]
    return [
        {"id": index, "type": item["type"], "box": item["box"]}
        for index, item in enumerate(objects, 1)
    ]


def selected_instances(ids, objects):
    by_id = {item["id"]: item for item in objects}
    if any(type(identifier) is not int or identifier not in by_id for identifier in ids):
        raise ValueError("Answer selected an unknown instance ID.")
    selected = list(dict.fromkeys(ids))
    return {
        "count": len(selected), "ids": selected,
        "boxes": [by_id[identifier]["box"] for identifier in selected],
    }


def inventory_then_count(image, question, call, inventory):
    objects = extract(call, image, question)
    answer = call(
        image,
        "Review the image and select the IDs of candidates that should be counted. "
        "Select each distinct matching object once.\n"
        f"Question: {question}\nCandidates: {json.dumps(objects)}",
        object_schema(ids=IDS),
    )
    return {**selected_instances(answer["ids"], objects), "inventory": objects}


def independent_recount(image, question, call, inventory):
    return recount(image, question, call)


def json_based(image, question, call, inventory):
    objects = inventory(image, call)
    answer = call(
        None,
        "Select all unique inventory IDs that match the counting question.\n"
        f"Question: {question}\nInventory: {json.dumps(objects)}",
        object_schema(ids=IDS),
    )
    return selected_instances(answer["ids"], objects)


HARNESSES = {
    "current": current,
    "direct": direct,
    "inventory-then-count": inventory_then_count,
    "independent-recount": independent_recount,
    "json-based": json_based,
}
