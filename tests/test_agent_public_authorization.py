"""Public chat authorization keeps read-only denials distinct from provider failures."""
import hashlib

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from test_agent_chat import AgentFixture
from test_public_access_integration import prepared, unlock


def example_session(client, document):
    project = next(item for item in client.get("/api/buildings").json()["projects"]
                   if document.id in item["building_ids"])
    response = client.post(f"/api/projects/{project['id']}/chats", json={"building_id": document.id})
    assert response.status_code == 201, response.text
    return project, response.json()


def request_body(project, session, document, message):
    return {"project_id": project["id"], "session_id": session["id"],
            "document_id": document.id, "revision_id": document.revision_id,
            "message": message, "request_id": "public-authorization-fixture"}


def stored_hashes(directory):
    return {str(path.relative_to(directory)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in directory.rglob("*") if path.is_file()}


@pytest.mark.parametrize("operation", ["render", "refine"])
def test_readonly_example_chat_mutation_returns_409_before_job_or_history(prepared, operation):
    root, document, _ = prepared
    provider = AgentFixture("render" if operation == "render" else "ui")
    if operation == "refine":
        provider.interact_agent = lambda *args, **kwargs: {"actions": [{"type": "refine", "edits": [{
            "property": "floor_height", "scope": {"floor_id": document.description.floors[0].persistent_id},
            "value": 3, "unit": "m"}]}]}
    message = "Render the model" if operation == "render" else "Set Ground floor height to 3 m"
    scheduled = []
    with TestClient(create_app(storage_root=root, provider_factory=lambda: provider), base_url="https://demo.test") as client:
        unlock(client)
        project, session = example_session(client, document)
        store, runner = client.app.state.documents, client.app.state.jobs
        runner.render = lambda *args, **kwargs: scheduled.append("render")
        runner.refine_inputs = lambda *args, **kwargs: scheduled.append("refine")
        before = stored_hashes(store.directory(document.id))
        response = client.post("/api/chat", json=request_body(project, session, document, message))
        assert response.status_code == 409, response.text
        assert "read-only" in response.json()["detail"]
        assert "provider" not in response.json()["detail"].lower()
        assert not scheduled and not runner.for_building(document.id)
        assert stored_hashes(store.directory(document.id)) == before
        restored = client.get(f"/api/projects/{project['id']}/chats/{session['id']}").json()
        assert restored["messages"] == []
        assert provider.closed


def test_readonly_example_source_question_remains_available_after_unlock(prepared):
    root, document, _ = prepared
    provider = AgentFixture("technical_basic")
    with TestClient(create_app(storage_root=root, provider_factory=lambda: provider), base_url="https://demo.test") as client:
        unlock(client)
        project, session = example_session(client, document)
        store = client.app.state.documents
        before = stored_hashes(store.directory(document.id))
        response = client.post("/api/chat", json=request_body(project, session, document, "What is depicted in the original?"))
        assert response.status_code == 200, response.text
        answer = response.json()["answer"]
        assert answer["status"] == "answered"
        assert answer["answered_revision_id"] == answer["display_revision_id"] == document.revision_id
        assert answer["evidence"] and answer["gate"] is None
        assert stored_hashes(store.directory(document.id)) == before
        assert len(client.get(f"/api/projects/{project['id']}/chats/{session['id']}").json()["messages"]) == 2


def test_anonymous_chat_is_denied_before_provider_or_context_body_validation(prepared):
    root, _, _ = prepared
    providers = []
    def forbidden():
        providers.append(True)
        raise AssertionError("Anonymous requests must not construct a provider")
    with TestClient(create_app(storage_root=root, provider_factory=forbidden), base_url="https://demo.test") as client:
        response = client.post("/api/chat", json={})
        assert response.status_code == 401
        assert not providers and not client.app.state.jobs.jobs
