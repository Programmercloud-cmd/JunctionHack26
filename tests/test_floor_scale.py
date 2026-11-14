"""Unknown floor sizes preserve page proportions rather than renormalizing each panel."""
from io import BytesIO
import math

import ifcopenshell
from PIL import Image
import pytest

from app.comparison import inverse_transform
from app.documents import DocumentStore
from app.ifc_artifact import load_artifact
from app.ifc_generate import generate_ifc
from test_ifc_generate import description, floor, manifest, mesh, region, room


@pytest.fixture
def document(tmp_path):
    output=BytesIO();Image.new("RGB",(475,650),"white").save(output,format="PNG")
    store=DocumentStore(tmp_path)
    try:
        yield store.add(output.getvalue(),"drawing.png")
    finally:
        store.close()


def create(document,*floors):
    data=generate_ifc(description(*floors),document)
    model=ifcopenshell.file.from_string(data.decode())
    return data,model,manifest(model)


def floor_with_room(label,bbox,polygon,**overrides):
    return floor(label,source=region(bbox=bbox),rooms=[room("Interior",polygon)],boundaries=[],**overrides)


def footprint(model,identifier):
    geometry=mesh(model,model.by_guid(identifier))
    return sorted({(round(geometry.verts[i],10),round(geometry.verts[i+1],10))for i in range(0,len(geometry.verts),3)})


def extents(points):
    return [max(p[i]for p in points)-min(p[i]for p in points)for i in (0,1)]


def test_same_page_equal_source_spans_have_equal_actual_ifc_extents_despite_panel_sizes(document):
    left=floor_with_room("Ground",[.043,.016,.498,.984],[[.1,.3],[.3,.3],[.3,.6],[.1,.6]])
    right=floor_with_room("Upper",[.52,.134,.924,.984],[[.6,.3],[.8,.3],[.8,.6],[.6,.6]])
    _,model,artifact=create(document,left,right)
    rooms=[e for e in artifact.scene.elements if e.kind=="room"]
    assert len(rooms)==2
    assert extents(footprint(model,rooms[0].id))==pytest.approx(extents(footprint(model,rooms[1].id)))
    assert extents(footprint(model,rooms[0].id))==pytest.approx([.2*475/650*10,3])
    assert [math.hypot(f.transform[0][1],f.transform[1][1])for f in artifact.scene.floors]==pytest.approx([10,10])
    assert artifact.scene.units=="relative" and artifact.scene.layout=="schematic"
    for f in artifact.scene.floors:
        assumption=next(a for a in f.assumptions if a.property=="page_extent")
        assert "does not prove equal physical scale" in assumption.reason
        assert f.scale_status=="unknown" and not any(a.property=="panel_extent" for a in f.assumptions)


def test_expanding_bbox_and_adding_outdoor_area_changes_existing_room_translation_only(document):
    polygon=[[.2,.3],[.4,.3],[.4,.6],[.2,.6]]
    original=floor_with_room("Ground",[.1,.2,.5,.8],polygon)
    expanded=floor_with_room("Ground",[.05,.01,.5,.98],polygon)
    expanded["rooms"].append(room("Terrace",[[.1,.02],[.45,.02],[.45,.19],[.1,.19]],environment="outdoor"))
    _,first,a=create(document,original)
    _,second,b=create(document,expanded)
    identity=a.scene.elements[0].id
    assert b.scene.elements[0].id==identity
    before,after=footprint(first,identity),footprint(second,identity)
    assert extents(before)==pytest.approx(extents(after))
    matrix_a,matrix_b=a.scene.floors[0].transform,b.scene.floors[0].transform
    for index in (0,1):
        assert matrix_a[index][:2]==pytest.approx(matrix_b[index][:2])
    delta=[matrix_b[i][2]-matrix_a[i][2]for i in (0,1)]
    for old,new in zip(before,after,strict=True):
        assert new==pytest.approx([old[i]+delta[i]for i in (0,1)])
    assert a.scene.elements[0].source==b.scene.elements[0].source


def test_independent_floor_rotations_change_orientation_not_page_scale(document):
    plans=[]
    for index,angle in enumerate((0,90,180)):
        x=.05+index*.3
        plans.append(floor_with_room(str(index),[x,.1,x+.2,.9],[[x+.02,.3],[x+.12,.3],[x+.12,.5],[x+.02,.5]],
            rotation_degrees=angle,orientation_basis="Visible diagram orientation"))
    _,model,artifact=create(document,*plans)
    distances=[]
    for element in artifact.scene.elements:
        points=footprint(model,element.id)
        distances.append(sorted(math.dist(a,b)for i,a in enumerate(points)for b in points[i+1:]))
    assert distances[0]==pytest.approx(distances[1]) and distances[0]==pytest.approx(distances[2])
    assert [f.rotation_degrees for f in artifact.scene.floors]==[0,90,180]


def test_calibrated_nonsquare_geometry_and_mixed_project_semantics_are_unchanged(document):
    polygon=[[.1,.2],[.3,.2],[.3,.5],[.1,.5]]
    calibration={"length_m":4,"segment":[[.1,.2],[.3,.2]],"source":region(),"note":"Printed reference segment"}
    known=floor_with_room("Known",[0,0,.5,1],polygon,calibration=calibration)
    _,model,artifact=create(document,known)
    assert extents(footprint(model,artifact.scene.elements[0].id))[0]==pytest.approx(4)
    assert artifact.scene.units=="m" and artifact.scene.floors[0].scale_status=="known"
    unknown=floor_with_room("Unknown",[.5,.1,1,.9],[[.6,.2],[.8,.2],[.8,.5],[.6,.5]])
    _,mixed,b=create(document,known,unknown)
    assert extents(footprint(mixed,b.scene.elements[0].id))[0]==pytest.approx(4)
    assert [f.scale_status for f in b.scene.floors]==["known","unknown"]
    assert b.scene.units=="relative" and b.scene.layout=="schematic"


def test_different_pages_are_schematic_and_fresh_reopen_preserves_ids_and_source_inverse(tmp_path):
    import pypdfium2 as pdfium
    store=DocumentStore(tmp_path)
    try:
        pdf=pdfium.PdfDocument.new()
        output=BytesIO()
        try:
            for width,height in ((200,100),(100,200)):
                page=pdf.new_page(width,height)
                page.close()
            pdf.save(output)
        finally:
            pdf.close()
        original=store.add(output.getvalue(),"pages.pdf")
        polygon=[[.1,.2],[.3,.2],[.3,.6],[.1,.6]]
        first=floor_with_room("Ground",[0,0,.5,1],polygon)
        second=floor("Upper",source=region(page=2,bbox=[0,.1,.5,.8]),rooms=[room("Interior",polygon)],boundaries=[],
                     rotation_degrees=90,orientation_basis="Visible orientation")
        data,model,artifact=create(original,first,second)
        assert artifact.scene.units=="relative" and artifact.scene.layout=="schematic"
        page_factors={p.number:10/max(p.width/p.height,1)for p in original.pages}
        assert page_factors[1]!=page_factors[2]
        for f in artifact.scene.floors:
            assert math.hypot(f.transform[0][1],f.transform[1][1])==pytest.approx(page_factors[f.source.page])
            assert f.scale_status=="unknown"
        new=store.add(data,"saved.ifc")
        assert new.id!=original.id and [e.id for e in new.scene.elements]==[e.id for e in artifact.scene.elements]
        assert [f.source.page for f in new.scene.floors]==[1,2]
        floors={f.id:f for f in new.scene.floors}
        for element in new.scene.elements:
            inverse=inverse_transform(floors[element.storey_id].transform)
            xy={tuple(round(v,8)for v in inverse(element.geometry.positions[i:i+3]))for i in range(0,len(element.geometry.positions),3)}
            assert xy=={tuple(p)for p in polygon}
            assert element.source.bbox==[.1,.2,.3,.6]
    finally:
        store.close()


def test_reader_preserves_saved_legacy_panel_transform_instead_of_recomputing_it(document,monkeypatch):
    import app.ifc_generate as generator
    current=generator._floor_frame
    def previous_panel_frame(floor,page,warnings):
        matrix,known,rotation=current(floor,page,warnings)
        if not known:
            aspect=page.width/page.height;l,t,r,b=floor.source.bbox
            ratio=max(aspect,1)/max(aspect*(r-l),b-t)
            matrix=[[value*ratio for value in row]for row in matrix[:2]]+[matrix[2]]
        return matrix,known,rotation
    old=floor_with_room("Saved old panel",[.5,.134,.95,.984],[[.6,.3],[.8,.3],[.8,.6],[.6,.6]])
    with monkeypatch.context() as patch:
        patch.setattr(generator,"_floor_frame",previous_panel_frame)
        data,model,saved=create(document,old)
    reopened,_,_=load_artifact(data,"fresh-id")
    assert reopened.floors[0].transform==saved.scene.floors[0].transform
    assert math.hypot(reopened.floors[0].transform[0][1],reopened.floors[0].transform[1][1])==pytest.approx(10/.85)
    assert [e.id for e in reopened.elements]==[e.id for e in saved.scene.elements]
    inverse=inverse_transform(reopened.floors[0].transform)
    element=reopened.elements[0]
    xy={tuple(round(v,8)for v in inverse(element.geometry.positions[i:i+3]))for i in range(0,len(element.geometry.positions),3)}
    assert xy=={tuple(p)for p in old["rooms"][0]["polygon"]}
