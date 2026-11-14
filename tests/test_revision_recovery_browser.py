"""Recovery-history UI checks with synthetic API records, never live inference."""
import os

import pytest
from test_browser import source_bytes
from test_browser_3d import scene_page
from test_sourcefirst_browser import setup_routes, static_server

pytestmark = pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS") != "1", reason="opt-in browser checks")


def open_fixture_job(page, static_server, document, job):
    page.route(
        f'**/api/buildings/{document["building_id"]}',
        lambda route: route.fulfill(json={**document, "jobs": [job]}),
    )
    page.goto(static_server)
    page.locator("#file-input").set_input_files(
        {"name": "plan.png", "mimeType": "image/png", "buffer": source_bytes()}
    )
    row = page.locator(f'[data-entry="job:{job["id"]}"]')
    row.wait_for(state="attached")
    for summary in row.locator("summary").all():summary.click()
    return row


def test_recovery_decisions_pin_original_source_and_render_safe_history(static_server, scene_page):
    from playwright.sync_api import expect

    page = scene_page
    document, _, requests = setup_routes(page)
    base_revision = "e" * 32
    event_revision = "f" * 32
    evidence = {"page": 1, "bbox": [.1, .2, .6, .7]}
    unsafe = '<img src=x onerror="window.recoveryInjected=true">'
    decisions = [
        {"request_id": f"request-{i}", "target_id": f"wall-{i}", "issue_id": "issue-1",
         "decision": status, "evidence": evidence, "reason": f"Original-source fixture: {status}. {unsafe}"}
        for i, status in enumerate(["approved", "denied", "unclear"])
    ]
    job = {
        "id": "recovery-job", "building_id": document["building_id"], "kind": "reconstruction",
        "base_revision_id": base_revision, "status": "needs_attention", "phase": "needs_attention",
        "message": "Previous usable revision retained; proposed correction not applied.", "issues": [],
        "recovery_events": [
            {"kind": "rejection", "attempt": 1, "message": "Atomic patch rejection.",
             "feedback": {"code": "target_outside_scope", "target_id": "wall-0",
                          "explanation": "This target needs explicit reviewed authority.",
                          "expected_contract": f"Request the exact target with source evidence. {unsafe}",
                          "private_trace": "DO_NOT_RENDER_INTERNALS"}},
            {"kind": "authorization", "attempt": 2, "base_revision_id": event_revision,
             "message": "Exact requested targets inspected against original evidence.",
             "requests": [{"request_id": d["request_id"], "target_id": d["target_id"]} for d in decisions]
                         + [{"request_id": "pending", "target_id": "wall-pending"}],
             "decisions": decisions},
            {"kind": "stopped", "attempt": 2, "message": "Same material proposal repeated; previous revision retained."},
        ],
    }
    row = open_fixture_job(page, static_server, document, job)
    expect(row.locator("details")).to_have_count(3)
    expect(row).to_contain_text("Required correction: Request the exact target")
    expect(row).to_contain_text("target_outside_scope")
    expect(row).to_contain_text("Approved correction target · target wall-0")
    expect(row).to_contain_text("Denied · target wall-1")
    expect(row).to_contain_text("Unclear · not authorized · target wall-2")
    expect(row).to_contain_text("wall-pending · no authorization decision recorded")
    expect(row).to_contain_text("does not mean a change was applied or accepted")
    expect(row).to_contain_text("Recovery · stopped")
    expect(row).to_contain_text(unsafe)
    expect(row).not_to_contain_text("DO_NOT_RENDER_INTERNALS")
    assert row.locator("img").count() == 0
    assert not page.evaluate("Boolean(window.recoveryInjected)")
    assert row.get_by_role("button").count() == 3  # source links only; no approval controls

    for source_link in row.locator(".chat-citation").all():
        source_link.click()
        expect(page.locator("#page-image")).to_have_attribute(
            "src", f'{static_server}/api/buildings/{document["building_id"]}/revisions/{event_revision}/pages/1'
        )
        expect(page.locator("#evidence-overlay")).to_be_visible()
        assert page.locator("#evidence-overlay").evaluate("el=>el.style.left") == "10%"
    expect(page.locator("#page-label")).to_contain_text("source revision")
    assert page.evaluate("state.document.revision_id") == document["revision_id"]
    assert not any(method == "POST" and path != "documents" for method, path, _ in requests)


@pytest.mark.parametrize("event_revision,has_link", [(None, True), ("../invalid", False)])
def test_recovery_legacy_revision_fallback_and_invalid_event_revision(static_server, scene_page, event_revision, has_link):
    from playwright.sync_api import expect

    page = scene_page
    document, _, _ = setup_routes(page)
    base_revision = "e" * 32
    event = {"kind": "authorization", "attempt": 1, "decisions": [
        {"request_id": "request-1", "target_id": "wall-1", "decision": "approved",
         "reason": "Synthetic original-source review.", "evidence": {"page": 1, "bbox": [.1, .2, .6, .7]}}
    ]}
    if event_revision is not None:
        event["base_revision_id"] = event_revision
    job = {"id": "legacy-recovery", "building_id": document["building_id"], "kind": "reconstruction",
           "base_revision_id": base_revision, "status": "needs_attention", "phase": "needs_attention",
           "message": "Previous revision retained.", "issues": [], "recovery_events": [event]}
    row = open_fixture_job(page, static_server, document, job)
    expect(row.locator(".chat-citation")).to_have_count(int(has_link))
    if has_link:
        row.locator(".chat-citation").click()
        expect(page.locator("#page-image")).to_have_attribute(
            "src", f'{static_server}/api/buildings/{document["building_id"]}/revisions/{base_revision}/pages/1'
        )


@pytest.mark.parametrize("status", ["needs_attention", "complete"])
def test_submitted_inputs_remain_attributed_without_claiming_application(static_server, scene_page, status):
    from playwright.sync_api import expect

    page = scene_page
    document, _, _ = setup_routes(page)
    job = {
        "id": "input-job", "building_id": document["building_id"], "kind": "refinement",
        "base_revision_id": "e" * 32, "status": status, "phase": status,
        "message": "Previous revision retained." if status == "needs_attention" else "Accepted revision published.",
        "issues": [], "submitted_values": [
            {"property": "display_height", "scope": {"floor_id": "assembly-floor"}, "value": 1.4,
             "unit": "relative", "reason": "Explicit user input; not source-observed."},
            {"property": "interpretation_correction", "scope": {"object_id": "feature-1"},
             "value": "<script>window.inputInjected=true</script>", "unit": None},
        ],
    }
    row = open_fixture_job(page, static_server, document, job)
    expect(row.locator("details")).to_have_count(1)
    expect(row).to_contain_text("User-provided values")
    expect(row).to_contain_text("assembly-floor")
    expect(row).to_contain_text("1.4 relative")
    expect(row).to_contain_text("not source-observed")
    expect(row).to_contain_text(job["message"])
    assert row.locator("script").count() == 0
    assert not page.evaluate("Boolean(window.inputInjected)")
