"""Source marks and model anchors stay attributed and pinned to their saved frame."""
from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.annotations import AnnotationRequest, save_annotation, selected_annotations, list_annotations, apply_measurements
from app.bundles import BuildingStore
from app.documents import DocumentError
from test_backend import png
from test_bundles_revisions import build
from test_ifc_generate import description


def test_source_annotation_survives_store_restart_without_modifying_originals(tmp_path):
    store = BuildingStore(tmp_path)
    document = store.add(png(), "plan.png")
    row = save_annotation(store, document.id, {"revision_id": document.revision_id, "kind": "stroke", "space": "source",
        "page": 1, "points": [[.2, .3], [.6, .7]], "label": "This area"})
    store.close()
    store = BuildingStore(tmp_path)
    try:
        assert list_annotations(store, document.id) == [row]
        assert selected_annotations(store, store.get(document.id), [row["id"]]) == [row]
        assert row["source_id"] == document.sources[0]["source_id"]
        assert row["provenance"] == "user_provided"
        assert store.get(document.id).source_bytes == png()
    finally:
        store.close()


@pytest.mark.parametrize("change", [
    {"points": [[float("nan"), .2]]}, {"points": [[1.1, .2]]}, {"points": [[.2, .2, .3]]},
    {"kind": "measurement", "points": [[.1, .1], [.3, .3]]},
    {"kind": "measurement", "points": [[.1, .1], [.1, .1]], "value": 3, "unit": "m"},
    {"kind": "point", "value": 3}, {"space": "model", "points": [[1, 2, 3]], "object_id": "x", "page": 1},
])
def test_invalid_marks_rejected(change):
    with pytest.raises(ValidationError):
        AnnotationRequest.model_validate({"revision_id": "revision", "kind": "point", "space": "source", "page": 1,
                                         "points": [[.1, .2]], **change})


def test_model_anchor_is_local_and_never_rebound_to_new_revision(tmp_path):
    store = BuildingStore(tmp_path)
    try:
        document = build(store, store.add(png(), "plan.png"), description())
        element = next(e for e in document.scene.elements if e.geometry)
        row = save_annotation(store, document.id, {"revision_id": document.revision_id, "kind": "point", "space": "model",
            "object_id": element.id, "points": [[0, 0, 0]]})
        assert row["floor_id"] == element.storey_id
        assert selected_annotations(store, document, [row["id"]])[0]["points"] == [[0, 0, 0]]
        newer = store.commit(store.prepare(document), document.revision_id, status="newer")
        with pytest.raises(DocumentError, match="another source/model revision"):
            selected_annotations(store, newer, [row["id"]])
        with pytest.raises(DocumentError, match="stale"):
            save_annotation(store, document.id, {"revision_id": document.revision_id, "kind": "point", "space": "model",
                "object_id": element.id, "points": [[0, 0, 0]]})
        # Explicit old-source navigation can still inspect its pinned attachment.
        assert selected_annotations(store, document, [row["id"]]) == [row]
    finally:
        store.close()


def test_wrong_source_identity_and_ambiguous_measurement_never_mutate(tmp_path):
    store = BuildingStore(tmp_path)
    try:
        document = build(store, store.add(png(), "plan.png"), description())
        with pytest.raises(DocumentError):
            save_annotation(store, document.id, {"revision_id": document.revision_id, "kind": "point", "space": "source",
                "page": 1, "source_id": "b" * 64, "points": [[.2, .2]]})
        row = save_annotation(store, document.id, {"revision_id": document.revision_id, "kind": "measurement", "space": "source",
            "page": 1, "points": [[.1, .2], [.7, .2]], "value": 6, "unit": "m"})
        with pytest.raises(DocumentError, match="Choose the floor"):
            apply_measurements(document, [row])
        assert store.get(document.id).revision_id == document.revision_id
        assert not store.get(document.id).user_values
    finally:
        store.close()


def test_multiple_consistent_measurements_share_scale_and_preserve_each_input(tmp_path):
    store = BuildingStore(tmp_path)
    try:
        document = build(store, store.add(png(), "plan.png"), description())
        floor_id = document.description.floors[0].persistent_id
        rows = [save_annotation(store, document.id, {"revision_id": document.revision_id, "kind": "measurement", "space": "source",
            "page": 1, "floor_id": floor_id, "points": [[.1, .2], [end, .2]], "value": length, "unit": "m"})
            for end, length in [(.7, 6), (.4, 3)]]
        candidate = apply_measurements(document, rows)
        assert candidate.description.floors[0].calibration.length_m == 6
        inputs = candidate.user_values[0]["measurement_annotations"]
        assert [row["annotation_id"] for row in inputs] == [row["id"] for row in rows]
        assert [row["value"] for row in inputs] == [6, 3]
        assert all(row["provenance"] == "user_provided" for row in inputs)
        assert store.get(document.id).revision_id == document.revision_id
    finally:
        store.close()


def test_conflicting_same_floor_measurements_clarify_without_applying_arbitrary_scale(tmp_path):
    store = BuildingStore(tmp_path)
    try:
        document = build(store, store.add(png(), "plan.png"), description())
        rows = [save_annotation(store, document.id, {"revision_id": document.revision_id, "kind": "measurement", "space": "source",
            "page": 1, "floor_id": document.description.floors[0].persistent_id,
            "points": [[.1, .2], [.7, .2]], "value": length, "unit": "m"}) for length in (6, 12)]
        with pytest.raises(DocumentError, match="different plan scales"):
            apply_measurements(document, rows)
        assert store.get(document.id).revision_id == document.revision_id
        assert not store.get(document.id).user_values
    finally:
        store.close()


def test_model_measurement_anchors_each_endpoint_to_its_own_floor_object(tmp_path):
    from test_ifc_generate import floor
    store = BuildingStore(tmp_path)
    try:
        document = build(store, store.add(png(), "plan.png"), description(floor(label="Lower"), floor(label="Upper")))
        objects = [next(e for e in document.scene.elements if e.storey_id == f.id and e.geometry)
                   for f in document.scene.floors]
        row = save_annotation(store, document.id, {"revision_id": document.revision_id, "kind": "measurement", "space": "model",
            "object_id": objects[0].id, "point_object_ids": [element.id for element in objects],
            "points": [[0, 0, 0], [0, 0, 0]], "value": 3, "unit": "m"})
        assert row["point_object_ids"] == [element.id for element in objects]
        assert row["floor_id"] == objects[0].storey_id
        assert row["provenance"] == "user_provided"
        assert selected_annotations(store, document, [row["id"]]) == [row]
        with pytest.raises(DocumentError, match="Every model point"):
            save_annotation(store, document.id, {"revision_id": document.revision_id, "kind": "stroke", "space": "model",
                "object_id": objects[0].id, "point_object_ids": [objects[0].id, "unknown"], "points": [[0, 0, 0], [1, 0, 0]]})
    finally:
        store.close()
