"""Focused agent UI/gesture contracts with explicit intercepted API fixtures."""
import json
import os

import pytest

from test_browser_3d import scene_page
from test_chat_ui_browser import chat_fixture, response
from test_sourcefirst_browser import static_server, setup_routes

pytestmark = pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS") != "1", reason="opt-in browser checks")


def test_project_conversation_posts_only_agent_chat(static_server, scene_page):
    from playwright.sync_api import expect
    page = scene_page
    doc, messages, calls = setup_routes(page)
    posted = []
    def chat(route):
        body = json.loads(route.request.post_data)
        posted.append(body)
        route.fulfill(json={**response(body, []), "tool": "conversation", "message": "Hello from the basic conversation worker."})
    page.route("**/api/chat", chat)
    page.goto(static_server)
    expect(page.locator("#question")).not_to_be_visible()
    page.locator("#home-library-list .home-file").first.click()
    page.locator("#new-project-chat").click()
    page.locator("#question").fill("Hello exactly as typed")
    page.locator("#ask-button").click()
    expect(page.locator("#chat-log")).to_contain_text("Hello from the basic conversation worker.")
    assert posted[0]["message"] == "Hello exactly as typed"
    assert posted[0]["document_id"]==doc["document_id"]
    assert posted[0]["project_id"] and posted[0]["session_id"]
    assert not any(path in {"chat/actions", "questions", "ask"} for _, path, _ in calls)


def test_source_measurement_and_point_attach_to_original_message(static_server, scene_page):
    from playwright.sync_api import expect
    page = scene_page
    document, scene, calls, pending = chat_fixture(page, static_server, model=False)
    marks = []
    submitted = []
    def annotations(route):
        if route.request.method == "GET":
            return route.fulfill(json={"annotations": marks})
        body = json.loads(route.request.post_data)
        row = {**body, "id": f"mark-{len(marks)}", "document_id": document["document_id"], "provenance": "user_provided"}
        marks.append(row)
        route.fulfill(json=row)
    page.route("**/api/buildings/*/annotations", annotations)
    def chat(route):
        body = json.loads(route.request.post_data)
        submitted.append(body)
        route.fulfill(json={**response(body, []), "tool": "conversation", "message": "Attached marks received."})
    page.route("**/api/chat", chat)
    page.locator("#annotation-toggle").click()
    page.locator("#annotation-measure").click()
    page.locator("#annotation-value").fill("6")
    page.locator("#annotation-unit").select_option("m")
    page.locator("#annotation-floor").select_option("f1")
    bounds = page.locator("#annotation-overlay").bounding_box()
    page.mouse.move(bounds["x"] + bounds["width"] * .6, bounds["y"] + bounds["height"] * .7)
    page.mouse.down()
    page.mouse.move(bounds["x"] + bounds["width"] * .9, bounds["y"] + bounds["height"] * .7, steps=8)
    page.mouse.up()
    expect(page.locator("#annotation-attachments button")).to_have_count(1)
    assert marks[0]["value"] == 6 and marks[0]["unit"] == "m"
    assert marks[0]["floor_id"] == "f1" and marks[0]["revision_id"] == document["revision_id"]
    assert abs(marks[0]["points"][0][0] - .6) < .01
    page.locator("#annotation-point").click()
    page.locator("#annotation-overlay").click(position={"x": bounds["width"] * .4, "y": bounds["height"] * .5})
    expect(page.locator("#annotation-attachments button")).to_have_count(2)
    page.locator("#annotation-draw").click()
    page.mouse.move(bounds["x"] + bounds["width"] * .65, bounds["y"] + bounds["height"] * .65)
    page.mouse.down()
    page.mouse.move(bounds["x"] + bounds["width"] * .8, bounds["y"] + bounds["height"] * .8, steps=5)
    page.mouse.up()
    expect(page.locator("#annotation-attachments button")).to_have_count(3)
    assert marks[2]["kind"] == "stroke" and len(marks[2]["points"]) >= 2
    page.locator("#question").fill("What is this marked thing?")
    page.locator("#ask-button").click()
    expect(page.locator("#chat-log")).to_contain_text("Attached marks received.")
    assert submitted[0]["message"] == "What is this marked thing?"
    assert submitted[0]["annotation_ids"] == ["mark-0", "mark-1", "mark-2"]
    old_points = marks[0]["points"]
    page.set_viewport_size({"width": 1200, "height": 900})
    assert page.locator("#annotation-overlay [data-annotation-id='mark-0'] polyline").get_attribute("points") == " ".join(",".join(str(n) for n in p) for p in old_points)


def test_model_point_uses_local_anchor_and_restores_orbit(static_server, scene_page):
    from playwright.sync_api import expect
    page = scene_page
    document, scene, calls, pending = chat_fixture(page, static_server)
    marks = []
    def annotations(route):
        body = json.loads(route.request.post_data)
        row = {**body, "id": "model-mark", "document_id": document["document_id"], "provenance": "user_provided"}
        marks.append(row)
        route.fulfill(json=row)
    page.route("**/api/buildings/*/annotations", annotations)
    page.locator("#workspace-model").click()
    page.locator("#annotation-toggle").click()
    page.locator("#annotation-point").click()
    assert page.evaluate("!state.viewer.controls.enabled")
    position = page.evaluate("""() => {
      const viewer=state.viewer, mesh=viewer.meshes.get('wall-1');mesh.geometry.computeBoundingSphere();
      const point=mesh.geometry.boundingSphere.center.clone();mesh.localToWorld(point);point.project(viewer.camera);
      const rect=viewer.renderer.domElement.getBoundingClientRect();return {x:rect.x+(point.x+1)*rect.width/2,y:rect.y+(1-point.y)*rect.height/2};
    }""")
    page.mouse.click(position["x"], position["y"])
    expect(page.locator("#annotation-attachments button")).to_have_count(1)
    assert marks[0]["space"] == "model" and len(marks[0]["points"][0]) == 3
    assert marks[0]["object_id"] in {"wall-1", "window-1", "window-2"}
    assert marks[0]["point_object_ids"] == [marks[0]["object_id"]]
    assert page.evaluate("state.viewer.controls.enabled")
    original = marks[0]["points"]
    page.evaluate("state.viewer.setExploded(true); state.viewer.fit()")
    expect(page.locator("#model-annotation-overlay [data-annotation-id='model-mark']")).to_be_visible()
    assert marks[0]["points"] == original


def test_late_answer_does_not_replace_latest_active_highlights(static_server, scene_page):
    from playwright.sync_api import expect
    page = scene_page
    document, scene, calls, pending = chat_fixture(page, static_server)
    delayed = []
    def result(body, title, identity):
        answer = {"status": "answered", "answer": title, "evidence": [], "model_evidence": [],
                  "highlight_ids": [identity], "answered_revision_id": document["revision_id"],
                  "display_revision_id": document["revision_id"], "gate": None, "usage": {}, "inspection_passes": 1}
        return {**response(body, []), "tool": "technical_basic", "message": title, "answer": answer}
    def chat(route):
        body = json.loads(route.request.post_data)
        if body["message"] == "First question":
            delayed.append((route, body))
        else:
            route.fulfill(json=result(body, "Newer answer", "window-2"))
    page.route("**/api/chat", chat)
    page.locator("#question").fill("First question")
    page.locator("#ask-button").click()
    page.wait_for_timeout(50)
    assert delayed
    page.locator("#question").fill("Second question")
    page.locator("#ask-button").click()
    expect(page.locator("#chat-log")).to_contain_text("Newer answer")
    delayed[0][0].fulfill(json=result(delayed[0][1], "Older answer", "window-1"))
    expect(page.locator("#chat-log")).to_contain_text("Older answer")
    assert page.evaluate("state.result.answer") == "Newer answer"
    assert page.evaluate("[...state.viewer.highlightIds]") == ["window-2"]


def test_saved_conversation_hydrates_once_without_factual_answer_label(static_server, scene_page):
    from playwright.sync_api import expect
    page = scene_page
    document, messages, calls = setup_routes(page)
    def chat(route):
        body = json.loads(route.request.post_data)
        messages.extend([{"id": "user-turn", "role": "user", "question": body["message"], "request_id": body["request_id"]},
                         {"id": "assistant-turn", "role": "assistant", "request_id": body["request_id"],
                          "answer": {"status": "conversation", "answer": "Plain conversation reply", "tool": "conversation"}}])
        route.fulfill(json={**response(body, []), "tool": "conversation", "message": "Plain conversation reply"})
    page.route("**/api/chat", chat)
    page.goto(static_server)
    page.locator("#home-library-list button").filter(has_text=document["filename"]).click()
    page.locator("#home-library-list button").filter(has_text=document["filename"]).click()
    page.locator("#question").fill("Hello")
    page.locator("#ask-button").click()
    expect(page.locator("#chat-log")).to_contain_text("Plain conversation reply")
    page.evaluate("refreshConversation()")
    expect(page.locator("#chat-log .chat-turn").filter(has_text="Plain conversation reply")).to_have_count(1)
    expect(page.locator("#chat-log .chat-answer")).to_have_count(0)
    page.reload()
    page.locator("#home-library-list button").filter(has_text=document["filename"]).click()
    page.locator("#home-library-list button").filter(has_text=document["filename"]).click()
    expect(page.locator("#chat-log .chat-turn").filter(has_text="Plain conversation reply")).to_have_count(1)
    expect(page.locator("#chat-log .chat-answer")).to_have_count(0)


def test_technical_clarification_has_one_actionable_suggestion(static_server, scene_page):
    from playwright.sync_api import expect
    page = scene_page
    document, scene, calls, pending = chat_fixture(page, static_server, model=False)
    messages = []
    def chat(route):
        body = json.loads(route.request.post_data)
        messages.append(body["message"])
        if body["message"] == "Which measurement?":
            clarification = {"message": "Which floor should I inspect?", "suggestions": ["Ground floor"], "free_text_allowed": True}
            answer = {"status": "clarification", "answer": clarification["message"], "clarification": clarification,
                      "answered_revision_id": document["revision_id"], "display_revision_id": document["revision_id"],
                      "gate": None, "evidence": [], "model_evidence": [], "highlight_ids": [], "usage": {}}
            route.fulfill(json={**response(body, []), "status": "clarification", "tool": "technical_basic",
                                "message": clarification["message"], "answer": answer, "clarification": clarification})
        else:
            route.fulfill(json={**response(body, []), "tool": "conversation", "message": "Following your exact clarification."})
    page.route("**/api/chat", chat)
    page.locator("#question").fill("Which measurement?")
    page.locator("#ask-button").click()
    expect(page.locator("#chat-log").get_by_text("Which floor should I inspect?", exact=True)).to_have_count(1)
    expect(page.locator("#chat-log").get_by_role("button", name="Ground floor", exact=True)).to_have_count(1)
    page.locator("#chat-log").get_by_role("button", name="Ground floor", exact=True).click()
    expect(page.locator("#chat-log")).to_contain_text("Following your exact clarification.")
    assert messages == ["Which measurement?", "Ground floor"]


def test_crossfloor_measurement_tracks_each_objects_local_frame(static_server, scene_page):
    from copy import deepcopy
    from playwright.sync_api import expect
    page = scene_page
    document, scene, calls, pending = chat_fixture(page, static_server)
    model = deepcopy(scene)
    model["revision_id"] = "e" * 32
    model["revision_number"] = 2
    upper = deepcopy(model["floors"][0])
    upper.update(id="f2", label="Upper fixture floor", order=1, base_elevation=4)
    model["floors"].append(upper)
    first = deepcopy(model["elements"][0])
    first.update(id="ground-target", storey_id="f1", geometry={"type": "box", "size": [2, 2, .3], "center": [-3, 0, .5]})
    second = deepcopy(first)
    second.update(id="upper-target", storey_id="f2", geometry={"type": "box", "size": [2, 2, .3], "center": [3, 0, 4.5]})
    model["elements"] = [first, second]
    page.evaluate("""async model => {
      state.document={...state.document,revision_id:model.revision_id,geometry_revision_id:model.revision_id,revision_number:2};
      await loadScene(model);await chatUI.execute({type:'switch_model'});state.viewer.fit();
    }""", model)
    marks = []
    def annotations(route):
        body = json.loads(route.request.post_data)
        row = {**body, "id": "crossfloor", "document_id": document["document_id"], "provenance": "user_provided"}
        marks.append(row)
        route.fulfill(json=row)
    page.route("**/api/buildings/*/annotations", annotations)
    page.locator("#annotation-toggle").click()
    page.locator("#annotation-measure").click()
    page.locator("#annotation-value").fill("4")
    positions = page.evaluate("""() => ['ground-target','upper-target'].map(id => {
      const viewer=state.viewer,mesh=viewer.meshes.get(id);mesh.geometry.computeBoundingSphere();
      const point=mesh.geometry.boundingSphere.center.clone();mesh.localToWorld(point);point.project(viewer.camera);
      const rect=viewer.renderer.domElement.getBoundingClientRect();return {x:rect.x+(point.x+1)*rect.width/2,y:rect.y+(1-point.y)*rect.height/2};
    })""")
    page.mouse.move(positions[0]["x"], positions[0]["y"])
    page.mouse.down()
    page.mouse.move(positions[1]["x"], positions[1]["y"], steps=1)
    page.mouse.up()
    expect(page.locator("#annotation-attachments button")).to_have_count(1)
    assert marks[0]["point_object_ids"] == ["ground-target", "upper-target"]
    page.evaluate("state.viewer.setExploded(true);state.viewer.fit()")
    page.wait_for_function("""row => {
      const line=document.querySelector("#model-annotation-overlay [data-annotation-id='crossfloor'] polyline");
      const actual=line?.getAttribute('points').split(' ').map(p=>p.split(',').map(Number));
      const expected=row.points.map((point,index)=>state.viewer.projectUserAnchor(row.point_object_ids[index],point));
      return actual&&actual.every((point,i)=>point.every((value,j)=>Math.abs(value-expected[i][j])<1e-6));
    }""",arg=marks[0])
    expected = page.evaluate("""row => row.points.map((point,index)=>state.viewer.projectUserAnchor(row.point_object_ids[index],point))""", marks[0])
    actual = page.locator("#model-annotation-overlay [data-annotation-id='crossfloor'] polyline").get_attribute("points")
    actual = [[float(value) for value in pair.split(",")] for pair in actual.split(" ")]
    for point, correct in zip(actual, expected):
        assert point == pytest.approx(correct)
    assert page.evaluate("state.viewer.controls.enabled")
