"""Production Gemini capability adapters through intercepted SDK HTTP; no live calls."""
import json

from app.agent_chat import AgentRoute, ConversationResponse
from app.providers.gemini import AGENT_EVIDENCE_INSTRUCTIONS
from app.review_schema import AnswerReview
from app.schemas import DraftAnswer
from test_gemini_schema import sdk_document, intercept


def parts(body):
    return body["contents"][0]["parts"]


def text_parts(body):
    return "\n".join(part.get("text", "") for part in parts(body))


def test_router_wire_selects_tools_without_sufficiency_or_rewritten_question(sdk_document):
    provider, document = sdk_document
    requests = intercept(provider, {"tool": "technical_basic", "reference": "document", "evidence_scope": "sources_only"})
    original = "What is the exact printed room label?"
    result = provider.route_agent(original, {"document_id": document.id, "current_message": original})
    assert isinstance(result, AgentRoute) and result.tool == "technical_basic"
    body = requests[0]
    schema = body["generationConfig"]["responseJsonSchema"]
    assert set(schema["properties"]) == {"tool", "reference", "evidence_scope"}
    assert not any("inlineData" in part for part in parts(body))
    assert json.dumps({"question": original}) in text_parts(body)
    assert provider.provider_calls[0]["model"] == provider.router_model


def test_conversation_and_ui_use_explicit_basic_capability_models(sdk_document):
    provider, document = sdk_document
    requests = intercept(provider, {"message": "Hello", "ui_request": "Use top camera"})
    result = provider.converse_agent("Hello and look down", {"history": []})
    assert isinstance(result, ConversationResponse) and result.ui_request == "Use top camera"
    assert provider.provider_calls[-1]["model"] == provider.basic_model
    assert not any("inlineData" in part for part in parts(requests[0]))
    requests = intercept(provider, {"status": "ready", "actions": [{"type": "set_camera", "preset": "top"}]})
    result = provider.interact_agent("Hello and look down", {"objects": [], "workspace": {}}, ui_request="Use top camera")
    assert result.canonical().actions[0].type == "set_camera"
    assert provider.provider_calls[-1]["model"] == provider.ui_model
    assert "Use top camera" in text_parts(requests[0])


def test_technical_wire_has_original_image_and_outer_worker_schema(sdk_document):
    provider, document = sdk_document
    draft = {"status": "answered", "answer": "One room is depicted.", "evidence": [{
        "page": 1, "bbox": [0, 0, 1, 1], "label": "Original", "observation": "Synthetic supplied original"}]}
    requests = intercept(provider, {"draft": draft, "clarification": None, "ui_request": "Show original"})
    provider.model = provider.basic_model
    response = provider.answer_agent(document, "Count rooms and show original")
    assert response.draft.answer == "One room is depicted."
    assert response.ui_request == "Show original"
    assert any("inlineData" in part for part in parts(requests[0]))
    schema = requests[0]["generationConfig"]["responseJsonSchema"]
    assert set(schema["properties"]) == {"draft", "clarification", "ui_request"}
    assert provider.provider_calls[-1]["model"] == provider.basic_model


def test_repair_with_no_preflight_uses_flat_draft_prompt_and_schema(sdk_document):
    provider, document = sdk_document
    draft = DraftAnswer(status="insufficient", answer="The original does not establish this height.")
    requests = intercept(provider, draft.model_dump(mode="json"))
    response = provider.revise_answer(document, "What is the height?", draft, None, AnswerReview(decision="unsupported"))
    body = requests[0]
    schema = body["generationConfig"]["responseJsonSchema"]
    instruction = body["systemInstruction"]["parts"][0]["text"]
    assert response.status == "insufficient"
    assert "status" in schema["properties"] and "draft" not in schema["properties"]
    assert AGENT_EVIDENCE_INSTRUCTIONS in instruction
    assert "Return either draft with the evidence answer" not in instruction
    assert "Overall sufficiency decision" not in instruction
