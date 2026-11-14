"""Shared, source-linked scene contract. Render assumptions are never source facts."""
import math
from typing import Literal

from pydantic import Field, model_validator
from .schemas import StrictModel
from .building import Alignment, Calibration, Measurement


class SourceRef(StrictModel):
    kind: Literal["ifc", "image"]
    global_id: str | None = None
    step_id: int | None = None
    page: int | None = None
    bbox: list[float] | None = None

    @model_validator(mode="after")
    def valid_source(self):
        if self.kind == "ifc":
            if not self.global_id or not self.step_id:
                raise ValueError("IFC source needs GlobalId and STEP ID")
        else:
            if not self.page or not self.bbox or len(self.bbox) != 4:
                raise ValueError("Image source needs page and bbox")
            l, t, r, b = self.bbox
            if not all(math.isfinite(x) and 0 <= x <= 1 for x in self.bbox) or l >= r or t >= b:
                raise ValueError("Invalid source region")
        return self


class Property(StrictModel):
    name: str
    value: str | float | int | bool | None
    unit: str | None = None
    origin: Literal["source", "derived"] = "source"


class Assumption(StrictModel):
    property: str
    value: str | float
    unit: str | None = None
    reason: str


class Geometry(StrictModel):
    type: Literal["mesh", "box", "floor"]
    positions: list[float] = Field(default_factory=list)
    indices: list[int] = Field(default_factory=list)
    center: list[float] | None = None
    size: list[float] | None = None
    rotation_z: float = 0
    polygon: list[list[float]] | None = None
    elevation: float = 0

    @model_validator(mode="after")
    def valid_geometry(self):
        if self.type == "mesh":
            if len(self.positions) < 9 or len(self.positions) % 3 or len(self.indices) < 3 or len(self.indices) % 3:
                raise ValueError("Invalid mesh arrays")
            if not all(math.isfinite(x) for x in self.positions):
                raise ValueError("Nonfinite mesh")
            if min(self.indices) < 0 or max(self.indices) >= len(self.positions) // 3:
                raise ValueError("Mesh index out of bounds")
        elif self.type == "box":
            if not self.center or not self.size or len(self.center) != 3 or len(self.size) != 3:
                raise ValueError("Box needs three coordinates")
            if not all(math.isfinite(x) for x in self.center + self.size) or min(self.size) <= 0:
                raise ValueError("Invalid box dimensions")
        else:
            if not self.polygon or not 3 <= len(self.polygon) <= 100:
                raise ValueError("Invalid polygon")
            if any(len(p) != 2 or not all(math.isfinite(v) for v in p) for p in self.polygon):
                raise ValueError("Invalid polygon coordinates")
        return self


class SceneElement(StrictModel):
    id: str
    kind: Literal["room", "wall", "door", "window", "other"]
    name: str
    ifc_type: str | None = None
    storey_id: str | None = None
    source: SourceRef
    properties: list[Property] = Field(default_factory=list)
    assumptions: list[Assumption] = Field(default_factory=list)
    geometry_origin: Literal["extracted", "inferred"] = "extracted"
    geometry: Geometry | None = None
    evidence_basis: Literal["observed", "inferred", "display_assumption"] = "observed"
    note: str = ""


class SceneFloor(StrictModel):
    id: str
    label: str
    source: SourceRef
    order: int | None = None
    scale_status: Literal["known", "unknown"] = "unknown"
    rotation_degrees: float = 0
    alignment_status: Literal["supported", "schematic"] = "schematic"
    observations: list[str] = Field(default_factory=list)
    assumptions: list[Assumption] = Field(default_factory=list)
    calibration: Calibration | None = None
    alignment: Alignment | None = None
    measurements: list[Measurement] = Field(default_factory=list)
    transform: list[list[float]] = Field(default_factory=list)


class Scene(StrictModel):
    version: int = 1
    document_id: str
    source_kind: Literal["ifc", "image"]
    units: Literal["m", "relative"]
    up_axis: Literal["z"] = "z"
    source_page: int | None = None
    elements: list[SceneElement]
    warnings: list[str] = Field(default_factory=list)
    catalog_complete: bool
    derived: bool = False
    artifact_id: str | None = None
    floors: list[SceneFloor] = Field(default_factory=list)
    ifc_url: str | None = None
    layout: Literal["native", "schematic", "aligned"] = "native"

    @model_validator(mode="after")
    def unique_ids(self):
        if len({e.id for e in self.elements}) != len(self.elements):
            raise ValueError("Duplicate scene IDs")
        return self
