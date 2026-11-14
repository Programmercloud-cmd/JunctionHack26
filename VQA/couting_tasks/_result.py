"""Counting result shared by image, document, and IFC harnesses."""

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class CountResult:
    count: int | None = None
    boxes: list[list[int]] = field(default_factory=list)
    status: Literal["ok", "unsupported", "failed"] = "ok"
    evidence: list[dict] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    verified_zero: bool = False
    detail: str | None = None
    invalid_evidence: bool = False

    def __iter__(self):
        yield self.count
        yield self.boxes


class UnsupportedCount(ValueError):
    """The source or proposed evidence cannot support the requested count."""


class InvalidEvidence(UnsupportedCount):
    """A proposed evidence locator fails source validation."""


def valid_box(box):
    return (
        isinstance(box, list) and len(box) == 4 and all(type(n) is int for n in box)
        and 0 <= box[0] < box[2] <= 1000 and 0 <= box[1] < box[3] <= 1000
    )


def object_schema(**fields):
    return {"type": "object", "properties": fields, "required": list(fields)}


def array_schema(items):
    return {"type": "array", "items": items}


TEXT = {"type": "string"}
INTEGER = {"type": "integer"}
