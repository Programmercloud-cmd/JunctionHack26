"""Corrective intent/whole-source fixtures; these are not live inference claims."""
import logging
import re

from fastapi.testclient import TestClient
import httpx
import pytest

from app.main import create_app
from app.schemas import Usage
from test_backend import pdf
from test_chat_actions import chat_client, payload, post, saved_drawing


@pytest.mark.parametrize('has_scene', [True, False])
@pytest.mark.parametrize('selector', [None, {'target':'all','kind':'window'}])
def test_building_window_count_routes_original_question_without_mesh_count(chat_client, has_scene, selector):
    client, store, provider = chat_client
    doc = saved_drawing(store, scene=has_scene)
    message = 'How many windows does this building have?'
    proposed = {'type':'question'}
    if selector is not None:
        proposed['selector'] = selector
    result = post(client, provider, payload(doc, message), [proposed]).json()
    assert result['status'] == 'ready'
    assert result['actions'] == [{'type':'question','question':message,
        'revision_id':doc.revision_id,'navigation_reference':None}]
    assert store.get(doc.id).revision_id == doc.revision_id
    assert client.app.state.jobs.for_building(doc.id) == []
    assert store.conversation(doc.id) == []


def test_general_count_keeps_interpretation_revision_while_focused_question_pins_geometry(chat_client):
    client, store, provider = chat_client
    older = saved_drawing(store)
    current = store.commit(older.snapshot(), older.revision_id, status='available')
    body = payload(current, 'How many windows does this building have?',
        geometry_revision_id=older.revision_id, focused_id='window-1', selected_ids=['window-1'])
    general = post(client, provider, body, [{'type':'question','selector':{'target':'all','kind':'window'}}]).json()
    assert general['actions'][0]['revision_id'] == current.revision_id
    assert general['actions'][0]['navigation_reference'] is None
    body['message'] = 'What is the actual height of this window?'
    focused = post(client, provider, body, [{'type':'question','selector':{'target':'focused'}}]).json()
    action = focused['actions'][0]
    assert action['question'] == body['message']
    assert action['revision_id'] == older.revision_id
    assert action['navigation_reference']['object_id'] == 'window-1'
    assert action['navigation_reference']['source']['bbox'] == [.1,.2,.4,.5]


def test_question_reference_validation_still_rejects_foreign_ids_and_ambiguous_names(chat_client):
    client, store, provider = chat_client
    doc = saved_drawing(store)
    response = post(client, provider, payload(doc, 'How many windows does this building have?'),
        [{'type':'question','selector':{'target':'all','ids':['foreign']}}])
    assert response.status_code == 422
    result = post(client, provider, payload(doc, 'What does this object show?'),
        [{'type':'question','selector':{'target':'named','label':'unknown'}}]).json()
    assert result['status'] == 'clarification'
    assert not result['actions']


@pytest.mark.parametrize('focused', [False, True])
def test_original_blueprint_without_selector_opens_whole_page_not_implicit_object(chat_client, focused):
    client, store, provider = chat_client
    doc = saved_drawing(store)
    body = payload(doc, 'Show the original blueprint.', focused_id='window-1' if focused else None)
    result = post(client, provider, body, [{'type':'show_source'}]).json()
    action = result['actions'][0]
    assert result['status'] == 'ready'
    assert action['source']['page'] == 1
    assert action['source']['bbox'] is None and action['object_id'] is None
    assert action['source_revision_id'] == doc.revision_id
    assert client.app.state.jobs.for_building(doc.id) == []


def test_multi_page_original_opens_first_page_and_catalog_exposes_supplied_choices(chat_client):
    client, store, provider = chat_client
    doc = store.add(pdf(pages=2), 'Two supplied fixture pages.pdf')
    result = post(client, provider, payload(doc, 'Show the original blueprint.'), [{'type':'show_source'}]).json()
    assert result['status'] == 'ready'
    assert result['actions'][0]['source']['page'] == 1
    choices = provider.calls[-1][1]['page_sources']
    assert [item['page'] for item in choices] == [1,2]
    assert all(set(item) == {'page','source_id','source_page','filename'} for item in choices)
    result = post(client, provider, payload(doc, 'Show page two.'), [{'type':'show_source','page':2}]).json()
    assert result['actions'][0]['source']['page'] == 2
    assert result['actions'][0]['source']['bbox'] is None
    assert client.app.state.jobs.for_building(doc.id) == []


@pytest.mark.parametrize('stage', ['provider_response','action_validation'])
def test_safe_intent_diagnostics_explain_stage_without_message_response_or_unknown_keys(tmp_path, caplog, stage):
    secret = 'PRIVATE_CREDENTIAL_OR_SOURCE_SENTINEL'
    class Transport:
        usage = Usage()
        closed = 0
        def _generate(self, document, question, instruction, schema, **kwargs):
            if stage == 'provider_response':
                # An arbitrary JSON key is also untrusted text, not a safe log path.
                return schema.model_validate({'actions':[{'type':'question',secret:secret}]})
            return schema.model_validate({'actions':[{'type':'question','question':secret,'theme':'dark'}]})
        def close(self):
            self.closed += 1
    provider = Transport()
    app = create_app(provider_factory=lambda:provider, storage_root=tmp_path)
    with TestClient(app) as client, caplog.at_level(logging.WARNING, logger='app.chat_actions'):
        doc = saved_drawing(app.state.documents)
        response = client.post('/api/chat/actions', json=payload(doc, secret))
    assert response.status_code == 502
    assert 'Chat interpretation failed operationally' in response.json()['detail']
    records = [record.getMessage() for record in caplog.records if record.name == 'app.chat_actions']
    assert len(records) == 1
    assert stage in records[0] and 'ValidationError' in records[0] and 'extra_forbidden' in records[0]
    assert secret not in records[0] and secret not in response.text
    assert '<field>' in records[0] if stage == 'provider_response' else 'theme' in records[0]
    assert provider.closed == 1


def test_safe_provider_exception_diagnostic_never_logs_exception_message(chat_client, caplog):
    client, store, provider = chat_client
    doc = saved_drawing(store)
    provider.error = RuntimeError('PRIVATE_PROVIDER_EXCEPTION_BODY')
    with caplog.at_level(logging.WARNING, logger='app.chat_actions'):
        response = client.post('/api/chat/actions', json=payload(doc, 'How many windows does this building have?'))
    assert response.status_code == 502
    assert 'adapter_response' in caplog.text and 'RuntimeError' in caplog.text
    assert 'PRIVATE_PROVIDER_EXCEPTION_BODY' not in caplog.text + response.text


def test_failure_diagnostics_correlate_unique_application_refs_without_private_ids(chat_client, caplog):
    client, store, provider = chat_client
    doc = saved_drawing(store)
    secret = 'PRIVATE_REQUEST_ID_AND_EXCEPTION_BODY'
    class TransportFailure(RuntimeError):
        status_code = 503
    provider.error = TransportFailure(secret)
    body = payload(doc, 'How many windows does this building have?')
    body['request_id'] = secret
    with caplog.at_level(logging.WARNING, logger='app.chat_actions'):
        responses = [client.post('/api/chat/actions', json=body) for _ in range(2)]
    records = [record.getMessage() for record in caplog.records if record.name == 'app.chat_actions']
    assert len(records) == 2  # No duplicate outer-boundary log for either inner failure.
    references = []
    for response, record in zip(responses, records):
        assert response.status_code == 502
        reference = re.search(r'Diagnostic reference: ([a-f0-9]{32})\.', response.json()['detail']).group(1)
        assert f"'reference': '{reference}'" in record
        assert "'http_status': 503" in record
        assert 'adapter_response' in record and 'TransportFailure' in record
        assert secret not in response.text + record
        references.append(reference)
    assert references[0] != references[1]


def test_non_numeric_exception_status_is_never_logged(chat_client, caplog):
    client, store, provider = chat_client
    doc = saved_drawing(store)
    error = RuntimeError('PRIVATE_EXCEPTION_BODY')
    error.status_code = 'PRIVATE_STATUS_VALUE'
    error.code = True
    provider.error = error
    with caplog.at_level(logging.WARNING, logger='app.chat_actions'):
        response = client.post('/api/chat/actions', json=payload(doc))
    assert response.status_code == 502
    assert 'http_status' not in caplog.text
    assert 'PRIVATE_' not in caplog.text + response.text


@pytest.mark.parametrize('timeout_class', [httpx.ReadTimeout, httpx.ConnectTimeout])
def test_transport_timeout_has_safe_specific_outcome_and_correlated_diagnostic(tmp_path, caplog, timeout_class):
    secret = 'PRIVATE_TIMEOUT_BODY_AND_REQUEST'
    class Transport:
        usage = Usage()
        closed = 0
        calls = 0
        def _generate(self, *args, **kwargs):
            self.calls += 1
            raise timeout_class(secret, request=httpx.Request('POST', f'https://example.invalid/{secret}'))
        def close(self):
            self.closed += 1
    provider = Transport()
    app = create_app(provider_factory=lambda:provider, storage_root=tmp_path)
    with TestClient(app) as client, caplog.at_level(logging.WARNING, logger='app.chat_actions'):
        doc = saved_drawing(app.state.documents)
        response = client.post('/api/chat/actions', json=payload(doc, 'How many windows does this building have?'))
        assert app.state.jobs.for_building(doc.id) == []
        assert app.state.documents.get(doc.id).revision_id == doc.revision_id
    assert response.status_code == 502
    detail = response.json()['detail']
    assert 'timed out before an action was resolved' in detail
    assert 'No action was executed' in detail and 'saved sources and usable model remain available' in detail
    reference = re.search(r'Diagnostic reference: ([a-f0-9]{32})\.', detail).group(1)
    records = [record.getMessage() for record in caplog.records if record.name == 'app.chat_actions']
    assert len(records) == 1 and reference in records[0]
    assert 'provider_response' in records[0] and timeout_class.__name__ in records[0]
    assert secret not in records[0] + detail and 'example.invalid' not in records[0] + detail
    assert provider.calls == 1 and provider.closed == 1
