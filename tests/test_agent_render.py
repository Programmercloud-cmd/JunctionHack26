"""Deterministic creator/parallel-review control flow; no live fidelity claims."""
from threading import Event
import pytest

from app.agent_render import RenderReview
from app.annotations import save_annotation
from app.bundles import BuildingStore
from app.jobs import JobRunner
from app.review_schema import DescriptionPatch
from app.schemas import Usage
from test_backend import png
from test_bundles_revisions import build
from test_ifc_generate import description, region


class RenderFixture:
    def __init__(self, index, state):
        self.index, self.state = index, state
        self.closed = False
        self.usage = Usage()

    def render_candidate(self, document, **kwargs):
        self.state["proposals"] += 1
        self.state.setdefault("creator_calls",[]).append(self.index)
        if self.state.get("reject_once"):
            self.state["reject_once"] = False
            raise ValueError("private fixture provider text")
        if document.description is None:
            return description()
        if self.state.get("noops", 0):
            self.state["noops"] -= 1
            return DescriptionPatch(base_revision_id=document.revision_id)
        floor = document.description.floors[0]
        wall = floor.boundaries[0]
        record = wall.model_dump(mode="json")
        record["note"] = f"Fixture correction {self.state['proposals']}"
        return DescriptionPatch(base_revision_id=document.revision_id, operations=[{
            "action": "replace", "collection": "boundaries", "floor_id": floor.persistent_id,
            "target_id": wall.persistent_id, "record": record, "evidence": region(),
            "reason": "Fixture reviewed correction", "issue_ids": ["reviewer1:wall", "reviewer2:wall"]}])

    def review_render(self, document, *, candidate_digest, **kwargs):
        self.state["calls"].append((self.index, candidate_digest))
        if self.state.get("pause_index") == self.index:
            self.state["entered"].set()
            assert self.state["release"].wait(15)
        self.state["rounds"] = self.state["proposals"]
        satisfied = self.state["rounds"] >= self.state.get("finish_after", 1)
        satisfied = satisfied or self.state.get("first_always",False) and self.index==1
        issues = [] if satisfied else [{"id": "wall", "object_ids": [document.description.floors[0].boundaries[0].persistent_id],
            "source": region(), "category": "extraction", "discrepancy": "Fixture change still needed",
            "evidence": "Synthetic only", "proposed_action": "Correct note", "actionable": True}]
        return RenderReview(satisfied=satisfied, candidate_supported=True, summary="Fixture review", issues=issues)

    def close(self):
        self.closed = True


def setup_runner(tmp_path, **options):
    store = BuildingStore(tmp_path)
    document = store.add(png(), "plan.png")
    state = {"proposals": 0, "rounds": 0, "calls": [], "entered": Event(), "release": Event(), **options}
    clients = []
    def factory():
        provider = RenderFixture(len(clients), state)
        clients.append(provider)
        return provider
    return store, document, JobRunner(store, factory), state, clients


def test_round_uses_one_creator_and_two_independent_reviews_beyond_old_attempt_limit(tmp_path):
    store, document, runner, state, clients = setup_runner(tmp_path, finish_after=4, first_always=True)
    try:
        job = runner.render(document.id, document.revision_id, "Original exact message")
        runner.futures[job["id"]].result(20)
        result = runner.get(job["id"])
        assert result["status"] == "complete"
        assert result["render_round"] == 4 and len(clients) == 3
        assert all(p.closed and p.reconstruction_model == "gemini-4-hydrogen" for p in clients)
        assert state["creator_calls"]==[0]*4
        assert sorted(index for index,_ in state["calls"])==[1]*4+[2]*4
        assert len(state["calls"])+state["proposals"]==12
        assert result["config"]["call_policy"]=="creator_then_two_parallel_reviews"
        for digest in {digest for _,digest in state["calls"]}:
            assert sorted(index for index,item in state["calls"] if item==digest)==[1,2]
        assert len({digest for _, digest in state["calls"]}) == 4
        assert len({vote["candidate_digest"] for vote in result["reviewer_votes"]}) == 1
        assert store.get(document.id).scene.derived
        assert store.get(document.id).source_bytes == png()
    finally:
        runner.close(); store.close()


def test_provider_error_retries_without_failure_or_fake_satisfaction(tmp_path):
    store, document, runner, state, clients = setup_runner(tmp_path, reject_once=True)
    try:
        job = runner.render(document.id, document.revision_id)
        runner.futures[job["id"]].result(15)
        assert runner.get(job["id"])["status"] == "complete"
        assert state["proposals"] == 2
        assert "private fixture" not in str(runner.get(job["id"]))
    finally:
        runner.close(); store.close()


def test_repeated_noop_patches_do_not_end_rendering(tmp_path):
    store, document, runner, state, clients = setup_runner(tmp_path, finish_after=2, noops=3)
    try:
        job = runner.render(document.id, document.revision_id)
        runner.futures[job["id"]].result(20)
        result = runner.get(job["id"])
        assert result["status"] == "complete"
        assert result["render_round"] == 5 and state["proposals"] == 5
        assert len(state["calls"]) == 4  # rejected no-ops never get invented approvals
    finally:
        runner.close(); store.close()


def test_render_executor_does_not_starve_other_background_work(tmp_path):
    from threading import Lock
    store = BuildingStore(tmp_path)
    first = store.add(png(), "one.png")
    second = store.add(png() + b"fixture-two", "two.png")
    entered, release = Event(), Event()
    lock = Lock()
    entered_count = 0
    class Paused(RenderFixture):
        def review_render(self, *args, **kwargs):
            nonlocal entered_count
            with lock:
                entered_count += 1
                if entered_count == 2:
                    entered.set()
            assert release.wait(15)
            return super().review_render(*args, **kwargs)
    clients = []
    state = {"proposals": 0, "rounds": 0, "calls": []}
    def factory():
        provider = Paused(len(clients), state)
        clients.append(provider)
        return provider
    runner = JobRunner(store, factory)
    try:
        jobs = [runner.render(document.id, document.revision_id) for document in (first, second)]
        assert entered.wait(10)
        assert runner.executor.submit(lambda: "ordinary work remains available").result(2) == "ordinary work remains available"
        for job in jobs:
            runner.stop(job["id"])
        release.set()
        for job in jobs:
            runner.futures[job["id"]].result(10)
        assert all(p.closed for p in clients)
    finally:
        release.set(); runner.close(); store.close()


def test_stop_during_independent_review_prevents_publication_and_closes_clients(tmp_path):
    store, document, runner, state, clients = setup_runner(tmp_path, pause_index=1)
    try:
        job = runner.render(document.id, document.revision_id)
        assert state["entered"].wait(10)
        assert len(runner.get(job["id"])["reviewer_votes"])<=1
        runner.stop(job["id"])
        state["release"].set()
        runner.futures[job["id"]].result(10)
        assert runner.get(job["id"])["status"] == "stopped"
        assert store.get(document.id).revision_id == document.revision_id
        assert all(p.closed for p in clients)
    finally:
        state["release"].set(); runner.close(); store.close()


def test_concurrent_source_revision_interrupts_without_late_publish(tmp_path):
    store, document, runner, state, clients = setup_runner(tmp_path, pause_index=1)
    try:
        job = runner.render(document.id, document.revision_id)
        assert state["entered"].wait(10)
        latest = store.commit(store.prepare(document), document.revision_id, status="user_changed")
        state["release"].set()
        runner.futures[job["id"]].result(10)
        assert runner.get(job["id"])["status"] == "interrupted"
        assert store.get(document.id).revision_id == latest.revision_id
    finally:
        state["release"].set(); runner.close(); store.close()


def test_attached_measurement_calibrates_before_generation_and_survives_reopen(tmp_path):
    store, document, runner, state, clients = setup_runner(tmp_path)
    try:
        document = build(store, document, description())
        # Source interpretation is already saved; generated model is optional here.
        row = save_annotation(store, document.id, {"revision_id": document.revision_id, "kind": "measurement", "space": "source",
            "page": 1, "floor_id": document.description.floors[0].persistent_id,
            "points": [[.1, .2], [.7, .2]], "value": 6, "unit": "m"})
        job = runner.render(document.id, document.revision_id, annotation_ids=[row["id"]])
        runner.futures[job["id"]].result(15)
        result = runner.get(job["id"])
        assert result["status"] == "complete"
        assert state["creator_calls"]==[0] and len(state["calls"])==2
        saved = store.get(document.id)
        assert saved.description.floors[0].calibration.provenance == "user_provided"
        assert saved.description.floors[0].calibration.length_m == 6
        assert saved.user_values[0]["provenance"] == "user_provided"
        from app.ifc_artifact import load_artifact
        restored = load_artifact(saved.ifc_bytes, saved.id)
        assert restored[0].derived
    finally:
        runner.close(); store.close()


def test_source_only_missing_geometry_enters_hydrogen_enrichment_and_completes(tmp_path):
    from app.identities import assign_identities
    from test_ifc_generate import boundary
    store = BuildingStore(tmp_path)
    source = store.add(png(), "source-only.png")
    candidate = store.prepare(source)
    candidate.description = assign_identities(candidate, description())
    candidate.description.floors[0].rooms[0].polygon = []
    candidate.description.floors[0].boundaries = []
    # Registry must reflect this intentionally source-only fixture.
    live = {candidate.description.floors[0].persistent_id, candidate.description.floors[0].rooms[0].persistent_id}
    candidate.identity_registry["objects"] = {k: v for k, v in candidate.identity_registry["objects"].items() if k in live}
    candidate.interpretation_status = "complete"
    document = store.commit(candidate, source.revision_id, status="interpreted")
    state = {"proposals": 0, "rounds": 0, "calls": []}
    clients = []
    class Enriching(RenderFixture):
        def render_candidate(self, document, **kwargs):
            assert kwargs["review"] is None
            self.state["proposals"] += 1
            floor = document.description.floors[0]
            record = floor.rooms[0].model_dump(mode="json")
            record["polygon"] = [[.1, .2], [.7, .2], [.7, .8], [.1, .8]]
            return DescriptionPatch(base_revision_id=document.revision_id, operations=[
                {"action": "replace", "collection": "rooms", "floor_id": floor.persistent_id,
                 "target_id": floor.rooms[0].persistent_id, "record": record,
                 "evidence": region(), "reason": "Fixture source-supported footprint"},
                {"action": "add", "collection": "boundaries", "floor_id": floor.persistent_id,
                 "record": boundary(), "evidence": region(), "reason": "Fixture explicit wall"}])
    def factory():
        provider = Enriching(len(clients), state)
        clients.append(provider)
        return provider
    runner = JobRunner(store, factory)
    try:
        job = runner.render(document.id, document.revision_id)
        runner.futures[job["id"]].result(15)
        assert runner.get(job["id"])["status"] == "complete"
        assert state["proposals"] == 1 and len(state["calls"]) == 2
        saved = store.get(document.id)
        assert saved.description.floors[0].rooms[0].polygon
        assert any(e.geometry for e in saved.scene.elements)
    finally:
        runner.close(); store.close()


def test_reviews_overlap_with_private_candidates_and_annotations(tmp_path):
    from app.agent_render import candidate_digest as digest_of
    from app.annotations import list_annotations
    store=BuildingStore(tmp_path);document=store.add(png(),"parallel.png")
    mark=save_annotation(store,document.id,{"revision_id":document.revision_id,"kind":"point","space":"source","page":1,"points":[[.3,.4]],"label":"Original user tag"})
    entered={1:Event(),2:Event()};mutated=Event();release=Event();received={};clients=[]
    state={"proposals":0,"rounds":0,"calls":[]}
    class Parallel(RenderFixture):
        def review_render(self, candidate, *, candidate_digest, annotations, **kwargs):
            assert self.index in (1,2),"The creator must not perform a self-review"
            received[self.index]=(candidate_digest,digest_of(candidate),candidate.ifc_bytes)
            entered[self.index].set()
            assert entered[3-self.index].wait(5),"Both requests must start before either finishes"
            if self.index==1:
                candidate.ifc_bytes=b"mutated only inside reviewer one"
                annotations[0]["label"]="private mutation"
                mutated.set()
            else:
                assert mutated.wait(5)
                assert candidate.ifc_bytes!=b"mutated only inside reviewer one"
                assert annotations[0]["label"]=="Original user tag"
            assert release.wait(8)
            return super().review_render(candidate,candidate_digest=candidate_digest,annotations=annotations,**kwargs)
    def factory():
        provider=Parallel(len(clients),state);clients.append(provider);return provider
    runner=JobRunner(store,factory)
    try:
        job=runner.render(document.id,document.revision_id,annotation_ids=[mark["id"]])
        assert entered[1].wait(5) and entered[2].wait(5)
        assert store.get(document.id).revision_id==document.revision_id
        assert state["proposals"]==1
        release.set();runner.futures[job["id"]].result(10)
        result=runner.get(job["id"])
        assert result["status"]=="complete" and len(clients)==3
        assert received[1]==received[2]
        assert received[1][0]==received[1][1]==result["candidate_digest"]
        assert list_annotations(store,document.id)==[mark]
        assert state["creator_calls"]==[0] and len(state["calls"])==2
    finally:
        release.set();runner.close();store.close()


@pytest.mark.parametrize("stop",[False,True])
def test_second_review_can_finish_first_but_cannot_publish_alone(tmp_path,stop):
    store,document,runner,state,clients=setup_runner(tmp_path,pause_index=1)
    partial=Event();original_update=runner._update
    def update(identity,**fields):
        result=original_update(identity,**fields)
        votes=fields.get("reviewer_votes",[])
        if len(votes)==1 and votes[0]["reviewer"]==2:partial.set()
        return result
    runner._update=update
    try:
        job=runner.render(document.id,document.revision_id)
        assert partial.wait(8)
        saved=runner.get(job["id"])
        assert saved["status"]=="running" and saved["reviewer_votes"][0]["satisfied"]
        assert store.get(document.id).revision_id==document.revision_id
        if stop:runner.stop(job["id"])
        state["release"].set();runner.futures[job["id"]].result(10)
        result=runner.get(job["id"])
        assert result["status"]==("stopped" if stop else "complete")
        if stop:assert store.get(document.id).revision_id==document.revision_id
        else:assert [vote["reviewer"] for vote in result["reviewer_votes"]]==[1,2]
        assert all(provider.closed for provider in clients)
    finally:
        state["release"].set();runner.close();store.close()


def test_failed_review_drains_sibling_before_retry_and_never_publishes_partial_approval(tmp_path):
    store=BuildingStore(tmp_path);document=store.add(png(),"review-error.png")
    failed=Event();sibling=Event();release=Event();clients=[];attempts=[]
    state={"proposals":0,"rounds":0,"calls":[]}
    class Failing(RenderFixture):
        def review_render(self,*args,**kwargs):
            attempts.append((self.index,self.state["proposals"]))
            if self.state["proposals"]==1:
                if self.index==1:
                    failed.set();raise ValueError("private review transport failure")
                sibling.set();assert release.wait(8)
            return super().review_render(*args,**kwargs)
    def factory():
        provider=Failing(len(clients),state);clients.append(provider);return provider
    runner=JobRunner(store,factory)
    try:
        job=runner.render(document.id,document.revision_id)
        assert failed.wait(5) and sibling.wait(5)
        assert state["proposals"]==1 and store.get(document.id).revision_id==document.revision_id
        release.set();runner.futures[job["id"]].result(15)
        result=runner.get(job["id"])
        assert result["status"]=="complete" and state["proposals"]==2
        assert sorted(attempts)==[(1,1),(1,2),(2,1),(2,2)]
        assert len({v["candidate_digest"] for v in result["reviewer_votes"]})==1
        assert "private review transport failure" not in str(result)
        assert all(provider.closed for provider in clients)
    finally:
        release.set();runner.close();store.close()


def test_stop_during_creator_call_never_launches_reviews(tmp_path):
    store=BuildingStore(tmp_path);document=store.add(png(),"creator-stop.png")
    entered=Event();release=Event();clients=[];state={"proposals":0,"rounds":0,"calls":[]}
    class Creating(RenderFixture):
        def render_candidate(self,*args,**kwargs):
            entered.set();assert release.wait(8)
            return super().render_candidate(*args,**kwargs)
    def factory():
        provider=Creating(len(clients),state);clients.append(provider);return provider
    runner=JobRunner(store,factory)
    try:
        job=runner.render(document.id,document.revision_id)
        assert entered.wait(5);runner.stop(job["id"]);release.set()
        runner.futures[job["id"]].result(10)
        assert runner.get(job["id"])["status"]=="stopped"
        assert not state["calls"] and store.get(document.id).revision_id==document.revision_id
        assert all(provider.closed for provider in clients)
    finally:
        release.set();runner.close();store.close()


@pytest.mark.parametrize("unsupported_index",[1,2])
def test_satisfaction_without_both_source_support_votes_keeps_published_ifc_lineage(tmp_path,unsupported_index):
    store=BuildingStore(tmp_path);document=store.add(png(),"unsupported.png")
    second_creator=Event();release=Event();clients=[];state={"proposals":0,"rounds":0,"calls":[]}
    class Unsupported(RenderFixture):
        def render_candidate(self,*args,**kwargs):
            if self.state["proposals"]==1:
                second_creator.set();assert release.wait(8)
            return super().render_candidate(*args,**kwargs)
        def review_render(self,candidate,**kwargs):
            state.setdefault("candidate_metadata",{})[self.state["proposals"]]=(
                candidate.revision_id,candidate.parent_revision_id,candidate.revision_number)
            vote=super().review_render(candidate,**kwargs)
            if self.state["proposals"]==1 and self.index==unsupported_index:
                return RenderReview.model_validate({**vote.model_dump(),"candidate_supported":False,"satisfied":True,"issues":[{
                    "id":"wall","object_ids":[candidate.description.floors[0].boundaries[0].persistent_id],
                    "source":region(),"category":"extraction","discrepancy":"Synthetic support rejection",
                    "evidence":"Synthetic original","proposed_action":"Correct note","actionable":True}]})
            return vote
    def factory():
        provider=Unsupported(len(clients),state);clients.append(provider);return provider
    runner=JobRunner(store,factory)
    try:
        job=runner.render(document.id,document.revision_id)
        assert second_creator.wait(8)
        assert store.get(document.id).revision_id==document.revision_id
        assert any(issue["discrepancy"]=="Synthetic support rejection" for issue in runner.get(job["id"])["issues"])
        release.set();runner.futures[job["id"]].result(10)
        assert runner.get(job["id"])["status"]=="complete" and state["proposals"]==2
        from app.ifc_artifact import load_artifact
        saved=store.get(document.id)
        reopened,_,manifest=load_artifact(saved.ifc_bytes,saved.id)
        rejected_id=state["candidate_metadata"][1][0]
        assert rejected_id!=saved.revision_id
        assert saved.revision_number==document.revision_number+1
        assert saved.parent_revision_id==document.revision_id
        for scene in (saved.scene,reopened,manifest.scene):
            assert scene.revision_id==saved.revision_id
            assert scene.revision_number==saved.revision_number
            assert scene.parent_revision_id==saved.parent_revision_id
        assert state["candidate_metadata"][2]==(saved.revision_id,document.revision_id,saved.revision_number)
        history=store.history(document.id)
        assert {item["revision_id"] for item in history}=={document.revision_id,saved.revision_id}
        assert (store.directory(document.id)/"revisions"/saved.parent_revision_id/"revision.json").is_file()
        assert saved.source_bytes==document.source_bytes==png()
    finally:
        release.set();runner.close();store.close()
