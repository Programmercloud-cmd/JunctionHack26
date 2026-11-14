from collections import Counter
import os
from pathlib import Path

import ifcopenshell
import pytest

from app.documents import DocumentError
from app.ifc_import import import_ifc


def fixture_model(*, millimetres=True):
    model = ifcopenshell.file(schema="IFC4")
    point = model.create_entity("IfcCartesianPoint", Coordinates=(0.0, 0.0, 0.0))
    axes = model.create_entity("IfcAxis2Placement3D", Location=point)
    context = model.create_entity("IfcGeometricRepresentationContext", ContextIdentifier="Model",
                                  ContextType="Model", CoordinateSpaceDimension=3, Precision=1e-5,
                                  WorldCoordinateSystem=axes)
    unit = model.create_entity("IfcSIUnit", UnitType="LENGTHUNIT", Prefix="MILLI" if millimetres else None, Name="METRE")
    units = model.create_entity("IfcUnitAssignment", Units=(unit,))
    model.create_entity("IfcProject", GlobalId=ifcopenshell.guid.new(), Name="Test project",
                        RepresentationContexts=(context,), UnitsInContext=units)
    factor = 1000.0 if millimetres else 1.0
    storey = model.create_entity("IfcBuildingStorey", GlobalId=ifcopenshell.guid.new(), Name="Ground floor", Elevation=2 * factor)
    placement = model.create_entity("IfcLocalPlacement", RelativePlacement=model.create_entity("IfcAxis2Placement3D",
                                    Location=model.create_entity("IfcCartesianPoint", Coordinates=(5 * factor, factor, 2 * factor))))
    profile = model.create_entity("IfcRectangleProfileDef", ProfileType="AREA", XDim=2 * factor, YDim=.1 * factor)
    solid = model.create_entity("IfcExtrudedAreaSolid", SweptArea=profile, Position=axes,
                               ExtrudedDirection=model.create_entity("IfcDirection", DirectionRatios=(0.0, 0.0, 1.0)), Depth=3 * factor)
    representation = model.create_entity("IfcShapeRepresentation", ContextOfItems=context,
                                        RepresentationIdentifier="Body", RepresentationType="SweptSolid", Items=(solid,))
    wall = model.create_entity("IfcWallStandardCase", GlobalId=ifcopenshell.guid.new(), Name="Source wall",
                               ObjectPlacement=placement,
                               Representation=model.create_entity("IfcProductDefinitionShape", Representations=(representation,)))
    window = model.create_entity("IfcWindow", GlobalId=ifcopenshell.guid.new(), Name="Source window",
                                 OverallHeight=1.2 * factor, OverallWidth=factor)
    space = model.create_entity("IfcSpace", GlobalId=ifcopenshell.guid.new(), Name="Room A")
    model.create_entity("IfcRelContainedInSpatialStructure", GlobalId=ifcopenshell.guid.new(),
                        RelatedElements=(wall, window), RelatingStructure=storey)
    model.create_entity("IfcRelAggregates", GlobalId=ifcopenshell.guid.new(), RelatingObject=storey, RelatedObjects=(space,))
    prop = model.create_entity("IfcPropertySingleValue", Name="SpecifiedHeight", NominalValue=model.create_entity("IfcLengthMeasure", 2.3),
                              Unit=model.create_entity("IfcSIUnit", UnitType="LENGTHUNIT", Name="METRE"))
    pset = model.create_entity("IfcPropertySet", GlobalId=ifcopenshell.guid.new(), Name="Dimensions", HasProperties=(prop,))
    model.create_entity("IfcRelDefinesByProperties", GlobalId=ifcopenshell.guid.new(), RelatedObjects=(window,), RelatingPropertyDefinition=pset)
    return model, wall, window, space


def encode(model):
    return model.to_string().encode()


def test_real_geometry_units_world_placement_and_complete_catalog():
    model, wall, window, space = fixture_model()
    scene = import_ifc(encode(model), "document-1")
    assert scene.catalog_complete and scene.units == "m" and scene.up_axis == "z"
    assert Counter(e.kind for e in scene.elements) == {"wall": 1, "window": 1, "room": 1}
    imported = {e.id: e for e in scene.elements}
    mesh = imported[wall.GlobalId].geometry
    assert mesh and mesh.type == "mesh"
    assert min(mesh.positions[0::3]) == pytest.approx(4)
    assert max(mesh.positions[0::3]) == pytest.approx(6)
    assert min(mesh.positions[1::3]) == pytest.approx(.95)
    assert max(mesh.positions[2::3]) == pytest.approx(5)
    assert imported[wall.GlobalId].ifc_type == "IfcWallStandardCase"
    assert imported[window.GlobalId].geometry is None
    assert imported[space.GlobalId].geometry is None
    assert imported[window.GlobalId].source.step_id == window.id()
    assert imported[window.GlobalId].source.global_id == window.GlobalId
    assert imported[wall.GlobalId].storey_id is not None
    assert any("no renderable geometry" in warning for warning in scene.warnings)
    values = {p.name: p for p in imported[window.GlobalId].properties}
    assert values["OverallWidth"].value == 1000
    assert values["OverallWidth"].unit == "mm"
    assert values["Dimensions.SpecifiedHeight"].value == 2.3
    assert values["Dimensions.SpecifiedHeight"].unit == "m"
    assert all(not e.assumptions and e.geometry_origin == "extracted" for e in scene.elements)


def test_metres_not_rescaled_and_ids_stable():
    model, wall, _, _ = fixture_model(millimetres=False)
    first = import_ifc(encode(model), "first")
    second = import_ifc(encode(model), "second")
    assert [e.id for e in first.elements] == [e.id for e in second.elements]
    imported = next(e for e in first.elements if e.id == wall.GlobalId)
    assert max(imported.geometry.positions[0::3]) == pytest.approx(6)


def test_duplicate_global_ids_rejected():
    model, wall, window, _ = fixture_model()
    window.GlobalId = wall.GlobalId
    with pytest.raises(DocumentError, match="GlobalIds"):
        import_ifc(encode(model), "doc")


@pytest.mark.parametrize("data", [b"not ifc", b"ISO-10303-21; invalid"])
def test_bad_ifc_rejected(data):
    with pytest.raises(DocumentError):
        import_ifc(data, "doc")


def test_element_limit_rejects_before_geometry(monkeypatch):
    import app.ifc_import as importer
    model, *_ = fixture_model()
    monkeypatch.setattr(importer, "MAX_ELEMENTS", 2)
    with pytest.raises(DocumentError) as error:
        import_ifc(encode(model), "doc")
    assert error.value.status == 413
    assert "not truncated" in error.value.message


def test_triangle_limit_rejects_instead_of_partial_scene(monkeypatch):
    import app.ifc_import as importer
    model, *_ = fixture_model()
    monkeypatch.setattr(importer, "MAX_TRIANGLES", 1)
    with pytest.raises(DocumentError) as error:
        import_ifc(encode(model), "doc")
    assert error.value.status == 413


def test_geometry_failure_preserves_metadata(monkeypatch):
    import app.ifc_import as importer
    model, *_ = fixture_model()
    class FailedIterator:
        def initialize(self):
            raise RuntimeError("geometry failure")
    monkeypatch.setattr(importer.ifcopenshell.geom, "iterator", lambda *args, **kwargs: FailedIterator())
    scene = import_ifc(encode(model), "doc")
    assert len(scene.elements) == 3 and scene.catalog_complete
    assert all(e.geometry is None for e in scene.elements)
    assert any("3 of 3" in w for w in scene.warnings)


def test_property_limits_disclosed(monkeypatch):
    import app.ifc_import as importer
    model, *_ = fixture_model()
    monkeypatch.setattr(importer, "MAX_PROPERTIES", 1)
    scene = import_ifc(encode(model), "doc")
    assert all(len(e.properties) <= 1 for e in scene.elements)
    assert any("Property view is bounded" in w for w in scene.warnings)


def test_missing_units_rejected():
    model, *_ = fixture_model()
    model.by_type("IfcProject")[0].UnitsInContext = None
    with pytest.raises(DocumentError, match="length unit"):
        import_ifc(encode(model), "doc")


@pytest.mark.skipif(not os.getenv("IFC_SAMPLE"), reason="Set IFC_SAMPLE to the external duplex_arc.ifc preview")
def test_actual_duplex():
    sample = Path(os.environ["IFC_SAMPLE"])
    scene = import_ifc(sample.read_bytes(), "real-sample")
    counts = Counter(e.kind for e in scene.elements)
    assert {kind: counts[kind] for kind in ("room", "wall", "door", "window")} == {
        "room": 21, "wall": 57, "door": 14, "window": 24,
    }
    assert scene.catalog_complete
    assert len({e.id for e in scene.elements}) == len(scene.elements)
    assert sum(e.geometry is not None for e in scene.elements) > 200
