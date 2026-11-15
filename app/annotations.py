"""Revision-pinned user marks. Original source pixels are never modified."""
from copy import deepcopy
import math
import time
import uuid
from typing import Literal

from pydantic import Field, model_validator

from .bundles import _atomic_json
from .documents import DocumentError, resolve_reference
from .schemas import StrictModel
from .user_inputs import RefinementRequest, prepare_inputs, METRES, _calibration_scale


class AnnotationRequest(StrictModel):
    revision_id: str
    kind: Literal["point", "stroke", "measurement"]
    space: Literal["source", "model"]
    points: list[list[float]]
    page: int | None = Field(default=None, ge=1)
    source_id: str | None = None
    source_page: int | None = Field(default=None, ge=1)
    object_id: str | None = None
    point_object_ids: list[str] | None = None
    floor_id: str | None = None
    label: str = ""
    value: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    unit: Literal["m", "mm", "cm", "ft", "in"] | None = None

    @model_validator(mode="after")
    def valid_points(self):
        dimensions = 2 if self.space == "source" else 3
        if not self.points or any(len(point) != dimensions or any(not math.isfinite(v) for v in point) for point in self.points):
            raise ValueError("Provide finite coordinates in the selected source/model frame")
        if self.space == "source" and any(not 0 <= v <= 1 for point in self.points for v in point):
            raise ValueError("Source coordinates must be normalized to the original page")
        if self.kind == "point" and len(self.points) != 1:
            raise ValueError("A point has one anchor")
        if self.kind == "stroke" and len(self.points) < 2:
            raise ValueError("A stroke needs at least two anchors")
        if self.kind == "measurement":
            distinct_objects = (self.space == "model" and self.point_object_ids is not None and
                                len(self.point_object_ids) == 2 and self.point_object_ids[0] != self.point_object_ids[1])
            if len(self.points) != 2 or (self.points[0] == self.points[1] and not distinct_objects) or self.value is None or self.unit is None:
                raise ValueError("A measurement needs distinct endpoints and an explicit positive value and unit")
        elif self.value is not None or self.unit is not None:
            raise ValueError("Only measurement marks have a numeric value and unit")
        if self.space == "source" and self.page is None:
            raise ValueError("Choose an original source page")
        if self.space == "source" and self.point_object_ids is not None:
            raise ValueError("Source marks use original-page points, not model anchors")
        if self.space == "model" and (not self.object_id or self.page is not None or self.source_id is not None or self.source_page is not None):
            raise ValueError("A model anchor needs an exact object identity, not a source-page position")
        if self.point_object_ids is not None and (len(self.point_object_ids) != len(self.points) or self.point_object_ids[0] != self.object_id):
            raise ValueError("Each model point needs its own object anchor; object_id identifies the first point")
        return self


class AnnotationStateRequest(StrictModel):
    revision_id: str
    annotation_ids: list[str] = Field(min_length=1)
    active: bool


def list_annotations(store, building_id, *, include_deleted=False):
    store.get(building_id)
    with store.lock:
        path = store.directory(building_id) / "annotations.json"
        if not path.exists():
            return []
        import json
        rows = json.loads(path.read_text())
        return rows if include_deleted else [row for row in rows if not row.get("deleted", False)]


def change_annotations(store, building_id, request):
    """Reversible mark visibility; keep stable IDs and their original provenance."""
    request = AnnotationStateRequest.model_validate(request)
    with store.lock:
        current = store.get(building_id)
        rows = list_annotations(store, building_id, include_deleted=True)
        indexed = {row["id"]: row for row in rows}
        ids = list(dict.fromkeys(request.annotation_ids))
        for identity in ids:
            row = indexed.get(identity)
            if row is None:
                raise DocumentError("A mark is unavailable in this building.", 404)
            expected = (current.geometry_revision_id or current.revision_id) if row["space"] == "model" else current.revision_id
            if row["revision_id"] != request.revision_id or request.revision_id != expected:
                raise DocumentError("The marks belong to an earlier revision; reopen the current view before editing.", 409)
        for identity in ids:
            if request.active:
                indexed[identity].pop("deleted", None)
            else:
                indexed[identity]["deleted"] = True
        _atomic_json(store.directory(building_id) / "annotations.json", rows)
        return {"annotations": deepcopy([indexed[identity] for identity in ids])}


def save_annotation(store, building_id, request):
    request = AnnotationRequest.model_validate(request)
    with store.lock:
        current = store.get(building_id)
        document = store.revision(building_id, request.revision_id)
        expected = (current.geometry_revision_id or current.revision_id) if request.space == "model" else current.revision_id
        if request.revision_id != expected:
            raise DocumentError("The annotation view is stale; reopen the current source/model before drawing.", 409)
        if request.space == "model":
            if not document.scene or document.scene.revision_id != request.revision_id:
                raise DocumentError("The annotation's saved model revision is unavailable.", 409)
            elements = {e.id: e for e in document.scene.elements}
            element = elements.get(request.object_id)
            if not element or element.geometry is None:
                raise DocumentError("Choose an object with saved model geometry.", 422)
            if request.floor_id and request.floor_id != element.storey_id:
                raise DocumentError("The model annotation refers to another floor.", 422)
            request.floor_id = element.storey_id
            request.point_object_ids = request.point_object_ids or [request.object_id] * len(request.points)
            if any(identity not in elements or elements[identity].geometry is None for identity in request.point_object_ids):
                raise DocumentError("Every model point must anchor to geometry in this exact saved revision.", 422)
        else:
            resolve_reference(document, request.page, request.source_id, request.source_page)
            page = next(p for p in document.pages if p.number == request.page)
            request.source_id, request.source_page = page.source_id, page.source_page
            floors = {f.persistent_id: f for f in document.description.floors} if document.description else {}
            if request.floor_id and (request.floor_id not in floors or floors[request.floor_id].source.page != request.page):
                raise DocumentError("Choose a floor depicted on this original page.", 422)
            if request.object_id:
                records = {e.id: e for e in document.scene.elements} if document.scene else {}
                element = records.get(request.object_id)
                if not element or element.source.page != request.page:
                    raise DocumentError("The selected source object is unavailable on this page.", 422)
        annotation = {**request.model_dump(mode="json"), "id": uuid.uuid4().hex,
                      "document_id": building_id, "provenance": "user_provided", "created_at": time.time()}
        rows = list_annotations(store, building_id, include_deleted=True)
        rows.append(annotation)
        _atomic_json(store.directory(building_id) / "annotations.json", rows)
        return annotation


def selected_annotations(store, document, identities, *, geometry_revision_id=None, mutation=False):
    if not identities:
        return []
    if document is None:
        raise DocumentError("Open the building that owns these annotations.", 422)
    available = {row["id"]: row for row in list_annotations(store, document.id)}
    result = []
    for identity in dict.fromkeys(identities):
        row = available.get(identity)
        if not row:
            raise DocumentError("An attached annotation is unavailable in this building.", 422)
        expected = ((geometry_revision_id or document.geometry_revision_id or document.revision_id)
                    if row["space"] == "model" else document.revision_id)
        if row["revision_id"] != expected:
            raise DocumentError("An attached annotation belongs to another source/model revision; reopen that view or draw it again.", 409)
        # Mutations cannot apply a mark from old retained model geometry to a replacement.
        if mutation and row["space"] == "model" and row["revision_id"] != document.revision_id:
            raise DocumentError("A model annotation must target the current revision before rendering.", 409)
        result.append(deepcopy(row))
    return result


def apply_measurements(document, annotations):
    """Apply explicitly scoped plan distances through the existing user-input authority."""
    measurements = [row for row in annotations if row["space"] == "source" and row["kind"] == "measurement"]
    if not measurements:
        return document
    if any(not row.get("floor_id") for row in measurements):
        raise DocumentError("Choose the floor for each blueprint measurement before generating the model.", 422)
    grouped = {}
    for row in measurements:
        grouped.setdefault(row["floor_id"], []).append(row)
    edits = []
    for rows in grouped.values():
        # A floor has one calibration transform. Multiple dimension marks can
        # establish the same scale; keep every mark and use one equivalent basis.
        intervals = []
        for mark in rows:
            page = next(p for p in document.pages if p.number == mark["page"])
            length = mark["value"] * METRES[mark["unit"]]
            scale = _calibration_scale(document, mark["page"], mark["points"], length)
            span = length / scale
            # Each endpoint is localized to original pixels; compare intervals
            # allowing one pixel per axis at each endpoint, not a percentage cap.
            uncertainty = 2 * math.sqrt(2) / page.height
            intervals.append((length / (span + uncertainty),
                              length / max(span - uncertainty, math.ulp(span))))
        if max(low for low, high in intervals) > min(high for low, high in intervals):
            raise DocumentError("These measurements imply different plan scales on the selected floor. Choose which dimension to use for calibration, or assign the marks to their correct views/floors.", 422)
        row = rows[0]
        page = next(p for p in document.pages if p.number == row["page"])
        xs, ys = zip(*row["points"])
        # A line's contextual citation has a one-pixel area; endpoints stay exact.
        box = [max(0, min(xs) - 1 / page.width), max(0, min(ys) - 1 / page.height),
               min(1, max(xs) + 1 / page.width), min(1, max(ys) + 1 / page.height)]
        edits.append({"property": "calibration", "scope": {"floor_id": row["floor_id"]},
                      "value": {"length": row["value"], "segment": row["points"]}, "unit": row["unit"],
                      "source": {"page": row["page"], "source_id": row.get("source_id"),
                                 "source_page": row.get("source_page"), "bbox": box},
                      "reason": "User-drawn measurements " + ", ".join(mark["id"] for mark in rows) +
                                "; equivalent plan scale, using " + row["id"] + "; not original drawing observations."})
    candidate, _, _, _, _ = prepare_inputs(document, RefinementRequest(base_revision_id=document.revision_id, edits=edits))
    # Preserve every selected numerical input alongside the chosen calibration;
    # marks themselves retain their exact coordinates/revisions in the sidecar.
    for value in candidate.user_values:
        if value.get("property") == "calibration":
            rows = grouped.get(value.get("scope", {}).get("floor_id"), [])
            if rows:
                value["measurement_annotations"] = [{"annotation_id": mark["id"], "value": mark["value"],
                    "unit": mark["unit"], "points": deepcopy(mark["points"]), "revision_id": mark["revision_id"],
                    "provenance": "user_provided"} for mark in rows]
    return candidate
