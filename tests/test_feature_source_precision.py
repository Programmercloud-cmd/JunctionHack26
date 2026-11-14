"""Feature-only raster precision; synthetic geometry, never dataset inference fixtures."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.ifc_artifact import load_artifact
from app.ifc_generate import _feature_polygon, _inside, _valid_polygon, generate_ifc
from test_ifc_generate import document, description, floor, feature, boundary, opening, region


BOX=[.2,.3,.4,.5]
FLOOR=[0,0,1,1]
PAGE=SimpleNamespace(width=200,height=100)


def rectangle(right=.4,bottom=.5):
    return [[.2,.3],[right,.3],[right,bottom],[.2,bottom]]


@pytest.mark.parametrize('axis',[0,1])
@pytest.mark.parametrize('pixel_overrun',[.012,.0335,.5])
def test_feature_source_subpixel_rounding_keeps_exact_inputs(axis,pixel_overrun):
    extent=BOX[axis+2]+pixel_overrun/[PAGE.width,PAGE.height][axis]
    points=rectangle(right=extent) if axis==0 else rectangle(bottom=extent)
    before=deepcopy(points);box=BOX.copy()
    shape,reason,rounded=_feature_polygon(points,box,FLOOR,PAGE)
    assert shape is not None and reason=='' and rounded
    assert list(shape.exterior.coords)[:-1]==[tuple(p)for p in points]
    assert points==before and box==BOX
    # Ordinary polygon/citation containment is still strict for all other callers.
    assert _valid_polygon(points,box) is None
    assert not all(_inside(p,box)for p in points)


@pytest.mark.parametrize('axis',[0,1])
def test_feature_beyond_half_pixel_remains_unresolved(axis):
    extent=BOX[axis+2]+.50001/[PAGE.width,PAGE.height][axis]
    points=rectangle(right=extent) if axis==0 else rectangle(bottom=extent)
    shape,reason,rounded=_feature_polygon(points,BOX,FLOOR,PAGE)
    assert shape is None and not rounded and 'more than half' in reason


@pytest.mark.parametrize('points,region_box,reason',[
    ([[.2,.3],[.4,.5],[.4,.3],[.2,.5]],FLOOR,'self-intersecting'),
    ([[.25,.375],[.3125,.4375],[.375,.5]],FLOOR,'positive area'),
    ([[.2,.3],[.3,.4]],FLOOR,'fewer than three'),
    ([[.2,.3],[1.000001,.3],[.4,.5]],FLOOR,'coordinates'),
    (rectangle(right=.40001),[.1,.1,.4,.7],'floor source region'),
])
def test_rounding_never_bypasses_topology_page_or_floor_guards(points,region_box,reason):
    shape,message,rounded=_feature_polygon(points,BOX,region_box,PAGE)
    assert shape is None and not rounded and reason in message


@pytest.mark.parametrize('dimensions',[(None,100),(200,0),(True,100),(200,float('nan')),(200.0,100)])
def test_invalid_saved_raster_dimensions_keep_strict_containment(dimensions):
    page=SimpleNamespace(width=dimensions[0],height=dimensions[1])
    shape,reason,rounded=_feature_polygon(rectangle(right=.40001),BOX,FLOOR,page)
    assert shape is None and not rounded and 'raster dimensions are unavailable' in reason
    # Missing dimensions do not invalidate an already strictly contained footprint.
    shape,reason,rounded=_feature_polygon(rectangle(),BOX,FLOOR,page)
    assert shape is not None and not reason and not rounded


def test_unclosed_valid_polygon_is_not_a_closure_error():
    shape,reason,rounded=_feature_polygon(rectangle(),BOX,FLOOR,PAGE)
    assert shape is not None and not reason and not rounded
    assert shape.exterior.coords[0]==shape.exterior.coords[-1]


def test_actual_ifc_reopen_preserves_source_polygon_ids_and_rounding_note(document):
    points=rectangle(right=.4+.0335/document.pages[0].width)
    item=feature(polygon=points,source=region(bbox=BOX))
    desc=description(floor(rooms=[],boundaries=[],features=[item]))
    before=desc.model_dump(mode='json')
    first=generate_ifc(desc,document)
    scene,pages,embedded=load_artifact(first,document.id)
    element=scene.elements[0]
    assert element.representation=='schematic' and element.geometry
    assert element.source.bbox==BOX and 'half a saved source-page pixel' in element.note
    assert embedded.description.model_dump(mode='json')==before
    assert desc.model_dump(mode='json')==before
    second=load_artifact(generate_ifc(desc,document),document.id)[0]
    assert second.elements[0].id==element.id
    assert second.elements[0].source==element.source
    assert second.elements[0].geometry.positions==element.geometry.positions
    assert embedded.pages[0].width==document.pages[0].width and embedded.pages[0].height==document.pages[0].height


def test_boundary_and_opening_source_checks_do_not_inherit_feature_tolerance(document):
    shift=.0335/document.pages[0].width
    wall=boundary(segment=[[.2,.2],[.4+shift,.2]],source=region(bbox=[.2,.19,.4,.21]))
    # This small source discrepancy must still invalidate the physical wall.
    desc=description(floor(rooms=[],boundaries=[wall]))
    scene=load_artifact(generate_ifc(desc,document),document.id)[0]
    assert scene.elements[0].representation=='unresolved' and scene.elements[0].geometry is None
    wall=boundary(segment=[[.1,.2],[.7,.2]])
    door=opening(segment=[[.2,.2],[.3+shift,.2]],source=region(bbox=[.19,.19,.3,.21]))
    scene=load_artifact(generate_ifc(description(floor(rooms=[],boundaries=[wall],openings=[door])),document),document.id)[0]
    element=next(e for e in scene.elements if e.kind=='door')
    assert element.representation=='unresolved' and element.geometry is None
    assert 'outside its original source region' in element.note
