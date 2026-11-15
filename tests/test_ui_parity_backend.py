"""Restored source, export and attributed correction boundaries, with no live inference."""
import pytest
from fastapi.testclient import TestClient

from app.agent_chat import agent_chat
from app.bundles import BuildingStore
from app.documents import DocumentError
from app.identities import assign_identities
from app.main import create_app
from app.review_schema import DescriptionPatch
from test_agent_chat import AgentFixture, Runner, request
from test_backend import png
from test_ifc_generate import description


def interpreted(store):
    source=store.add(png(),"primary.png")
    candidate=store.prepare(source)
    candidate.description=assign_identities(candidate,description())
    candidate.interpretation_status="complete"
    from app.reasoning import build_reasoning
    candidate.reasoning=build_reasoning(candidate)
    return store.commit(candidate,source.revision_id,status="interpreted")


def test_attaching_sources_and_batch_upload_preserve_original_membership(tmp_path):
    with TestClient(create_app(storage_root=tmp_path,provider_factory=lambda:None)) as client:
        store=client.app.state.documents
        original=store.add(png(),"primary.png")
        scheduled=[]
        client.app.state.jobs.extract=lambda *args,**kwargs:scheduled.append((args,kwargs)) or []
        response=client.post(f"/api/buildings/{original.id}/sources",files=[("files",("section.png",png()+b"section")),("files",("elevation.png",png()+b"elevation"))])
        assert response.status_code==200,response.text
        assert response.json()["document_id"]==original.id
        assert len(response.json()["sources"])==3 and len(response.json()["pages"])==3
        assert store.revision(original.id,original.revision_id).source_bytes==png()
        assert scheduled and len(scheduled[0][0][1])==2
        batch=client.post("/api/documents",files=[("files",("new-a.png",png()+b"newa")),("files",("new-b.png",png()+b"newb"))])
        assert batch.status_code==200 and len(batch.json()["sources"])==2


def test_explicit_corrections_are_attributed_and_scheduled_once_after_authorization(tmp_path):
    store=BuildingStore(tmp_path)
    try:
        document=interpreted(store)
        runner=Runner();submitted=[];authorized=[]
        runner.refine_inputs=lambda identity,batch:submitted.append((identity,batch)) or {"id":"refine","kind":"refinement","status":"queued"}
        provider=AgentFixture("ui")
        provider.interact_agent=lambda *args,**kwargs:{"actions":[{"type":"refine","edits":[{"property":"floor_height","scope":{"floor_id":"Ground floor"},"value":3.4,"unit":"m"}]}]}
        result=agent_chat(store,runner,lambda:provider,request(document,"Set Ground floor height to 3.4 m"),authorize_tool=authorized.append)
        assert authorized==["ui","refine"]
        assert result["job"]["kind"]=="refinement" and result["actions"]==[]
        assert len(submitted)==1 and submitted[0][1].edits[0].value==3.4
        assert submitted[0][1].edits[0].scope.floor_id==document.description.floors[0].persistent_id
        assert "Provided by user" in submitted[0][1].edits[0].reason
        assert store.get(document.id).revision_id==document.revision_id
    finally:store.close()


def test_readonly_correction_is_rejected_before_job_or_history_mutation(tmp_path):
    store=BuildingStore(tmp_path)
    try:
        document=interpreted(store);runner=Runner();submitted=[]
        runner.refine_inputs=lambda *args:submitted.append(args)
        provider=AgentFixture("ui")
        provider.interact_agent=lambda *args,**kwargs:{"actions":[{"type":"refine","edits":[{"property":"floor_height","scope":{"floor_id":"Ground floor"},"value":3,"unit":"m"}]}]}
        def authorize(tool):
            if tool=="refine":raise DocumentError("Shared example is read-only",409)
        with pytest.raises(DocumentError,match="read-only"):
            agent_chat(store,runner,lambda:provider,request(document,"Set Ground floor height to 3 m"),authorize_tool=authorize)
        assert not submitted and not store.conversation(document.id)
    finally:store.close()


def test_model_cannot_invent_numeric_user_correction(tmp_path):
    store=BuildingStore(tmp_path)
    try:
        document=interpreted(store);runner=Runner()
        runner.refine_inputs=lambda *args:pytest.fail("Unstated numeric value was submitted")
        provider=AgentFixture("ui")
        provider.interact_agent=lambda *args,**kwargs:{"actions":[{"type":"refine","edits":[{"property":"floor_height","scope":{"floor_id":"Ground floor"},"value":3,"unit":"m"}]}]}
        result=agent_chat(store,runner,lambda:provider,request(document,"Show the floor height"))
        assert result["status"]=="clarification" and not result["job"]
    finally:store.close()
