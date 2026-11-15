"""Persistent project organization and reversible marks, without live inference."""
import pytest
from fastapi.testclient import TestClient

from app.annotations import change_annotations, list_annotations, save_annotation, selected_annotations
from app.bundles import BuildingStore
from app.documents import DocumentError
from app.main import create_app
from test_backend import png
from test_public_access_integration import prepared, unlock


def test_projects_migrate_rename_group_and_resume_without_rewriting_sources(tmp_path):
    with TestClient(create_app(storage_root=tmp_path,provider_factory=lambda:None)) as client:
        store=client.app.state.documents
        a=store.add(png(),"plan.png");b=store.add(png()+b"section","section.png")
        catalog=client.get("/api/buildings").json()
        project=next(p for p in catalog["projects"] if a.id in p["building_ids"])
        assert client.patch(f"/api/projects/{project['id']}",json={"name":"Renovation A"}).json()["name"]=="Renovation A"
        assert client.put(f"/api/projects/{project['id']}/files/{b.id}").status_code==200
        assert client.put(f"/api/projects/{project['id']}/active-file/{b.id}").json()["active_building_id"]==b.id
        assert client.put(f"/api/projects/{project['id']}/active-file/{'f'*64}").status_code==422
        assert store.get(a.id).source_bytes==png() and store.get(b.id).source_bytes==png()+b"section"
        assert store.get(a.id).revision_id==a.revision_id
    with TestClient(create_app(storage_root=tmp_path,provider_factory=lambda:None)) as client:
        project=next(p for p in client.get("/api/buildings").json()["projects"] if p["id"]==project["id"])
        assert project["name"]=="Renovation A" and project["active_building_id"]==b.id
        assert project["building_ids"]==[a.id,b.id]


def test_empty_project_and_unlink_preserve_saved_files_without_remigration(tmp_path):
    with TestClient(create_app(storage_root=tmp_path,provider_factory=lambda:None)) as client:
        assert client.post("/api/projects",json={"name":"  "}).status_code==422
        project=client.post("/api/projects",json={"name":"New project"}).json()
        document=client.app.state.documents.add(png(),"plan.png")
        assert client.put(f"/api/projects/{project['id']}/files/{document.id}").status_code==200
        assert len(client.get("/api/buildings").json()["projects"])==1
        assert client.delete(f"/api/projects/{project['id']}/files/{document.id}").status_code==200
        catalog=client.get("/api/buildings").json()
        assert len(catalog["projects"])==1 and not catalog["projects"][0]["building_ids"]
        assert client.app.state.documents.get(document.id).source_bytes==png()
        assert client.put(f"/api/projects/{project['id']}/files/{document.id}").status_code==200


def test_erased_marks_are_not_chat_inputs_and_restore_the_same_identity_after_restart(tmp_path):
    store=BuildingStore(tmp_path);document=store.add(png(),"plan.png")
    row=save_annotation(store,document.id,{"revision_id":document.revision_id,"kind":"stroke","space":"source","page":1,"points":[[.1,.2],[.5,.6]]})
    body={"revision_id":document.revision_id,"annotation_ids":[row["id"]],"active":False}
    change_annotations(store,document.id,body)
    assert not list_annotations(store,document.id)
    with pytest.raises(DocumentError,match="unavailable"):
        selected_annotations(store,document,[row["id"]])
    # Creating another mark must not discard the erased mark needed by Redo/Undo.
    save_annotation(store,document.id,{"revision_id":document.revision_id,"kind":"point","space":"source","page":1,"points":[[.7,.8]]})
    store.close();store=BuildingStore(tmp_path)
    restored=change_annotations(store,document.id,{**body,"active":True})["annotations"][0]
    assert restored==row and len(list_annotations(store,document.id))==2
    assert store.get(document.id).source_bytes==png();store.close()


def test_mark_batch_is_atomic_and_cannot_edit_a_replaced_revision(tmp_path):
    store=BuildingStore(tmp_path);document=store.add(png(),"plan.png")
    row=save_annotation(store,document.id,{"revision_id":document.revision_id,"kind":"point","space":"source","page":1,"points":[[.2,.3]]})
    body={"revision_id":document.revision_id,"annotation_ids":[row["id"],"unknown"],"active":False}
    with pytest.raises(DocumentError):change_annotations(store,document.id,body)
    assert list_annotations(store,document.id)==[row]
    store.commit(store.prepare(document),document.revision_id,status="changed")
    with pytest.raises(DocumentError,match="earlier revision"):
        change_annotations(store,document.id,{**body,"annotation_ids":[row["id"]]})
    assert list_annotations(store,document.id)==[row];store.close()


def test_public_projects_do_not_leak_private_names_and_edits_check_authorization(prepared):
    root,document,private=prepared
    with TestClient(create_app(storage_root=root,provider_factory=lambda:None),base_url="https://demo.test") as client:
        catalog=client.get("/api/buildings").json()
        assert len(catalog["projects"])==1 and catalog["projects"][0]["read_only"]
        assert private.id not in str(catalog["projects"])
        assert client.post("/api/projects",json={"name":"New"}).status_code==401
        assert client.patch(f"/api/buildings/{document.id}/annotations",json={}).status_code==401
        unlock(client)
        assert client.patch(f"/api/buildings/{document.id}/annotations",json={"revision_id":document.revision_id,"annotation_ids":["unknown"],"active":False}).status_code==409
        assert client.patch(f"/api/projects/{catalog['projects'][0]['id']}",json={"name":"Changed"}).status_code==404
