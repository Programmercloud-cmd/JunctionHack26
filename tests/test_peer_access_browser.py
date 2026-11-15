"""Peer-review access UI with explicit API fixtures; no live providers or codes."""
import os

import pytest

from test_browser_3d import scene_page
from test_chat_ui_browser import response
from test_sourcefirst_browser import setup_routes, static_server

pytestmark = pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS") != "1", reason="opt-in browser checks")


def peer_fixture(page, *, require_code=False):
    document, messages, requests = setup_routes(page)
    document.update(public_example=True, read_only_model=True, pinned_revision_id=document["revision_id"])
    access = {"public_demo": True, "access_code_required": require_code,
              "can_work": not require_code, "shared_workspace": not require_code}
    access_calls = []

    def status(route):
        access_calls.append(route.request.method)
        route.fulfill(json=access)

    page.route("**/api/access**", status)
    return document, messages, requests, access, access_calls


def test_open_peer_workspace_has_no_code_barrier_and_keeps_example_readonly(static_server, scene_page):
    from playwright.sync_api import expect
    page = scene_page
    document, _, _, access, access_calls = peer_fixture(page)
    submitted = []
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))

    def chat(route):
        body = route.request.post_data_json
        submitted.append(body)
        route.fulfill(json={**response(body, []), "tool": "conversation",
                            "message": "Explicit fixture reply in the peer-review workspace."})

    page.route("**/api/chat", chat)
    page.goto(static_server)
    expect(page.locator("#access-title")).to_have_text("Peer-review workspace")
    expect(page.locator("#access-description")).to_contain_text("without an access code")
    expect(page.locator("#access-shared")).to_contain_text("All visitors share this workspace")
    expect(page.locator("#access-form")).not_to_be_visible()
    expect(page.locator("#access-lock")).not_to_be_visible()
    expect(page.locator("#file-input")).to_be_enabled()
    expect(page.locator("#home-new-project")).to_be_enabled()
    page.locator("#home-library-list .home-file").first.click()
    expect(page.locator("#new-project-chat")).to_be_enabled()
    page.locator("#new-project-chat").click()
    expect(page.locator("#question")).to_be_enabled()
    expect(page.locator("#workspace-attach-sources")).to_be_disabled()
    expect(page.locator("#generate-scene")).to_be_disabled()
    expect(page.locator("#access-model-note")).not_to_contain_text("entering the code")
    page.locator("#question").fill("Hello from a peer reviewer")
    page.locator("#ask-button").click()
    expect(page.locator("#chat-log")).to_contain_text("Explicit fixture reply")
    assert submitted[0]["document_id"] == document["document_id"]
    assert submitted[0]["message"] == "Hello from a peer reviewer"
    assert access_calls and all(method == "GET" for method in access_calls)
    assert not errors


def test_access_refresh_reflects_operator_open_and_require_code_modes(static_server, scene_page):
    from playwright.sync_api import expect
    page = scene_page
    _, _, _, access, access_calls = peer_fixture(page, require_code=True)
    page.goto(static_server)
    expect(page.locator("#access-title")).to_have_text("Explore the public examples")
    expect(page.locator("#access-form")).to_be_visible()
    expect(page.locator("#file-input")).to_be_disabled()
    access.update(access_code_required=False, can_work=True, shared_workspace=True)
    page.locator("#access-refresh").click()
    expect(page.locator("#access-title")).to_have_text("Peer-review workspace")
    expect(page.locator("#access-form")).not_to_be_visible()
    expect(page.locator("#access-lock")).not_to_be_visible()
    expect(page.locator("#file-input")).to_be_enabled()
    access.update(access_code_required=True, can_work=False, shared_workspace=False)
    page.locator("#access-refresh").click()
    expect(page.locator("#access-title")).to_have_text("Explore the public examples")
    expect(page.locator("#access-form")).to_be_visible()
    expect(page.locator("#access-lock")).not_to_be_visible()
    expect(page.locator("#file-input")).to_be_disabled()
    assert access_calls and all(method == "GET" for method in access_calls)


def test_missing_access_code_required_keeps_legacy_locked_behavior(static_server, scene_page):
    from playwright.sync_api import expect
    page = scene_page
    _, _, _, access, _ = peer_fixture(page, require_code=True)
    del access["access_code_required"]
    page.goto(static_server)
    expect(page.locator("#access-title")).to_have_text("Explore the public examples")
    expect(page.locator("#access-form")).to_be_visible()
    expect(page.locator("#file-input")).to_be_disabled()
    access.update(can_work=True, shared_workspace=True)
    page.locator("#access-refresh").click()
    expect(page.locator("#access-title")).to_have_text("Workspace unlocked")
    expect(page.locator("#access-lock")).to_be_visible()


def test_timed_access_refreshes_shared_projects_then_clears_private_workspace(static_server, scene_page):
    from copy import deepcopy
    from playwright.sync_api import expect
    page = scene_page
    document, _, requests, _, _ = peer_fixture(page, require_code=True)
    private = deepcopy(document)
    private.update(document_id="e" * 64, building_id="e" * 64,
                   filename="Private peer fixture.png", public_example=False,
                   read_only_model=False, pinned_revision_id=None)
    access_calls = []
    stage = {"value": 0}
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    opens = "2000-01-01T00:00:02+00:00"
    closes = "2000-01-01T00:00:05+00:00"

    def status(route):
        access_calls.append(route.request.method)
        current = min(stage["value"], 2)
        stage["value"] += 1
        is_open = current == 1
        route.fulfill(json={"public_demo": True, "access_code_required": not is_open,
                            "can_work": is_open, "shared_workspace": is_open,
                            "access_window": {"opens_at": opens, "closes_at": closes,
                                              "checked_at": ["2000-01-01T00:00:00+00:00", opens, closes][current],
                                              "next_change_at": [opens, closes, None][current]}})

    page.route("**/api/access**", status)
    page.route("**/api/buildings", lambda route: route.fulfill(
        json={"buildings": [document, private] if stage["value"] == 2 else [document]}))
    page.route(f"**/api/buildings/{private['building_id']}",
               lambda route: route.fulfill(json={**private, "jobs": []}))
    page.goto(static_server)
    expect(page.locator("#access-title")).to_have_text("Explore the public examples")
    expect(page.locator("#home-library-list tr")).to_have_count(1)
    # Deliberately old server dates prove timing does not use the browser's wall clock.
    expect(page.locator("#access-title")).to_have_text("Peer-review workspace")
    expect(page.locator("#home-library-list tr")).to_have_count(2)
    page.locator("#home-library-list .home-file", has_text="Private peer fixture.png").click()
    page.locator("#home-library-list .home-file").first.click()
    expect(page.locator("#question")).to_be_visible()
    expect(page.locator("#attachment-summary")).to_contain_text("Private peer fixture.png")
    # Closing reloads the page, removing private files/chat state without replaying work.
    expect(page.locator("#access-title")).to_have_text("Explore the public examples")
    expect(page.locator("#home-library-list tr")).to_have_count(1)
    expect(page.locator("#question")).not_to_be_visible()
    assert page.evaluate("state.document===null && !state.activeSessionId")
    assert all(method == "GET" for method in access_calls)
    assert not any(method == "POST" and path in {"chat", "chat/actions", "questions", "ask"}
                   for method, path, _ in requests)
    assert not errors


def test_access_refresh_replaces_a_superseded_window_timer(static_server, scene_page):
    from playwright.sync_api import expect
    page = scene_page
    _, _, _, access, access_calls = peer_fixture(page, require_code=True)
    access["access_window"] = {"opens_at": "2000-01-01T00:00:01+00:00",
                               "closes_at": "2000-01-01T01:00:00+00:00",
                               "checked_at": "2000-01-01T00:00:00+00:00",
                               "next_change_at": "2000-01-01T00:00:01+00:00"}
    page.goto(static_server)
    expect(page.locator("#access-form")).to_be_visible()
    access.pop("access_window")
    page.locator("#access-refresh").click()
    page.wait_for_function("!document.getElementById('access-message').textContent")
    page.wait_for_timeout(1300)
    assert access_calls == ["GET", "GET"]
    expect(page.locator("#access-form")).to_be_visible()
