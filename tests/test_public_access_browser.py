"""Public access with current Building overview and /api/chat; synthetic APIs only."""
from copy import deepcopy
import os

import pytest
from test_browser_3d import scene_page
from test_chat_ui_browser import response
from test_sourcefirst_browser import setup_routes, static_server

pytestmark=pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS")!="1",reason="opt-in browser checks")


def public_fixture(page):
    document,messages,requests=setup_routes(page)
    document.update(public_example=True,read_only_model=True,pinned_revision_id=document["revision_id"],example_title="Assembly hall example")
    access={"public_demo":True,"can_work":False,"shared_workspace":False};access_calls=[]
    def handle_access(route):
        path=route.request.url.split("/api/access",1)[1];access_calls.append((route.request.method,path))
        if path=="/unlock":
            if route.request.post_data_json["code"]!="fixture-access-code":return route.fulfill(status=401,json={"detail":"Access code not accepted."})
            access.update(can_work=True,shared_workspace=True)
        elif path=="/lock":access.update(can_work=False,shared_workspace=False)
        route.fulfill(json=access)
    page.route("**/api/access**",handle_access)
    def chat(route):
        body=route.request.post_data_json;requests.append(("POST","chat",body))
        if not access["can_work"]:return route.fulfill(status=401,json={"detail":"Enter the access code to use paid or private features."})
        route.fulfill(json={**response(body,[]),"tool":"conversation","message":"Explicit synthetic public-workspace reply."})
    page.route("**/api/chat",chat)
    examples=[{**document,"building_id":f"{index:064x}","document_id":f"{index:064x}","example_title":f"Cached example {index}"} for index in range(8)]+[document]
    page.route("**/api/buildings",lambda route:route.fulfill(json={"buildings":examples}))
    return document,messages,requests,access,access_calls,examples


def open_example(page,url,document):
    from playwright.sync_api import expect
    page.goto(url);expect(page.locator("#access-panel")).to_be_visible()
    page.get_by_role("button",name=document["example_title"],exact=True).click()
    page.locator("#home-library-list .home-file").first.click();expect(page.locator("#page-image")).to_be_visible()


def unlock(page):
    from playwright.sync_api import expect
    page.locator("#home-tab").click();page.locator("#access-code").fill("fixture-access-code");page.locator("#access-unlock").click()
    expect(page.locator("#access-title")).to_have_text("Workspace unlocked");expect(page.locator("#access-code")).to_have_value("")
    expect(page.locator("#access-lock")).to_be_enabled()


def open_chat(page,document):
    page.locator("#home-tab").click();page.get_by_role("button",name=document["example_title"],exact=True).click()
    page.locator("#new-project-chat").click();page.wait_for_function("!state.sessionOpening&&state.activeSessionId!==null&&chatUI.chatAvailable()")


def test_anonymous_examples_and_unlock_do_not_replay_paid_actions(static_server,scene_page):
    from playwright.sync_api import expect
    page=scene_page;document,_,requests,_,_,_=public_fixture(page);page.goto(static_server)
    expect(page.locator("#home-library-list tr")).to_have_count(9)
    open_example(page,static_server,document)
    expect(page.locator("#question")).not_to_be_visible();expect(page.locator("#file-input")).to_be_disabled()
    assert not any("/chats" in path or path.endswith("/conversation") for _,path,_ in requests)
    page.locator("#question-form").evaluate("form=>form.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}))")
    expect(page.locator("#access-message")).to_contain_text("explicitly submit")
    page.locator("#access-code").fill("incorrect-fixture-code");page.locator("#access-unlock").click()
    expect(page.locator("#access-message")).to_have_text("Access code not accepted.");expect(page.locator("#access-code")).to_have_value("")
    unlock(page);assert not any(path=="chat" for _,path,_ in requests)
    open_chat(page,document);expect(page.locator("#question")).to_be_enabled()
    expect(page.locator("#attach-drawings,#workspace-attach-sources")).to_have_count(0)
    page.locator("#back-project-overview").click();expect(page.locator("#home-upload")).to_be_disabled()
    page.locator("#project-chat-list .session-name").first.click();expect(page.locator("#question")).to_be_visible()
    page.locator("#question").fill("Hello after explicit unlock");page.locator("#ask-button").click()
    expect(page.locator("#chat-log")).to_contain_text("Explicit synthetic public-workspace reply")
    assert len([1 for _,path,_ in requests if path=="chat"])==1
    assert "fixture-access-code" not in page.evaluate("JSON.stringify([localStorage,sessionStorage])")


def test_expired_access_requires_explicit_retry_and_lock_clears_workspace(static_server,scene_page):
    from playwright.sync_api import expect
    page=scene_page;document,_,_,access,calls,_=public_fixture(page);page.goto(static_server);unlock(page);open_chat(page,document)
    denied=[]
    def deny(route):denied.append(route.request.post_data_json);route.fulfill(status=401,json={"detail":"Enter the access code to use paid or private features."})
    page.route("**/api/chat",deny);page.locator("#question").fill("Expired question");page.locator("#ask-button").click()
    expect(page.locator("#chat-log")).to_contain_text("Enter the access code")
    access.update(can_work=False,shared_workspace=False);page.locator("#home-tab").click();page.locator("#access-refresh").click()
    expect(page.locator("#access-form")).to_be_visible();unlock(page);assert len(denied)==1
    open_chat(page,document);page.locator("#question").fill("Explicit retry");page.locator("#ask-button").click()
    expect(page.locator("#chat-log")).to_contain_text("Enter the access code");assert len(denied)==2
    page.locator("#home-tab").click();page.locator("#access-lock").click()
    expect(page.locator("#access-title")).to_have_text("Explore the public examples")
    assert page.evaluate("state.document===null&&!state.activeSessionId")
    expect(page.locator("#question")).not_to_be_visible();expect(page.locator("#file-input")).to_be_disabled();assert ("POST","/lock") in calls


def test_lock_discards_private_workspace_and_late_chat_response(static_server,scene_page):
    from playwright.sync_api import expect
    page=scene_page;document,_,requests,access,_,examples=public_fixture(page);private=deepcopy(document)
    private.update(document_id="e"*64,building_id="e"*64,filename="Private uploaded source.png",example_title="Private Building",public_example=False,read_only_model=False,pinned_revision_id=None)
    page.route("**/api/buildings",lambda route:route.fulfill(json={"buildings":[*examples,private] if access["can_work"] else examples}))
    page.route(f'**/api/buildings/{private["document_id"]}',lambda route:route.fulfill(json=private))
    page.goto(static_server);unlock(page);open_chat(page,private);expect(page.locator("#question")).to_be_visible()
    pending=[];page.route("**/api/chat",lambda route:pending.append(route));page.locator("#question").fill("Private in-flight question");page.locator("#ask-button").click()
    expect(page.locator("#chat-log")).to_contain_text("Private in-flight question");assert len(pending)==1;body=pending[0].request.post_data_json
    page.locator("#home-tab").click();page.locator("#access-lock").click();expect(page.locator("#access-title")).to_have_text("Explore the public examples")
    pending[0].fulfill(json={**response(body,[]),"tool":"conversation","message":"Late private response must not reappear."})
    expect(page.locator("#chat-log")).to_be_empty();expect(page.locator("#visual-workspace")).not_to_be_visible()
    assert page.evaluate("state.document===null&&state.scene===null&&state.viewer===null&&!state.activeSessionId")
    assert not any(path=="chat" for _,path,_ in requests)


def test_lock_disabled_until_unlock_refresh_of_building_catalog_finishes(static_server,scene_page):
    from playwright.sync_api import expect
    page=scene_page;_,_,_,_,calls,examples=public_fixture(page);page.goto(static_server);expect(page.locator("#access-form")).to_be_visible()
    held=[];page.route("**/api/buildings",lambda route:held.append(route))
    page.locator("#access-code").fill("fixture-access-code");page.locator("#access-unlock").click()
    expect(page.locator("#access-lock")).to_be_disabled();assert held
    held.pop().fulfill(json={"buildings":examples});expect(page.locator("#access-lock")).to_be_enabled()
    page.locator("#access-lock").click();expect(page.locator("#access-title")).to_have_text("Explore the public examples")
    assert ("POST","/lock") in calls
