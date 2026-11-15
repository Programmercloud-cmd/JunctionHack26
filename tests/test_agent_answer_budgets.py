"""Selected agent answer/correction budgets are explicit, with no truncation acceptance."""
import pytest

from app.providers.gemini import ProviderError
from app.review_schema import AnswerReview
from app.schemas import DraftAnswer
from test_gemini_schema import sdk_document, intercept


@pytest.mark.parametrize("advanced,expected", [(False, 8192), (True, 65536)])
def test_selected_worker_and_correction_share_output_allowance(sdk_document, monkeypatch, advanced, expected):
    monkeypatch.delenv("GEMINI_AGENT_ANSWER_TOKENS", raising=False)
    monkeypatch.delenv("GEMINI_ADVANCED_THINKING_LEVEL", raising=False)
    provider, document = sdk_document
    provider.model = provider.advanced_model if advanced else provider.basic_model
    draft = DraftAnswer(status="insufficient", answer="The inspected material does not establish the requested value.")
    requests = intercept(provider, {"draft": draft.model_dump(mode="json")})
    provider.answer_agent(document, "What is the footprint?")
    assert requests[0]["generationConfig"]["maxOutputTokens"] == expected
    if advanced:
        assert "thinkingConfig" not in requests[0]["generationConfig"]
    else:
        assert requests[0]["generationConfig"]["thinkingConfig"]["thinking_level"].lower() == "low"
    correction = intercept(provider, draft.model_dump(mode="json"))
    provider.revise_answer(document, "What is the footprint?", draft, None, AnswerReview(decision="unsupported"))
    assert correction[0]["generationConfig"]["maxOutputTokens"] == expected
    if advanced:
        assert "thinkingConfig" not in correction[0]["generationConfig"]
    else:
        assert correction[0]["generationConfig"]["thinkingConfig"]["thinking_level"].lower() == "low"


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


def timed_requests(provider, outputs, *, status_code=200):
    """Capture the real SDK's transport timeout and upstream timeout header."""
    import json
    import httpx2
    captured = []
    responses = iter(outputs)
    def handle(request):
        captured.append({'transport': request.extensions['timeout'],
                         'server_timeout': request.headers.get('X-Server-Timeout')})
        output = next(responses)
        if status_code != 200:return httpx2.Response(status_code, json=output)
        return httpx2.Response(200, json={'candidates': [{'content': {'role': 'model', 'parts': [
            {'text': json.dumps(output)}]}, 'finishReason': 'STOP'}],
            'usageMetadata': {'promptTokenCount': 10, 'candidatesTokenCount': 5}})
    provider.client._api_client._httpx_client.close()
    provider.client._api_client._httpx_client = httpx2.Client(transport=httpx2.MockTransport(handle))
    return captured


def limited_draft():
    return DraftAnswer(status='insufficient', answer='The synthetic source does not establish the requested value.')


@pytest.mark.parametrize('advanced,total,legacy,expected', [
    (True, 180, 90, 180),
    (True, 150, 35, 150),
    (False, 180, 90, 90),
    (False, 180, 35, 35),
])
def test_selected_worker_and_correction_share_sdk_timeout_ceiling(sdk_document, monkeypatch, advanced, total, legacy, expected):
    monkeypatch.delenv('GEMINI_AGENT_ANSWER_SECONDS', raising=False)
    monkeypatch.setenv('QA_TOTAL_SECONDS', str(total))
    monkeypatch.setenv('GEMINI_DRAFT_SECONDS', str(legacy))
    provider, document = sdk_document
    provider.model = provider.advanced_model if advanced else provider.basic_model
    draft = limited_draft()
    calls = timed_requests(provider, [{'draft': draft.model_dump(mode='json')}, draft.model_dump(mode='json')])
    provider.answer_agent(document, 'What is the footprint?')
    provider.revise_answer(document, 'What is the footprint?', draft, None, AnswerReview(decision='unsupported'))
    assert len(calls) == 2
    assert [call['transport']['read'] for call in calls] == [expected, expected]
    assert [call['server_timeout'] for call in calls] == [str(expected), str(expected)]
    assert [call['timeout_ms'] for call in provider.provider_calls] == [expected*1000, expected*1000]


@pytest.mark.parametrize('advanced', [False, True])
def test_explicit_agent_seconds_override_applies_to_worker_and_correction(sdk_document, monkeypatch, advanced):
    monkeypatch.setenv('GEMINI_AGENT_ANSWER_SECONDS', '125.5')
    provider, document = sdk_document
    provider.model = provider.advanced_model if advanced else provider.basic_model
    draft = limited_draft()
    calls = timed_requests(provider, [{'draft': draft.model_dump(mode='json')}, draft.model_dump(mode='json')])
    provider.answer_agent(document, 'What is the footprint?')
    provider.revise_answer(document, 'What is the footprint?', draft, None, AnswerReview(decision='unsupported'))
    assert [call['transport']['read'] for call in calls] == [125.5, 125.5]
    # The installed SDK rounds its upstream server header to whole seconds.
    assert [call['server_timeout'] for call in calls] == ['126', '126']


def test_legacy_draft_timeout_is_unchanged(sdk_document, monkeypatch):
    monkeypatch.setenv('GEMINI_DRAFT_SECONDS', '38')
    monkeypatch.setenv('GEMINI_AGENT_ANSWER_SECONDS', '150')
    provider, document = sdk_document
    draft = limited_draft()
    calls = timed_requests(provider, [draft.model_dump(mode='json')])
    provider.answer(document, 'What is the height?', None)
    assert calls[0]['transport']['read'] == 38
    assert calls[0]['server_timeout'] == '38'


def test_existing_deadline_clamps_initial_and_corrective_agent_calls(sdk_document, monkeypatch):
    from app.providers import gemini
    clock = [100.0]
    monkeypatch.setattr(gemini, 'monotonic', lambda: clock[0])
    monkeypatch.setenv('GEMINI_AGENT_ANSWER_SECONDS', '240')
    provider, document = sdk_document
    provider.model = provider.advanced_model
    provider.request_deadline = 107.5
    draft = limited_draft()
    calls = timed_requests(provider, [{'draft': draft.model_dump(mode='json')}, draft.model_dump(mode='json')])
    provider.answer_agent(document, 'What is the footprint?')
    clock[0] = 104.25
    provider.revise_answer(document, 'What is the footprint?', draft, None, AnswerReview(decision='unsupported'))
    assert [call['transport']['read'] for call in calls] == [7.5, 3.25]
    assert [call['server_timeout'] for call in calls] == ['8', '4']
    assert [call['timeout_ms'] for call in provider.provider_calls] == [7500, 3250]
    clock[0] = 108
    with pytest.raises(ProviderError, match='budget') as failure:
        provider.revise_answer(document, 'What is the footprint?', draft, None, AnswerReview(decision='unsupported'))
    assert failure.value.status == 504 and len(calls) == 2


@pytest.mark.parametrize('value', ['0', '-1', 'nan', 'inf', '-inf', 'invalid'])
def test_agent_seconds_override_must_be_positive_and_finite(sdk_document, monkeypatch, value):
    monkeypatch.setenv('GEMINI_AGENT_ANSWER_SECONDS', value)
    provider, document = sdk_document
    provider.model = provider.advanced_model
    calls = timed_requests(provider, [])
    with pytest.raises(ProviderError, match='GEMINI_AGENT_ANSWER_SECONDS'):
        provider.answer_agent(document, 'What is the footprint?')
    assert not calls


def test_technical_worker_upstream_timeout_is_operational_504_without_retry(sdk_document, monkeypatch):
    monkeypatch.delenv('GEMINI_AGENT_ANSWER_SECONDS', raising=False)
    provider, document = sdk_document
    provider.model = provider.advanced_model
    calls = timed_requests(provider, [{'error': {'code': 504, 'status': 'DEADLINE_EXCEEDED',
                                                'message': 'Synthetic upstream timeout'}}], status_code=504)
    with pytest.raises(ProviderError, match='timed out while drafting') as failure:
        provider.answer_agent(document, 'What is the footprint?')
    assert failure.value.status == 504 and len(calls) == 1
    assert provider.provider_calls[-1]['outcome'] == 'provider_timeout'
    assert provider.provider_calls[-1]['http_status'] == 504


@pytest.mark.parametrize('setting', [None, '', 'default', ' DEFAULT '])
def test_advanced_default_omits_thinking_config_for_worker_and_correction(sdk_document, monkeypatch, setting):
    if setting is None:monkeypatch.delenv('GEMINI_ADVANCED_THINKING_LEVEL', raising=False)
    else:monkeypatch.setenv('GEMINI_ADVANCED_THINKING_LEVEL', setting)
    provider, document = sdk_document
    provider.model = provider.advanced_model
    draft = limited_draft()
    initial = intercept(provider, {'draft': draft.model_dump(mode='json')})
    provider.answer_agent(document, 'What is the footprint?')
    correction = intercept(provider, draft.model_dump(mode='json'))
    provider.revise_answer(document, 'What is the footprint?', draft, None, AnswerReview(decision='unsupported'))
    assert 'thinkingConfig' not in initial[0]['generationConfig']
    assert 'thinkingConfig' not in correction[0]['generationConfig']
    assert [call['thinking_level'] for call in provider.provider_calls] == [None, None]
    assert provider.model == provider.advanced_model


@pytest.mark.parametrize('setting', ['minimal', 'low', 'medium', 'HIGH', 'xhigh'])
def test_explicit_sdk_thinking_level_is_reused_for_correction(sdk_document, monkeypatch, setting):
    monkeypatch.setenv('GEMINI_ADVANCED_THINKING_LEVEL', setting)
    provider, document = sdk_document
    provider.model = provider.advanced_model
    draft = limited_draft()
    initial = intercept(provider, {'draft': draft.model_dump(mode='json')})
    provider.answer_agent(document, 'What is the footprint?')
    # Changing the environment cannot silently change a correction's selected policy.
    monkeypatch.setenv('GEMINI_ADVANCED_THINKING_LEVEL', 'default')
    correction = intercept(provider, draft.model_dump(mode='json'))
    provider.revise_answer(document, 'What is the footprint?', draft, None, AnswerReview(decision='unsupported'))
    for body in [initial[0], correction[0]]:
        assert body['generationConfig']['thinkingConfig']['thinking_level'].lower() == setting.lower()
    assert [call['thinking_level'] for call in provider.provider_calls] == [setting.lower(), setting.lower()]


@pytest.mark.parametrize('setting', ['unknown', 'unspecified', 'THINKING_LEVEL_UNSPECIFIED', 'none'])
def test_invalid_advanced_thinking_setting_fails_without_a_provider_call(sdk_document, monkeypatch, setting):
    monkeypatch.setenv('GEMINI_ADVANCED_THINKING_LEVEL', setting)
    provider, document = sdk_document
    provider.model = provider.advanced_model
    calls = timed_requests(provider, [])
    with pytest.raises(ProviderError, match='GEMINI_ADVANCED_THINKING_LEVEL') as failure:
        provider.answer_agent(document, 'What is the footprint?')
    assert failure.value.status == 503 and not calls


def test_basic_custom_model_alias_keeps_low_thinking_for_both_calls(sdk_document, monkeypatch):
    monkeypatch.setenv('GEMINI_ADVANCED_THINKING_LEVEL', 'HIGH')
    provider, document = sdk_document
    provider.basic_model = provider.model = 'offline-custom-basic-alias'
    draft = limited_draft()
    initial = intercept(provider, {'draft': draft.model_dump(mode='json')})
    provider.answer_agent(document, 'What is the footprint?')
    correction = intercept(provider, draft.model_dump(mode='json'))
    provider.revise_answer(document, 'What is the footprint?', draft, None, AnswerReview(decision='unsupported'))
    assert all(body['generationConfig']['thinkingConfig']['thinking_level'].lower() == 'low'
               for body in [initial[0], correction[0]])


def test_explicit_thinking_error_does_not_retry_or_fall_back(sdk_document, monkeypatch):
    from google.genai import errors
    monkeypatch.setenv('GEMINI_ADVANCED_THINKING_LEVEL', 'HIGH')
    provider, document = sdk_document
    provider.model = provider.advanced_model
    selected_model = provider.model
    calls = timed_requests(provider, [{'error': {'code': 400, 'status': 'INVALID_ARGUMENT',
                                                'message': 'Synthetic unsupported thinking selection'}}], status_code=400)
    with pytest.raises(errors.APIError):
        provider.answer_agent(document, 'What is the footprint?')
    assert len(calls) == 1 and provider.model == selected_model
    assert len(provider.provider_calls) == 1
    assert provider.provider_calls[0]['thinking_level'] == 'high'
    assert provider.provider_calls[0]['model'] == selected_model
