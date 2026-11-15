"""Production rendering adapters through the real SDK with intercepted HTTP, never live."""
import json

import httpx2

from app.agent_render import inspect, propose, candidate_digest
from app.bundles import BuildingStore
from app.providers.gemini import GeminiProvider
from app.review_schema import ReconstructionReview
from test_backend import png
from test_bundles_revisions import build
from test_ifc_generate import description, region


def test_hydrogen_render_vote_inspects_originals_and_actual_geometry(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "offline-render-test")
    store = BuildingStore(tmp_path)
    document = build(store, store.add(png(), "plan.png"), description())
    provider = GeminiProvider()
    provider.reconstruction_model = "gemini-4-hydrogen"
    calls = []
    def handle(request):
        body = json.loads(request.content)
        calls.append((str(request.url), body))
        output = {"candidate_supported": True, "satisfied": True, "summary": "Intercepted render review", "issues": []}
        return httpx2.Response(200, json={"candidates": [{"content": {"role": "model", "parts": [{"text": json.dumps(output)}]}, "finishReason": "STOP"}],
                                         "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5}})
    provider.client._api_client._httpx_client.close()
    provider.client._api_client._httpx_client = httpx2.Client(transport=httpx2.MockTransport(handle))
    try:
        digest = candidate_digest(document)
        vote = inspect(provider, document, digest, [], "Keep the original shape")
        assert vote.satisfied
        url, body = calls[0]
        assert "gemini-4-hydrogen" in url
        assert "satisfied" in body["generationConfig"]["responseJsonSchema"]["required"]
        parts = body["contents"][0]["parts"]
        text = "\n".join(part.get("text", "") for part in parts)
        assert digest in text and "actual_geometry_inventory" in text
        assert sum("inlineData" in part for part in parts) >= 2  # original + actual-IFC overlay
    finally:
        provider.close(); store.close()


def test_hydrogen_proposal_uses_typed_patch_and_keeps_user_marks_attributed(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "offline-render-test")
    store = BuildingStore(tmp_path)
    document = build(store, store.add(png(), "plan.png"), description())
    provider = GeminiProvider()
    provider.reconstruction_model = "gemini-4-hydrogen"
    calls = []
    def handle(request):
        calls.append(json.loads(request.content))
        output = {"base_revision_id": document.revision_id, "operations": []}
        return httpx2.Response(200, json={"candidates": [{"content": {"role": "model", "parts": [{"text": json.dumps(output)}]}, "finishReason": "STOP"}],
                                         "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5}})
    provider.client._api_client._httpx_client.close()
    provider.client._api_client._httpx_client = httpx2.Client(transport=httpx2.MockTransport(handle))
    annotation = {"id": "fixture-mark", "space": "source", "points": [[.2, .3]], "provenance": "user_provided"}
    try:
        result = propose(provider, document, ReconstructionReview(candidate_supported=True, summary="Synthetic finding"),
                         None, [annotation], "Use this mark")
        assert result.base_revision_id == document.revision_id
        assert len(calls)==1
        body = calls[0]
        text = "\n".join(part.get("text", "") for part in body["contents"][0]["parts"])
        assert "fixture-mark" in text and "user_provided" in text
        assert "User-authored instructions and dimensions" in text
        assert "persistent_id" in text
    finally:
        provider.close(); store.close()


def test_real_sdk_issues_one_creation_and_two_overlapping_review_requests(tmp_path,monkeypatch):
    from threading import Barrier, Lock
    from app.jobs import JobRunner
    monkeypatch.setenv("GEMINI_API_KEY","offline-parallel-render-test")
    store=BuildingStore(tmp_path);document=store.add(png(),"parallel-sdk.png")
    barrier=Barrier(2,timeout=8);lock=Lock();calls=[];providers=[]
    def factory():
        index=len(providers);provider=GeminiProvider();providers.append(provider)
        def handle(request):
            body=json.loads(request.content)
            with lock:calls.append((index,str(request.url),body))
            if index==0:output=description().model_dump(mode="json")
            else:
                barrier.wait()  # a sequential implementation cannot pass
                output={"candidate_supported":True,"satisfied":True,"summary":"Intercepted independent review","issues":[]}
            return httpx2.Response(200,json={"candidates":[{"content":{"role":"model","parts":[{"text":json.dumps(output)}]},"finishReason":"STOP"}],
                                           "usageMetadata":{"promptTokenCount":10,"candidatesTokenCount":5}})
        provider.client._api_client._httpx_client.close()
        provider.client._api_client._httpx_client=httpx2.Client(transport=httpx2.MockTransport(handle))
        return provider
    runner=JobRunner(store,factory)
    try:
        job=runner.render(document.id,document.revision_id)
        runner.futures[job["id"]].result(20)
        result=runner.get(job["id"])
        assert result["status"]=="complete" and result["render_round"]==1
        assert len(providers)==3 and sorted(index for index,_,_ in calls)==[0,1,2]
        for index,url,body in calls:
            assert "gemini-4-hydrogen" in url
            if index:
                parts=body["contents"][0]["parts"]
                text="\n".join(part.get("text","") for part in parts)
                assert result["candidate_digest"] in text and "actual_geometry_inventory" in text
                assert sum("inlineData" in part for part in parts)>=2
        assert [c["role"] for c in result["provider_calls"]]==["creator","reviewer_1","reviewer_2"]
        assert store.get(document.id).source_bytes==png()
    finally:
        barrier.abort();runner.close();store.close()
