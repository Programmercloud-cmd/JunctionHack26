"""Original resources, append-only page mapping, stable extraction and portable inputs."""
import hashlib
from io import BytesIO
from PIL import Image
import pytest
from app.bundles import BuildingStore
from app.documents import DocumentStore, DocumentError, resolve_reference
from app.building import BuildingDescription
from app.ifc_generate import generate_ifc
from app.ifc_artifact import load_artifact
from test_ifc_generate import description


def pixels(color):
    output=BytesIO();Image.new('RGB',(120,100),color).save(output,format='PNG');return output.getvalue()


def test_append_cache_revision_pinning_and_cross_building_mapping(tmp_path):
    store=BuildingStore(tmp_path)
    a,b=pixels('white'),pixels('gray')
    initial=store.add(a,'A.png');sid=hashlib.sha256(a).hexdigest()
    store.save_interpretation(sid,description())
    first=store.merge_interpretation(initial.id,sid,store.cached_interpretation(sid))
    old_revision=first.revision_id
    ids=[f.persistent_id for f in first.description.floors]
    combined=store.add_many([(b,'B.png')],first.id)
    assert [p.number for p in combined.pages]==[1,2]
    bid=hashlib.sha256(b).hexdigest()
    local=store.source_document(combined,bid)
    assert local.pages[0].number==1 and local.pages[0].source_page==1
    upper=description();upper.floors[0].label="Upper"
    store.save_interpretation(bid,upper)
    combined=store.merge_interpretation(first.id,bid,store.cached_interpretation(bid))
    assert combined.description.floors[0].persistent_id==ids[0]
    second=combined.description.floors[1]
    assert second.source.page==2 and second.source.source_page==1 and second.source.source_id==bid
    assert second.persistent_id!=ids[0]
    assert len(store.revision(first.id,old_revision).pages)==1
    store.close();reopened=BuildingStore(tmp_path)
    restored=reopened.get(first.id)
    assert restored.source_files=={sid:a,bid:b}
    assert len(restored.pages)==2 and restored.description==combined.description
    assert reopened.add(a,'renamed.png').revision_id==combined.revision_id
    assert reopened.cached_interpretation(bid)==upper
    with pytest.raises(DocumentError):resolve_reference(restored,2,sid,1)
    other=reopened.add(b,'separate.png')
    other=reopened.merge_interpretation(other.id,bid,reopened.cached_interpretation(bid))
    assert other.description.floors[0].source.page==1
    assert other.description.floors[0].persistent_id!=second.persistent_id


def test_late_source_result_keeps_appended_source_and_user_values(tmp_path):
    store=BuildingStore(tmp_path);a,b=pixels('white'),pixels('black')
    first=store.add(a,'A.png');sid=first.sources[0]['source_id']
    appended=store.add_many([(b,'B.png')],first.id)
    candidate=store.prepare(appended)
    candidate.user_values=[{'id':'height','provenance':'user_provided','property':'floor_height','value':3,'unit':'m'}]
    current=store.commit(candidate,appended.revision_id,status='user_input_saved')
    merged=store.merge_interpretation(first.id,sid,description())
    assert len(merged.sources)==2 and merged.user_values==current.user_values
    assert merged.interpretation_status=='partial'
    with pytest.raises(DocumentError):
        store.merge_interpretation(first.id,sid,description().model_copy(update={'limitations':['different interpretation']}))
    assert store.get(first.id).revision_id==merged.revision_id


def test_multisource_ifc_roundtrip_restores_exact_originals_and_inputs(tmp_path):
    store=BuildingStore(tmp_path/'store');a,b=pixels('white'),pixels('gray')
    doc=store.add_many([(a,'A.png'),(b,'B.png')])
    for source in doc.sources:
        sid=source['source_id'];store.save_interpretation(sid,description())
        doc=store.merge_interpretation(doc.id,sid,description())
    doc.user_values=[{'id':'given','property':'display_height','value':1.5,'unit':'relative','provenance':'user_provided'}]
    doc.geometry_revision_id=doc.revision_id
    data=generate_ifc(doc.description,doc)
    parsed=DocumentStore(tmp_path/'import').add(data,'reopened.ifc')
    assert parsed.kind=='drawing' and parsed.scene.derived
    assert parsed.source_files==doc.source_files
    assert parsed.source_interpretations==doc.source_interpretations
    assert parsed.user_values==doc.user_values
    assert [(p.source_id,p.source_page)for p in parsed.pages]==[(p.source_id,p.source_page)for p in doc.pages]
    assert load_artifact(data,'again')[2].geometry_revision_id==doc.revision_id


def test_repeated_floor_view_stays_source_only_not_an_extra_storey(tmp_path):
    store=BuildingStore(tmp_path);doc=store.add_many([(pixels('white'),'view.png'),(pixels('gray'),'alternate.png')])
    for source in doc.sources:
        doc=store.merge_interpretation(doc.id,source['source_id'],description())
    assert len(doc.description.floors)==1
    assert any('alternate' in view.reason for view in doc.description.unresolved_views)
    scene,_,manifest=load_artifact(generate_ifc(doc.description,doc),'repeat')
    assert len(scene.floors)==1 and len(manifest.source_interpretations)==2
    assert any(o.source.page==2 for o in doc.description.observations)


def test_native_grouping_rejected_before_publication(tmp_path):
    from test_ifc_import import fixture_model,encode
    native=encode(fixture_model()[0])
    store=BuildingStore(tmp_path)
    with pytest.raises(DocumentError,match='Native IFC'):
        store.add_many([(pixels('white'),'plan.png'),(native,'native.ifc')])
    assert store.list()==[]
    doc=store.add(pixels('white'),'plan.png')
    with pytest.raises(DocumentError,match='Native IFC'):store.add_many([(native,'native.ifc')],doc.id)
    assert store.get(doc.id).revision_id==doc.revision_id


def test_legacy_page_membership_survives_append_restart_and_export(tmp_path):
    original_store=DocumentStore(tmp_path/'original')
    original=original_store.add(pixels('white'),'plan.png')
    # A legacy imported document may preserve normalized pages but no exact source bytes.
    original.source_bytes=None;original.sources=[];original.source_files={}
    for page in original.pages:page.source_id=None;page.source_page=None
    data=generate_ifc(description(),original)
    store=BuildingStore(tmp_path/'store');doc=store.add(data,'legacy.ifc')
    first_revision=doc.revision_id
    assert not doc.sources and len(doc.pages)==1
    from test_ifc_import import fixture_model,encode
    with pytest.raises(DocumentError,match='Native IFC'):
        store.add_many([(encode(fixture_model()[0]),'native.ifc')],doc.id)
    assert store.get(doc.id).revision_id==first_revision
    doc=store.add_many([(pixels('gray'),'additional.png')],doc.id)
    store.close();store=BuildingStore(tmp_path/'store');doc=store.get(doc.id)
    assert [p.number for p in doc.pages]==[1,2]
    assert doc.pages[0].path.read_bytes()==original.pages[0].path.read_bytes()
    assert len(store.revision(doc.id,first_revision).pages)==1
    scene,pages,manifest=load_artifact(generate_ifc(doc.description,doc),'legacy-appended')
    assert len(pages)==2 and manifest.pages[0].source_id is None
    assert manifest.pages[1].source_id==doc.sources[0]['source_id']
