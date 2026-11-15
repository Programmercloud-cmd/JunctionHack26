"""Output-limit recovery uses real SDK requests intercepted locally, never live inference."""
import json
from threading import Barrier, Event, Lock

import httpx2

from app.bundles import BuildingStore
from app.identities import assign_identities
from app.jobs import JobRunner
from app.providers.gemini import GeminiProvider
from test_backend import png
from test_ifc_generate import boundary, description, region


def response(output, *, limit=False):
    return httpx2.Response(200, json={
        "candidates": [{"content": {"role": "model", "parts": [{"text": json.dumps(output)}]},
                        "finishReason": "MAX_TOKENS" if limit else "STOP"}],
        "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 40000 if limit else 100,
                          "thoughtsTokenCount": 25536 if limit else 10}})


def test_output_limit_recovers_incrementally_with_all_findings_and_parallel_reviews(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "offline-incremental-render-test")
    store = BuildingStore(tmp_path)
    original = store.add(png(), "source-only.png")
    candidate = store.prepare(original)
    source_only = description()
    source_only.floors[0].boundaries = []
    source_only.floors[0].rooms[0].polygon = []
    candidate.description = assign_identities(candidate, source_only)
    candidate.interpretation_status = "complete"
    document = store.commit(candidate, original.revision_id, status="interpreted")
    barrier = Barrier(2, timeout=8)
    providers, creator_inputs, review_inputs = [], [], []
    lock = Lock()

    def factory():
        index = len(providers)
        provider = GeminiProvider()
        providers.append(provider)

        def handle(request):
            body = json.loads(request.content)
            parts = body["contents"][0]["parts"]
            data = next(json.loads(part["text"]) for part in parts
                        if "text" in part and '"user_annotations"' in part["text"])
            assert any("inlineData" in part for part in parts), "Original source must remain supplied"
            if index == 0:
                creator_inputs.append((body, data))
                count = len(creator_inputs)
                if count == 1:
                    return response({"private_truncated_response": "never accepted"}, limit=True)
                floor = data["description"]["floors"][0]
                if count == 2:
                    room = dict(floor["rooms"][0])
                    room["polygon"] = [[.1, .2], [.7, .2], [.7, .8], [.1, .8]]
                    operation = {"action": "replace", "collection": "rooms", "target_id": room["persistent_id"],
                                 "record": json.dumps(room)}
                else:
                    assert floor["rooms"][0]["polygon"] and not floor["boundaries"]
                    assert len(data["review"]["issues"]) == 2
                    operation = {"action": "add", "collection": "boundaries", "record": json.dumps(boundary()),
                                 "issue_ids": [item["id"] for item in data["review"]["issues"]]}
                operation.update(floor_id=floor["persistent_id"], evidence=region(), reason="Synthetic inspected change")
                return response({"base_revision_id": data["base_revision_id"], "operations": [operation]})
            with lock:
                review_inputs.append((index, data))
            barrier.wait()
            floor = data["description"]["floors"][0]
            complete = bool(floor["boundaries"])
            issues = [] if complete else [{"id": "missing-wall", "object_ids": [floor["persistent_id"]],
                "category": "extraction", "source": region(), "discrepancy": "Explicit wall remains missing",
                "evidence": "Synthetic source", "proposed_action": "Add the depicted wall", "actionable": True}]
            return response({"candidate_supported": True, "satisfied": complete,
                             "summary": "Synthetic independent review", "issues": issues})

        provider.client._api_client._httpx_client.close()
        provider.client._api_client._httpx_client = httpx2.Client(transport=httpx2.MockTransport(handle))
        return provider

    runner = JobRunner(store, factory)
    try:
        job = runner.render(document.id, document.revision_id, "Build this drawing")
        runner.futures[job["id"]].result(25)
        result = runner.get(job["id"])
        assert result["status"] == "complete" and result["render_round"] == 3
        assert len(creator_inputs) == 3 and len(review_inputs) == 4
        feedback = creator_inputs[1][1]["validation_feedback"]
        assert feedback["category"] == "provider_output_limit"
        assert "smaller coherent part" in feedback["message"]
        assert creator_inputs[1][1]["suggested_incremental_focus"]
        instruction = creator_inputs[1][0]["systemInstruction"]["parts"][0]["text"]
        assert "guidance, not a restriction" in instruction
        assert "all review findings remain context" in instruction
        assert len(result["provider_calls"]) == 7
        assert result["provider_calls"][0]["outcome"] == "output_limit"
        assert result["last_render_failure"]["category"] == "provider_output_limit"
        for first, second in (review_inputs[:2], review_inputs[2:]):
            assert {first[0], second[0]} == {1, 2}
            assert first[1]["candidate_digest"] == second[1]["candidate_digest"]
        saved = store.get(document.id)
        assert saved.description.floors[0].rooms[0].polygon
        assert saved.description.floors[0].boundaries
        assert saved.source_bytes == original.source_bytes == png()
        assert len(store.history(document.id)) == 4  # original, interpretation, supported partial, completion
    finally:
        barrier.abort()
        runner.close()
        store.close()


def test_late_output_limit_after_stop_preserves_safe_telemetry_without_reopening_job(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "offline-stopped-render-test")
    entered, release = Event(), Event()
    store = BuildingStore(tmp_path)
    document = store.add(png(), "stop.png")
    providers = []

    def factory():
        provider = GeminiProvider()
        providers.append(provider)

        def handle(request):
            entered.set()
            assert release.wait(8)
            # A malicious/unrecognized payload field must never enter public job metadata.
            provider.provider_calls[-1]["private_response"] = "private fixture body"
            return response({"private_response": "private fixture body"}, limit=True)

        provider.client._api_client._httpx_client.close()
        provider.client._api_client._httpx_client = httpx2.Client(transport=httpx2.MockTransport(handle))
        return provider

    runner = JobRunner(store, factory)
    try:
        job = runner.render(document.id, document.revision_id)
        assert entered.wait(5)
        runner.stop(job["id"])
        release.set()
        runner.futures[job["id"]].result(10)
        result = runner.get(job["id"])
        assert result["status"] == result["phase"] == "stopped"
        assert len(result["provider_calls"]) == 1
        assert result["provider_calls"][0]["outcome"] == "output_limit"
        assert result["provider_calls"][0]["candidate_tokens"] == 40000
        assert result["provider_calls"][0]["role"] == "creator"
        assert "private fixture" not in json.dumps(result)
        assert not result["reviewer_votes"]
        assert store.get(document.id).revision_id == document.revision_id
        assert len(providers) == 3
    finally:
        release.set()
        runner.close()
        store.close()


def test_failed_review_call_is_saved_while_sibling_is_still_in_flight(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "offline-failed-review-test")
    failed_saved, sibling_entered, release = Event(), Event(), Event()
    store = BuildingStore(tmp_path)
    document = store.add(png(), "failed-review.png")
    providers = []

    def factory():
        index = len(providers)
        provider = GeminiProvider()
        providers.append(provider)

        def handle(request):
            if index == 0:
                return response(description().model_dump(mode="json"))
            if index == 1:
                assert sibling_entered.wait(5)
                return response({"private_response": "truncated review"}, limit=True)
            sibling_entered.set()
            assert release.wait(8)
            return response({"candidate_supported": True, "satisfied": True, "summary": "Synthetic", "issues": []})

        provider.client._api_client._httpx_client.close()
        provider.client._api_client._httpx_client = httpx2.Client(transport=httpx2.MockTransport(handle))
        return provider

    runner = JobRunner(store, factory)
    save_job = store.save_job

    def observe_save(building_id, job):
        save_job(building_id, job)
        if any(call.get("role") == "reviewer_1" and call.get("outcome") == "output_limit"
               for call in job.get("provider_calls", [])):
            failed_saved.set()

    store.save_job = observe_save
    try:
        job = runner.render(document.id, document.revision_id)
        assert failed_saved.wait(8), "Failed review telemetry must not wait for the sibling or a successful pair"
        current = runner.get(job["id"])
        assert current["status"] == "running" and current["phase"] == "render_review_parallel"
        assert store.get(document.id).revision_id == document.revision_id
        runner.stop(job["id"])
        release.set()
        runner.futures[job["id"]].result(10)
        result = runner.get(job["id"])
        assert result["status"] == "stopped"
        assert len(result["provider_calls"]) == 3
        assert result["provider_calls"][1]["outcome"] == "output_limit"
        assert not result["reviewer_votes"]
        assert store.get(document.id).revision_id == document.revision_id
    finally:
        release.set()
        runner.close()
        store.close()
