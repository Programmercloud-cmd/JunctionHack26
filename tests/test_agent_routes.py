"""Public and revision boundaries for agent rendering and user mark storage."""
from fastapi.testclient import TestClient

from app.main import create_app
from test_public_access_integration import prepared, unlock


def test_new_paid_routes_reject_anonymous_before_body_or_provider(prepared):
    root, document, _ = prepared
    calls = []
    def forbidden():
        calls.append(True)
        raise AssertionError("Anonymous inference")
    with TestClient(create_app(storage_root=root, provider_factory=forbidden), base_url="https://demo.test") as client:
        for path in ["/api/chat", f"/api/buildings/{document.id}/render", f"/api/buildings/{document.id}/annotations"]:
            assert client.post(path, json={}).status_code == 401
        assert client.get(f"/api/buildings/{document.id}/annotations").status_code == 404
        assert not calls


def test_readonly_example_rejects_render_and_annotations_before_side_effects(prepared):
    root, document, _ = prepared
    calls = []
    def forbidden():
        calls.append(True)
        raise AssertionError("A read-only model cannot start inference")
    with TestClient(create_app(storage_root=root, provider_factory=forbidden), base_url="https://demo.test") as client:
        unlock(client)
        store = client.app.state.documents
        directory = store.directory(document.id)
        before = {str(p.relative_to(directory)): p.read_bytes() for p in directory.rglob("*") if p.is_file()}
        assert client.post(f"/api/buildings/{document.id}/render", json={"base_revision_id": document.revision_id}).status_code == 409
        assert client.post(f"/api/buildings/{document.id}/annotations", json={"revision_id": document.revision_id,
            "kind": "point", "space": "source", "page": 1, "points": [[.2, .3]]}).status_code == 409
        after = {str(p.relative_to(directory)): p.read_bytes() for p in directory.rglob("*") if p.is_file()}
        assert before == after and not calls


def test_stale_annotation_write_rejects_before_disk_mutation(tmp_path):
    from test_backend import png
    with TestClient(create_app(storage_root=tmp_path, provider_factory=lambda: None)) as client:
        store = client.app.state.documents
        original = store.add(png(), "plan.png")
        latest = store.commit(store.prepare(original), original.revision_id, status="changed")
        response = client.post(f"/api/buildings/{original.id}/annotations", json={"revision_id": original.revision_id,
            "kind": "point", "space": "source", "page": 1, "points": [[.2, .3]]})
        assert response.status_code == 409
        assert client.get(f"/api/buildings/{original.id}/annotations").json() == {"annotations": []}
        assert store.get(original.id).revision_id == latest.revision_id


def test_grouped_drawing_chat_and_saved_history_use_all_originals(tmp_path):
    from test_backend import png
    from test_agent_chat import AgentFixture
    provider = AgentFixture("technical_basic")
    with TestClient(create_app(storage_root=tmp_path, provider_factory=lambda: provider)) as client:
        store = client.app.state.documents
        document = store.add_many([(png(), "plan.png"), (png() + b"second-source-fixture", "section.png")])
        project=client.get("/api/buildings").json()["projects"][0]
        session=client.post(f"/api/projects/{project['id']}/chats",json={"building_id":document.id}).json()
        response = client.post("/api/chat", json={"document_id": document.id, "revision_id": document.revision_id,
            "project_id":project["id"],"session_id":session["id"],"request_id": "grouped-chat", "message": "What is depicted across these sources?"})
        assert response.status_code == 200, response.text
        assert len(provider.seen[0][0].pages) == 2
        history = client.get(f"/api/projects/{project['id']}/chats/{session['id']}")
        assert history.status_code == 200
        messages = history.json()["messages"]
        assert len(messages) == 2
        assert messages[0]["question"] == "What is depicted across these sources?"
        assert messages[1]["request_id"] == "grouped-chat"
