"""Bounded native IFC catalog and geometry import. No inferred building facts."""
import math
import re

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.element
import ifcopenshell.util.unit
import ifcopenshell.util.placement

from .documents import DocumentError
from .scene import Assumption, Geometry, Property, Scene, SceneElement, SceneFloor, SourceRef

MAX_IFC_BYTES = 25 * 1024 * 1024
MAX_ELEMENTS = 4000
MAX_TRIANGLES = 1_000_000
MAX_PROPERTIES = 48
MAX_PROPERTY_TEXT = 500
GLOBAL_ID = re.compile(r"[0-3][0-9A-Za-z_$]{21}\Z")


def _kind(element):
    for ifc_type, kind in (("IfcSpace", "room"), ("IfcWall", "wall"),
                           ("IfcDoor", "door"), ("IfcWindow", "window")):
        if element.is_a(ifc_type):
            return kind
    return "other"


def _unit_symbol(unit):
    if unit is None:
        return None
    try:
        return ifcopenshell.util.unit.get_unit_symbol(unit)
    except Exception:
        # Preserve a supplied unit's name even when the library lacks a symbol.
        return str(getattr(unit, "Name", None) or unit.is_a())[:80]


def _properties(element, model, length_unit, storey):
    """Prioritize dimensions and identity; preserve raw values in their source units."""
    result = []
    omitted = False

    def append(name, value, unit=None):
        nonlocal omitted
        if hasattr(value, "wrappedValue"):
            value = value.wrappedValue
        if not isinstance(value, (str, float, int, bool, type(None))):
            omitted = True
            return
        if isinstance(value, float) and not math.isfinite(value):
            omitted = True
            return
        if len(result) >= MAX_PROPERTIES:
            omitted = True
            return
        if isinstance(value, str) and len(value) > MAX_PROPERTY_TEXT:
            omitted = True
            value = value[:MAX_PROPERTY_TEXT] + "… [truncated]"
        result.append(Property(name=str(name)[:200], value=value, unit=unit))

    for attr in ("Name", "Description", "ObjectType", "Tag", "PredefinedType"):
        if (value := getattr(element, attr, None)) is not None:
            append(attr, value)
    for attr in ("OverallHeight", "OverallWidth"):
        if (value := getattr(element, attr, None)) is not None:
            append(attr, value, length_unit)
    if storey is not None:
        append("Storey.Name", storey.Name)
        if storey.Elevation is not None:
            append("Storey.Elevation", storey.Elevation, length_unit)

    definitions = []
    for relation in getattr(element, "IsDefinedBy", ()):
        if relation.is_a("IfcRelDefinesByProperties"):
            definition = relation.RelatingPropertyDefinition
            if hasattr(definition, "is_a"):
                definitions.append(("", definition))
            else:
                # IFC4 can encode multiple definitions in a property-definition set.
                try:
                    definitions.extend(("", item) for item in definition)
                except TypeError:
                    omitted = True
    type_element = ifcopenshell.util.element.get_type(element)
    if type_element:
        definitions.extend(("Type::", definition) for definition in getattr(type_element, "HasPropertySets", ()) or ())
    for prefix, definition in definitions:
        members = getattr(definition, "HasProperties", None) or getattr(definition, "Quantities", None)
        if members is None:
            omitted = True
            continue
        for prop in members:
            name = f"{prefix}{definition.Name or definition.is_a()}.{prop.Name}"
            try:
                unit = _unit_symbol(ifcopenshell.util.unit.get_property_unit(prop, model))
                if prop.is_a("IfcPropertySingleValue"):
                    append(name, prop.NominalValue, unit)
                elif prop.is_a("IfcPhysicalSimpleQuantity"):
                    append(name, prop[3], unit)
                else:
                    omitted = True
            except Exception:
                omitted = True
    return result, omitted


def _catalog(model):
    # Openings/subtraction features are not physical objects to display or count twice.
    products = [element for element in model.by_type("IfcElement")
                if not element.is_a("IfcFeatureElement")]
    products.extend(model.by_type("IfcSpace"))
    if len(products) > MAX_ELEMENTS:
        raise DocumentError(f"IFC exceeds the {MAX_ELEMENTS:,}-element limit. Export a smaller model; the inventory was not truncated.", 413)
    if not products:
        raise DocumentError("This IFC contains no supported building elements or spaces.")
    seen = set()
    for element in products:
        global_id = getattr(element, "GlobalId", None)
        if not isinstance(global_id, str) or not GLOBAL_ID.fullmatch(global_id) or global_id in seen:
            raise DocumentError("IFC contains missing, invalid or duplicate element GlobalIds; stable source selection is unavailable.")
        seen.add(global_id)
    return products


def _mesh_elements(model, products, elements):
    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", True)
    settings.set("convert-back-units", False)
    # IfcOpenShell emits metres here, including placements. Do not apply project scale again.
    triangles = 0
    try:
        iterator = ifcopenshell.geom.iterator(settings, model, 1, include=products)
        ready = iterator.initialize()
        while ready:
            shape = iterator.get()
            target = elements.get(shape.guid)
            if target is not None:
                try:
                    positions = list(shape.geometry.verts)
                    indices = list(shape.geometry.faces)
                    triangles += len(indices) // 3
                    if triangles > MAX_TRIANGLES:
                        raise DocumentError(f"IFC exceeds the {MAX_TRIANGLES:,}-triangle limit. Export a smaller or simpler model.", 413)
                    target.geometry = Geometry(type="mesh", positions=positions, indices=indices)
                except DocumentError:
                    raise
                except Exception:
                    # Invalid/unrenderable geometry does not erase source facts from the catalog.
                    target.geometry = None
            ready = iterator.next()
    except DocumentError:
        raise
    except Exception:
        # Keep any completed meshes and mark all remaining elements unavailable through warnings.
        pass


def _supplied_storey(element):
    """Containment may be indirect through spaces or aggregation; ambiguity is visible."""
    found={};visited=set();pending=[element]
    while pending:
        current=pending.pop()
        if current.id() in visited:continue
        visited.add(current.id())
        if current.is_a('IfcBuildingStorey'):
            found[current.id()]=current
            continue
        pending.extend(r.RelatingStructure for r in getattr(current,'ContainedInStructure',()))
        pending.extend(r.RelatingObject for r in getattr(current,'Decomposes',()) if r.is_a('IfcRelAggregates') or r.is_a('IfcRelNests'))
    return next(iter(found.values())) if len(found)==1 else None


def _native_floors(model, elements, scale):
    """Expose supplied storeys even when their own representation is absent."""
    floors = []
    for storey in model.by_type("IfcBuildingStorey"):
        if not GLOBAL_ID.fullmatch(storey.GlobalId or "") or any(f.id == storey.GlobalId for f in floors):
            raise DocumentError("IFC storeys need unique usable GlobalIds for floor selection.")
        elevation = None
        if storey.ObjectPlacement:
            try:
                elevation = float(ifcopenshell.util.placement.get_local_placement(storey.ObjectPlacement)[2,3]) * scale
            except Exception:
                pass
        if elevation is None and storey.Elevation is not None:
            elevation = float(storey.Elevation) * scale
        members = [e for e in elements.values() if e.storey_id == storey.GlobalId and e.geometry]
        zs = [z for e in members for z in e.geometry.positions[2::3]]
        supported = elevation is not None and math.isfinite(elevation)
        base = elevation if supported else min(zs) if zs else 0
        floors.append(SceneFloor(id=storey.GlobalId, label=str(storey.Name or "Unnamed storey"),
            source=SourceRef(kind="ifc",global_id=storey.GlobalId,step_id=storey.id()),
            scale_status="known",base_elevation=base,
            elevation_basis="Supplied IFC storey placement/elevation" if supported else "Contained geometry display reference" if zs else "Unavailable; no supplied elevation or geometry",
            reference_height=max(zs)-base if zs and max(zs)>base else None,
            reference_height_basis="Contained geometry extent for clipping; not a measured storey height" if zs and max(zs)>base else "Unavailable"))
    supported = sorted([f for f in floors if f.elevation_basis.startswith("Supplied")], key=lambda f:f.base_elevation)
    for floor in supported:
        higher = next((other for other in supported if other.base_elevation > floor.base_elevation), None)
        if higher:
            floor.reference_height = higher.base_elevation-floor.base_elevation
            floor.reference_height_basis = "Difference between supplied IFC storey elevations; clipping reference"
    uncontained = [z for e in elements.values() if not e.storey_id and e.geometry for z in e.geometry.positions[2::3]]
    reference = ({"base_elevation":min(uncontained),"reference_height":max(uncontained)-min(uncontained),
                  "basis":"Uncontained geometry extent; scene-wide display clipping reference"} if uncontained else None)
    return floors, reference


def import_ifc(data: bytes, document_id: str) -> Scene:
    if not data or len(data) > MAX_IFC_BYTES:
        raise DocumentError("IFC must be non-empty and at most 25 MiB.", 413 if data else 400)
    if not data.lstrip().startswith(b"ISO-10303-21;"):
        raise DocumentError("Use an uncompressed IFC STEP file beginning ISO-10303-21;.", 415)
    try:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = data.decode("latin-1")
        model = ifcopenshell.file.from_string(text)
        from .ifc_artifact import artifact_from_model
        artifact = artifact_from_model(model, document_id)
        if artifact:
            return artifact[0]
        products = _catalog(model)
        length_unit = ifcopenshell.util.unit.get_project_unit(model, "LENGTHUNIT")
        scale = ifcopenshell.util.unit.calculate_unit_scale(model)
        if length_unit is None or not math.isfinite(scale) or scale <= 0:
            raise DocumentError("IFC has no usable project length unit; metre geometry cannot be established.")
        symbol = _unit_symbol(length_unit)
        elements = {}
        omitted_count = 0
        metadata_warnings = 0
        for element in products:
            try:
                storey = _supplied_storey(element)
            except Exception:
                storey = None
                metadata_warnings += 1
            try:
                properties, omitted = _properties(element, model, symbol, storey)
                omitted_count += int(omitted)
            except Exception:
                properties = []
                metadata_warnings += 1
            elements[element.GlobalId] = SceneElement(
                id=element.GlobalId, kind=_kind(element), name=str(element.Name or element.is_a())[:500],
                ifc_type=element.is_a(), storey_id=storey.GlobalId if storey else None,
                source=SourceRef(kind="ifc", global_id=element.GlobalId, step_id=element.id()),
                properties=properties, geometry_origin="extracted", geometry=None,
            )
        _mesh_elements(model, products, elements)
        missing = sum(element.geometry is None for element in elements.values())
        warnings = ["Counts describe recorded objects in the uploaded IFC, not completeness of the physical building."]
        if missing:
            warnings.append(f"{missing} of {len(elements)} source elements have no renderable geometry; they remain in the catalog and counts.")
        if omitted_count:
            warnings.append(f"Property view is bounded to {MAX_PROPERTIES} primitive values per element; complex, excess or long values were omitted/truncated for {omitted_count} elements.")
        if metadata_warnings:
            warnings.append(f"Some optional property or storey metadata could not be read ({metadata_warnings} occurrences); object identity and types were retained.")
        floors, reference = _native_floors(model, elements, scale)
        if any(e.storey_id is None for e in elements.values()):
            warnings.append("Some source objects have no unique supplied storey containment; floor assignment was not invented.")
        return Scene(document_id=document_id, source_kind="ifc", units="m", elements=list(elements.values()),
                     warnings=warnings, catalog_complete=True, floors=floors, uncontained_reference=reference)
    except DocumentError:
        raise
    except Exception:
        raise DocumentError("Could not import this IFC. Use a valid IFC2X3 or IFC4 STEP building model.") from None
