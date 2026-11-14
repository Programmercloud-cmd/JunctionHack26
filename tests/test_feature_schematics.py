"""Actual IFC display motifs stay source-footprint bound and never become QA facts."""
from io import BytesIO
import json

import ifcopenshell
from PIL import Image
import pytest
from shapely.geometry import Polygon

from app.comparison import _projection, inverse_transform
from app.documents import DocumentStore
from app.ifc_artifact import load_artifact
from app.ifc_generate import generate_ifc
from app.source_context import source_context
from test_ifc_generate import description, feature, floor, manifest, region

RATIOS={"table":.30,"chair":.20,"bed":.20,"sofa":.25,"cabinet":.50,"appliance":.40,
        "sink":.25,"toilet":.25,"shower":.10,"bath":.10,"stairs":.10,"other":.10}
CONCAVE=[[.2,.3],[.4,.3],[.4,.36],[.28,.36],[.28,.5],[.2,.5]]


@pytest.fixture
def document(tmp_path):
    png=BytesIO();Image.new("RGB",(475,650),"white").save(png,format="PNG")
    store=DocumentStore(tmp_path)
    try:
        yield store.add(png.getvalue(),"original.png")
    finally:
        store.close()


def build(document,kind,known=False,points=None):
    supplied=feature(kind,polygon=points or CONCAVE)
    calibration={"length_m":6,"segment":[[.2,.2],[.2,.8]],"source":region(),"note":"Printed reference"} if known else None
    d=description(floor(rooms=[],boundaries=[],features=[supplied],calibration=calibration,
                        rotation_degrees=90,orientation_basis="Depicted orientation"))
    data=generate_ifc(d,document)
    model=ifcopenshell.file.from_string(data.decode())
    scene,_,_=load_artifact(data,"reopened")
    return data,model,scene,supplied


@pytest.mark.parametrize("kind",list(RATIOS))
@pytest.mark.parametrize("known",[False,True])
def test_category_height_and_concave_footprint_survive_actual_ifc_reopen(document,kind,known):
    data,model,scene,supplied=build(document,kind,known)
    element=scene.elements[0]
    assert element.representation=="schematic" and element.geometry is not None
    h=2.6 if known else 1.2
    plate=.04 if known else .02
    zs=element.geometry.positions[2::3]
    assert min(zs)==pytest.approx(plate)
    assert max(zs)==pytest.approx(plate+h*RATIOS[kind])
    inverse=inverse_transform(scene.floors[0].transform)
    projection=_projection(element.geometry,inverse)
    footprint=Polygon(supplied["polygon"])
    assert projection.symmetric_difference(footprint).area<1e-12
    assert element.source.bbox==supplied["source"]["bbox"]
    original=manifest(model)
    assert element.id==original.scene.elements[0].id
    assert element.assumptions==original.scene.elements[0].assumptions
    assert original.description.floors[0].features[0].polygon==supplied["polygon"]
    height=next(a for a in element.assumptions if a.property=="height")
    assert height.value==pytest.approx(h*RATIOS[kind])
    assert height.unit==("m" if known else "relative")
    assert "not a source measurement" in height.reason
    assert any(a.property=="schematic_motif" for a in element.assumptions)
    assert data==generate_ifc(original.description,document)


def horizontal_triangle_area(geometry,z):
    points=[geometry.positions[i:i+3] for i in range(0,len(geometry.positions),3)]
    area=0
    for i in range(0,len(geometry.indices),3):
        triangle=[points[index] for index in geometry.indices[i:i+3]]
        if all(abs(p[2]-z)<1e-8 for p in triangle):
            area+=Polygon([p[:2]for p in triangle]).area
    return area


@pytest.mark.parametrize("kind",["table","chair"])
def test_top_and_clipped_supports_are_distinct_geometry_without_facing_claim(document,kind):
    _,model,scene,_=build(document,kind)
    entity=model.by_guid(scene.elements[0].id)
    items=entity.Representation.Representations[0].Items
    assert len(items)>=3
    top,supports=items[0],items[1:]
    assert top.Position.Location.Coordinates[2]>.02
    assert all(item.Position.Location.Coordinates[2]==pytest.approx(.02)for item in supports)
    assert all(item.Depth==pytest.approx(top.Position.Location.Coordinates[2]-.02)for item in supports)
    motif=next(a for a in scene.elements[0].assumptions if a.property=="schematic_motif")
    assert "real leg counts" in motif.reason and "no chair facing" in motif.reason


@pytest.mark.parametrize("kind",["sink","toilet","shower","bath"])
def test_sanitary_rim_has_actual_recess_and_stays_within_concave_outline(document,kind):
    _,model,scene,_=build(document,kind)
    element=scene.elements[0]
    items=model.by_guid(element.id).Representation.Representations[0].Items
    assert len(items)>=2
    assert any(item.SweptArea.is_a("IfcArbitraryProfileDefWithVoids")for item in items[1:])
    zs=element.geometry.positions[2::3]
    bottom_area=horizontal_triangle_area(element.geometry,min(zs))
    top_area=horizontal_triangle_area(element.geometry,max(zs))
    assert 0<top_area<bottom_area


def test_stairs_remain_level_without_step_count_ascent_or_travel_direction(document):
    _,model,scene,_=build(document,"stairs")
    stairs=model.by_guid(scene.elements[0].id)
    body,*marks=stairs.Representation.Representations[0].Items
    assert marks and len({round(mark.Position.Location.Coordinates[2],12)for mark in marks})==1
    assert all(mark.Position.Location.Coordinates[2]==pytest.approx(body.Position.Location.Coordinates[2]+body.Depth)for mark in marks)
    assert stairs.NumberOfRisers is None and stairs.NumberOfTreads is None
    assert stairs.RiserHeight is None and stairs.TreadLength is None
    assert any("No stair travel direction" in a.reason for a in scene.elements[0].assumptions)


def test_fresh_store_reopen_preserves_assumptions_but_excludes_them_from_original_qa(document,tmp_path):
    data,_,scene,_=build(document,"cabinet",True)
    store=DocumentStore(tmp_path/"fresh")
    try:
        reopened=store.add(data,"portable.ifc")
        assert reopened.kind=="drawing" and reopened.pages
        assert reopened.pages[0].path.read_bytes()==document.pages[0].path.read_bytes()
        assert reopened.scene.elements[0].id==scene.elements[0].id
        assert reopened.scene.elements[0].assumptions==scene.elements[0].assumptions
        # Even an incorrectly tagged document cannot promote the derived artifact to factual IFC.
        reopened.kind="ifc"
        context=json.loads(source_context(reopened))
        assert set(context)=={"association_index_only","floors","objects"}
        assert set(context["objects"][0])=={"id","kind","name","page","bbox","floor_id"}
        for assumption in scene.elements[0].assumptions:
            assert assumption.reason not in json.dumps(context)
        assert "counts_by_kind" not in context
    finally:
        store.close()
