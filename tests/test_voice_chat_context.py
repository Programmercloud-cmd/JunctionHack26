"""Captured Building/chat context is checked before paid speech synthesis."""
from fastapi.testclient import TestClient
import pytest

from app.main import create_app
from test_backend import png
from test_public_access_integration import prepared, unlock
from test_voice import FakeSpeech, voice_app


def empty_chat(client, name='Voice Building'):
    owner=client.post('/api/projects',json={'name':name}).json()
    chat=client.post(f"/api/projects/{owner['id']}/scopes/shared/chats",json={}).json()
    return {'project_id':owner['id'],'session_id':chat['id'],'document_id':None}


def test_source_free_chat_speech_preserves_text_and_disallows_stale_null_after_upload(voice_app):
    client,app,_,_,provider=voice_app
    context=empty_chat(client)
    text='Hello. Which drawing would you like to discuss?'
    response=client.post('/api/voice/speech',json=context|{'text':text})
    assert response.status_code==200 and response.content==b'ID3fixture-audio'
    assert response.headers['cache-control']=='no-store' and provider.text==text and provider.closed
    app.state.jobs.extract=lambda *args,**kwargs:[]
    uploaded=client.post(f"/api/projects/{context['project_id']}/scopes/shared/sources",
        files=[('files',('floor.png',png()+b'voice-floor')),('files',('section.png',png()+b'voice-section'))])
    assert uploaded.status_code==200,uploaded.text
    provider.text=None;provider.closed=False
    stale=client.post('/api/voice/speech',json=context|{'text':'Outdated source-free reply'})
    assert stale.status_code==409 and provider.text is None and not provider.closed
    current=context|{'document_id':uploaded.json()['document_id'],'text':'The marked room is shown.'}
    grouped=client.post('/api/voice/speech',json=current)
    assert grouped.status_code==200 and provider.text==current['text']


def test_speech_rejects_wrong_owner_document_deleted_chat_and_scope_before_provider(voice_app):
    client,app,document,_,provider=voice_app
    a=empty_chat(client,'A');b=empty_chat(client,'B')
    attempts=[(a|{'project_id':b['project_id']},404),
              (a|{'document_id':document},409),
              (a|{'document_id':'missing'},409),
              (a|{'session_id':'f'*32},404),
              (a|{'project_id':'f'*32},404)]
    for context,status in attempts:
        response=client.post('/api/voice/speech',json=context|{'text':'Read this reply'})
        assert response.status_code==status,response.text
        assert provider.text is None and not provider.closed
    assert client.delete(f"/api/projects/{a['project_id']}/scopes/shared").status_code==200
    assert client.post('/api/voice/speech',json=a|{'text':'Removed Building'}).status_code==409
    assert client.delete(f"/api/projects/{b['project_id']}/chats/{b['session_id']}").status_code==200
    assert client.post('/api/voice/speech',json=b|{'text':'Removed chat'}).status_code==404
    assert provider.text is None and not provider.closed


@pytest.mark.parametrize('context',[{}, {'project_id':'a'}, {'session_id':'a'},
    {'project_id':None,'session_id':'a'}, {'project_id':'a','session_id':[]},
    {'document_id':42}])
def test_invalid_speech_context_has_safe_error_without_provider(voice_app,context):
    client,_,_,_,provider=voice_app
    response=client.post('/api/voice/speech',json=context|{'text':'PRIVATE_TEXT_NOT_IN_ERROR'})
    assert response.status_code==400 and 'PRIVATE_TEXT_NOT_IN_ERROR' not in response.text
    assert provider.text is None and not provider.closed


def test_existing_document_is_required_even_when_session_membership_matches(voice_app,monkeypatch):
    client,app,document,_,provider=voice_app
    owner=client.get('/api/buildings').json()['projects'][0]
    chat=client.post(f"/api/projects/{owner['id']}/chats",json={'building_id':document}).json()
    # Membership alone cannot establish a supplied document still exists.
    from app.documents import DocumentError
    monkeypatch.setattr(app.state.documents,'get',lambda _: (_ for _ in ()).throw(DocumentError('Building not found.',404)))
    response=client.post('/api/voice/speech',json={'project_id':owner['id'],'session_id':chat['id'],
        'document_id':document,'text':'Stored reply'})
    assert response.status_code==404 and provider.text is None and not provider.closed


def test_speech_same_origin_gate_applies_to_empty_chats(voice_app):
    client,_,_,_,provider=voice_app
    context=empty_chat(client)
    response=client.post('/api/voice/speech',json=context|{'text':'Reply'},headers={'origin':'https://foreign.example'})
    assert response.status_code==403 and provider.text is None and not provider.closed


def test_virtual_public_example_owner_speech_requires_editor_and_uses_existing_context(prepared,monkeypatch):
    root,document,_=prepared
    monkeypatch.setenv('ELEVENLABS_API_KEY','fixture-never-sent')
    monkeypatch.setenv('ELEVENLABS_VOICE_ID','fixture-voice')
    calls=[]
    def factory():
        provider=FakeSpeech();calls.append(provider);return provider
    with TestClient(create_app(storage_root=root,provider_factory=lambda:None,speech_factory=factory),base_url='https://demo.test') as client:
        owner=client.get('/api/buildings').json()['projects'][0]
        assert owner['id']=='example-'+document.id
        unlock(client)
        chat=client.post(f"/api/projects/{owner['id']}/scopes/{document.id}/chats",json={}).json()
        body={'project_id':owner['id'],'session_id':chat['id'],'document_id':document.id,'text':'The inspected drawing shows this room.'}
        response=client.post('/api/voice/speech',json=body)
        assert response.status_code==200 and calls[0].text==body['text']
        client.post('/api/access/lock')
        assert client.post('/api/voice/speech',json=body).status_code==401 and len(calls)==1


@pytest.mark.parametrize('formatter_failure',[False,True])
def test_product_technical_answer_prepares_speech_before_serializing_and_saving(voice_app,monkeypatch,formatter_failure):
    import app.voice_format as formatting
    from app.schemas import DraftAnswer
    from test_agent_chat import AgentFixture
    from test_backend import evidence
    client,app,document,_,_=voice_app
    owner=client.post('/api/projects',json={'name':'Technical speech'}).json()
    assert client.put(f"/api/projects/{owner['id']}/files/{document}").status_code==200
    chat=client.post(f"/api/projects/{owner['id']}/chats",json={'building_id':document}).json()
    written='The room is shown (coordinates [0.1, 0.2, 0.7, 0.8]; citation 1).'
    provider=AgentFixture('technical_basic',draft=DraftAnswer(status='answered',answer=written,evidence=[evidence()]))
    app.state.provider_factory=lambda:provider
    original=formatting.prepare_spoken_answer;seen=[]
    def prepare(answer,question,**kwargs):
        seen.append(question)
        if formatter_failure:raise RuntimeError('PRIVATE_FORMATTER_ERROR')
        return original(answer,question,**kwargs)
    monkeypatch.setattr(formatting,'prepare_spoken_answer',prepare)
    question='What is shown in this drawing?'
    response=client.post('/api/chat',json={'project_id':owner['id'],'session_id':chat['id'],
        'document_id':document,'revision_id':app.state.documents.get(document).revision_id,
        'message':question,'request_id':'technical-speech'})
    assert response.status_code==200,response.text
    answer=response.json()['answer']
    assert answer['answer']==written and answer['evidence']==[{**evidence(),'source_id':document,'source_page':1}]
    assert seen and all(value==question for value in seen)
    assert provider.calls==[(name,question) for name in ('route','answer','review')]
    saved=app.state.project_chats.get(owner['id'],chat['id'])['messages'][-1]['answer']
    assert saved==answer
    if formatter_failure:
        assert answer['spoken_answer'] is None and answer['spoken_answer_with_details'] is None
        assert 'PRIVATE_FORMATTER_ERROR' not in response.text
    else:
        assert answer['spoken_answer'] and '0.1' not in answer['spoken_answer'] and 'citation 1' not in answer['spoken_answer']
        assert '0.1' in answer['spoken_answer_with_details'] and 'citation 1' in answer['spoken_answer_with_details']


def test_structured_technical_clarification_prepares_only_human_message_for_speech(voice_app):
    from test_agent_chat import AgentFixture
    client,app,document,_,_=voice_app
    owner=client.get('/api/buildings').json()['projects'][0]
    chat=client.post(f"/api/projects/{owner['id']}/chats",json={'building_id':document}).json()
    message='Should I use the horizontal measurement or the vertical measurement?'
    class ClarifyingFixture(AgentFixture):
        def answer_agent(self,source,question):
            self.calls.append(('answer',question))
            return {'clarification':{'message':message,'suggestions':['Horizontal','Vertical']}}
    provider=ClarifyingFixture('technical_advanced');app.state.provider_factory=lambda:provider
    question='Use my measurements to find the building footprint.'
    response=client.post('/api/chat',json={'project_id':owner['id'],'session_id':chat['id'],
        'document_id':document,'revision_id':app.state.documents.get(document).revision_id,
        'message':question,'request_id':'clarification-speech'})
    assert response.status_code==200,response.text
    result=response.json();answer=result['answer']
    assert result['status']=='clarification' and answer['answer']==message
    assert answer['spoken_answer']==answer['spoken_answer_with_details']==message
    assert answer['evidence']==[] and answer['clarification']['suggestions']==['Horizontal','Vertical']
    assert provider.calls==[(name,question) for name in ('route','answer')]
    assert app.state.project_chats.get(owner['id'],chat['id'])['messages'][-1]['answer']==answer
