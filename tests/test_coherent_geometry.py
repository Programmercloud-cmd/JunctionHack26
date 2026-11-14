"""Source frames, building placement, exact originals and actual reopened geometry."""
import base64
import hashlib

import ifcopenshell
import pytest
from shapely.geometry import Polygon

from app.building import BuildingDescription
from app.ifc_generate import generate_ifc, _transform
from app.ifc_artifact import load_artifact
from app.documents import DocumentError
from test_ifc_generate import document, description, floor, feature, boundary, opening, region, room


def two_floors():
    lower=floor('Lower',order=0,order_basis='Source level label',features=[feature('stairs',
        polygon=[[.2,.4],[.3,.4],[.3,.6],[.2,.6]],source=region(),connection={
            'target_floor_id':'Upper','target_feature_id':'stairs','source':region(),
            'basis':'Depicted matching staircase and numbered floors','status':'supported'})])
    upper=floor('Upper',order=1,order_basis='Source level label',rooms=[room(polygon=[[.6,.2],[.9,.2],[.9,.7],[.6,.7]])],
        boundaries=[],features=[feature('stairs',polygon=[[.7,.4],[.8,.4],[.8,.6],[.7,.6]],source=region())],
        registration={'reference_floor_id':'Lower','anchor':[.7,.4],'reference_anchor':[.2,.4],
            'source':region(),'reference_source':region(),'basis':'Matching exterior and stair anchors','status':'supported'})
    return description(lower,upper)


def test_actual_registered_stacked_storeys_stairs_and_original_overlays(document):
    original=two_floors()
    data=generate_ifc(original,document)
    scene,_,manifest=load_artifact(data,'reopened')
    lower,upper=scene.floors
    assert scene.units=='relative' and scene.layout=='aligned'
    assert upper.base_elevation-lower.base_elevation==pytest.approx(1.2)
    assert _transform(lower.building_transform,_transform(lower.transform,[.2,.4]))==pytest.approx(
        _transform(upper.building_transform,_transform(upper.transform,[.7,.4])))
    stairs=[e for e in scene.elements if e.kind=='stairs']
    lower_stair=next(e for e in stairs if e.storey_id==lower.id)
    assert max(lower_stair.geometry.positions[2::3])>=upper.base_elevation
    assert any(a.property=='connectivity' for a in lower_stair.assumptions)
    upper_room=next(e for e in scene.elements if e.storey_id==upper.id and e.kind=='room')
    assert min(upper_room.geometry.positions[2::3])>1
    overlay=next(e for e in scene.comparison if e.element_id==upper_room.id)
    assert Polygon(overlay.polygons[0]).bounds==pytest.approx((.6,.2,.9,.7))
    assert manifest.description==original
    assert lower.transform==upper.transform, 'Shared original-page frame is not silently rescaled'
    assert upper.building_transform!=lower.building_transform


def test_unknown_scale_user_height_changes_only_attributed_vertical_display(document):
    original=two_floors(); original.floors[0].persistent_id='0ABCDEFGHIJKLMNOPQRSTU'
    document.user_values=[{'id':'height-value','scope':{'floor_id':original.floors[0].persistent_id},
        'property':'storey_height','value':3.9,'unit':'m','provenance':'user_provided'}]
    scene,_,manifest=load_artifact(generate_ifc(original,document),'height')
    assert scene.units=='relative'
    assert scene.floors[1].base_elevation==pytest.approx(1.8)
    assert 'Provided by user' in scene.floors[0].reference_height_basis
    assert any(a.property=='vertical_display_conversion' for a in scene.floors[0].assumptions)
    assert manifest.user_values==document.user_values
    assert original.floors[0].height is None


def test_tapered_wall_actual_mesh_keeps_source_polygon_and_named_host(document):
    footprint=[[.1,.2],[.7,.2],[.7,.28],[.1,.22]]
    d=description(floor(rooms=[],boundaries=[boundary(footprint=footprint)],openings=[]))
    scene,_,_=load_artifact(generate_ifc(d,document),'taper')
    wall=next(e for e in scene.elements if e.kind=='wall')
    entry=next(e for e in scene.comparison if e.element_id==wall.id)
    actual=Polygon(entry.polygons[0])
    assert actual.symmetric_difference(Polygon(footprint)).area<1e-9
    assert not any(a.property=='thickness' for a in wall.assumptions)
    values=d.model_dump();values["floors"][0]["openings"]=[opening(host="not-the-host")]
    d=BuildingDescription.model_validate(values)
    scene,_,_=load_artifact(generate_ifc(d,document),'host')
    assert next(e for e in scene.elements if e.kind=='door').representation=='unresolved'
    assert scene.consistency_findings


def test_v5_embeds_exact_original_and_rejects_missing_original_files(document):
    original=document.source_bytes
    data=generate_ifc(description(),document)
    _,_,manifest=load_artifact(data,'portable')
    assert manifest.version==5
    assert base64.b64decode(manifest.sources[0].original_base64)==original
    assert manifest.sources[0].source_id==hashlib.sha256(original).hexdigest()
    assert manifest.pages[0].source_id==manifest.sources[0].source_id
    document.sources=[{'source_id':hashlib.sha256(b'missing').hexdigest(),'filename':'missing.svg','kind':'drawing','pages':[]}]
    document.source_files={}
    with pytest.raises(DocumentError,match='exact original source bytes'):
        generate_ifc(description(),document)


def test_unclear_registration_does_not_connect_stairs(document):
    d=two_floors();d.floors[1].registration.status='unclear'
    scene,_,_=load_artifact(generate_ifc(d,document),'unclear')
    assert scene.layout=='schematic'
    assert not any(a.property=='connectivity' for e in scene.elements for a in e.assumptions)
    assert any('registration remains' in warning for warning in scene.warnings)
