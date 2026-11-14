"""Fixture provider concurrency tests; no live reconstruction claims."""
from threading import Event

from fastapi.testclient import TestClient

from app.bundles import BuildingStore
from app.jobs import JobRunner
from app.main import create_app
from app.review_schema import ReconstructionReview,DescriptionPatch
from app.schemas import Usage,AskRequest,DraftAnswer
from test_backend import png,evidence
from test_bundles_revisions import build
from test_ifc_generate import description,floor,boundary,opening,region
from test_ifc_generate import feature
import pytest
from test_reviewed_qa import ReviewedFixture


class ReconstructionFixture:
    def __init__(self,*,pause=False,regression=False,section=False):
        self.usage=Usage();self.entered=Event();self.release=Event();self.pause=pause
        self.regression=regression;self.section=section;self.reviews=0
    def reconstruct(self,document):
        return description(floor(boundaries=[boundary()],openings=[opening()],view_type="section" if self.section else "floor_plan"))
    def review_reconstruction(self,document,description,scene,**kwargs):
        self.reviews+=1;self.entered.set()
        if self.pause:assert self.release.wait(10)
        issues=[]
        if self.regression:
            issues=[{"id":"wall","object_ids":[description.floors[0].boundaries[0].persistent_id],
                "source":region(),"category":"extraction","discrepancy":"Fixture malformed wall requested",
                "evidence":"Fixture only","proposed_action":"Replace wall","actionable":True}]
        assessment={"delta_support":"unsupported" if self.regression else "supported","source_conflicts":[],
            "new_regressions":[],"pre_existing_issue_ids":[],"unresolved":[],"issue_resolutions":[]} if kwargs.get("change_context") is not None else None
        return ReconstructionReview(candidate_supported=not self.regression,summary="Fixture review",issues=issues,candidate_assessment=assessment)
    def patch_reconstruction(self,document,description,scene,review):
        f=description.floors[0];wall=f.boundaries[0];record=wall.model_dump();record["segment"]=[[.1,.2]]
        return DescriptionPatch(base_revision_id=document.revision_id,operations=[{
            "action":"replace","collection":"boundaries","floor_id":f.persistent_id,"target_id":wall.persistent_id,
            "record":record,"evidence":region(),"reason":"Fixture loss test","issue_ids":["wall"]}])
    def close(self):pass


def test_preview_is_published_before_review_and_stop_prevents_late_result(tmp_path):
    store=BuildingStore(tmp_path);doc=store.add(png(),"plan.png")
    provider=ReconstructionFixture(pause=True);runner=JobRunner(store,lambda:provider)
    try:
        job=runner.reconstruct(doc.id,doc.revision_id)
        assert provider.entered.wait(10)
        preview=store.get(doc.id)
        assert preview.scene and preview.review_status=="preview_reviewing"
        assert runner.get(job["id"])["status"]=="running"
        runner.stop(job["id"]);provider.release.set();runner.futures[job["id"]].result(10)
        assert runner.get(job["id"])["status"]=="stopped"
        assert store.get(doc.id).revision_id==preview.revision_id
    finally:provider.release.set();runner.close();store.close()


def test_regressive_patch_preserves_usable_revision_and_saved_candidate(tmp_path):
    store=BuildingStore(tmp_path);doc=store.add(png(),"plan.png")
    provider=ReconstructionFixture(regression=True);runner=JobRunner(store,lambda:provider)
    try:
        job=runner.reconstruct(doc.id);runner.futures[job["id"]].result(10)
        final=runner.get(job["id"])
        assert final["status"]=="needs_attention" and final["attempts"][0]["accepted"] is False
        assert store.get(doc.id).scene.elements
        assert any(e.kind=="door" and e.geometry for e in store.get(doc.id).scene.elements)
        assert (store.directory(doc.id)/final["attempts"][0]["candidate"]/"model.ifc").exists()
    finally:runner.close();store.close()


def test_section_job_publishes_source_inventory_without_placeholder_geometry(tmp_path):
    store=BuildingStore(tmp_path);doc=store.add(png(),"section.png")
    provider=ReconstructionFixture(section=True);runner=JobRunner(store,lambda:provider)
    try:
        job=runner.reconstruct(doc.id);runner.futures[job["id"]].result(10)
        saved=store.get(doc.id)
        assert saved.review_status=="source_only" and saved.scene is None
        assert saved.public()["unresolved_views"][0]["view_type"]=="section"
        assert provider.reviews==0
    finally:runner.close();store.close()


def test_qa_pins_revision_and_revalidates_highlights_after_concurrent_revision(tmp_path):
    store=BuildingStore(tmp_path);source=store.add(png(),"plan.png");doc=build(store,source,description())
    room=next(e for e in doc.scene.elements if e.kind=="room")
    entered=Event();release=Event()
    class SlowQA(ReviewedFixture):
        def review_answer(self,*args,**kwargs):
            entered.set();assert release.wait(10)
            return super().review_answer(*args,**kwargs)
        def close(self):pass
    provider=SlowQA(DraftAnswer(status="answered",answer="Room footprint shown.",
        evidence=[evidence(bbox=room.source.bbox)|{"label":room.name,"observation":room.name}],highlight_ids=[room.id]))
    runner=JobRunner(store,lambda:provider)
    try:
        job=runner.question(AskRequest(document_id=doc.id,revision_id=doc.revision_id,question="Which room?"))
        assert entered.wait(10)
        changed=store.prepare(doc);changed.scene.elements=[e for e in changed.scene.elements if e.id!=room.id]
        latest=store.commit(changed,doc.revision_id,status="preview_reviewing")
        release.set();runner.futures[job["id"]].result(10)
        answer=runner.get(job["id"])["answer"]
        assert answer["answered_revision_id"]==doc.revision_id and answer["display_revision_id"]==latest.revision_id
        assert answer["evidence"] and answer["highlight_ids"]==[]
    finally:release.set();runner.close();store.close()


def test_api_repeat_upload_and_restart_reopen_without_inference(tmp_path):
    def forbidden():raise AssertionError("Reopen must not call inference")
    with TestClient(create_app(storage_root=tmp_path,provider_factory=forbidden))as client:
        first=client.post("/api/documents",files={"file":("plan.png",png())}).json()
        second=client.post("/api/documents",files={"file":("renamed.png",png())}).json()
        assert first["is_new_upload"] and not second["is_new_upload"]
        assert first["revision_id"]==second["revision_id"]
    with TestClient(create_app(storage_root=tmp_path,provider_factory=forbidden))as client:
        saved=client.get("/api/buildings").json()["buildings"]
        assert len(saved)==1 and saved[0]["revision_id"]==first["revision_id"]
        opened=client.get("/api/buildings/"+first["building_id"]).json()
        assert opened["pages"]
        # New upload starts source extraction once; reopen and reupload never retry it.
        assert len(opened["jobs"])==1 and opened["jobs"][0]["kind"]=="extraction"


def test_deadline_crossed_during_bundle_write_does_not_publish(tmp_path,monkeypatch):
    import app.bundles as bundles
    import app.jobs as jobs
    store=BuildingStore(tmp_path);doc=store.add(png(),"plan.png")
    provider=ReconstructionFixture();runner=JobRunner(store,lambda:provider)
    write=bundles._json;now=[100.0]
    monkeypatch.setattr(jobs,"monotonic",lambda:now[0])
    def expire(path,value):
        write(path,value)
        if path.name=="scene.json":now[0]=10000
    monkeypatch.setattr(bundles,"_json",expire)
    try:
        job=runner.reconstruct(doc.id);runner.futures[job["id"]].result(10)
        assert runner.get(job["id"])["status"]=="budget_exhausted"
        saved=store.get(doc.id)
        assert saved.revision_id!=doc.revision_id and saved.description is not None
        assert saved.scene is None and saved.reasoning["interpretation"] is not None
    finally:runner.close();store.close()


def test_stop_between_qa_final_check_and_publication_discards_answer(tmp_path,monkeypatch):
    store=BuildingStore(tmp_path);doc=store.add(png(),"plan.png")
    class QA(ReviewedFixture):
        def close(self):pass
    provider=QA(DraftAnswer(status="answered",answer="Fixture",evidence=[evidence()]))
    runner=JobRunner(store,lambda:provider)
    # Create the request explicitly to deterministically intercept the final store read.
    identity=runner._new(doc,"question")
    get=store.get
    def stop_at_read(key):
        runner.events[identity].set()
        return get(key)
    monkeypatch.setattr(store,"get",stop_at_read)
    try:
        runner._question(identity,doc.snapshot(),"Fixture question")
        assert "answer" not in runner.get(identity)
        runner.stop(identity)
        assert runner.get(identity)["status"]=="stopped"
    finally:runner.close();store.close()


@pytest.mark.parametrize("case",["unchanged","additive","missing","duplicate","section"])
def test_existing_model_reextraction_requires_identity_and_source_review(tmp_path,case):
    store=BuildingStore(tmp_path);source=store.add(png(),"plan.png")
    original=description(floor(boundaries=[boundary()],openings=[opening()]))
    current=build(store,source,original)
    class Replacement(ReconstructionFixture):
        def reconstruct(self,document):
            replacement=original.model_copy(deep=True)
            if case=="additive":
                from app.building import FeatureDescription
                replacement.floors[0].features.append(FeatureDescription.model_validate(feature()))
            elif case=="missing":replacement.floors[0].openings=[]
            elif case=="duplicate":replacement.floors[0].boundaries.append(replacement.floors[0].boundaries[0].model_copy(deep=True))
            elif case=="section":replacement.floors[0].view_type="section"
            return replacement
        def review_reconstruction(self,document,description,scene,**kwargs):
            assert store.get(current.id).revision_id==current.revision_id
            assert kwargs["previous_scene"]
            return super().review_reconstruction(document,description,scene,**kwargs)
    provider=Replacement();runner=JobRunner(store,lambda:provider)
    try:
        job=runner.reconstruct(current.id,current.revision_id,"reconstruct");runner.futures[job["id"]].result(10)
        saved=store.get(current.id);status=runner.get(job["id"])["status"]
        if case in {"unchanged","additive"}:
            assert status=="complete" and provider.reviews==1
            assert {e.id for e in current.scene.elements}<={e.id for e in saved.scene.elements}
            assert saved.scene.floors[0].transform==current.scene.floors[0].transform
        else:
            assert status=="needs_attention" and provider.reviews==0
            assert saved.revision_id==current.revision_id and saved.ifc_bytes==current.ifc_bytes
    finally:runner.close();store.close()


def test_pinned_native_record_inspection_includes_nonrendered_semantic_records(tmp_path):
    from test_ifc_import import fixture_model,encode
    model,*_=fixture_model();storey=model.by_type("IfcBuildingStorey")[0]
    with TestClient(create_app(storage_root=tmp_path))as client:
        doc=client.post("/api/documents",files={"file":("source.ifc",encode(model))}).json()
        scene=client.get(doc["scene_url"]).json()
        assert storey.GlobalId not in {e["id"]for e in scene["elements"]}
        base=f'/api/buildings/{doc["building_id"]}/revisions/{doc["revision_id"]}/evidence/'
        result=client.get(base+storey.GlobalId)
        assert result.status_code==200 and result.json()["record"]["ifc_type"]=="IfcBuildingStorey"
        assert result.json()["record"]["values"] and result.json()["source_kind"]=="ifc"
        assert client.get(base+"unknown").status_code==404
        drawing=client.post("/api/documents",files={"file":("plan.png",png())}).json()
        assert client.get(f'/api/buildings/{drawing["building_id"]}/revisions/{drawing["revision_id"]}/evidence/'+storey.GlobalId).status_code==422
