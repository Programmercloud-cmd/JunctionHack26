"""Task destinations and activity dismissal preserve work/results and source state."""
from fastapi.testclient import TestClient

from app.main import create_app
from test_agent_chat import AgentFixture
from test_backend import png
from test_project_chats import create_session, submission
from test_public_access_integration import prepared


def test_chat_task_records_exact_project_session_and_initiating_message(tmp_path):
    with TestClient(create_app(storage_root=tmp_path,provider_factory=lambda:AgentFixture("render"))) as client:
        store=client.app.state.documents;runner=client.app.state.jobs;document=store.add(png(),"plan.png")
        project=client.get("/api/buildings").json()["projects"][0];session=create_session(client,project,document)
        def scheduled(*args,**kwargs):
            with runner.lock:
                identity=runner._new(document,"render")
                runner._update(identity,status="complete",phase="complete",message="Synthetic metadata-only task")
                return runner.get(identity)
        runner.render=scheduled
        response=client.post("/api/chat",json=submission(project,session,document,"Render this plan"))
        assert response.status_code==200,response.text
        job=response.json()["job"]
        messages=client.get(f"/api/projects/{project['id']}/chats/{session['id']}").json()["messages"]
        assert job["origin"]=={"project_id":project["id"],"session_id":session["id"],"request_id":"Render this plan","message_id":messages[0]["id"]}
        before=runner.get(job["id"])
        dismissed=client.post(f"/api/jobs/{job['id']}/dismiss").json()
        assert dismissed["activity_dismissed"] and dismissed["status"]=="complete"
        assert dismissed["updated_at"]==before["updated_at"]
        assert store.get(document.id).source_bytes==png() and store.get(document.id).revision_id==document.revision_id
    with TestClient(create_app(storage_root=tmp_path,provider_factory=lambda:None)) as client:
        saved=client.get(f"/api/jobs/{job['id']}").json()
        assert saved["activity_dismissed"] and saved["origin"]==job["origin"]
        assert len(client.get(f"/api/projects/{project['id']}/chats/{session['id']}").json()["messages"])==2


def test_direct_task_origin_validates_project_file_and_is_immutable(tmp_path):
    with TestClient(create_app(storage_root=tmp_path,provider_factory=lambda:None)) as client:
        store=client.app.state.documents;runner=client.app.state.jobs
        document=store.add(png(),"a.png");other=store.add(png()+b"other","b.png")
        projects=client.get("/api/buildings").json()["projects"]
        project=next(p for p in projects if document.id in p["building_ids"]);wrong=next(p for p in projects if other.id in p["building_ids"])
        session=create_session(client,project,document)
        with runner.lock:identity=runner._new(document,"extraction")
        before=runner.get(identity)
        path=f"/api/jobs/{identity}/origin"
        assert client.post(path,json={"project_id":wrong["id"]}).status_code==422
        assert client.post(path,json={"project_id":project["id"],"session_id":session["id"],"message_id":"invented"}).status_code==422
        origin={"project_id":project["id"],"session_id":session["id"]}
        response=client.post(path,json=origin)
        assert response.status_code==200 and response.json()["origin"]==origin
        assert response.json()["updated_at"]==before["updated_at"]
        assert client.post(path,json={"project_id":project["id"]}).status_code==409
        assert client.post(f"/api/jobs/{identity}/dismiss").status_code==409
        assert runner.get(identity)["status"]=="queued" and not runner.events[identity].is_set()


def test_activity_mutations_reject_anonymous_before_job_access(prepared):
    root,document,_=prepared
    with TestClient(create_app(storage_root=root,provider_factory=lambda:None),base_url="https://demo.test") as client:
        assert client.post("/api/jobs/unknown/dismiss").status_code==401
        assert client.post("/api/jobs/unknown/origin",json={}).status_code==401
