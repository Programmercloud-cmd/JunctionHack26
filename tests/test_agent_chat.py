"""Tool coordination uses original messages and inspected sources, never preflight calls."""
from copy import deepcopy

import pytest

from app.agent_chat import agent_chat, AgentChatRequest
from app.bundles import BuildingStore
from app.documents import DocumentError
from app.providers.gemini import ProviderError
from app.review_schema import AnswerReview
from app.schemas import DraftAnswer, CropRequest, Usage
from test_backend import png, evidence
from test_bundles_revisions import build
from test_ifc_generate import description


class Runner:
    def __init__(self):
        self.rendered = []

    def for_building(self, identity):
        return []

    def render(self, *args, **kwargs):
        self.rendered.append((args, kwargs))
        return {"id": "fixture-render", "kind": "render", "status": "queued"}


class AgentFixture:
    basic_model = "fixture-basic"
    advanced_model = "fixture-advanced"

    def __init__(self, tool="conversation", *, ui=False, draft=None, route=None, reviews=("supported",), revised=None):
        self.tool, self.ui = tool, ui
        self.route = route or {}
        self.draft = draft or DraftAnswer(status="answered", answer="The source depicts a room.", evidence=[evidence()])
        self.revised = revised or self.draft
        self.reviews = iter(reviews)
        self.usage = Usage()
        self.calls = []
        self.closed = False
        self.seen = []

    def route_agent(self, message, context):
        self.calls.append(("route", message))
        self.router_context = deepcopy(context)
        return {"tool": self.tool, **self.route}

    def converse_agent(self, message, context):
        self.calls.append(("conversation", message))
        self.conversation_context = deepcopy(context)
        return {"message": "Hello from the conversational worker.", "ui_request": "Use dark theme" if self.ui else None}

    def interact_agent(self, message, catalog, **kwargs):
        self.calls.append(("ui", message))
        self.ui_context = (deepcopy(catalog), kwargs)
        return {"actions": [{"type": "set_theme", "theme": "dark"}]}

    def answer_agent(self, document, question):
        self.calls.append(("answer", question))
        self.seen.append((document.snapshot(), self.model))
        return {"draft": self.draft.model_copy(deep=True), "ui_request": "Use dark theme" if self.ui else None}

    def review_answer(self, document, question, draft, gate, crop=None, **kwargs):
        assert gate is None
        self.calls.append(("review", question))
        return AnswerReview(decision=next(self.reviews))

    def revise_answer(self, document, question, draft, gate, review, crop=None, **kwargs):
        assert gate is None
        self.calls.append(("repair", question))
        return self.revised.model_copy(deep=True)

    def choose_crop(self, *args):
        return CropRequest(page=1, bbox=[0, 0, 1, 1], reason="Fixture no new detail")

    def gate(self, *args):
        raise AssertionError("No Decisions sufficiency preflight in product chat")

    def resolve_intent(self, *args):
        raise AssertionError("No rewritten factual question in product chat")

    def close(self):
        self.closed = True


@pytest.fixture
def workspace(tmp_path):
    store = BuildingStore(tmp_path)
    document = store.add(png(), "original.png")
    yield store, document, Runner()
    store.close()


def request(document=None, message="Please answer this exact original message", **kwargs):
    return AgentChatRequest(message=message, request_id="fixture-request", document_id=document.id if document else None,
                            revision_id=document.revision_id if document else None, **kwargs)


def test_document_free_conversation_and_shared_ui(workspace):
    store, _, runner = workspace
    provider = AgentFixture(ui=True)
    result = agent_chat(store, runner, lambda: provider, request(message="Hello and use dark theme",
        history=[{"role": "user", "content": "Earlier greeting"}]))
    assert result["tool"] == "conversation" and result["actions"] == [{"type": "set_theme", "theme": "dark"}]
    assert result["answer"] is None and provider.closed
    assert provider.calls == [(name, "Hello and use dark theme") for name in ("route", "conversation", "ui")]
    assert provider.conversation_context["conversation"]["messages"][0]["content"] == "Earlier greeting"


def test_ui_can_interrupt_only_an_existing_validated_building_job(workspace):
    store, document, runner = workspace
    runner.for_building = lambda identity: [{"id": "active-render", "kind": "render", "status": "running"}]
    provider = AgentFixture("ui")
    provider.interact_agent = lambda *args, **kwargs: {"actions": [{"type": "stop_job"}]}
    result = agent_chat(store, runner, lambda: provider, request(document, "Stop rendering"))
    assert result["actions"] == [{"type": "stop_job", "job_id": "active-render"}]
    assert not runner.rendered
    another = AgentFixture("ui")
    another.interact_agent = lambda *args, **kwargs: {"actions": [{"type": "stop_job", "job_id": "another-building-job"}]}
    result = agent_chat(store, runner, lambda: another, request(document, "Stop that other job"))
    assert result["status"] == "clarification" and not result["actions"]


@pytest.mark.parametrize("tool, model", [("technical_basic", "fixture-basic"), ("technical_advanced", "fixture-advanced")])
def test_technical_tools_inspect_originals_with_exact_message_and_can_invoke_same_ui(workspace, tool, model):
    store, document, runner = workspace
    provider = AgentFixture(tool, ui=True)
    original = "Count the depicted rooms, then use dark theme."
    result = agent_chat(store, runner, lambda: provider, request(document, original))
    assert result["answer"]["status"] == "answered" and result["answer"]["gate"] is None
    assert result["actions"] == [{"type": "set_theme", "theme": "dark"}]
    assert provider.seen[0][1] == model
    assert provider.seen[0][0].pages[0].path.read_bytes() == document.pages[0].path.read_bytes()
    assert provider.calls == [(name, original) for name in ("route", "answer", "review", "ui")]
    assert store.conversation(document.id)[0]["question"] == original
    assert provider.closed


def test_ui_route_cannot_implicitly_render(workspace):
    store, document, runner = workspace
    provider = AgentFixture("ui")
    provider.interact_agent = lambda *args, **kwargs: {"actions": [{"type": "show_model"}]}
    result = agent_chat(store, runner, lambda: provider, request(document, "Show model"))
    assert result["status"] == "clarification" and not result["actions"] and not runner.rendered


@pytest.mark.parametrize("action", [{"type": "reconstruct", "mode": "reconstruct"}, {"type": "retry_extraction"}, {"type": "question", "question": "Rewrite"}])
def test_ui_worker_cannot_escalate_to_mutation_or_another_answer(workspace, action):
    store, document, runner = workspace
    provider = AgentFixture("ui")
    provider.interact_agent = lambda *args, **kwargs: {"actions": [action]}
    with pytest.raises(ProviderError, match="navigation capability"):
        agent_chat(store, runner, lambda: provider, request(document))
    assert not runner.rendered and not store.conversation(document.id) and provider.closed


def test_render_calls_authorization_before_scheduling_or_history(workspace):
    store, document, runner = workspace
    provider = AgentFixture("render")
    def denied(tool):
        assert tool == "render"
        raise DocumentError("Read-only model", 409)
    with pytest.raises(DocumentError, match="Read-only"):
        agent_chat(store, runner, lambda: provider, request(document), authorize_tool=denied)
    assert not runner.rendered and not store.conversation(document.id) and provider.closed
    allowed = AgentFixture("render")
    result = agent_chat(store, runner, lambda: allowed, request(document, "Generate exactly this model"))
    assert result["job"]["kind"] == "render"
    assert runner.rendered[0][0] == (document.id, document.revision_id, "Generate exactly this model")


def test_technical_without_sources_clarifies_without_answer_call(workspace):
    store, _, runner = workspace
    provider = AgentFixture("technical_advanced")
    result = agent_chat(store, runner, lambda: provider, request())
    assert result["status"] == "clarification"
    assert [name for name, _ in provider.calls] == ["route"] and provider.closed


def test_confident_unsupported_claim_is_withheld_despite_no_preflight(workspace):
    store, document, runner = workspace
    provider = AgentFixture("technical_basic", draft=DraftAnswer(status="answered", answer="Actual height is 3 m.", evidence=[evidence()]), reviews=("unsupported",))
    result = agent_chat(store, runner, lambda: provider, request(document, "What is actual height?"))
    assert result["answer"]["status"] == "unclear"
    assert "3 m" not in result["answer"]["answer"] and not result["answer"]["highlight_ids"]
    assert [name for name, _ in provider.calls] == ["route", "answer", "review", "repair"]


def test_document_scope_keeps_current_sources_when_old_geometry_and_mark_are_attached(workspace):
    store, document, runner = workspace
    old = build(store, document, description())
    current = store.add_many([(png() + b"second", "section.png")], building_id=old.id)
    provider = AgentFixture("technical_basic")
    object_id = old.scene.elements[0].id
    result = agent_chat(store, runner, lambda: provider, request(current, "Count every supplied drawing room", workspace={"geometry_revision_id": old.revision_id}),
                        annotations=[{"id": "server-mark", "object_id": object_id, "space": "model", "revision_id": old.revision_id}])
    assert result["answer"]["answered_revision_id"] == current.revision_id
    assert len(provider.seen[0][0].pages) == 2


def test_pinned_display_does_not_follow_current_revision(workspace):
    store, document, runner = workspace
    current = store.commit(store.prepare(document), document.revision_id, status="changed")
    provider = AgentFixture("technical_basic")
    result = agent_chat(store, runner, lambda: provider, request(document), document=document, pin_display=True)
    assert result["answer"]["display_revision_id"] == document.revision_id != current.revision_id


def test_operational_exceptions_are_credential_safe_and_close_client(workspace):
    store, document, runner = workspace
    provider = AgentFixture()
    def broken(*args):
        raise RuntimeError("private provider text and api-key fixture")
    provider.route_agent = broken
    with pytest.raises(ProviderError, match="Chat failed operationally") as error:
        agent_chat(store, runner, lambda: provider, request(document))
    assert "api-key" not in error.value.message and provider.closed


def test_unknown_and_stale_workspace_references_fail_before_provider(workspace):
    store, document, runner = workspace
    called = []
    def factory():
        called.append(True)
        return AgentFixture()
    with pytest.raises(DocumentError):
        agent_chat(store, runner, factory, request(document, workspace={"focused_id": "unknown"}))
    with pytest.raises(DocumentError):
        agent_chat(store, runner, factory, request(document, workspace={"geometry_revision_id": "0" * 32}))
    assert not called
