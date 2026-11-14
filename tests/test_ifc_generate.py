"""Real IFC checks for explicit physical boundaries and accountable feature inventories."""
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


def room(label="Room",polygon=None,environment="indoor"):
    return {"label":label,"polygon":polygon or [[.1,.2],[.7,.2],[.7,.8],[.1,.8]],"environment":environment,"basis":"observed","note":"Visible footprint"}


def boundary(key="w1",segment=None,kind="wall",**overrides):
    return {"key":key,"kind":kind,"label":key,"segment":segment or [[.1,.2],[.7,.2]],
            "source":region(),"thickness_segment":[],"basis":"observed","note":"Explicit physical boundary"}|overrides


def opening(kind="door",host="w1",**overrides):
    return {"kind":kind,"label":kind,"host_wall":host,"segment":[[.2,.2],[.3,.2]],
            "source":region(bbox=[.19,.19,.31,.23]),"basis":"observed","note":"Depicted gap"}|overrides


def feature(kind="table",**overrides):
    return {"kind":kind,"label":kind,"polygon":[[.2,.3],[.4,.3],[.4,.5],[.2,.5]],
            "source":region(bbox=[.19,.29,.41,.51]),"basis":"observed","note":"Visible feature footprint"}|overrides


def floor(label="Ground floor",**overrides):
    source=overrides.get("source",region())
    # Explicit fixture descriptions; production never derives walls from these room edges.
    vertices=room()["polygon"]
    walls=[boundary(f"w{i+1}",[a,b],source=source) for i,(a,b) in enumerate(zip(vertices,vertices[1:]+vertices[:1]))]
    return {"label":label,"source":source,"order":None,"order_basis":"","rotation_degrees":None,
            "orientation_basis":"","calibration":None,"alignment":None,"measurements":[],
            "rooms":[room()],"boundaries":walls,"openings":[],"features":[],"unresolved":[]}|overrides


def description(*floors):
    return BuildingDescription(floors=list(floors or [floor()]),limitations=["Original drawing remains authoritative."])


def manifest(model):
    value=ifcopenshell.util.element.get_psets(model.by_type("IfcProject")[0])[PSET_NAME][MANIFEST_PROPERTY]
    return ArtifactManifest.model_validate_json(value)


def mesh(model,element):
    settings=ifcopenshell.geom.settings();settings.set("use-world-coords",True)
    shape=ifcopenshell.geom.create_shape(settings,element)
    return SimpleNamespace(verts=list(shape.geometry.verts),faces=list(shape.geometry.faces))


def build(document,*floors):
    return ifcopenshell.file.from_string(generate_ifc(description(*floors),document).decode())


@pytest.fixture

def document(tmp_path):
    output=BytesIO();Image.new("RGB",(200,100),"white").save(output,format="PNG")
    store=DocumentStore(tmp_path)
    try:yield store.add(output.getvalue(),"source.png")
    finally:store.close()


def test_v4_exact_description_pixels_stable_ids_and_unscaled_semantics(document):
    d=description()
    model=ifcopenshell.file.from_string(generate_ifc(d,document).decode())
    artifact=manifest(model)
    assert artifact.version==4 and artifact.description==d
    assert model.by_type("IfcProject")[0].Description==ARTIFACT_MARKER
    assert model.by_type("IfcContextDependentUnit")[0].Name==DISPLAY_UNIT and not model.by_type("IfcSIUnit")
    assert artifact.scene.derived and artifact.scene.source_kind=="image" and not artifact.scene.catalog_complete
    assert artifact.scene.units=="relative" and artifact.scene.layout=="schematic"
    original=document.pages[0].path.read_bytes()
    assert base64.b64decode(artifact.pages[0].png_base64)==original
    assert artifact.pages[0].sha256==hashlib.sha256(original).hexdigest()
    assert all(e.geometry is None and e.geometry_origin=="inferred" and e.source.kind=="image" for e in artifact.scene.elements)
    assert len(model.by_type("IfcSpace"))==1 and len(model.by_type("IfcWall"))==4
    assert all(s.Elevation is None for s in model.by_type("IfcBuildingStorey"))
    for element in artifact.scene.elements:
        props=ifcopenshell.util.element.get_psets(model.by_guid(element.id))[PSET_NAME]
        assert props["Representation"]==element.representation
        assert props["SemanticType"]==element.semantic_type and props["Environment"]==element.environment
        assert json.loads(props["Source"])["bbox"]==element.source.bbox
        assert len(mesh(model,model.by_guid(element.id)).faces)>0
    again=build(document)
    assert [e.GlobalId for e in again.by_type("IfcRoot")]==[e.GlobalId for e in model.by_type("IfcRoot")]


def test_nonsquare_calibration_rotation_and_mixed_scale_keep_original_source(document):
    calibration={"length_m":6,"segment":[[.1,.2],[.7,.2]],"source":region(),"note":"Printed reference"}
    calibrated=floor(calibration=calibration,rotation_degrees=90,orientation_basis="Visible orientation")
    model=build(document,calibrated)
    artifact=manifest(model);f=artifact.scene.floors[0]
    assert artifact.scene.units=="m" and model.by_type("IfcSIUnit")[0].Name=="METRE"
    assert f.calibration.segment==calibration["segment"]
    matrix=f.transform
    mapped=lambda p:[sum(matrix[i][j]*[p[0],p[1],1][j] for j in range(3))for i in range(2)]
    assert mapped([.1,.2])==pytest.approx([-1.5,-4]) and mapped([.7,.2])==pytest.approx([-1.5,2])
    vertices=mesh(model,model.by_type("IfcSpace")[0]).verts
    assert max(vertices[0::3])-min(vertices[0::3])==pytest.approx(3)
    assert max(vertices[1::3])-min(vertices[1::3])==pytest.approx(6)
    assert next(e for e in artifact.scene.elements if e.kind=="room").source.bbox==[.1,.2,.7,.8]
    mixed=build(document,calibrated,floor("Upper"))
    assert manifest(mixed).scene.units=="relative" and mixed.by_type("IfcContextDependentUnit")[0].Name==DISPLAY_UNIT


def test_room_footprints_never_create_walls_or_enclose_outdoors(document):
    model=build(document,floor(rooms=[room(environment="outdoor")],boundaries=[]))
    assert not model.by_type("IfcWall")
    element=manifest(model).scene.elements[0]
    assert element.kind=="outdoor" and element.environment=="outdoor"
    assert len(model.by_type("IfcSpace"))==1
    model=build(document,floor(boundaries=[boundary("open",kind="open_edge"),boundary("rail",[[.7,.2],[.7,.8]],kind="railing")]))
    assert not model.by_type("IfcWall") and len(model.by_type("IfcRailing"))==1
    scene=manifest(model).scene
    assert {e.kind for e in scene.elements}=={"room","open_edge","railing"}
    edge=next(e for e in scene.elements if e.kind=="open_edge")
    assert edge.representation=="schematic" and max(mesh(model,model.by_guid(edge.id)).verts[2::3])<.1


def test_open_edge_polyline_is_one_flat_source_linked_schematic(document):
    segment=[[.1,.2],[.7,.2],[.7,.8],[.1,.8]]
    supplied=boundary("outdoor-perimeter",segment,kind="open_edge",source=region(bbox=[.05,.15,.75,.85]))
    model=build(document,floor(rooms=[room(environment="outdoor")],boundaries=[supplied]))
    assert not model.by_type("IfcWall") and not model.by_type("IfcRailing")
    proxies=model.by_type("IfcBuildingElementProxy")
    assert len(proxies)==1 and len(proxies[0].Representation.Representations[0].Items)==3
    entry=next(e for e in manifest(model).scene.elements if e.kind=="open_edge")
    assert entry.id==proxies[0].GlobalId and entry.representation=="schematic"
    assert entry.source.bbox==supplied["source"]["bbox"]
    geometry=mesh(model,proxies[0])
    assert min(geometry.verts[2::3])==pytest.approx(0)
    assert max(geometry.verts[2::3])==pytest.approx(.02)
    again=build(document,floor(boundaries=[supplied]))
    assert again.by_type("IfcBuildingElementProxy")[0].GlobalId==entry.id


@pytest.mark.parametrize("kind,segment",[
    ("open_edge",[[.1,.2],[.1,.2],[.7,.8]]),
    ("open_edge",[[.1,.2],[.7,.2],[.1,.2]]),
    ("open_edge",[[.1,.2],[.7,.2],[1.1,.8]]),
    ("wall",[[.1,.2],[.7,.2],[.7,.8]]),
    ("railing",[[.1,.2],[.7,.2],[.7,.8]]),
])
def test_polyline_support_does_not_accept_degenerate_edges_or_change_wall_hosts(document,kind,segment):
    model=build(document,floor(boundaries=[boundary(segment=segment,kind=kind)]))
    entry=next(e for e in manifest(model).scene.elements if e.kind==kind)
    assert entry.representation=="unresolved" and model.by_guid(entry.id).Representation is None


def test_one_explicit_shared_wall_and_opening_survive_invalid_room(document):
    invalid=room("Broken",[[.1,.1],[.9,.9],[.1,.9],[.9,.1]])
    model=build(document,floor(rooms=[invalid],boundaries=[boundary()],openings=[opening()]))
    assert len(model.by_type("IfcWall"))==1 and len(model.by_type("IfcDoor"))==1
    assert len(model.by_type("IfcRelVoidsElement"))==len(model.by_type("IfcRelFillsElement"))==1
    room_element=next(e for e in manifest(model).scene.elements if e.kind=="room")
    assert room_element.representation=="unresolved" and model.by_guid(room_element.id).Representation is None
    assert model.by_type("IfcWall")[0].Representation and model.by_type("IfcDoor")[0].Representation


def test_door_leaf_like_diagonal_feature_cannot_turn_into_wall(document):
    diagonal=feature("other",polygon=[[.2,.2],[.3,.3],[.31,.29]],source=region())
    model=build(document,floor(boundaries=[],features=[diagonal]))
    assert not model.by_type("IfcWall") and len(model.by_type("IfcBuildingElementProxy"))==1


@pytest.mark.parametrize("boundaries",[
    [boundary("same"),boundary("same",[[.7,.2],[.7,.8]])],
    [boundary("w1"),boundary("other",[[.2,.2],[.8,.2]])],
])
def test_conflicting_keys_or_overlapping_walls_and_dependents_are_unresolved(document,boundaries):
    model=build(document,floor(boundaries=boundaries,openings=[opening(host=boundaries[0]["key"])]))
    entries=[e for e in manifest(model).scene.elements if e.kind in {"wall","door"}]
    assert len(entries)==3 and all(e.representation=="unresolved" for e in entries)
    assert all(model.by_guid(e.id).Representation is None for e in entries)
    assert not model.by_type("IfcOpeningElement")


def test_exact_shared_boundary_aliases_have_one_mesh_and_host_either_key(document):
    model=build(document,floor(boundaries=[boundary("a"),boundary("b",[[.7,.2],[.1,.2]])],openings=[opening(host="b")]))
    assert sum(bool(w.Representation)for w in model.by_type("IfcWall"))==1
    assert len(model.by_type("IfcOpeningElement"))==1
    entries=[e for e in manifest(model).scene.elements if e.kind=="wall"]
    assert sorted(e.representation for e in entries)==["reconstructed","unresolved"]


def test_all_conflicting_opening_intervals_remain_unresolved_not_first_wins(document):
    model=build(document,floor(openings=[opening(),opening("window",segment=[[.25,.2],[.35,.2]],source=region())]))
    entries=[e for e in manifest(model).scene.elements if e.kind in {"door","window"}]
    assert len(entries)==2 and all(e.representation=="unresolved" for e in entries)
    assert not model.by_type("IfcOpeningElement")


@pytest.mark.parametrize("override",[
    {"host_wall":None},{"host_wall":"missing"},
    {"source":region(bbox=[.5,.5,.6,.6])},
    {"source":region(page=2)},
    {"segment":[[.2,.4],[.3,.4]],"source":region()},
    {"segment":[[.2,.202],[.3,.202]],"source":region(bbox=[.19,.201,.31,.205])},
])
def test_invalid_openings_are_preserved_individually_without_invented_hosts(document,override):
    model=build(document,floor(openings=[opening(**override)]))
    element=next(e for e in manifest(model).scene.elements if e.kind=="door")
    assert element.representation=="unresolved" and element.note
    assert model.by_guid(element.id).Representation is None and not model.by_type("IfcOpeningElement")


def test_valid_openings_actual_boolean_subtractions_and_unchanged_source(document):
    model=build(document,floor(openings=[opening(),opening("window","w2",segment=[[.7,.3],[.7,.5]],source=region())]))
    assert len(model.by_type("IfcOpeningElement"))==2
    for relation in model.by_type("IfcRelFillsElement"):
        fill=relation.RelatedBuildingElement
        assert fill.OverallHeight is None and fill.OverallWidth is None
        assert len(mesh(model,fill).faces)>0
        assert relation.RelatingOpeningElement.VoidsElements[0].RelatingBuildingElement.is_a("IfcWall")
    def volume(g):
        xyz=[g.verts[i:i+3]for i in range(0,len(g.verts),3)];total=0
        for i in range(0,len(g.faces),3):
            a,b,c=[xyz[j]for j in g.faces[i:i+3]]
            total+=a[0]*(b[1]*c[2]-b[2]*c[1])+a[1]*(b[2]*c[0]-b[0]*c[2])+a[2]*(b[0]*c[1]-b[1]*c[0])
        return abs(total)/6
    plain=build(document)
    for relation in model.by_type("IfcRelVoidsElement"):
        wall=relation.RelatingBuildingElement
        assert volume(mesh(model,wall))<volume(mesh(plain,plain.by_guid(wall.GlobalId)))
    door=next(e for e in manifest(model).scene.elements if e.kind=="door")
    assert door.source.bbox==opening()["source"]["bbox"]
    assert {a.property for a in door.assumptions}>={"height","sill_height","thickness"}


def test_meaningful_feature_categories_all_have_schematics_without_known_height(document):
    kinds=["stairs","table","chair","cabinet","bed","sofa","sink","toilet","shower","bath","appliance","other"]
    model=build(document,floor(features=[feature(k)for k in kinds]))
    entries=[e for e in manifest(model).scene.elements if e.semantic_type in kinds]
    assert len(entries)==len(kinds) and {e.semantic_type for e in entries}==set(kinds)
    for entry in entries:
        assert entry.representation=="schematic" and entry.assumptions
        assert len(mesh(model,model.by_guid(entry.id)).faces)>0
    stairs=model.by_type("IfcStairFlight")[0]
    assert stairs.NumberOfRisers is None and stairs.NumberOfTreads is None


@pytest.mark.parametrize("kind",["table","cabinet","sink","stairs"])
def test_empty_feature_polygon_uses_explicit_source_box_assumption(document,kind):
    supplied=feature(kind,polygon=[])
    model=build(document,floor(features=[supplied]))
    entry=next(e for e in manifest(model).scene.elements if e.semantic_type==kind)
    assert entry.representation=="schematic" and entry.source.bbox==supplied["source"]["bbox"]
    assert any(a.property=="footprint" and a.value=="Source bounding box" for a in entry.assumptions)
    geometry=mesh(model,model.by_guid(entry.id))
    assert geometry.faces
    matrix=manifest(model).scene.floors[0].transform
    left,top,right,bottom=supplied["source"]["bbox"]
    expected=[[sum(matrix[i][j]*[u,v,1][j] for j in range(3))for i in range(2)]for u,v in [(left,top),(right,bottom)]]
    assert [min(geometry.verts[0::3]),max(geometry.verts[0::3])]==pytest.approx(sorted(p[0]for p in expected))
    assert [min(geometry.verts[1::3]),max(geometry.verts[1::3])]==pytest.approx(sorted(p[1]for p in expected))


def test_invalid_nonempty_feature_does_not_use_bbox_fallback(document):
    supplied=feature(polygon=[[.2,.3],[.4,.5],[.2,.5],[.4,.3]])
    model=build(document,floor(features=[supplied]))
    entry=next(e for e in manifest(model).scene.elements if e.semantic_type=="table")
    assert entry.representation=="unresolved" and model.by_guid(entry.id).Representation is None
    assert not any(a.property=="footprint" for a in entry.assumptions)


def test_stair_graphic_is_level_symbol_not_inferred_risers_or_direction(document):
    model=build(document,floor(features=[feature("stairs")]))
    stairs=model.by_type("IfcStairFlight")[0]
    items=list(stairs.Representation.Representations[0].Items)
    assert len(items)>1
    base,marks=items[0],items[1:]
    assert all(mark.Position.Location.Coordinates[2]==pytest.approx(base.Position.Location.Coordinates[2]+base.Depth)for mark in marks)
    assert len({mark.Depth for mark in marks})==1
    assert stairs.NumberOfRisers is None and stairs.NumberOfTreads is None
    entry=next(e for e in manifest(model).scene.elements if e.kind=="stairs")
    assumption=next(a for a in entry.assumptions if a.property=="stair_symbol")
    assert "not a source step count or rise" in assumption.reason and "No stair travel direction" in assumption.reason
    assert len(mesh(model,stairs).faces)>12


def test_entry_door_region_can_extend_beyond_floor_without_changing_gap_or_source(document):
    panel=region(bbox=[.1,.1,.9,.98])
    cited=region(bbox=[.19,.92,.41,.985])
    wall=boundary(segment=[[.15,.938],[.8,.938]],source=region(bbox=[.1,.92,.9,.985]))
    door=opening(segment=[[.2,.938],[.4,.938]],source=cited)
    model=build(document,floor(source=panel,rooms=[],boundaries=[wall],openings=[door]))
    entry=next(e for e in manifest(model).scene.elements if e.kind=="door")
    assert entry.representation=="reconstructed" and entry.source.bbox==cited["bbox"]
    assert len(model.by_type("IfcOpeningElement"))==1
    assert model.by_type("IfcRelVoidsElement")[0].RelatingBuildingElement.GlobalId==next(e.id for e in manifest(model).scene.elements if e.kind=="wall")


@pytest.mark.parametrize("category",["boundary","feature","opening"])
def test_overlapping_source_region_does_not_permit_geometry_outside_floor(document,category):
    panel=region(bbox=[.1,.1,.8,.9])
    cited=region(bbox=[.1,.1,.95,.9])
    args={"source":panel,"rooms":[],"boundaries":[boundary(source=cited)]}
    if category=="boundary":
        args["boundaries"]=[boundary(segment=[[.2,.2],[.9,.2]],source=cited)]
    elif category=="feature":
        args["features"]=[feature(polygon=[[.7,.3],[.9,.3],[.9,.5],[.7,.5]],source=cited)]
    else:
        args["openings"]=[opening(segment=[[.7,.2],[.9,.2]],source=cited)]
    model=build(document,floor(**args))
    kind={"boundary":"wall","feature":"furniture","opening":"door"}[category]
    entry=next(e for e in manifest(model).scene.elements if e.kind==kind)
    assert entry.representation=="unresolved" and entry.source.bbox==cited["bbox"]


def test_feature_with_valid_polygon_preserves_overhanging_source_region_but_empty_shape_does_not_invent_it(document):
    panel=region(bbox=[.1,.1,.8,.9]);cited=region(bbox=[.1,.1,.95,.9])
    supplied=feature(source=cited)
    model=build(document,floor(source=panel,features=[supplied]))
    entry=next(e for e in manifest(model).scene.elements if e.kind=="furniture")
    assert entry.representation=="schematic" and entry.source.bbox==cited["bbox"]
    model=build(document,floor(source=panel,features=[supplied|{"polygon":[]}]))
    entry=next(e for e in manifest(model).scene.elements if e.kind=="furniture")
    assert entry.representation=="unresolved" and model.by_guid(entry.id).Representation is None
    assert not any(a.property=="footprint" for a in entry.assumptions)


@pytest.mark.parametrize("cited",[region(page=2),region(bbox=[.81,.1,.99,.9]),region(bbox=[.8,.1,.99,.9])])
def test_wrong_page_disjoint_or_only_touching_source_is_explicitly_unlocalized(document,cited):
    panel=region(bbox=[.1,.1,.8,.9])
    model=build(document,floor(source=panel,features=[feature(source=cited)]))
    entry=next(e for e in manifest(model).scene.elements if e.kind=="furniture")
    assert entry.representation=="unresolved" and entry.source.bbox==panel["bbox"]
    assert "Unlocalized" in entry.note


def test_invalid_feature_and_room_keep_source_or_explicit_coarse_floor_region(document):
    bad=feature(polygon=[[.2,.3],[.4,.5],[.2,.5],[.4,.3]])
    invalid=room(polygon=[[-1,.1],[.2,.2],[.3,.3]])
    model=build(document,floor(rooms=[invalid],boundaries=[],features=[bad]))
    entries=manifest(model).scene.elements
    assert all(e.representation=="unresolved" for e in entries)
    r=next(e for e in entries if e.kind=="room")
    assert r.source.bbox==[0,0,1,1] and "Unlocalized" in r.note
    f=next(e for e in entries if e.kind=="furniture")
    assert f.source.bbox==bad["source"]["bbox"]
    assert any("No 3D geometry" in w for w in manifest(model).scene.warnings)


def test_room_overlap_chain_keeps_all_entries_and_original_ids(document):
    rooms=[room("A",[[.05,.1],[.3,.1],[.3,.6],[.05,.6]]),room("B",[[.2,.1],[.45,.1],[.45,.6],[.2,.6]]),
           room("C",[[.35,.1],[.6,.1],[.6,.6],[.35,.6]]),room("D",[[.7,.1],[.9,.1],[.9,.6],[.7,.6]])]
    model=build(document,floor(rooms=rooms,boundaries=[]))
    entries=manifest(model).scene.elements
    assert len(entries)==4 and [e.representation for e in entries]==["unresolved"]*3+["reconstructed"]
    original_id=entries[3].id
    model=build(document,floor(rooms=rooms[:3]+[room("Changed D",rooms[3]["polygon"])],boundaries=[]))
    assert manifest(model).scene.elements[3].id==original_id


def test_all_unresolved_inventory_is_portable_with_explicit_no_geometry(document):
    from app.ifc_artifact import load_artifact
    d=description(floor(rooms=[],boundaries=[],unresolved=[{"label":"Unclear feature","category":"fixture","source":region(),"reason":"Symbol unclear"}]))
    data=generate_ifc(d,document);model=ifcopenshell.file.from_string(data.decode())
    artifact=manifest(model)
    assert len(artifact.scene.elements)==1 and artifact.scene.elements[0].representation=="unresolved"
    assert not model.by_type("IfcBuildingElementProxy")[0].Representation
    scene,restored,_=load_artifact(data,"new-id")
    assert scene.derived and all(e.geometry is None for e in scene.elements)
    assert restored[0][1]==document.pages[0].path.read_bytes()


def test_supported_registration_multipage_and_reopen_preserve_original_coordinates(tmp_path):
    from app.ifc_artifact import load_artifact
    from test_backend import pdf
    store=DocumentStore(tmp_path)
    try:
        document=store.add(pdf(2),"floors.pdf")
        calibration={"length_m":6,"segment":[[.1,.2],[.7,.2]],"source":region(),"note":"Reference"}
        alignment={"group":"Grid A1","anchor":[.1,.2],"source":region(),"basis":"Printed grid"}
        first=floor(calibration=calibration,alignment=alignment,rotation_degrees=0,orientation_basis="Printed orientation")
        second=floor("Upper",source=region(page=2),calibration=calibration|{"source":region(page=2)},
                     alignment=alignment|{"source":region(page=2)},rotation_degrees=180,orientation_basis="Printed orientation")
        data=generate_ifc(description(first,second),document)
        scene,pages,artifact=load_artifact(data,"new-id")
        assert scene.layout=="aligned" and [f.source.page for f in scene.floors]==[1,2]
        for f in scene.floors:
            assert [r[0]*.1+r[1]*.2+r[2]for r in f.transform[:2]]==pytest.approx([0,0])
        assert [raw for _,raw in pages]==[p.path.read_bytes()for p in document.pages]
        assert [e.id for e in scene.elements]==[e.id for e in artifact.scene.elements]
    finally:store.close()


def test_existing_resource_limits_fail_explicitly(document,monkeypatch):
    with pytest.raises(DocumentError):generate_ifc(description(floor(source=region(page=2))),document)
    monkeypatch.setattr("app.ifc_generate.MAX_ELEMENTS",2)
    with pytest.raises(DocumentError,match="element limit"):generate_ifc(description(),document)
    monkeypatch.setattr("app.ifc_generate.MAX_ELEMENTS",4000)
    monkeypatch.setattr("app.ifc_generate.MAX_TRIANGLES",1)
    with pytest.raises(DocumentError,match="triangle limit"):generate_ifc(description(),document)
    monkeypatch.setattr("app.ifc_generate.MAX_TRIANGLES",1_000_000)
    monkeypatch.setattr("app.ifc_generate.MAX_IFC_BYTES",1)
    with pytest.raises(DocumentError,match="25 MiB"):generate_ifc(description(),document)
