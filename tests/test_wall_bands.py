"""Supplied wall faces survive transforms and host real openings without gap snapping."""
from io import BytesIO
import math

import ifcopenshell
from PIL import Image
import pytest
from shapely.geometry import Polygon

from app.comparison import inverse_transform, _section
from app.documents import DocumentStore
from app.ifc_artifact import load_artifact
from app.ifc_generate import generate_ifc
from test_ifc_generate import boundary, description, floor, manifest, mesh, opening, region


@pytest.fixture
def document(tmp_path):
    output=BytesIO();Image.new("RGB",(475,650),"white").save(output,format="PNG")
    store=DocumentStore(tmp_path)
    try:
        yield store.add(output.getvalue(),"source.png")
    finally:
        store.close()


def build(document,walls,openings=None,**overrides):
    d=description(floor(rooms=[],boundaries=walls,openings=openings or [],**overrides))
    data=generate_ifc(d,document)
    model=ifcopenshell.file.from_string(data.decode())
    return data,model,manifest(model)


def source_polygon(model,element,scene):
    inverse=inverse_transform(next(f.transform for f in scene.floors if f.id==element.storey_id))
    geometry=mesh(model,model.by_guid(element.id))
    points={tuple(round(v,12)for v in inverse(geometry.verts[i:i+3]))for i in range(0,len(geometry.verts),3)}
    return Polygon(list(points)).convex_hull


@pytest.mark.parametrize("rotation",[0,90,180,270])
@pytest.mark.parametrize("reverse",[False,True])
def test_source_endpoint_crossing_preserves_depicted_face_band_under_rotation(document,rotation,reverse):
    axis=[[.448,.94],[.448,.134]]
    wall=boundary(segment=list(reversed(axis)) if reverse else axis,thickness_segment=[[.418,.5],[.448,.5]])
    _,model,artifact=build(document,[wall],source=region(bbox=[.043,.016,.498,.984]),
        rotation_degrees=rotation,orientation_basis="Visible diagram orientation")
    element=artifact.scene.elements[0]
    assert element.representation=="reconstructed"
    assert not any(a.property=="thickness" for a in element.assumptions)
    assert any(a.property=="normal_offsets" and "not assumed to be a centerline" in a.reason for a in element.assumptions)
    assert source_polygon(model,element,artifact.scene).bounds==pytest.approx((.418,.134,.448,.94))
    assert artifact.description.floors[0].boundaries[0].segment==wall["segment"]


def test_supported_face_contact_connects_without_moving_axes_but_positive_gap_remains(document):
    vertical=boundary("outer",[[.2,.2],[.2,.8]],thickness_segment=[[.2,.4],[.24,.4]])
    touching=boundary("partition",[[.24,.5],[.7,.5]],thickness_segment=[[.4,.5],[.4,.52]])
    _,model,artifact=build(document,[vertical,touching])
    a,b=[source_polygon(model,e,artifact.scene)for e in artifact.scene.elements]
    assert a.distance(b)<1e-10
    assert a.bounds==pytest.approx((.2,.2,.24,.8))
    assert b.bounds==pytest.approx((.24,.5,.7,.52))
    intentional=touching|{"segment":[[.25,.5],[.7,.5]]}
    _,model,artifact=build(document,[vertical,intentional])
    a,b=[source_polygon(model,e,artifact.scene)for e in artifact.scene.elements]
    assert a.distance(b)==pytest.approx(.01)
    assert artifact.description.floors[0].boundaries[1].segment==intentional["segment"]


@pytest.mark.parametrize("reverse_host,reverse_gap",[(False,False),(True,False),(False,True),(True,True)])
def test_void_cuts_full_asymmetric_band_and_fill_is_centered_between_faces(document,reverse_host,reverse_gap):
    axis=[[.2,.2],[.2,.8]];gap=[[.2,.35],[.2,.5]]
    wall=boundary(segment=list(reversed(axis)) if reverse_host else axis,thickness_segment=[[.2,.4],[.24,.4]])
    source=region(bbox=[.19,.34,.25,.51])
    door=opening(segment=list(reversed(gap)) if reverse_gap else gap,source=source)
    data,model,artifact=build(document,[wall],[door],rotation_degrees=90,orientation_basis="Visible diagram orientation")
    scene,_,_=load_artifact(data,"reopened")
    wall_element=next(e for e in scene.elements if e.kind=="wall")
    door_element=next(e for e in scene.elements if e.kind=="door")
    assert door_element.representation=="reconstructed" and door_element.source.bbox==source["bbox"]
    inverse=inverse_transform(scene.floors[0].transform)
    actual=_section(wall_element.geometry,.4,inverse)
    assert actual.area==pytest.approx(.04*(.6-.15),rel=1e-7)
    fill=source_polygon(model,door_element,scene)
    assert (fill.bounds[0]+fill.bounds[2])/2==pytest.approx(.22)
    assert fill.bounds[1::2]==pytest.approx((.35,.5))
    assert model.by_type("IfcRelVoidsElement")[0].RelatingBuildingElement.GlobalId==wall_element.id
    assert model.by_type("IfcRelFillsElement")[0].RelatedBuildingElement.GlobalId==door_element.id
    assert any(a.property=="cross_wall_center" for a in door_element.assumptions)
    assert [e.id for e in scene.elements]==[e.id for e in artifact.scene.elements]


@pytest.mark.parametrize("gap_x,expected",[(.235,"reconstructed"),(.195,"unresolved")])
def test_gap_acceptance_uses_actual_signed_side_not_old_centered_band(document,gap_x,expected):
    wall=boundary(segment=[[.2,.2],[.2,.8]],thickness_segment=[[.2,.4],[.24,.4]])
    door=opening(segment=[[gap_x,.35],[gap_x,.5]],source=region(bbox=[.19,.34,.25,.51]))
    _,model,artifact=build(document,[wall],[door])
    element=next(e for e in artifact.scene.elements if e.kind=="door")
    assert element.representation==expected
    assert len(model.by_type("IfcOpeningElement"))==(1 if expected=="reconstructed" else 0)


@pytest.mark.parametrize("rotation",[0,90,180,270])
@pytest.mark.parametrize("gap_x",[.2,.22,.24])
@pytest.mark.parametrize("reverse_host,reverse_gap",[(False,False),(True,False),(False,True),(True,True)])
def test_full_span_glazing_projection_is_independent_of_display_rotation(document,rotation,gap_x,reverse_host,reverse_gap):
    axis=[[.2,.2],[.2,.8]];gap=[[gap_x,.2],[gap_x,.8]]
    wall=boundary(segment=list(reversed(axis)) if reverse_host else axis,thickness_segment=[[.2,.4],[.24,.4]])
    window=opening(kind="window",segment=list(reversed(gap)) if reverse_gap else gap,source=region())
    data,model,artifact=build(document,[wall],[window],rotation_degrees=rotation,orientation_basis="Visible diagram orientation")
    element=next(e for e in artifact.scene.elements if e.kind=="window")
    assert element.representation=="reconstructed"
    assert source_polygon(model,element,artifact.scene).bounds[1::2]==pytest.approx((.2,.8))
    scene,_,_=load_artifact(data,"reopened")
    reopened=next(e for e in scene.elements if e.id==element.id)
    assert reopened.representation=="reconstructed" and reopened.geometry is not None


@pytest.mark.parametrize("rotation",[0,90,180,270])
@pytest.mark.parametrize("reverse_host",[False,True])
def test_opening_beyond_host_end_is_not_snapped_into_range(document,rotation,reverse_host):
    axis=[[.2,.2],[.2,.8]]
    wall=boundary(segment=list(reversed(axis)) if reverse_host else axis,thickness_segment=[[.2,.4],[.24,.4]])
    window=opening(kind="window",segment=[[.22,.199],[.22,.8]],source=region())
    _,model,artifact=build(document,[wall],[window],rotation_degrees=rotation,orientation_basis="Visible diagram orientation")
    element=next(e for e in artifact.scene.elements if e.kind=="window")
    assert element.representation=="unresolved"
    assert not model.by_type("IfcOpeningElement")


@pytest.mark.parametrize("width_segment",[[],[[.3,.4],[.34,.4]],[[.2,.4],[.24,.5]]])
def test_missing_disconnected_or_oblique_width_keeps_explicit_symmetric_assumption(document,width_segment):
    wall=boundary(segment=[[.2,.2],[.2,.8]],thickness_segment=width_segment)
    _,model,artifact=build(document,[wall])
    element=artifact.scene.elements[0]
    assert any(a.property=="thickness" and a.value==.08 for a in element.assumptions)
    footprint=source_polygon(model,element,artifact.scene)
    assert (footprint.bounds[0]+footprint.bounds[2])/2==pytest.approx(.2)


def test_depicted_relative_width_is_not_replaced_by_generic_maximum(document):
    wall=boundary(segment=[[.186,.344],[.324,.344]],thickness_segment=[[.186,.344],[.186,.411]])
    _,model,artifact=build(document,[wall])
    element=artifact.scene.elements[0]
    assert not any(a.property=="thickness" for a in element.assumptions)
    assert source_polygon(model,element,artifact.scene).bounds==pytest.approx((.186,.344,.324,.411))


def test_symmetric_depicted_width_calibration_and_opening_identity_are_preserved(document):
    wall=boundary(segment=[[.2,.2],[.2,.8]],thickness_segment=[[.18,.4],[.22,.4]])
    calibration={"length_m":6,"segment":[[.2,.2],[.2,.8]],"source":region(),"note":"Printed reference"}
    data,model,artifact=build(document,[wall],[opening(segment=[[.2,.35],[.2,.5]],source=region())],calibration=calibration)
    scene,_,_=load_artifact(data,"other")
    assert scene.units=="m" and scene.floors[0].scale_status=="known"
    wall_element=next(e for e in scene.elements if e.kind=="wall")
    geometry=mesh(model,model.by_guid(wall_element.id))
    assert max(geometry.verts[1::3])-min(geometry.verts[1::3])==pytest.approx(6)
    assert wall_element.source==artifact.scene.elements[0].source
    assert scene.artifact_id==artifact.artifact_id
