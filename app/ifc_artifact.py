"""Reopen our generated IFC as drawing-derived data, never native source facts."""
import base64
import hashlib
import json
import math
from io import BytesIO

import ifcopenshell
import ifcopenshell.util.unit
import ifcopenshell.util.placement
from PIL import Image

from .artifact_schema import ARTIFACT_MARKER, DISPLAY_UNIT, MANIFEST_PROPERTY, PSET_NAME, ArtifactManifest
from .documents import DocumentError, MAX_EDGE, MAX_IFC_UPLOAD, MAX_PAGES, MAX_PIXELS
from .scene import SourceRef, SceneFloor


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


def _provenance(entity, version):
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
    if values.get("ArtifactMarker") != f"BlueprintQA::DrawingDerived:v{version}":
        raise ValueError("Missing element derived marker")
    return values


def _within(inner, outer):
    return all(a >= b - 1e-12 for a, b in zip(inner[:2], outer[:2])) and all(
        a <= b + 1e-12 for a, b in zip(inner[2:], outer[2:]))


def _overlaps(a, b):
    return min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1])


def artifact_from_model(model, document_id):
    """Return (scene, [(page metadata, exact PNG bytes)], manifest) or None for native IFC."""
    if not has_artifact_marker(model):
        return None
    try:
        from .ifc_import import _catalog, _mesh_elements, GLOBAL_ID
        manifest = ArtifactManifest.model_validate_json(_manifest_text(model))
        if manifest.version >= 3 and manifest.description is None:
            raise ValueError("Missing original building description")
        scene = manifest.scene.model_copy(deep=True)
        if (not scene.derived or scene.source_kind != "image" or scene.catalog_complete
                or not manifest.artifact_id or scene.artifact_id != manifest.artifact_id or not scene.floors):
            raise ValueError("Inconsistent derived classification")
        if not manifest.pages or (manifest.version < 5 and len(manifest.pages) > MAX_PAGES):
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
        if manifest.version >= 5:
            source_ids = set()
            mapped_pages = set()
            for source in manifest.sources:
                if source.source_id in source_ids:
                    raise ValueError("Duplicate original source")
                source_ids.add(source.source_id)
                original = base64.b64decode(source.original_base64,validate=True)
                if not original or hashlib.sha256(original).hexdigest() != source.sha256 or source.sha256 != source.source_id:
                    raise ValueError("Original source hash mismatch")
                if source.kind == "pdf" and len(source.pages) > MAX_PAGES:
                    raise ValueError("Original source exceeds per-file page coverage")
                locals_seen = set()
                for mapping in source.pages:
                    number, local = mapping["page"], mapping["source_page"]
                    if number in mapped_pages or local in locals_seen or not isinstance(local,int) or local < 1:
                        raise ValueError("Ambiguous original source page mapping")
                    mapped_pages.add(number);locals_seen.add(local)
                    page = next((p for p in manifest.pages if p.number == number),None)
                    if (not page or page.source_id != source.source_id or page.source_page != local
                            or any(mapping.get(k,getattr(page,k)) != getattr(page,k) for k in ("width","height","sha256"))):
                        raise ValueError("Original source/page metadata mismatch")
            if manifest.sources and mapped_pages != {p.number for p in manifest.pages if p.source_id is not None}:
                raise ValueError("Original source coverage incomplete")
            if not manifest.sources and any(p.source_id or p.source_page for p in manifest.pages):
                raise ValueError("Original source bytes missing")
        by_page = {p.number:p for p in manifest.pages}
        for ref in [f.source for f in scene.floors]+[e.source for e in scene.elements]:
            page=by_page.get(ref.page)
            if page and ((ref.source_id is not None and ref.source_id!=page.source_id)
                         or (ref.source_page is not None and ref.source_page!=page.source_page)):
                raise ValueError("Source reference conflicts with immutable page mapping")
        floor_ids = {f.id for f in scene.floors}
        if len(floor_ids) != len(scene.floors):
            raise ValueError("Duplicate floor identity")
        if manifest.version >= 4:
            from .identities import expected_registry,frame_signature
            expected=expected_registry(manifest.description,manifest.artifact_id)
            registry=manifest.identity_registry
            if (registry.get("version")!=1 or registry.get("objects")!=expected
                    or set(expected)!={e.id for e in scene.elements}|floor_ids):
                raise ValueError("Identity registry disagrees with description and actual inventory")
            tombstones=registry.get("tombstones",[])
            if (len(tombstones)!=len(set(tombstones)) or set(tombstones)&set(expected)
                    or any(not isinstance(i,str) or not GLOBAL_ID.fullmatch(i)for i in tombstones)):
                raise ValueError("Invalid or reassigned deleted identity")
            if set(manifest.frame_registry)!=floor_ids:
                raise ValueError("Incomplete source frame registry")
            if any(expected[e.id]["floor_id"]!=e.storey_id for e in scene.elements):
                raise ValueError("Identity registry assigns an object to another floor")
            for description,floor in zip(manifest.description.floors,scene.floors,strict=True):
                saved=manifest.frame_registry[floor.id]
                if ((description.persistent_id and description.persistent_id!=floor.id)
                        or saved.get("transform")!=floor.transform or saved.get("signature")!=frame_signature(description)
                        or saved.get("known")!=(floor.scale_status=="known") or saved.get("rotation")!=floor.rotation_degrees
                        or saved.get("aligned")!=(floor.alignment_status=="supported")):
                    raise ValueError("Source frame registry disagrees with original floor provenance")
        for floor in scene.floors:
            if floor.source.kind != "image" or floor.source.page not in page_ids:
                raise ValueError("Floor missing original page")
            entity = model.by_guid(floor.id)
            if not entity or not entity.is_a("IfcBuildingStorey"):
                raise ValueError("Missing storey identity")
            metadata = _provenance(entity, manifest.version)
            if (SourceRef.model_validate_json(metadata["Source"]) != floor.source
                    or SceneFloor.model_validate_json(metadata["Floor"]) != floor):
                raise ValueError("Storey metadata disagrees with manifest")
            if manifest.version >= 5:
                actual = ifcopenshell.util.placement.get_local_placement(entity.ObjectPlacement)
                expected = floor.building_transform
                if (not math.isclose(actual[2,3],floor.base_elevation,abs_tol=1e-9)
                        or any(not math.isclose(actual[i,j],expected[i][j],abs_tol=1e-9) for i in (0,1) for j in (0,1))
                        or any(not math.isclose(actual[i,3],expected[i][2],abs_tol=1e-9) for i in (0,1))
                        or entity.Elevation != floor.base_elevation):
                    raise ValueError("Actual storey placement disagrees with recorded building placement")
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
            belongs = (_within(element.source.bbox, floor.source.bbox) if manifest.version == 2
                       else _overlaps(element.source.bbox, floor.source.bbox))
            if element.source.page != floor.source.page or not belongs:
                raise ValueError("Element references another floor region")
            entity = model.by_guid(element.id)
            expected_types = {"room": ("IfcSpace",), "outdoor": ("IfcSpace",), "wall": ("IfcWall",),
                "railing": ("IfcRailing",), "open_edge": ("IfcBuildingElementProxy",),
                "door": ("IfcDoor",), "window": ("IfcWindow",), "stairs": ("IfcStairFlight",),
                "furniture": ("IfcFurnishingElement",), "fixture": ("IfcSanitaryTerminal", "IfcFurnishingElement", "IfcBuildingElementProxy"),
                "other": ("IfcBuildingElementProxy",)}.get(element.kind, ())
            if manifest.version >= 3 and element.representation == "unresolved":
                expected_types = (*expected_types, "IfcBuildingElementProxy")
                if entity.Representation is not None:
                    raise ValueError("Unresolved item has fabricated geometry")
            if entity.is_a() != element.ifc_type or not any(entity.is_a(t) for t in expected_types):
                raise ValueError("Element type disagrees with manifest")
            memberships = ([r.RelatingObject.GlobalId for r in entity.Decomposes if r.is_a("IfcRelAggregates")]
                           if entity.is_a("IfcSpace") else
                           [r.RelatingStructure.GlobalId for r in entity.ContainedInStructure])
            if memberships != [element.storey_id]:
                raise ValueError("Element storey disagrees with IFC containment")
            metadata = _provenance(entity, manifest.version)
            if (SourceRef.model_validate_json(metadata["Source"]) != element.source
                    or json.loads(metadata["Assumptions"]) != [a.model_dump() for a in element.assumptions]
                    or metadata["EvidenceBasis"] != element.evidence_basis or metadata["Note"] != element.note):
                raise ValueError("Element metadata disagrees with manifest")
            if manifest.version >= 3:
                if (metadata.get("Representation") != element.representation
                        or metadata.get("SemanticType") != element.semantic_type
                        or metadata.get("Environment") != element.environment):
                    raise ValueError("Semantic classification disagrees with manifest")
                if element.kind in {"door", "window"} and element.representation != "unresolved":
                    fills = list(entity.FillsVoids)
                    if len(fills) != 1:
                        raise ValueError("Resolved opening lacks a unique void")
                    cuts = list(fills[0].RelatingOpeningElement.VoidsElements)
                    host = elements.get(cuts[0].RelatingBuildingElement.GlobalId) if len(cuts) == 1 else None
                    if not host or host.kind != "wall" or host.storey_id != element.storey_id or host.representation == "unresolved":
                        raise ValueError("Opening has an invalid physical wall host")
        unit = ifcopenshell.util.unit.get_project_unit(model, "LENGTHUNIT")
        if scene.units == "relative":
            if not unit or not unit.is_a("IfcContextDependentUnit") or unit.Name != DISPLAY_UNIT:
                raise ValueError("Unknown scale was converted to a physical unit")
        elif (not all(f.scale_status == "known" and f.calibration for f in scene.floors)
              or not unit or not unit.is_a("IfcSIUnit") or unit.Name != "METRE" or unit.Prefix):
            raise ValueError("Metric geometry lacks calibration")
        _mesh_elements(model, products, elements)
        if manifest.version == 2 and not any(e.geometry for e in elements.values()):
            raise ValueError("No generated IFC geometry could be tessellated")
        missing = sum(e.geometry is None and e.representation != "unresolved" for e in elements.values())
        if missing:
            scene.warnings.append(f"{missing} derived elements could not be rendered; their source references remain available.")
        scene.document_id = document_id
        scene.ifc_url = f"/api/documents/{document_id}/model.ifc"
        from .comparison import build_comparison
        scene.comparison = build_comparison(scene)
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
