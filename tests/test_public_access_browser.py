"""Public access UI with synthetic API fixtures; no live inference or secrets."""
import os

import pytest
from test_browser_3d import scene_page
from test_sourcefirst_browser import setup_routes, static_server

pytestmark = pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS") != "1", reason="opt-in browser checks")


def public_fixture(page):
    document, messages, requests = setup_routes(page)
    document.update(public_example=True, read_only_model=True, pinned_revision_id=document["revision_id"], example_title="Assembly hall example")
    access = {"public_demo": True, "can_work": False, "shared_workspace": False}
    access_calls = []

    def handle_access(route):
        path = route.request.url.split("/api/access", 1)[1]
        access_calls.append((route.request.method, path))
        if path == "/unlock":
            if route.request.post_data_json["code"] != "fixture-access-code":
                return route.fulfill(status=401, json={"detail": "Access code not accepted."})
            access.update(can_work=True, shared_workspace=True)
        elif path == "/lock":
            access.update(can_work=False, shared_workspace=False)
        route.fulfill(json=access)

    page.route("**/api/access**", handle_access)
    def route_chat(route):
        data = route.request.post_data_json
        requests.append((route.request.method, "chat/actions", None))
        if not access["can_work"]:
            return route.fulfill(status=401, json={"detail": "Enter the access code to use paid or private features."})
        route.fulfill(json={"request_id": data["request_id"], "document_id": data["document_id"],
                            "revision_id": data["revision_id"], "geometry_revision_id": data["workspace"]["geometry_revision_id"],
                            "navigation_epoch": data["workspace"]["navigation_epoch"], "status": "ready",
                            "actions": [{"type": "question", "question": data["message"]}]})
    page.route("**/api/chat/actions", route_chat)
    examples = [{**document, "building_id": f"{i:064x}", "document_id": f"{i:064x}", "example_title": f"Cached example {i}"} for i in range(8)] + [document]
    page.route("**/api/buildings", lambda route: route.fulfill(json={"buildings": [item for item in examples if access["can_work"] or item["public_example"]]}))
    return document, messages, requests, access, access_calls


def open_example(page, url, document):
    from playwright.sync_api import expect
    page.goto(url)
    expect(page.locator("#access-panel")).to_be_visible()
    page.locator("#home-library-list").get_by_role("button", name=document["example_title"]).click()
    expect(page.locator("#page-image")).to_be_visible()


def unlock(page):
    from playwright.sync_api import expect
    page.get_by_role("tab", name="Home").click()
    page.locator("#access-code").fill("fixture-access-code")
    page.locator("#access-unlock").click()
    expect(page.locator("#access-title")).to_have_text("Workspace unlocked")
    expect(page.locator("#access-code")).to_have_value("")


def test_anonymous_examples_and_unlock_do_not_replay_paid_actions(static_server, scene_page):
    from playwright.sync_api import expect
    page = scene_page
    document, messages, requests, access, calls = public_fixture(page)
    page.route("**/api/voice/config", lambda route: route.fulfill(
        status=200 if access["can_work"] else 404,
        json={"transcription_ready": access["can_work"], "speech_ready": access["can_work"]},
    ))
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    open_example(page, static_server, document)
    expect(page.locator("#home-library-list li")).to_have_count(9)
    expect(page.locator("#attachment-summary")).to_contain_text(document["filename"])
    expect(page.locator("#access-shared")).to_contain_text("not a private personal workspace")
    expect(page.locator("#question")).to_be_disabled()
    expect(page.locator("#file-input")).to_be_disabled()
    expect(page.locator("#home-upload")).to_be_disabled()
    expect(page.locator("#voice-record")).to_be_disabled()
    expect(page.locator("#voice-read-answers")).to_be_disabled()
    expect(page.locator("#access-model-note")).to_contain_text("read-only model")
    assert not any(path.endswith("/conversation") for _, path, _ in requests)
    expect(page.locator("#conversation-error")).to_be_hidden()
    # Even a scripted submit/drop does not replay a paid action after unlock.
    page.locator("#question-form").evaluate("form=>form.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}))")
    expect(page.locator("#access-message")).to_contain_text("explicitly submit")
    page.locator("#access-code").fill("incorrect-fixture-code")
    page.locator("#access-unlock").click()
    expect(page.locator("#access-message")).to_have_text("Access code not accepted.")
    expect(page.locator("#access-code")).to_have_value("")
    unlock(page)
    expect(page.locator("#question")).to_be_enabled()
    expect(page.locator("#file-input")).to_be_enabled()
    expect(page.locator("#home-upload")).to_be_enabled()
    expect(page.locator("#voice-record")).to_be_enabled()
    expect(page.locator("#voice-read-answers")).to_be_enabled()
    expect(page.locator("#voice-read-answers")).to_have_attribute("aria-pressed", "false")
    expect(page.locator("#append-sources")).to_be_disabled()
    expect(page.locator("#generate-scene")).to_be_disabled()
    expect(page.locator("#assumption-rows input").first).to_be_disabled()
    assert not any(method == "POST" for method, _, _ in requests)
    assert "fixture-access-code" not in page.evaluate("JSON.stringify([localStorage,sessionStorage])")
    page.locator("#home-library-list button").filter(has_text=document["example_title"]).click()
    page.locator("#question").fill("Which space is depicted?")
    page.locator("#ask-button").click()
    expect(page.locator("#chat-log")).to_contain_text("assembly hall")
    assert len([1 for method, path, _ in requests if method == "POST" and path == "questions"]) == 1
    assert not errors


def test_expired_access_401_requires_explicit_retry_and_lock_clears_private_chat(static_server, scene_page):
    from playwright.sync_api import expect
    page = scene_page
    document, messages, requests, access, calls = public_fixture(page)
    open_example(page, static_server, document)
    unlock(page)
    page.locator("#home-library-list button").filter(has_text=document["example_title"]).click()
    denied = []

    def deny_question(route):
        denied.append(route.request.method)
        route.fulfill(status=401, json={"detail": "Enter the access code to use paid or private features."})

    page.route("**/api/chat/actions", deny_question)
    page.locator("#question").fill("A question after access expires")
    page.locator("#ask-button").click()
    expect(page.locator("#chat-log")).to_contain_text("Enter the access code")
    access.update(can_work=False, shared_workspace=False)
    page.get_by_role("tab", name="Home").click()
    page.locator("#access-refresh").click()
    expect(page.locator("#access-form")).to_be_visible()
    unlock(page)
    assert denied == ["POST"]  # unlock never resubmits the rejected question
    page.locator("#home-library-list button").filter(has_text=document["example_title"]).click()
    page.locator("#question").fill("Explicitly retried question")
    page.locator("#ask-button").click()
    expect(page.locator("#chat-log")).to_contain_text("Enter the access code")
    assert denied == ["POST", "POST"]
    page.get_by_role("tab", name="Home").click()
    page.locator("#access-lock").click()
    expect(page.locator("#access-title")).to_have_text("Explore the public examples")
    expect(page.locator("#conversation")).to_be_empty()
    expect(page.locator("#file-input")).to_be_disabled()
    assert ("POST", "/lock") in calls


def test_lock_discards_private_workspace_and_late_action_response(static_server, scene_page):
    from playwright.sync_api import expect
    from test_browser import source_bytes
    page = scene_page
    document, messages, requests, access, calls = public_fixture(page)
    open_example(page, static_server, document)
    unlock(page)
    private_id = "e" * 64
    private = dict(document, document_id=private_id, building_id=private_id,
                   public_example=False, read_only_model=False, example_title=None,
                   filename="Private uploaded source.png")
    page.route("**/api/documents", lambda route: route.fulfill(json=private))
    page.route(f"**/api/buildings/{private_id}", lambda route: route.fulfill(json=private))
    page.route("**/api/buildings", lambda route: route.fulfill(
        json={"buildings": [document, private] if access["can_work"] else [document]},
    ))
    page.get_by_role("tab", name="Home").click()
    page.wait_for_function("!document.getElementById('home-upload').disabled")
    page.locator("#file-input").set_input_files({"name": "private.png", "mimeType": "image/png", "buffer": source_bytes()})
    page.locator("#home-library-list button").filter(has_text="Private uploaded source.png").click()
    page.wait_for_function("state.document?.read_only_model===false")
    pending = []
    page.route("**/api/chat/actions", lambda route: pending.append(route))
    page.locator("#question").fill("Private in-flight question")
    page.locator("#ask-button").click()
    expect(page.locator("#chat-log")).to_contain_text("Private in-flight question")
    assert len(pending) == 1
    body = pending[0].request.post_data_json
    page.get_by_role("tab", name="Home").click()
    page.locator("#access-lock").click()
    expect(page.locator("#access-title")).to_have_text("Explore the public examples")
    # A completed response for the discarded document context cannot restore it.
    pending[0].fulfill(json={"request_id": body["request_id"], "document_id": body["document_id"],
                             "revision_id": body["revision_id"], "geometry_revision_id": body["workspace"]["geometry_revision_id"],
                             "navigation_epoch": body["workspace"]["navigation_epoch"], "status": "ready",
                             "actions": [{"type": "question", "question": "Do not replay this"}]})
    expect(page.locator("#chat-log")).to_be_empty()
    expect(page.locator("#visual-workspace")).to_be_hidden()
    assert page.evaluate("state.document===null&&state.scene===null&&state.viewer===null")
    assert page.evaluate("chatUI.snapshot().selected_ids") == []
    assert not any(method == "POST" and path == "questions" for method, path, _ in requests)


def test_lock_is_disabled_until_unlock_metadata_refresh_finishes(static_server, scene_page):
    from playwright.sync_api import expect
    page = scene_page
    document, _, _, _, calls = public_fixture(page)
    open_example(page, static_server, document)
    pending = []
    page.route("**/conversation", lambda route: pending.append(route))
    unlock(page)
    expect(page.locator("#access-lock")).to_be_disabled()
    assert len(pending) == 1
    pending[0].fulfill(json={"conversation_id": document["building_id"], "messages": []})
    expect(page.locator("#access-lock")).to_be_enabled()
    page.get_by_role("tab", name="Home").click()
    page.locator("#access-lock").click()
    expect(page.locator("#access-title")).to_have_text("Explore the public examples")
    assert ("POST", "/lock") in calls
