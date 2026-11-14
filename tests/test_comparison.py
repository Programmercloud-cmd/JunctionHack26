"""Comparison must reflect actual reopened IFC geometry rather than intended description."""
import json
from pathlib import Path

import ifcopenshell
import pytest
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

from app.building import BuildingDescription
from app.documents import DocumentStore, DocumentError
from app.ifc_generate import generate_ifc
from app.ifc_artifact import load_artifact
from app.artifact_schema import PSET_NAME, MANIFEST_PROPERTY
from test_backend import png


def description():
    source={'page':1,'bbox':[0,0,1,1]}
    return BuildingDescription(floors=[dict(label='Original floor',source=source,order=None,order_basis='',
        rotation_degrees=90,orientation_basis='Visible rotated caption',calibration=None,alignment=None,measurements=[],
        rooms=[dict(label='Terrace',environment='outdoor',polygon=[[.1,.2],[.8,.2],[.8,.8],[.1,.8]],basis='observed',note='Open footprint')],
        boundaries=[dict(key='wall1',kind='wall',label='Explicit shared wall',segment=[[.1,.2],[.8,.2]],source=source,
                         thickness_segment=[],basis='observed',note='Wall material either side of door')],
        openings=[dict(kind='door',label='Door',segment=[[.3,.2],[.5,.2]],source=source,host_wall='wall1',basis='observed',note='Visible gap')],
        features=[dict(kind='table',label='Table',polygon=[[.3,.4],[.5,.4],[.5,.6],[.3,.6]],source=source,basis='observed',note='Table footprint only')],
        unresolved=[dict(label='Unreadable fixture',category='fixture',source=source,reason='Ambiguous symbol')])],limitations=[])


@pytest.fixture
def bundle(tmp_path):
    store=DocumentStore(tmp_path)
    try:
        document=store.add(png(),'drawing.png')
        data=generate_ifc(description(),document)
        yield data,store
    finally:
        store.close()


def area(entry):
    return unary_union([Polygon(p) for p in entry.polygons])


def test_actual_wall_section_preserves_door_void_and_rotated_original_footprints(bundle):
    scene,_,manifest=load_artifact(bundle[0],'fresh')
    wall=next(e for e in scene.elements if e.kind=='wall')
    opening=next(e for e in scene.elements if e.kind=='door')
    section=next(x for x in scene.comparison if x.element_id==wall.id)
    gap=next(x for x in scene.comparison if x.element_id==opening.id)
    assert section.layer=='walls' and section.cut_height is not None
    assert not area(section).covers(Point(.4,.2)), 'A filled wall projection must not conceal the actual door cut'
    assert area(section).covers(Point(.2,.2)) and area(section).covers(Point(.7,.2))
    assert area(gap).covers(Point(.4,.2)) and gap.layer=='openings'
    room=next(e for e in scene.elements if e.kind=='outdoor')
    plan=next(x for x in scene.comparison if x.element_id==room.id)
    assert area(plan).bounds==pytest.approx((.1,.2,.8,.8))
    assert manifest.description==description()
    unresolved=next(e for e in scene.elements if e.representation=='unresolved')
    missing=next(x for x in scene.comparison if x.element_id==unresolved.id)
    assert missing.layer=='unresolved' and not missing.polygons and not missing.lines


def test_comparison_changes_when_actual_ifc_moves_even_with_identical_description_and_refs(bundle):
    data,_=bundle
    before,_,original=load_artifact(data,'before')
    model=ifcopenshell.file.from_string(data.decode())
    space=model.by_type('IfcSpace')[0]
    # Move only the actual IFC placement. Description and all source metadata remain untouched.
    axis=model.create_entity('IfcAxis2Placement3D',Location=model.create_entity('IfcCartesianPoint',Coordinates=[1.,0.,0.]))
    space.ObjectPlacement=model.create_entity('IfcLocalPlacement',RelativePlacement=axis)
    after,_,changed=load_artifact(model.to_string().encode(),'after')
    old=next(e for e in before.comparison if e.element_id==space.GlobalId)
    new=next(e for e in after.comparison if e.element_id==space.GlobalId)
    assert original.description==changed.description
    assert next(e.source for e in before.elements if e.id==space.GlobalId)==next(e.source for e in after.elements if e.id==space.GlobalId)
    assert area(old).bounds!=pytest.approx(area(new).bounds)


def test_v3_semantics_and_opening_relations_cannot_disagree_with_ifc(bundle):
    data,_=bundle
    for corruption in ['semantic','void']:
        model=ifcopenshell.file.from_string(data.decode())
        if corruption=='void':
            relation=model.by_type('IfcRelFillsElement')[0]
            model.remove(relation)
        else:
            space=model.by_type('IfcSpace')[0]
            pset=next(r.RelatingPropertyDefinition for r in space.IsDefinedBy if r.RelatingPropertyDefinition.Name==PSET_NAME)
            prop=next(p for p in pset.HasProperties if p.Name=='Environment')
            prop.NominalValue=model.create_entity('IfcText','indoor')
        with pytest.raises(DocumentError):
            load_artifact(model.to_string().encode(),'corrupt')


def test_v2_manifest_remains_readable_without_new_semantic_properties(bundle):
    model=ifcopenshell.file.from_string(bundle[0].decode())
    # Build an old-format equivalent from compatible space/wall/opening entities only.
    # External real V2 artifacts are also exercised during live integration.
    for pset in model.by_type('IfcPropertySet'):
        for prop in pset.HasProperties:
            if prop.Name=='ArtifactMarker':prop.NominalValue=model.create_entity('IfcText','BlueprintQA::DrawingDerived:v2')
    project=model.by_type('IfcProject')[0];project.Description='BlueprintQA::DrawingDerived:v2'
    manifest_prop=next(p for rel in model.by_type('IfcRelDefinesByProperties') if project in rel.RelatedObjects
                       for p in rel.RelatingPropertyDefinition.HasProperties if p.Name==MANIFEST_PROPERTY)
    values=json.loads(manifest_prop.NominalValue.wrappedValue);values['version']=2;values.pop('description')
    manifest_prop.NominalValue=model.create_entity('IfcText',json.dumps(values))
    scene,_,manifest=load_artifact(model.to_string().encode(),'v2')
    assert manifest.version==2 and scene.derived and scene.source_kind=='image'
