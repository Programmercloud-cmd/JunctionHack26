"""Selected OpenAI transcription: injected clients, no credentials or network calls."""
import asyncio
from io import BytesIO
from types import SimpleNamespace
from threading import Event
import wave

from fastapi.testclient import TestClient
import httpx
from openai import AsyncOpenAI
from PIL import Image
import pytest

from app.main import create_app
from app.openai_transcription import OpenAITranscriptionProvider
from app.voice_config import VoiceError, voice_settings
from app.voice_providers import GeminiTranscriptionProvider, create_transcription_provider


class FakeClient:
    def __init__(self, state):
        self.state = state
        self.audio = SimpleNamespace(transcriptions=SimpleNamespace(create=self.transcribe))

    async def transcribe(self, **kwargs):
        self.state['requests'].append(kwargs)
        self.state['entered'].set()
        try:
            if self.state.get('hold'):
                await asyncio.Future()
            if self.state.get('error'):
                raise RuntimeError('SECRET_PROVIDER_BODY_AND_KEY')
            return SimpleNamespace(text='Talotekniikka on the ground floor.')
        except asyncio.CancelledError:
            self.state['cancelled'].set()
            raise

    async def close(self):
        self.state['closed'].set()


@pytest.fixture
def selected_openai(monkeypatch):
    monkeypatch.setenv('AI_PROVIDER', 'openai')
    monkeypatch.setenv('OPENAI_API_KEY', 'fixture-never-sent')
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    monkeypatch.delenv('OPENAI_TRANSCRIPTION_MODEL', raising=False)
    monkeypatch.setenv('VOICE_CONNECT_TIMEOUT_SECONDS', '1')
    monkeypatch.setenv('VOICE_FINALIZATION_TIMEOUT_SECONDS', '1')
    state = {'requests': [], 'arguments': [], 'entered': Event(), 'cancelled': Event(), 'closed': Event()}
    def factory(**kwargs):
        state['arguments'].append(kwargs)
        return FakeClient(state)
    return state, factory


@pytest.mark.asyncio
async def test_pcm_buffers_until_stop_then_one_wav_request_and_final_events(selected_openai):
    state, factory = selected_openai
    provider = OpenAITranscriptionProvider(client_factory=factory)
    pcm = b'\0\1\2\3' * 1600
    async with provider.connect(['Talotekniikka', 'Ground floor'], ['fi-FI']) as session:
        events = session.events()
        waiting = asyncio.create_task(anext(events))
        await asyncio.sleep(0)
        await session.send_audio(pcm[:3200]); await session.send_audio(pcm[3200:])
        assert not state['requests']
        await session.end_audio(); await session.end_audio()
        final = await waiting
        done = await anext(events)
        assert final.final and final.text == 'Talotekniikka on the ground floor.'
        assert done.terminal and not done.text
        assert len(state['requests']) == 1
        request = state['requests'][0]
        assert request['model'] == 'gpt-transcribe' and request['response_format'] == 'json'
        assert 'language' not in request
        assert request['extra_body'] == {'keywords':['Talotekniikka','Ground floor'],'languages':['fi']}
        assert 'spelling hints' in request['prompt']
        name, data, content_type = request['file']
        assert name.endswith('.wav') and content_type == 'audio/wav'
        with wave.open(BytesIO(data), 'rb') as audio:
            assert (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) == (1, 2, 16000)
            assert audio.readframes(audio.getnframes()) == pcm
        assert not session.audio
        await events.aclose()
    assert state['closed'].is_set()
    assert state['arguments'][0]['max_retries'] == 0
    assert state['arguments'][0]['timeout'] == 1


@pytest.mark.asyncio
async def test_cancel_before_stop_discards_buffer_without_paid_request(selected_openai):
    state, factory = selected_openai
    async with OpenAITranscriptionProvider(client_factory=factory).connect([], []) as session:
        await session.send_audio(b'\0\0' * 100)
        waiting = asyncio.create_task(anext(session.events()))
        await asyncio.sleep(0)
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):await waiting
    assert not state['requests'] and state['closed'].is_set() and not session.audio


@pytest.mark.asyncio
async def test_explicit_legacy_model_override_retains_autodetection(selected_openai, monkeypatch):
    state, factory = selected_openai
    monkeypatch.setenv('OPENAI_TRANSCRIPTION_MODEL', 'gpt-4o-mini-transcribe')
    async with OpenAITranscriptionProvider(client_factory=factory).connect([], ['fi-FI', 'en-US']) as session:
        await session.send_audio(b'\0\0' * 100);await session.end_audio()
        events=[event async for event in session.events()]
    assert len(events)==2
    assert state['requests'][0]['model']=='gpt-4o-mini-transcribe'
    assert 'language' not in state['requests'][0] and 'prompt' not in state['requests'][0]


@pytest.mark.asyncio
async def test_sdk_multipart_wire_uses_actual_transcription_endpoint(selected_openai):
    captured=[]
    def handler(request):
        captured.append(request)
        return httpx.Response(200, json={'text':'Synthetic wire transcript'})
    def factory(**kwargs):
        return AsyncOpenAI(**kwargs, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    async with OpenAITranscriptionProvider(client_factory=factory).connect(['Fixture'], ['en-US','fi-FI']) as session:
        await session.send_audio(b'\0\0' * 100);await session.end_audio()
        events=[event async for event in session.events()]
    assert [event.text for event in events if event.text]==['Synthetic wire transcript']
    assert len(captured)==1 and captured[0].url.path=='/v1/audio/transcriptions'
    assert captured[0].headers['content-type'].startswith('multipart/form-data; boundary=')
    assert b'RIFF' in captured[0].content and b'WAVE' in captured[0].content
    assert b'gpt-transcribe' in captured[0].content
    assert b'keywords' in captured[0].content and b'languages' in captured[0].content
    assert b'Fixture' in captured[0].content and b'fi' in captured[0].content
    assert b'name="language"' not in captured[0].content


@pytest.mark.asyncio
async def test_missing_selected_key_does_not_construct_client_or_fall_back(selected_openai, monkeypatch):
    state,factory=selected_openai;monkeypatch.delenv('OPENAI_API_KEY');monkeypatch.setenv('GEMINI_API_KEY','unselected-fixture')
    assert not voice_settings().public()['transcription_ready']
    with pytest.raises(VoiceError,match='OPENAI_API_KEY'):
        async with OpenAITranscriptionProvider(client_factory=factory).connect([],[]):pass
    assert not state['arguments']


@pytest.mark.parametrize('provider,key,ready,mode',[('openai','OPENAI_API_KEY',True,'batch'),('gemini','GEMINI_API_KEY',True,'live')])
def test_readiness_and_factory_follow_selected_provider(monkeypatch,provider,key,ready,mode):
    monkeypatch.setenv('AI_PROVIDER',provider)
    monkeypatch.delenv('OPENAI_API_KEY',raising=False);monkeypatch.delenv('GEMINI_API_KEY',raising=False)
    monkeypatch.setenv(key,'fixture-never-sent')
    config=voice_settings().public()
    assert config['transcription_provider']==provider and config['transcription_mode']==mode and config['transcription_ready'] is ready
    assert isinstance(create_transcription_provider(),OpenAITranscriptionProvider if provider=='openai' else GeminiTranscriptionProvider)
    assert 'fixture-never-sent' not in str(config)


def test_invalid_provider_is_safe_configuration_error(monkeypatch):
    monkeypatch.setenv('AI_PROVIDER','not-supported')
    with pytest.raises(VoiceError,match='AI_PROVIDER'):voice_settings()


@pytest.fixture
def websocket_app(selected_openai, monkeypatch, tmp_path):
    state,factory=selected_openai
    monkeypatch.setattr('app.openai_transcription.AsyncOpenAI',factory)
    app=create_app(storage_root=tmp_path)
    with TestClient(app) as client:
        image=BytesIO();Image.new('RGB',(40,40),'white').save(image,format='PNG')
        document=app.state.documents.add(image.getvalue(),'Fixture.png')
        yield client,document.id,state


def test_selected_openai_websocket_ready_final_done_and_large_vocabulary(websocket_app):
    client,document_id,state=websocket_app
    config=client.get('/api/voice/config').json()
    assert config['transcription_ready'] and config['transcription_provider']=='openai' and config['transcription_mode']=='batch'
    with client.websocket_connect('/api/voice/transcribe') as ws:
        ws.send_json({'type':'start','document_id':document_id,'custom_vocabulary':[f'Fixture {i}' for i in range(1001)]})
        assert ws.receive_json()=={'type':'ready'}
        ws.send_bytes(b'\0\0'*1600)
        assert not state['requests']
        ws.send_json({'type':'stop'})
        assert ws.receive_json()=={'type':'transcript','text':'Talotekniikka on the ground floor.','final':True}
        assert ws.receive_json()=={'type':'done'}
    assert len(state['requests'])==1 and state['closed'].wait(1)


@pytest.mark.parametrize('cancel',[True,False])
def test_websocket_cancel_or_disconnect_before_stop_never_submits(websocket_app,cancel):
    client,document_id,state=websocket_app
    with client.websocket_connect('/api/voice/transcribe') as ws:
        ws.send_json({'type':'start','document_id':document_id});assert ws.receive_json()['type']=='ready'
        ws.send_bytes(b'\0\0'*100)
        if cancel:ws.send_json({'type':'cancel'})
    assert state['closed'].wait(1) and not state['requests']


def test_disconnect_cancels_inflight_transcription_and_closes_client(websocket_app):
    client,document_id,state=websocket_app;state['hold']=True
    with client.websocket_connect('/api/voice/transcribe') as ws:
        ws.send_json({'type':'start','document_id':document_id});assert ws.receive_json()['type']=='ready'
        ws.send_bytes(b'\0\0'*100);ws.send_json({'type':'stop'});assert state['entered'].wait(1)
    assert state['cancelled'].wait(1) and state['closed'].wait(1)
    assert len(state['requests'])==1


def test_websocket_provider_error_is_safe_and_does_not_fallback(websocket_app):
    client,document_id,state=websocket_app;state['error']=True
    with client.websocket_connect('/api/voice/transcribe') as ws:
        ws.send_json({'type':'start','document_id':document_id});assert ws.receive_json()['type']=='ready'
        ws.send_bytes(b'\0\0'*100);ws.send_json({'type':'stop'});error=ws.receive_json()
    assert error['type']=='error' and 'OpenAI transcription failed' in error['message']
    assert 'SECRET' not in str(error) and len(state['requests'])==1 and state['closed'].wait(1)


def test_finalization_timeout_cancels_request(websocket_app, monkeypatch):
    client,document_id,state=websocket_app;state['hold']=True
    monkeypatch.setenv('VOICE_FINALIZATION_TIMEOUT_SECONDS','.05')
    with client.websocket_connect('/api/voice/transcribe') as ws:
        ws.send_json({'type':'start','document_id':document_id});assert ws.receive_json()['type']=='ready'
        ws.send_bytes(b'\0\0'*100);ws.send_json({'type':'stop'});error=ws.receive_json()
    assert error['type']=='error' and 'timeout' in error['message']
    assert state['cancelled'].wait(1) and state['closed'].wait(1)


def test_empty_recording_fails_without_transcription_call(websocket_app):
    client,document_id,state=websocket_app
    with client.websocket_connect('/api/voice/transcribe') as ws:
        ws.send_json({'type':'start','document_id':document_id});assert ws.receive_json()['type']=='ready'
        ws.send_json({'type':'stop'});error=ws.receive_json()
    assert error['type']=='error' and 'No recorded audio' in error['message']
    assert not state['requests'] and state['closed'].wait(1)


@pytest.mark.asyncio
async def test_new_model_preserves_multilingual_hints_and_unsafe_keyword_spelling_in_prompt(selected_openai):
    state,factory=selected_openai
    terms=['Talotekniikka','Room <A>','Two\nlines','Air handler']
    async with OpenAITranscriptionProvider(client_factory=factory).connect(terms,['en-US','fi-FI','zh-CN','yue','en']) as session:
        await session.send_audio(b'\0\0'*100);await session.end_audio()
        events=[event async for event in session.events()]
    request=state['requests'][0]
    assert request['model']=='gpt-transcribe' and 'language' not in request
    assert request['extra_body']=={'keywords':['Talotekniikka','Air handler'],'languages':['en','fi','zh-cn','yue']}
    assert 'Room <A>' in request['prompt'] and 'Two\nlines' in request['prompt']
    assert events[0].final and events[1].terminal


@pytest.mark.asyncio
async def test_explicit_legacy_model_single_language_uses_legacy_wire(selected_openai, monkeypatch):
    state,factory=selected_openai;monkeypatch.setenv('OPENAI_TRANSCRIPTION_MODEL','gpt-4o-mini-transcribe')
    async with OpenAITranscriptionProvider(client_factory=factory).connect(['Legacy hint'],['fi-FI']) as session:
        await session.send_audio(b'\0\0'*100);await session.end_audio()
        _=[event async for event in session.events()]
    assert state['requests'][0]['language']=='fi' and 'extra_body' not in state['requests'][0]
    assert 'Legacy hint' in state['requests'][0]['prompt']
