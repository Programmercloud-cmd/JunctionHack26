"""Line citations must not discard an otherwise usable building description."""
import pytest
from pydantic import ValidationError

from app.building import BoundaryRegion, PageRegion
from app.ifc_artifact import load_artifact
from app.ifc_generate import generate_ifc
from app.scene import SourceRef
from app.schemas import Evidence
from test_ifc_generate import boundary, description, document, floor, region, opening


@pytest.mark.parametrize("box,segment,padded", [
    ([.1,.2,.7,.2], [[.1,.2],[.7,.2]], [.1,.19,.7,.21]),
    ([.1,.2,.1,.8], [[.1,.2],[.1,.8]], [.095,.2,.105,.8]),
    ([0,.2,0,.8], [[0,.2],[0,.8]], [0,.2,.005,.8]),
    ([1,.2,1,.8], [[1,.2],[1,.8]], [.995,.2,1,.8]),
    ([.1,0,.7,0], [[.1,0],[.7,0]], [.1,0,.7,.01]),
    ([.1,1,.7,1], [[.1,1],[.7,1]], [.1,.99,.7,1]),
])
def test_boundary_line_reopens_with_original_citation_and_selection_padding(document, box, segment, padded):
    entry = boundary(kind="open_edge", segment=segment, source=region(bbox=box))
    original = description(floor(rooms=[], boundaries=[entry]))
    scene, pages, manifest = load_artifact(generate_ifc(original,document), "reopened")
    element = scene.elements[0]
    assert element.geometry and element.representation == "schematic"
    assert element.source.bbox == pytest.approx(padded)
    assert "selection region padded" in element.note and "not measured" in element.note
    assert manifest.description.floors[0].boundaries[0].source.bbox == box
    assert manifest.description.floors[0].boundaries[0].segment == segment
    assert pages[0][1] == document.pages[0].path.read_bytes()
    assert scene.derived and scene.units == "relative"
    # Selection padding must not change physical mesh positions or stable IDs.
    area = description(floor(rooms=[], boundaries=[entry | {"source":region(bbox=padded)}]))
    comparison, _, _ = load_artifact(generate_ifc(area,document), "other")
    assert element.id == comparison.elements[0].id
    assert element.geometry.positions == comparison.elements[0].geometry.positions


@pytest.mark.parametrize("segment,page,panel", [
    ([[.1,.201],[.7,.201]],1,[0,0,1,1]),  # Within eventual padding, outside original line.
    ([[.1,.2],[.8,.2]],1,[0,0,1,1]),
    ([[.1,.2],[.7,.2]],2,[0,0,1,1]),
    ([[.1,.2],[.7,.2]],1,[.2,.1,.9,.9]),
])
def test_padding_cannot_rescue_inconsistent_boundary_association(document,segment,page,panel):
    item=boundary(kind="open_edge",segment=segment,source=region(page=page,bbox=[.1,.2,.7,.2]))
    scene,_,_=load_artifact(generate_ifc(description(floor(source=region(bbox=panel),rooms=[],boundaries=[item])),document),"new")
    element=scene.elements[0]
    assert element.representation=="unresolved" and element.geometry is None
    assert element.source.bbox==panel and "Unlocalized" in element.note


@pytest.mark.parametrize("box", [[.1,.2,.1,.2],[.7,.2,.1,.2],[-.1,.2,.7,.2],[.1,.2,1.1,.2]])
def test_invalid_boundary_regions_are_not_coerced(box):
    with pytest.raises(ValidationError):BoundaryRegion(page=1,bbox=box)


def test_only_boundary_descriptions_accept_line_sources():
    box=[.1,.2,.7,.2]
    with pytest.raises(ValidationError):PageRegion(page=1,bbox=box)
    with pytest.raises(ValidationError):SourceRef(kind="image",page=1,bbox=box)
    with pytest.raises(ValidationError):Evidence(page=1,bbox=box,label="Line",observation="Source")
    with pytest.raises(ValidationError):description(floor(source=region(bbox=box)))


def test_selection_padding_never_establishes_measured_wall_thickness(document):
    item=boundary(segment=[[.1,.2],[.7,.2]],source=region(bbox=[.1,.2,.7,.2]),
                  thickness_segment=[[.4,.199],[.4,.201]])
    scene,_,_=load_artifact(generate_ifc(description(floor(rooms=[],boundaries=[item])),document),"new")
    element=scene.elements[0]
    assert element.geometry and "selection region padded" in element.note
    assert any(a.property=="thickness" and a.value==.08 for a in element.assumptions)


def test_opening_line_citation_preserves_source_and_true_hosted_gap(document):
    line=region(bbox=[.2,.2,.3,.2])
    original=description(floor(boundaries=[boundary()],openings=[opening(source=line)]))
    scene,_,manifest=load_artifact(generate_ifc(original,document),"reopened")
    door=next(e for e in scene.elements if e.kind=="door")
    assert door.geometry and door.representation=="reconstructed"
    assert door.source.bbox==pytest.approx([.2,.19,.3,.21])
    assert "selection region padded"in door.note
    assert manifest.description.floors[0].openings[0].source.bbox==line["bbox"]
    assert manifest.description.floors[0].openings[0].segment==[[.2,.2],[.3,.2]]
    area=description(floor(boundaries=[boundary()],openings=[opening(source=region(bbox=[.2,.19,.3,.21]))]))
    other=next(e for e in load_artifact(generate_ifc(area,document),"other")[0].elements if e.kind=="door")
    assert other.id==door.id and other.geometry==door.geometry
