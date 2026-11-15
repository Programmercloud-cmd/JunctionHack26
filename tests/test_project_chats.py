"""Session history and evidence must never cross project/file boundaries."""
from fastapi.testclient import TestClient

from app.main import create_app
from test_agent_chat import AgentFixture
from test_backend import png
from test_public_access_integration import prepared, unlock


def create_session(client,project,document=None):
    response=client.post(f"/api/projects/{project['id']}/chats",json={"building_id":document.id if document else None})
    assert response.status_code==201,response.text
    return response.json()


def submission(project,session,document=None,message="Hello",**extra):
    return {"project_id":project["id"],"session_id":session["id"],"document_id":document.id if document else None,
            "revision_id":document.revision_id if document else None,"message":message,"request_id":message,**extra}


def test_sessions_use_only_server_owned_project_history_and_survive_restart(tmp_path):
    providers=[]
    def factory():
        provider=AgentFixture();providers.append(provider);return provider
    with TestClient(create_app(storage_root=tmp_path,provider_factory=factory)) as client:
        document=client.app.state.documents.add(png(),"plan.png")
        project=client.get("/api/buildings").json()["projects"][0]
        first=create_session(client,project,document);second=create_session(client,project,document)
        assert client.post("/api/chat",json=submission(project,first,document,"First scoped message")).status_code==200
        assert client.post("/api/chat",json=submission(project,first,document,"Follow up")).status_code==200
        assert len(providers[-1].conversation_context["conversation"]["messages"])==2
        assert client.post("/api/chat",json=submission(project,second,document,"Separate session",history=[{"role":"user","content":"Wrong imported context"}])).status_code==200
        assert providers[-1].conversation_context["conversation"]["messages"]==[]
        other=client.post("/api/projects",json={"name":"Same original, different project"}).json()
        client.put(f"/api/projects/{other['id']}/files/{document.id}")
        other_chat=create_session(client,other,document)
        assert client.post("/api/chat",json=submission(other,other_chat,document,"Other project's session")).status_code==200
        assert providers[-1].conversation_context["conversation"]["messages"]==[]
        assert not client.app.state.documents.conversation(document.id)
    with TestClient(create_app(storage_root=tmp_path,provider_factory=factory)) as client:
        restored=client.get(f"/api/projects/{project['id']}/chats/{first['id']}").json()
        assert len(restored["messages"])==4
        assert restored["messages"][0]["question"]=="First scoped message"


def test_cross_project_session_or_file_rejected_before_any_model_call(tmp_path):
    calls=[]
    with TestClient(create_app(storage_root=tmp_path,provider_factory=lambda:calls.append(True))) as client:
        store=client.app.state.documents;a=store.add(png(),"a.png");b=store.add(png()+b"second","b.png")
        projects=client.get("/api/buildings").json()["projects"]
        pa=next(p for p in projects if a.id in p["building_ids"]);pb=next(p for p in projects if b.id in p["building_ids"])
        chat=create_session(client,pa,a)
        assert client.post("/api/chat",json={"document_id":a.id,"revision_id":a.revision_id,"message":"Unscoped old page","request_id":"old"}).status_code==422
        assert client.post("/api/chat",json=submission(pb,chat,b)).status_code==404
        assert client.post("/api/chat",json=submission(pa,chat,b)).status_code==409
        assert client.post(f"/api/projects/{pb['id']}/chats",json={"building_id":a.id}).status_code==422
        assert client.get(f"/api/projects/{pb['id']}/chats/{chat['id']}").status_code==404
        assert client.patch(f"/api/projects/{pb['id']}/chats/{chat['id']}",json={"name":"Wrong"}).status_code==404
        assert not calls


def test_empty_project_cannot_inherit_last_building_or_client_history(tmp_path):
    providers=[]
    def factory():
        provider=AgentFixture("technical_basic");providers.append(provider);return provider
    with TestClient(create_app(storage_root=tmp_path,provider_factory=factory)) as client:
        unrelated=client.app.state.documents.add(png(),"previous.png")
        empty=client.post("/api/projects",json={"name":"Empty project"}).json();chat=create_session(client,empty)
        assert client.post("/api/chat",json=submission(empty,chat,unrelated)).status_code==409
        result=client.post("/api/chat",json=submission(empty,chat,message="How many rooms?",history=[{"role":"assistant","content":"Previous building facts"}]))
        assert result.status_code==200 and result.json()["status"]=="clarification"
        assert providers[-1].router_context["document_id"] is None
        assert providers[-1].router_context["conversation"]["messages"]==[]
        assert not providers[-1].seen


def test_rename_last_active_delete_and_legacy_import_do_not_resurrect(tmp_path):
    with TestClient(create_app(storage_root=tmp_path,provider_factory=lambda:None)) as client:
        store=client.app.state.documents;document=store.add(png(),"legacy.png")
        store.append_conversation(document.id,{"id":"past","role":"user","question":"Historical question","timestamp":123.0})
        project=client.get("/api/buildings").json()["projects"][0]
        path=f"/api/projects/{project['id']}/chats";chats=client.get(path).json()["chats"]
        assert len(chats)==1
        chat=chats[0];assert chat["last_active"]==123.0
        renamed=client.patch(path+"/"+chat["id"],json={"name":"Saved discussion"}).json()
        assert renamed["name"]=="Saved discussion" and renamed["last_active"]==123.0
        assert client.delete(path+"/"+chat["id"]).status_code==200
        assert client.get(path).json()["chats"]==[]
        assert client.get(path+"/"+chat["id"]).status_code==404
        assert store.get(document.id).source_bytes==png()


def test_anonymous_cannot_read_sessions_and_authorized_example_chat_keeps_originals_readonly(prepared):
    root,document,_=prepared
    with TestClient(create_app(storage_root=root,provider_factory=lambda:AgentFixture()),base_url="https://demo.test") as client:
        project=client.get("/api/buildings").json()["projects"][0]
        path=f"/api/projects/{project['id']}/chats"
        assert client.get(path).status_code in {401,404}
        assert client.post(path,json={}).status_code==401
        unlock(client);chat=create_session(client,project,document)
        assert client.post("/api/chat",json=submission(project,chat,document)).status_code==200
        assert client.get(path).json()["chats"][0]["id"]==chat["id"]
        assert client.app.state.documents.get(document.id).revision_id==document.revision_id
