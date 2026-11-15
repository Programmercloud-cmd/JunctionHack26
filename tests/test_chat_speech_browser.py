"""Current product chat -> owned speech API -> browser playback, all providers fake."""
import asyncio
from io import BytesIO
import os
import socket
from threading import Thread
import time
import wave

import pytest
from test_agent_e2e_browser import AgentBrowserProvider
from test_browser import source_bytes
from test_browser_3d import scene_page
from test_chat_ui_browser import response
from test_ifc_generate import description

pytestmark=pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS")!="1",reason="opt-in browser checks")


@pytest.fixture
def speech_server(tmp_path,monkeypatch):
    import uvicorn
    from app.bundles import BuildingStore
    from app.identities import assign_identities
    from app.main import create_app
    from app.reasoning import build_reasoning
    from app.voice_config import VoiceError
    for key in ["GEMINI_API_KEY","ELEVENLABS_API_KEY","ELEVENLABS_VOICE_ID"]:monkeypatch.setenv(key,"fixture-never-sent")
    store=BuildingStore(tmp_path/"store");original=store.add(source_bytes(),"Speech fixture.png");candidate=store.prepare(original)
    candidate.description=assign_identities(candidate,description());candidate.interpretation_status="complete";candidate.reasoning=build_reasoning(candidate)
    document=store.commit(candidate,original.revision_id,status="interpreted");store.close()
    state={"texts":[],"messages":[],"question_annotations":[],"hold":False,"fail":False,"closed":0}
    class Chat(AgentBrowserProvider):
        def converse_agent(self,message,context):return {"message":f"Fixture reply: {message}","ui_request":None}
        def answer_agent(self,document,question):
            if question=="Clarify which marked level":return {"draft":None,"clarification":{"message":"Which depicted level do you mean?","suggestions":["Ground floor","Upper floor"],"free_text_allowed":True},"ui_request":None}
            return super().answer_agent(document,question)
    class Speech:
        async def synthesize(self,text):
            state["texts"].append(text)
            while state["hold"]:await asyncio.sleep(.01)
            if state["fail"]:raise VoiceError("Synthetic speech service unavailable.")
            output=BytesIO()
            with wave.open(output,"wb") as audio:
                audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(16000);audio.writeframes(bytes(16000*2*10))
            return output.getvalue()
        async def aclose(self):state["closed"]+=1
    app=create_app(provider_factory=lambda:Chat(state),speech_factory=Speech,storage_root=tmp_path/"store")
    sock=socket.socket();sock.bind(("127.0.0.1",0));server=uvicorn.Server(uvicorn.Config(app,log_level="error"));thread=Thread(target=server.run,kwargs={"sockets":[sock]},daemon=True);thread.start()
    deadline=time.monotonic()+5
    while not server.started and time.monotonic()<deadline:time.sleep(.02)
    assert server.started
    try:yield f"http://127.0.0.1:{sock.getsockname()[1]}",app,document,state
    finally:state["hold"]=False;server.should_exit=True;thread.join(5);sock.close()


def empty_chat(page,url):
    from playwright.sync_api import expect
    page.goto(url);page.locator("#home-new-project").click();page.locator("#project-create-name").fill("Speaking Building")
    page.locator("#project-create-form button[type=submit]").click();page.locator("#new-project-chat").click()
    expect(page.locator("#question")).to_be_visible();expect(page.locator("#voice-read-answers")).to_be_enabled()


def say(page,text):page.locator("#question").fill(text);page.locator("#ask-button").click()


def test_source_free_conversation_opt_in_owned_payload_and_no_history_replay(speech_server,scene_page):
    from playwright.sync_api import expect
    url,_,_,state=speech_server;page=scene_page;posted=[]
    page.on("request",lambda request:posted.append(request.post_data_json) if request.url.endswith("/api/voice/speech") else None)
    empty_chat(page,url);toggle=page.locator("#voice-read-answers")
    expect(toggle).to_have_attribute("aria-pressed","false");expect(toggle).to_have_attribute("aria-disabled","false")
    expect(toggle).to_have_attribute("title","Read answers aloud: off")
    say(page,"Before opting in");expect(page.locator("#chat-log")).to_contain_text("Fixture reply: Before opting in");assert not state["texts"]
    toggle.click();expect(toggle).to_have_attribute("aria-pressed","true");assert not state["texts"]
    say(page,"Speak my normal reply");expect(page.locator("#voice-speech-status")).to_contain_text("Reading the answer aloud")
    assert state["texts"]==["Fixture reply: Speak my normal reply"]
    captured=page.evaluate("({project:state.activeProjectId,session:state.activeSessionId})")
    assert posted==[{"project_id":captured["project"],"session_id":captured["session"],"document_id":None,"text":state["texts"][0]}]
    toggle.click();assert page.evaluate("voice.speech===null")
    page.locator("#back-project-overview").click();page.locator(f'[data-session-id="{captured["session"]}"] .session-name').click()
    expect(page.locator("#chat-log")).to_contain_text("Speak my normal reply");assert len(state["texts"])==1


def test_grouped_technical_prepared_text_null_denial_and_message_clarification(speech_server,scene_page):
    from playwright.sync_api import expect
    url,app,document,state=speech_server
    app.state.documents.add_many([(source_bytes()+b"second","Other speech drawing.png")],building_id=document.id)
    page=scene_page;page.goto(url);page.locator("#home-library-list .home-file").first.click();page.locator("#new-project-chat").click()
    expect(page.locator("#voice-read-answers")).to_be_enabled();page.locator("#voice-read-answers").click()
    say(page,"What is marked in these drawings?");expect(page.locator("#voice-speech-status")).to_contain_text("Reading the answer aloud")
    assert len(state["texts"])==1 and "marked original page" in state["texts"][0]
    say(page,"Clarify which marked level");expect(page.locator("#chat-log")).to_contain_text("Which depicted level do you mean?")
    page.wait_for_function("voice.speech!==null && document.getElementById('voice-speech-status').textContent==='Reading the answer aloud.'")
    assert state["texts"][-1]=="Which depicted level do you mean?" and len(state["texts"])==2
    def controlled(route):
        body=route.request.post_data_json
        if body["message"]=="Clarify my request":return route.fulfill(json={**response(body,[]),"status":"clarification","tool":"conversation","message":"Envelope text must not play twice.","clarification":{"message":"Which floor should I inspect?","suggestions":[]}})
        route.fulfill(json={**response(body,[]),"tool":"technical_basic","message":"Never speak this envelope.","answer":{"status":"answered","answer":"Written answer remains available.","answered_revision_id":body["revision_id"],"spoken_answer":None,"spoken_answer_with_details":None,"evidence":[]}})
    page.route("**/api/chat",controlled)
    say(page,"Prepared audio failed");expect(page.locator("#voice-speech-error")).to_contain_text("Audio is unavailable")
    expect(page.locator("#chat-log")).to_contain_text("Written answer remains available");assert len(state["texts"])==2
    say(page,"Clarify my request");expect(page.locator("#voice-speech-status")).to_contain_text("Reading the answer aloud")
    assert state["texts"][-1]=="Which floor should I inspect?" and len(state["texts"])==3


def test_delayed_old_reply_is_written_without_replacing_newest_audio(speech_server,scene_page):
    from playwright.sync_api import expect
    url,_,_,state=speech_server;page=scene_page;empty_chat(page,url);page.locator("#voice-read-answers").click();held=[]
    def delayed(route):
        if route.request.post_data_json["message"]=="Delayed old reply":held.append(route)
        else:route.continue_()
    page.route("**/api/chat",delayed);say(page,"Delayed old reply");say(page,"Newest reply")
    expect(page.locator("#voice-speech-status")).to_contain_text("Reading the answer aloud");assert len(held)==1
    body=held[0].request.post_data_json;held[0].fulfill(json={**response(body,[]),"tool":"conversation","message":"Delayed old spoken text"})
    expect(page.locator("#chat-log")).to_contain_text("Delayed old spoken text")
    assert state["texts"]==["Fixture reply: Newest reply"]


def test_new_request_home_session_and_toggle_abort_stale_synthesis(speech_server,scene_page):
    from playwright.sync_api import expect
    url,_,_,state=speech_server;page=scene_page;empty_chat(page,url);page.locator("#voice-read-answers").click();state["hold"]=True
    say(page,"Hold this audio");page.wait_for_function("voice.speech!==null");page.evaluate("window.oldSpeech=voice.speech")
    say(page,"Replacement audio");page.wait_for_function("oldSpeech.controller.signal.aborted&&voice.speech!==oldSpeech&&voice.speech!==null")
    page.evaluate("window.oldSpeech=voice.speech");page.locator("#voice-read-answers").click()
    assert page.evaluate("oldSpeech.controller.signal.aborted&&voice.speech===null")
    page.locator("#voice-read-answers").click();say(page,"Canceled by Home");page.wait_for_function("voice.speech!==null");page.evaluate("window.oldSpeech=voice.speech")
    page.locator("#home-tab").click();assert page.evaluate("oldSpeech.controller.signal.aborted&&voice.speech===null")
    state["hold"]=False;expect(page.locator("#voice-play-answer")).not_to_be_visible()


def test_autoplay_retry_reuses_audio_and_speech_failure_keeps_written_reply(speech_server,scene_page):
    from playwright.sync_api import expect
    url,_,_,state=speech_server;page=scene_page;empty_chat(page,url);page.locator("#voice-read-answers").click()
    page.evaluate("""()=>{const play=Audio.prototype.play;Audio.prototype.play=function(){Audio.prototype.play=play;return Promise.reject(new DOMException('Autoplay blocked','NotAllowedError'));};}""")
    say(page,"Autoplay fallback");expect(page.locator("#voice-play-answer")).to_be_visible();assert len(state["texts"])==1
    page.locator("#voice-play-answer").click();expect(page.locator("#voice-speech-status")).to_contain_text("Reading the answer aloud");assert len(state["texts"])==1
    state["fail"]=True;say(page,"Keep text after speech error")
    expect(page.locator("#voice-speech-error")).to_contain_text("Synthetic speech service unavailable")
    expect(page.locator("#chat-log")).to_contain_text("Fixture reply: Keep text after speech error")


def test_session_upload_and_microphone_start_cancel_pending_audio(speech_server,scene_page):
    from playwright.sync_api import expect
    from test_buildings_shared_browser import drop_drawing
    url,app,_,state=speech_server;page=scene_page;empty_chat(page,url);page.locator("#voice-read-answers").click();state["hold"]=True
    say(page,"Before another session");page.wait_for_function("voice.speech!==null");page.evaluate("window.oldSpeech=voice.speech");original=page.evaluate("state.activeSessionId")
    page.locator("#back-project-overview").click();page.locator("#new-project-chat").click();page.wait_for_function("id=>state.activeSessionId!==id&&!state.sessionOpening",arg=original)
    assert page.evaluate("oldSpeech.controller.signal.aborted&&voice.speech===null")
    say(page,"Before uploading drawings");page.wait_for_function("voice.speech!==null");page.evaluate("window.oldSpeech=voice.speech")
    app.state.jobs.extract=lambda *args,**kwargs:[]
    with page.expect_response(lambda response:"/scopes/" in response.url and response.url.endswith("/sources")) as uploaded:
        drop_drawing(page,"#chat-column","Speech upload.png",source_bytes()+b"speech-upload")
    assert uploaded.value.ok;page.wait_for_function("!state.busy&&state.document!==null")
    assert page.evaluate("oldSpeech.controller.signal.aborted&&voice.speech===null")
    say(page,"Before starting the microphone");page.wait_for_function("voice.speech!==null");page.evaluate("window.oldSpeech=voice.speech")
    # Reject local capture before any transcription connection; this test concerns
    # cancellation at microphone start, not speech recognition or permissions.
    page.evaluate("()=>{navigator.mediaDevices.getUserMedia=async()=>{throw new DOMException('Fixture denies microphone','NotAllowedError')}}")
    page.locator("#voice-record").click();page.wait_for_function("!voice.recording")
    assert page.evaluate("oldSpeech.controller.signal.aborted&&voice.speech===null")
    state["hold"]=False;expect(page.locator("#voice-play-answer")).not_to_be_visible()
