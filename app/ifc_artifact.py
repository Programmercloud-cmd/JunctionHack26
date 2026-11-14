"""Reopen our generated IFC as drawing-derived data, never native source facts."""
import base64
import hashlib
import json
from io import BytesIO

import ifcopenshell
import ifcopenshell.util.unit
from PIL import Image

from .artifact_schema import ARTIFACT_MARKER, DISPLAY_UNIT, MANIFEST_PROPERTY, PSET_NAME, ArtifactManifest
from .documents import DocumentError, MAX_EDGE, MAX_IFC_UPLOAD, MAX_PAGES, MAX_PIXELS


def has_artifact_marker(model):
    return (any(PSET_NAME == p.Name for p in model.by_type("IfcPropertySet"))
            or any(ARTIFACT_MARKER.split(":v")[0] in (p.Description or "") for p in model.by_type("IfcProject"))
            or any(u.Name == DISPLAY_UNIT for u in model.by_type("IfcContextDependentUnit")))


def _manifest_text(model):
    projects = model.by_type("IfcProject")
    if len(projects) != 1:
        raise ValueError("One project required")
    values = []
    for rel in model.by_type("IfcRelDefinesByProperties"):
        if projects[0] not in rel.RelatedObjects:
            continue
        pset = rel.RelatingPropertyDefinition
        if not pset.is_a("IfcPropertySet") or pset.Name != PSET_NAME:
            continue
        for prop in pset.HasProperties:
            if prop.Name == MANIFEST_PROPERTY and prop.is_a("IfcPropertySingleValue") and prop.NominalValue:
                values.append(prop.NominalValue.wrappedValue)
    if len(values) != 1 or not isinstance(values[0], str):
        raise ValueError("Missing or duplicated derived manifest")
    return values[0]


def _provenance(entity):
    """Read exactly one own metadata set; duplicate or missing fields are invalid."""
    sets = [r.RelatingPropertyDefinition for r in entity.IsDefinedBy
            if r.is_a("IfcRelDefinesByProperties")
            and r.RelatingPropertyDefinition.is_a("IfcPropertySet")
            and r.RelatingPropertyDefinition.Name == PSET_NAME]
    if len(sets) != 1:
        raise ValueError("Missing or duplicate element provenance")
    values = {}
    for prop in sets[0].HasProperties:
        if prop.Name in values or not prop.is_a("IfcPropertySingleValue") or not prop.NominalValue:
            raise ValueError("Invalid provenance property")
        values[prop.Name] = prop.NominalValue.wrappedValue
    if values.get("ArtifactMarker") != ARTIFACT_MARKER:
        raise ValueError("Missing element derived marker")
    return values


def _within(inner, outer):
    return all(a >= b - 1e-12 for a, b in zip(inner[:2], outer[:2])) and all(
        a <= b + 1e-12 for a, b in zip(inner[2:], outer[2:]))


def artifact_from_model(model, document_id):
    """Return (scene, [(page metadata, exact PNG bytes)], manifest) or None for native IFC."""
    if not has_artifact_marker(model):
        return None
    try:
        from .ifc_import import _catalog, _mesh_elements
        manifest = ArtifactManifest.model_validate_json(_manifest_text(model))
        scene = manifest.scene.model_copy(deep=True)
        if (not scene.derived or scene.source_kind != "image" or scene.catalog_complete
                or not manifest.artifact_id or scene.artifact_id != manifest.artifact_id or not scene.floors):
            raise ValueError("Inconsistent derived classification")
        if not 1 <= len(manifest.pages) <= MAX_PAGES:
            raise ValueError("Source page coverage unavailable")
        restored = []
        for index, page in enumerate(manifest.pages, start=1):
            if page.number != index:
                raise ValueError("Page numbering changed")
            data = base64.b64decode(page.png_base64, validate=True)
            if hashlib.sha256(data).hexdigest() != page.sha256:
                raise ValueError("Source hash mismatch")
            with Image.open(BytesIO(data)) as image:
                if (image.format != "PNG" or image.size != (page.width, page.height)
                        or image.width * image.height > MAX_PIXELS or max(image.size) > MAX_EDGE
                        or getattr(image, "n_frames", 1) != 1):
                    raise ValueError("Invalid original source page")
                image.load()
            restored.append((page, data))
        page_ids = {p.number for p in manifest.pages}
        floor_ids = {f.id for f in scene.floors}
        if len(floor_ids) != len(scene.floors):
            raise ValueError("Duplicate floor identity")
        for floor in scene.floors:
            if floor.source.kind != "image" or floor.source.page not in page_ids:
                raise ValueError("Floor missing original page")
            entity = model.by_guid(floor.id)
            if not entity or not entity.is_a("IfcBuildingStorey"):
                raise ValueError("Missing storey identity")
            metadata = _provenance(entity)
            if (json.loads(metadata["Source"]) != floor.source.model_dump()
                    or json.loads(metadata["Floor"]) != floor.model_dump()):
                raise ValueError("Storey metadata disagrees with manifest")
            if floor.calibration and floor.calibration.source.page != floor.source.page:
                raise ValueError("Wrong calibration page")
            if any(m.source and m.source.page not in page_ids for m in floor.measurements):
                raise ValueError("Measurement references missing source")
        products = _catalog(model)
        elements = {e.id: e for e in scene.elements}
        if set(elements) != {e.GlobalId for e in products}:
            raise ValueError("IFC/manifest element inventory mismatch")
        for element in scene.elements:
            if (element.source.kind != "image" or element.source.page not in page_ids
                    or element.geometry_origin != "inferred" or element.storey_id not in floor_ids
                    or element.geometry is not None or any(p.origin != "derived" for p in element.properties)):
                raise ValueError("Invalid element provenance")
            floor = next(f for f in scene.floors if f.id == element.storey_id)
            if element.source.page != floor.source.page or not _within(element.source.bbox, floor.source.bbox):
                raise ValueError("Element references another floor region")
            entity = model.by_guid(element.id)
            expected_type = {"room": "IfcSpace", "wall": "IfcWall", "door": "IfcDoor", "window": "IfcWindow"}.get(element.kind)
            if entity.is_a() != element.ifc_type or not expected_type or not entity.is_a(expected_type):
                raise ValueError("Element type disagrees with manifest")
            memberships = ([r.RelatingObject.GlobalId for r in entity.Decomposes if r.is_a("IfcRelAggregates")]
                           if entity.is_a("IfcSpace") else
                           [r.RelatingStructure.GlobalId for r in entity.ContainedInStructure])
            if memberships != [element.storey_id]:
                raise ValueError("Element storey disagrees with IFC containment")
            metadata = _provenance(entity)
            if (json.loads(metadata["Source"]) != element.source.model_dump()
                    or json.loads(metadata["Assumptions"]) != [a.model_dump() for a in element.assumptions]
                    or metadata["EvidenceBasis"] != element.evidence_basis or metadata["Note"] != element.note):
                raise ValueError("Element metadata disagrees with manifest")
        unit = ifcopenshell.util.unit.get_project_unit(model, "LENGTHUNIT")
        if scene.units == "relative":
            if not unit or not unit.is_a("IfcContextDependentUnit") or unit.Name != DISPLAY_UNIT:
                raise ValueError("Unknown scale was converted to a physical unit")
        elif (not all(f.scale_status == "known" and f.calibration for f in scene.floors)
              or not unit or not unit.is_a("IfcSIUnit") or unit.Name != "METRE" or unit.Prefix):
            raise ValueError("Metric geometry lacks calibration")
        _mesh_elements(model, products, elements)
        if not any(e.geometry for e in elements.values()):
            raise ValueError("No generated IFC geometry could be tessellated")
        missing = sum(e.geometry is None for e in elements.values())
        if missing:
            scene.warnings.append(f"{missing} derived elements could not be rendered; their source references remain available.")
        scene.document_id = document_id
        scene.ifc_url = f"/api/documents/{document_id}/model.ifc"
        return scene, restored, manifest
    except DocumentError:
        raise
    except Exception:
        raise DocumentError("This drawing-derived IFC has missing, invalid or inconsistent provenance/source pages. It cannot be treated as authoritative IFC evidence.", 422) from None


def load_artifact(data, document_id):
    if len(data) > MAX_IFC_UPLOAD:
        raise DocumentError("Generated IFC exceeds the existing 25 MiB limit, including embedded source pages.", 413)
    try:
        model = ifcopenshell.file.from_string(data.decode("utf-8-sig"))
    except Exception:
        # Native IFC may use a legacy encoding; its existing importer handles it.
        if any(marker.encode() in data for marker in (PSET_NAME, DISPLAY_UNIT, ARTIFACT_MARKER)):
            raise DocumentError("Drawing-derived IFC provenance could not be parsed; no source conclusion was made.", 422) from None
        return None
    return artifact_from_model(model, document_id)
