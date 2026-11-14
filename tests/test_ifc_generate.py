"""Real IFC kernel checks for deterministic, source-linked generated artifacts."""
import base64
import hashlib
from io import BytesIO
import json
from types import SimpleNamespace

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.element
from PIL import Image
import pytest

from app.artifact_schema import ARTIFACT_MARKER, DISPLAY_UNIT, MANIFEST_PROPERTY, PSET_NAME, ArtifactManifest
from app.building import BuildingDescription
from app.documents import DocumentError, DocumentStore
from app.ifc_generate import generate_ifc


def region(page=1,bbox=None):
    return {"page":page,"bbox":bbox or [0,0,1,1]}


def room(label="Room", polygon=None):
    return {"label":label,"polygon":polygon or [[.1,.2],[.7,.2],[.7,.8],[.1,.8]],"basis":"observed","note":"Visible perimeter"}


def floor(label="Ground floor",**overrides):
    return {"label":label,"source":region(),"order":None,"order_basis":"","rotation_degrees":None,
            "orientation_basis":"","calibration":None,"alignment":None,"measurements":[],"rooms":[room()],"openings":[]} | overrides


def description(*floors):
    return BuildingDescription(floors=list(floors or [floor()]),limitations=["Original drawing remains authoritative."])


def manifest(model):
    data = ifcopenshell.util.element.get_psets(model.by_type("IfcProject")[0])[PSET_NAME][MANIFEST_PROPERTY]
    return ArtifactManifest.model_validate_json(data)


def mesh(model, element):
    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords",True)
    shape=ifcopenshell.geom.create_shape(settings,element)
    return SimpleNamespace(verts=list(shape.geometry.verts),faces=list(shape.geometry.faces))


@pytest.fixture
def document(tmp_path):
    output=BytesIO()
    Image.new("RGB",(200,100),"white").save(output,format="PNG")
    store=DocumentStore(tmp_path)
    try:
        yield store.add(output.getvalue(),"source.png")
    finally:
        store.close()


def test_generated_artifact_real_roundtrip_exact_pixels_stable_ids_and_unscaled_units(document):
    data=generate_ifc(description(),document)
    model=ifcopenshell.file.from_string(data.decode())
    artifact=manifest(model)
    assert model.by_type("IfcProject")[0].Description==ARTIFACT_MARKER
    assert model.by_type("IfcContextDependentUnit")[0].Name==DISPLAY_UNIT
    assert not model.by_type("IfcSIUnit")
    assert artifact.scene.derived and artifact.scene.source_kind=="image" and not artifact.scene.catalog_complete
    assert artifact.scene.units=="relative" and artifact.scene.layout=="schematic"
    assert artifact.scene.floors[0].scale_status=="unknown"
    original=document.pages[0].path.read_bytes()
    assert base64.b64decode(artifact.pages[0].png_base64)==original
    assert artifact.pages[0].sha256==hashlib.sha256(original).hexdigest()
    assert all(e.geometry is None and e.geometry_origin=="inferred" and e.source.kind=="image" for e in artifact.scene.elements)
    assert {e.id for e in artifact.scene.elements}=={e.GlobalId for e in model.by_type("IfcWall")+model.by_type("IfcSpace")}
    assert len(model.by_type("IfcSpace"))==1 and len(model.by_type("IfcWall"))==4
    assert all(s.Elevation is None for s in model.by_type("IfcBuildingStorey"))
    for element in model.by_type("IfcWall")+model.by_type("IfcSpace"):
        assert len(mesh(model,element).faces)>0
        props=ifcopenshell.util.element.get_psets(element)[PSET_NAME]
        assert json.loads(props["Source"])["kind"]=="image"
        assert json.loads(props["Assumptions"])
    again=ifcopenshell.file.from_string(generate_ifc(description(),document).decode())
    assert [e.GlobalId for e in again.by_type("IfcRoot")]==[e.GlobalId for e in model.by_type("IfcRoot")]
    room_source=next(e.source for e in artifact.scene.elements if e.kind=="room")
    assert room_source.bbox==[.1,.2,.7,.8]


def test_nonsquare_calibration_rotation_and_transform_preserve_original_coordinates(document):
    calibration={"length_m":6,"segment":[[.1,.2],[.7,.2]],"source":region(bbox=[.1,.1,.7,.2]),"note":"Printed reference length"}
    described=floor(calibration=calibration,rotation_degrees=90,orientation_basis="Rotate visible diagram caption upright",
        measurements=[{"label":"Ceiling height","status":"unknown","value":None,"unit":None,"source":None,"note":"Not shown"}])
    model=ifcopenshell.file.from_string(generate_ifc(description(described),document).decode())
    artifact=manifest(model)
    f=artifact.scene.floors[0]
    assert artifact.scene.units=="m" and f.scale_status=="known"
    assert model.by_type("IfcSIUnit")[0].Name=="METRE"
    assert f.calibration.segment==calibration["segment"] and f.measurements[0].value is None
    matrix=f.transform
    transformed=lambda p:[sum(matrix[i][j]*[p[0],p[1],1][j] for j in range(3)) for i in range(2)]
    assert transformed([.1,.2])==pytest.approx([-1.5,-4.])
    assert transformed([.7,.2])==pytest.approx([-1.5,2.])
    vertices=list(mesh(model,model.by_type("IfcSpace")[0]).verts)
    xs,ys=vertices[0::3],vertices[1::3]
    assert max(xs)-min(xs)==pytest.approx(3)
    assert max(ys)-min(ys)==pytest.approx(6)
    assert next(e for e in artifact.scene.elements if e.kind=="room").source.bbox==[.1,.2,.7,.8]
    assert all(e.properties==[] for e in artifact.scene.elements)


def test_mixed_scale_and_multiple_diagrams_are_not_compared_as_metres(document):
    calibrated=floor(calibration={"length_m":6,"segment":[[.1,.2],[.7,.2]],"source":region(),"note":"Reference"})
    second=floor("Upper floor",order=1,order_basis="Printed first floor label")
    model=ifcopenshell.file.from_string(generate_ifc(description(calibrated,second),document).decode())
    artifact=manifest(model)
    assert len(model.by_type("IfcBuildingStorey"))==2 and len(model.by_type("IfcSpace"))==2
    assert [f.scale_status for f in artifact.scene.floors]==["known","unknown"]
    assert artifact.scene.units=="relative" and model.by_type("IfcContextDependentUnit")[0].Name==DISPLAY_UNIT
    assert artifact.scene.layout=="schematic" and artifact.scene.floors[1].order==1
    assert len({e.storey_id for e in artifact.scene.elements})==2


def test_hosted_doors_windows_have_real_void_fill_relations_and_meshes(document):
    openings=[{"kind":"door","label":"Door","segment":[[.2,.2],[.3,.2]],"source":region(bbox=[.19,.18,.31,.24]),
               "host_room":1,"host_edge":0,"basis":"observed","note":"Visible door"},
              {"kind":"window","label":"Window","segment":[[.7,.3],[.7,.5]],"source":region(bbox=[.68,.29,.72,.51]),
               "host_room":1,"host_edge":1,"basis":"observed","note":"Visible window"}]
    model=ifcopenshell.file.from_string(generate_ifc(description(floor(openings=openings)),document).decode())
    artifact=manifest(model)
    assert len(model.by_type("IfcOpeningElement"))==2
    assert len(model.by_type("IfcRelVoidsElement"))==len(model.by_type("IfcRelFillsElement"))==2
    for relation in model.by_type("IfcRelFillsElement"):
        fill=relation.RelatedBuildingElement
        assert fill.OverallHeight is None and fill.OverallWidth is None
        assert relation.RelatingOpeningElement.VoidsElements[0].RelatingBuildingElement.is_a("IfcWall")
        assert len(mesh(model,fill).faces)>0
        element=next(e for e in artifact.scene.elements if e.id==fill.GlobalId)
        assert {a.property for a in element.assumptions}>={"height","sill_height","thickness"}
    for wall in model.by_type("IfcWall"):
        assert len(mesh(model,wall).faces)>0
    # Actual wall tessellation includes the subtraction, not only relation records.
    def volume(geometry):
        xyz=[geometry.verts[i:i+3] for i in range(0,len(geometry.verts),3)]
        total=0
        for index in range(0,len(geometry.faces),3):
            a,b,c=[xyz[i] for i in geometry.faces[index:index+3]]
            total+=a[0]*(b[1]*c[2]-b[2]*c[1])+a[1]*(b[2]*c[0]-b[0]*c[2])+a[2]*(b[0]*c[1]-b[1]*c[0])
        return abs(total)/6
    plain=ifcopenshell.file.from_string(generate_ifc(description(),document).decode())
    for relation in model.by_type("IfcRelVoidsElement"):
        cut=relation.RelatingBuildingElement
        assert volume(mesh(model,cut)) < volume(mesh(plain,plain.by_guid(cut.GlobalId)))


def test_ambiguous_or_off_boundary_openings_are_omitted_without_guessing(document):
    invalid={"kind":"door","label":"Ambiguous","segment":[[.2,.4],[.3,.4]],"source":region(),
             "host_room":0,"host_edge":-1,"basis":"observed","note":"Host unclear"}
    model=ifcopenshell.file.from_string(generate_ifc(description(floor(openings=[invalid,invalid|{"host_room":1,"host_edge":0}])),document).decode())
    assert not model.by_type("IfcOpeningElement") and not model.by_type("IfcDoor")
    assert any("omitted 2 openings" in w for w in manifest(model).scene.warnings)


def test_partial_rooms_preserve_original_ids_and_empty_floor_records(document):
    invalid=room("Invalid",[[.1,.1],[.9,.9],[.1,.9],[.9,.1]])
    good=room("Good",[[.1,.2],[.4,.2],[.4,.6],[.1,.6]])
    empty=floor("Empty",rooms=[invalid])
    partial=floor("Partial",rooms=[invalid,good])
    model=ifcopenshell.file.from_string(generate_ifc(description(empty,partial),document).decode())
    artifact=manifest(model)
    assert len(artifact.scene.floors)==2 and len(model.by_type("IfcSpace"))==1
    assert any("no renderable rooms" in w for w in artifact.scene.warnings)
    partial_id=model.by_type("IfcSpace")[0].GlobalId
    alternate=floor("Partial",rooms=[room("Different",[[.6,.2],[.9,.2],[.9,.6],[.6,.6]]),good])
    model2=ifcopenshell.file.from_string(generate_ifc(description(empty,alternate),document).decode())
    assert next(e for e in model2.by_type("IfcSpace") if e.Name=="Good").GlobalId==partial_id
    with pytest.raises(DocumentError,match="No valid room"):
        generate_ifc(description(empty),document)


def test_all_overlap_conflicts_are_removed_before_selecting_survivors(document):
    rooms=[room("A",[[.05,.1],[.3,.1],[.3,.6],[.05,.6]]),room("B",[[.2,.1],[.45,.1],[.45,.6],[.2,.6]]),
           room("C",[[.35,.1],[.6,.1],[.6,.6],[.35,.6]]),room("D",[[.7,.1],[.9,.1],[.9,.6],[.7,.6]])]
    model=ifcopenshell.file.from_string(generate_ifc(description(floor(rooms=rooms)),document).decode())
    assert [e.Name for e in model.by_type("IfcSpace")]==["D"]
    assert any("3 ambiguous overlap" in w for w in manifest(model).scene.warnings)


def test_invalid_calibration_does_not_turn_into_measured_scale(document):
    calibration={"length_m":6,"segment":[[.1,.2],[.1,.2]],"source":region(),"note":"Bad zero length"}
    model=ifcopenshell.file.from_string(generate_ifc(description(floor(calibration=calibration)),document).decode())
    artifact=manifest(model)
    assert artifact.scene.units=="relative" and artifact.scene.floors[0].calibration is None
    assert any("invalid calibration" in w for w in artifact.scene.warnings)


def test_generation_rejects_unavailable_pages_and_existing_resource_limits(document,monkeypatch):
    with pytest.raises(DocumentError):
        generate_ifc(description(floor(source=region(page=2))),document)
    monkeypatch.setattr("app.ifc_generate.MAX_ELEMENTS",2)
    with pytest.raises(DocumentError,match="element limit"):
        generate_ifc(description(),document)
    monkeypatch.setattr("app.ifc_generate.MAX_ELEMENTS",4000)
    monkeypatch.setattr("app.ifc_generate.MAX_TRIANGLES",1)
    with pytest.raises(DocumentError,match="triangle limit"):
        generate_ifc(description(),document)
    monkeypatch.setattr("app.ifc_generate.MAX_TRIANGLES",1_000_000)
    monkeypatch.setattr("app.ifc_generate.MAX_IFC_BYTES",1)
    with pytest.raises(DocumentError,match="25 MiB"):
        generate_ifc(description(),document)


def test_multipage_floors_keep_original_regions_and_embedded_page_identities(tmp_path):
    from test_backend import pdf
    store=DocumentStore(tmp_path)
    try:
        document=store.add(pdf(2),"floors.pdf")
        model=ifcopenshell.file.from_string(generate_ifc(description(floor(),floor("Upper",source=region(page=2))),document).decode())
        artifact=manifest(model)
        assert [p.number for p in artifact.pages]==[1,2]
        assert [f.source.page for f in artifact.scene.floors]==[1,2]
        rooms=[e for e in artifact.scene.elements if e.kind=="room"]
        assert [r.source.page for r in rooms]==[1,2]
        assert rooms[0].id!=rooms[1].id and rooms[0].source.bbox==rooms[1].source.bbox
        for embedded,page in zip(artifact.pages,document.pages,strict=True):
            assert base64.b64decode(embedded.png_base64)==page.path.read_bytes()
    finally:
        store.close()


def test_only_common_supported_registration_aligns_floors(document):
    calibration={"length_m":6,"segment":[[.1,.2],[.7,.2]],"source":region(),"note":"Reference"}
    alignment={"group":"Grid A1","anchor":[.1,.2],"source":region(),"basis":"Visible labeled grid anchor"}
    first=floor(calibration=calibration,alignment=alignment,rotation_degrees=0,orientation_basis="Printed direction")
    second=floor("Upper",calibration=calibration,alignment=alignment,rotation_degrees=180,orientation_basis="Caption rotated")
    artifact=manifest(ifcopenshell.file.from_string(generate_ifc(description(first,second),document).decode()))
    assert artifact.scene.layout=="aligned"
    for f in artifact.scene.floors:
        assert f.alignment_status=="supported"
        assert f.alignment.group=="Grid A1" and f.alignment.source.page==1
        assert f.alignment.anchor==[.1,.2]
        assert [r[0]*.1+r[1]*.2+r[2] for r in f.transform[:2]]==pytest.approx([0,0])
    unknown=second|{"rotation_degrees":None,"orientation_basis":""}
    artifact=manifest(ifcopenshell.file.from_string(generate_ifc(description(first,unknown),document).decode()))
    assert artifact.scene.layout=="schematic"
    assert all(f.alignment_status=="schematic" for f in artifact.scene.floors)


def test_generated_bytes_reopen_through_artifact_reader_as_original_drawing(document):
    from app.ifc_artifact import load_artifact
    data=generate_ifc(description(),document)
    scene,restored,original=load_artifact(data,"fresh-session-id")
    assert scene.document_id=="fresh-session-id" and scene.derived and scene.source_kind=="image"
    assert not scene.catalog_complete and scene.units=="relative"
    assert all(e.geometry is not None and e.geometry_origin=="inferred" for e in scene.elements)
    assert [e.id for e in scene.elements]==[e.id for e in original.scene.elements]
    assert restored[0][1]==document.pages[0].path.read_bytes()


def test_host_projection_accepts_only_within_rendered_wall_band(document):
    opening={"kind":"door","label":"Door","segment":[[.2,.202],[.3,.202]],"source":region(bbox=[.19,.19,.31,.23]),
             "host_room":1,"host_edge":0,"basis":"observed","note":"Visible door"}
    data=generate_ifc(description(floor(openings=[opening])),document)
    model=ifcopenshell.file.from_string(data.decode())
    assert len(model.by_type("IfcDoor"))==1
    e=next(e for e in manifest(model).scene.elements if e.kind=="door")
    assert e.source.bbox==opening["source"]["bbox"]
    assert any(a.property=="host_projection" and "wall band" in a.value for a in e.assumptions)
    outside=opening|{"segment":[[.2,.22],[.3,.22]]}
    model=ifcopenshell.file.from_string(generate_ifc(description(floor(openings=[outside])),document).decode())
    assert not model.by_type("IfcDoor")


@pytest.mark.parametrize("source,segment",[
    (region(bbox=[.5,.5,.6,.6]),[[.2,.2],[.3,.2]]),
    (region(page=2,bbox=[.19,.19,.31,.23]),[[.2,.2],[.3,.2]]),
    (region(bbox=[0,0,.4,.3]),[[.2,.2],[.3,.2]]),
    (region(bbox=[.19,.201,.31,.205]),[[.2,.202],[.3,.202]]),
])
def test_opening_must_stay_in_its_unchanged_source_region_and_depicted_floor(document,source,segment):
    opening={"kind":"door","label":"Door","segment":segment,"source":source,
             "host_room":1,"host_edge":0,"basis":"observed","note":"Visible door"}
    described=floor(source=region(bbox=[.05,.1,.95,.9]),openings=[opening])
    model=ifcopenshell.file.from_string(generate_ifc(description(described),document).decode())
    assert not model.by_type("IfcDoor") and not model.by_type("IfcOpeningElement")
    artifact=manifest(model)
    assert any("omitted 1 openings" in w for w in artifact.scene.warnings)
    assert all(e.kind!="door" for e in artifact.scene.elements)


def test_valid_opening_preserves_full_source_region_without_shrinking(document):
    source=region(bbox=[.15,.15,.4,.3])
    opening={"kind":"door","label":"Door","segment":[[.2,.2],[.3,.2]],"source":source,
             "host_room":1,"host_edge":0,"basis":"observed","note":"Visible door"}
    model=ifcopenshell.file.from_string(generate_ifc(description(floor(openings=[opening])),document).decode())
    element=next(e for e in manifest(model).scene.elements if e.kind=="door")
    assert element.source.bbox==source["bbox"]
    assert len(model.by_type("IfcOpeningElement"))==1


def test_boundary_source_padding_stays_inside_its_original_floor_region(document):
    bbox=[.1,.2,.7,.8]
    model=ifcopenshell.file.from_string(generate_ifc(description(floor(source=region(bbox=bbox))),document).decode())
    for element in manifest(model).scene.elements:
        l,t,r,b=element.source.bbox
        assert bbox[0]<=l<r<=bbox[2] and bbox[1]<=t<b<=bbox[3]
