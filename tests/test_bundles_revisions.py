"""Durable source bundles, immutable identities, frames and failed-candidate retention."""
import json
from pathlib import Path
from threading import Event

import pytest

from app.bundles import BuildingStore
from app.documents import DocumentError,DocumentStore
from app.building import FeatureDescription
from app.identities import assign_identities,new_identity
from app.ifc_generate import generate_ifc
from app.ifc_artifact import load_artifact
from app.reasoning import build_reasoning
from app.revisions import apply_patch,regression_findings,normalize_views
from app.review_schema import DescriptionPatch,ReconstructionReview
from test_backend import png
from test_ifc_generate import description,floor,boundary,opening,feature,region


def build(store,document,desc):
    candidate=store.prepare(document)
    candidate.description=assign_identities(candidate,desc)
    candidate.ifc_bytes=generate_ifc(candidate.description,candidate)
    candidate.scene=load_artifact(candidate.ifc_bytes,candidate.id)[0]
    candidate.reasoning=build_reasoning(candidate)
    return store.commit(candidate,document.revision_id,status="preview_reviewing")


def test_restart_and_content_identity_restore_complete_bundle_without_provider(tmp_path):
    store=BuildingStore(tmp_path)
    source=png();doc=store.add(source,"original.png")
    assert store.add(source,"different-name.jpg").id==doc.id
    current=build(store,doc,description())
    original_ids=[e.id for e in current.scene.elements]
    revision=current.revision_id;data=current.ifc_bytes
    store.close()
    reopened_store=BuildingStore(tmp_path)
    reopened=reopened_store.get(doc.id)
    assert reopened.source_bytes==source and reopened.ifc_bytes==data
    assert reopened.revision_id==revision and reopened.description==current.description
    assert reopened.reasoning==current.reasoning and reopened.frame_registry==current.frame_registry
    assert [e.id for e in reopened.scene.elements]==original_ids
    assert reopened.pages[0].path.read_bytes()==current.pages[0].path.read_bytes()
    assert reopened_store.add(source,"third.png").revision_id==revision
    assert len(reopened_store.history(doc.id))==2
    reopened_store.close()


def test_long_storage_paths_preserve_unicode_upload_and_conversation(tmp_path):
    root = tmp_path / ("a" * 130) / ("b" * 130)
    source = png()
    filename = "\u6771\u4eac-\u00e9tage.png"
    message = {"role": "user", "question": "\u7a93\u306f\u3044\u304f\u3064\uff1f"}

    store = BuildingStore(root)
    document = store.add_many([(source, filename)])
    preview = document.pages[0].path.read_bytes()
    store.append_conversation(document.id, message)
    store.close()

    reopened = BuildingStore(root)
    original = reopened.get(document.id)
    assert original.filename == filename
    assert original.source_bytes == source
    assert original.pages[0].path.read_bytes() == preview
    assert reopened.conversation(document.id) == [message]
    reopened.close()


def test_reorder_insert_bbox_expansion_preserves_ids_exact_meshes_and_frames(tmp_path):
    store=BuildingStore(tmp_path)
    doc=store.add(png(),"plan.png")
    current=build(store,doc,description(floor(source=region(bbox=[.05,.1,.95,.9]))))
    candidate=store.prepare(current)
    f=candidate.description.floors[0]
    f.boundaries.reverse();f.source.bbox=[0,0,1,1]
    added=FeatureDescription.model_validate(feature("table"))
    added.persistent_id=new_identity(candidate.identity_registry)
    candidate.identity_registry["objects"][added.persistent_id]={"collection":"features","floor_id":f.persistent_id}
    f.features.insert(0,added)
    candidate.ifc_bytes=generate_ifc(candidate.description,candidate)
    candidate.scene=load_artifact(candidate.ifc_bytes,candidate.id)[0]
    before={e.id:e for e in current.scene.elements};after={e.id:e for e in candidate.scene.elements}
    assert set(before)<set(after)
    assert current.scene.floors[0].transform==candidate.scene.floors[0].transform
    for identity in before:
        assert before[identity].geometry==after[identity].geometry
        assert before[identity].source==after[identity].source
    assert not regression_findings(current,candidate,{})


def test_import_preserves_existing_artifact_globalids_and_description(tmp_path):
    original=DocumentStore(tmp_path/"old")
    doc=original.add(png(),"plan.png")
    data=generate_ifc(description(),doc)
    scene,_,manifest=load_artifact(data,doc.id)
    store=BuildingStore(tmp_path/"new")
    saved=store.add(data,"existing.ifc")
    assert saved.kind=="drawing" and saved.description
    assert [e.id for e in saved.scene.elements]==[e.id for e in scene.elements]
    assert saved.description.floors[0].persistent_id==scene.floors[0].id
    regenerate=generate_ifc(saved.description,saved)
    new_scene,_,new_manifest=load_artifact(regenerate,saved.id)
    assert new_manifest.artifact_id==manifest.artifact_id
    assert set(e.id for e in new_scene.elements)==set(e.id for e in scene.elements)
    assert new_scene.floors[0].transform==scene.floors[0].transform


def test_stale_and_stopped_publication_leave_previous_revision(tmp_path):
    store=BuildingStore(tmp_path)
    doc=store.add(png(),"plan.png")
    a=store.prepare(doc);b=store.prepare(doc)
    latest=store.commit(a,doc.revision_id,status="source_available")
    with pytest.raises(DocumentError,match="Stale"):
        store.commit(b,doc.revision_id,status="source_available")
    with pytest.raises(DocumentError,match="Stale"):
        store.commit(store.prepare(latest),latest.revision_id,status="source_available",job_guard=lambda:False)
    assert store.get(doc.id).revision_id==latest.revision_id
    store.close()
    assert BuildingStore(tmp_path).get(doc.id).revision_id==latest.revision_id


def test_targeted_bad_wall_does_not_hide_disappeared_hosted_opening(tmp_path):
    store=BuildingStore(tmp_path);doc=store.add(png(),"plan.png")
    current=build(store,doc,description(floor(boundaries=[boundary()],openings=[opening()])))
    old=current.description.floors[0].boundaries[0];floor_id=current.description.floors[0].persistent_id
    review=ReconstructionReview(candidate_supported=False,summary="Fixture correction",issues=[{
        "id":"fixture-wall","object_ids":[old.persistent_id],"source":region(),"category":"extraction",
        "discrepancy":"Fixture deliberately introduces malformed geometry","evidence":"Fixture only",
        "proposed_action":"Replace boundary","actionable":True}])
    changed=old.model_dump();changed["segment"]=[[.1,.2]]
    patch=DescriptionPatch(base_revision_id=current.revision_id,operations=[{
        "action":"replace","collection":"boundaries","target_id":old.persistent_id,"floor_id":floor_id,
        "record":changed,"evidence":region(),"reason":"Fixture only","issue_ids":["fixture-wall"]}])
    candidate,changes=apply_patch(current,patch,review)
    candidate.ifc_bytes=generate_ifc(candidate.description,candidate)
    candidate.scene=load_artifact(candidate.ifc_bytes,candidate.id)[0]
    failures=regression_findings(current,candidate,changes)
    assert any(e.id in " ".join(failures)for e in current.scene.elements if e.kind=="door")
    assert store.get(doc.id).revision_id==current.revision_id
    patch.base_revision_id="older"
    with pytest.raises(DocumentError,match="Stale"):
        apply_patch(current,patch,review)


def test_section_remains_building_source_inventory_without_placeholder_floor(tmp_path):
    source=description(floor(label="North-south section",view_type="section"))
    normalized=normalize_views(source)
    assert not normalized.floors and normalized.unresolved_views[0].view_type=="section"
    store=BuildingStore(tmp_path);doc=store.add(png(),"section.png")
    candidate=store.prepare(doc);candidate.description=normalized;candidate.reasoning=build_reasoning(candidate)
    saved=store.commit(candidate,doc.revision_id,status="source_only")
    assert saved.scene is None and saved.pages and not saved.ifc_bytes
    assert saved.reasoning["interpretation"]["unresolved_views"][0]["label"]=="North-south section"
    store.close();assert BuildingStore(tmp_path).get(doc.id).description==normalized


def test_stop_during_revision_write_cannot_publish(tmp_path,monkeypatch):
    import app.bundles as bundles
    store=BuildingStore(tmp_path);doc=store.add(png(),"plan.png")
    candidate=store.prepare(doc);stopped=Event();write=bundles._json
    def interrupt(path,value):
        write(path,value)
        if path.name=="reasoning.json":stopped.set()
    monkeypatch.setattr(bundles,"_json",interrupt)
    with pytest.raises(DocumentError,match="Stopped"):
        store.commit(candidate,doc.revision_id,status="preview_reviewing",job_guard=lambda:not stopped.is_set())
    assert store.get(doc.id).revision_id==doc.revision_id
    assert BuildingStore(tmp_path).get(doc.id).revision_id==doc.revision_id


@pytest.mark.parametrize("corruption",["frame","identity","tombstone"])
def test_reopen_rejects_registry_disagreement(tmp_path,corruption):
    import ifcopenshell
    from app.artifact_schema import MANIFEST_PROPERTY
    from test_ifc_artifact import property_for
    store=BuildingStore(tmp_path);doc=store.add(png(),"plan.png")
    current=build(store,doc,description())
    model=ifcopenshell.file.from_string(current.ifc_bytes.decode())
    prop=property_for(model,model.by_type("IfcProject")[0],MANIFEST_PROPERTY)
    data=json.loads(prop.NominalValue.wrappedValue)
    floor_id=current.scene.floors[0].id
    if corruption=="frame":data["frame_registry"][floor_id]["transform"][0][2] = 999
    elif corruption=="identity":data["identity_registry"]["objects"][current.scene.elements[0].id]["floor_id"]="wrong"
    else:data["identity_registry"]["tombstones"]=[current.scene.elements[0].id]
    prop.NominalValue=model.create_entity("IfcText",json.dumps(data))
    with pytest.raises(DocumentError):load_artifact(model.to_string().encode(),doc.id)


def test_region_only_review_cannot_remove_unrelated_feature(tmp_path):
    store=BuildingStore(tmp_path);doc=store.add(png(),"plan.png")
    current=build(store,doc,description(floor(features=[feature(source=region(bbox=[.6,.6,.8,.8]),polygon=[[.6,.6],[.8,.6],[.8,.8],[.6,.8]])])))
    f=current.description.floors[0];item=f.features[0];source=region(bbox=[.1,.1,.2,.2])
    review=ReconstructionReview(candidate_supported=False,summary="Fixture unrelated region",issues=[{
        "id":"left","object_ids":[],"source":source,"category":"extraction","discrepancy":"Fixture only",
        "evidence":"Fixture only","proposed_action":"Remove feature here","actionable":True}])
    patch=DescriptionPatch(base_revision_id=current.revision_id,operations=[{
        "action":"remove","collection":"features","floor_id":f.persistent_id,"target_id":item.persistent_id,
        "evidence":source,"reason":"Fixture only","issue_ids":["left"]}])
    with pytest.raises(DocumentError,match="unrelated"):
        apply_patch(current,patch,review)
