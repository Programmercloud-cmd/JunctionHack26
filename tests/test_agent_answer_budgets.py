"""Selected agent answer/correction budgets are explicit, with no truncation acceptance."""
import pytest

from app.providers.gemini import ProviderError
from app.review_schema import AnswerReview
from app.schemas import DraftAnswer
from test_gemini_schema import sdk_document, intercept


@pytest.mark.parametrize("advanced,expected", [(False, 8192), (True, 65536)])
def test_selected_worker_and_correction_share_output_allowance(sdk_document, monkeypatch, advanced, expected):
    monkeypatch.delenv("GEMINI_AGENT_ANSWER_TOKENS", raising=False)
    provider, document = sdk_document
    provider.model = provider.advanced_model if advanced else provider.basic_model
    draft = DraftAnswer(status="insufficient", answer="The inspected material does not establish the requested value.")
    requests = intercept(provider, {"draft": draft.model_dump(mode="json")})
    provider.answer_agent(document, "What is the footprint?")
    assert requests[0]["generationConfig"]["maxOutputTokens"] == expected
    assert requests[0]["generationConfig"]["thinkingConfig"]["thinking_level"].lower() == ("high" if advanced else "low")
    correction = intercept(provider, draft.model_dump(mode="json"))
    provider.revise_answer(document, "What is the footprint?", draft, None, AnswerReview(decision="unsupported"))
    assert correction[0]["generationConfig"]["maxOutputTokens"] == expected


def test_explicit_agent_budget_override_preserves_output_limit_error(sdk_document, monkeypatch):
    monkeypatch.setenv("GEMINI_AGENT_ANSWER_TOKENS", "24576")
    provider, document = sdk_document
    provider.model = provider.advanced_model
    requests = intercept(provider, {"draft": {"status": "answered", "answer": "Truncated"}}, finish_reason="MAX_TOKENS")
    with pytest.raises(ProviderError) as failure:
        provider.answer_agent(document, "What is the footprint based on my measurements?")
    assert failure.value.category == "provider_output_limit"
    assert requests[0]["generationConfig"]["maxOutputTokens"] == 24576
    assert provider.provider_calls[-1]["outcome"] == "output_limit"
