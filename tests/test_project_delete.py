"""Deleting project organization keeps shared files and reversible session ownership."""
from fastapi.testclient import TestClient

from app.main import create_app
from test_backend import png
from test_public_access_integration import prepared, unlock


def test_project_delete_restore_shared_files_and_chats_survive_restart(tmp_path):
    with TestClient(create_app(storage_root=tmp_path,provider_factory=lambda:None)) as client:
        assert client.get("/api/health").json()["project_deletion_ready"] is True
        store=client.app.state.documents;document=store.add(png(),"plan.png")
        project=client.get("/api/buildings").json()["projects"][0]
        path=f"/api/projects/{project['id']}"
        chat=client.post(path+"/chats",json={"name":"Saved discussion","building_id":document.id}).json()
        shared=client.post("/api/projects",json={"name":"Shared original"}).json()
        client.put(f"/api/projects/{shared['id']}/files/{document.id}")
        assert client.delete(path).status_code==200
        assert client.get(path+"/chats/"+chat["id"]).status_code==404
        assert client.post("/api/chat",json={"project_id":project["id"],"session_id":chat["id"],"document_id":document.id,"revision_id":document.revision_id,"message":"Deleted context","request_id":"deleted"}).status_code==404
        for _ in range(2):
            catalog=client.get("/api/buildings").json()
            assert [p["id"] for p in catalog["projects"]]==[shared["id"]]
        # Another metadata write must preserve the deleted project tombstone.
        client.patch(f"/api/projects/{shared['id']}",json={"name":"Renamed shared project"})
        assert store.get(document.id).source_bytes==png()
        assert store.get(document.id).revision_id==document.revision_id
    with TestClient(create_app(storage_root=tmp_path,provider_factory=lambda:None)) as client:
        assert project["id"] not in str(client.get("/api/buildings").json()["projects"])
        assert client.post(path+"/restore").json()==project
        assert client.get(path+"/chats/"+chat["id"]).json()["name"]=="Saved discussion"
        assert client.post(path+"/restore").status_code==404
        assert client.delete(path).status_code==200
        assert client.delete(path).status_code==404
        assert client.delete(f"/api/projects/{shared['id']}").status_code==200
        assert client.get("/api/buildings").json()["projects"]==[]


def test_project_delete_and_restore_require_editor_and_reject_examples(prepared):
    root,document,private=prepared
    with TestClient(create_app(storage_root=root,provider_factory=lambda:None),base_url="https://demo.test") as client:
        example=client.get("/api/buildings").json()["projects"][0]
        for method,path in [("delete",f"/api/projects/{example['id']}"),("post",f"/api/projects/{example['id']}/restore")]:
            assert getattr(client,method)(path).status_code==401
        unlock(client)
        assert client.delete(f"/api/projects/{example['id']}").status_code==404
        assert client.post(f"/api/projects/{example['id']}/restore").status_code==404
        project=client.post("/api/projects",json={"name":"Private project"}).json()
        client.put(f"/api/projects/{project['id']}/files/{private.id}")
        assert client.delete(f"/api/projects/{project['id']}").status_code==200
        client.cookies.clear()
        assert client.post(f"/api/projects/{project['id']}/restore").status_code==401
        assert "Private project" not in str(client.get("/api/buildings").json())
