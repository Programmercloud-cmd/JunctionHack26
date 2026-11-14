"""Voice routes layered beside the existing source-grounded question pipeline."""
import asyncio
from contextlib import AsyncExitStack, suppress
import json
from urllib.parse import urlsplit

from fastapi import HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response

from .documents import DocumentError
from .voice_config import VoiceError, voice_settings
from .voice_providers import ElevenLabsSpeechProvider, GeminiTranscriptionProvider

GOOGLE_VOCABULARY_LIMIT = 1000
SPEECH_TEXT_LIMIT = 6000  # Existing DraftAnswer bound; longer final answers stay readable.


def normalized_terms(terms):
    result, seen = [], set()
    for term in terms:
        if not isinstance(term, str):
            raise VoiceError("Vocabulary entries must be text.", 400)
        term = " ".join(term.split())
        if term and term.casefold() not in seen:
            result.append(term)
            seen.add(term.casefold())
    return result


def document_vocabulary(document):
    scene = document.scene
    if scene is None:
        return {"terms": [], "rooms": [], "warnings": [
            "Automatic room names become available after model generation. You can add custom words now."
        ]}
    floors = {floor.id: " ".join(floor.label.split()) for floor in scene.floors}
    rooms = []
    for element in scene.elements:
        if element.kind != "room" or not element.name.strip():
            continue
        floor_label = floors.get(element.storey_id, "")
        if not floor_label:
            floor_label = next((" ".join(str(prop.value).split()) for prop in element.properties
                                if prop.name == "Storey.Name" and prop.value is not None), "")
        rooms.append({"id": element.id, "name": " ".join(element.name.split()), "floor_label": floor_label})
    terms = normalized_terms([room["name"] for room in rooms] + list(floors.values()) + [room["floor_label"] for room in rooms])
    warnings = []
    if scene.source_kind == "image" or scene.derived:
        warnings.append("Drawing-derived room names may be misread. Vocabulary hints are not factual evidence.")
    if not rooms:
        warnings.append("No room names are available in this model. Add custom words if needed.")
    if len(terms) > GOOGLE_VOCABULARY_LIMIT:
        warnings.append("This building exceeds Google's 1,000-phrase vocabulary limit; live transcription cannot start with all its hints.")
    return {"terms": terms, "rooms": rooms, "warnings": warnings}


def _same_origin(connection):
    origin = connection.headers.get("origin")
    if not origin:  # Nonbrowser clients do not supply Origin.
        return True
    try:
        parsed = urlsplit(origin)
    except ValueError:
        return False
    expected_scheme = "https" if connection.url.scheme in {"https", "wss"} else "http"
    return parsed.scheme == expected_scheme and parsed.netloc == connection.headers.get("host") and not parsed.path and not parsed.query and not parsed.fragment


def _control(text):
    try:
        value = json.loads(text)
        if not isinstance(value, dict):
            raise ValueError
        return value
    except (ValueError, TypeError):
        raise VoiceError("Send a valid voice control message.", 400) from None


async def _cancel_tasks(tasks):
    for task in tasks:
        if not task.done():
            task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


def attach_voice_routes(application, transcription_factory=None, speech_factory=None):
    transcription_factory = transcription_factory or GeminiTranscriptionProvider
    speech_factory = speech_factory or ElevenLabsSpeechProvider

    @application.get("/api/voice/config")
    async def config():
        try:
            return voice_settings().public()
        except VoiceError as error:
            raise HTTPException(error.status, error.message) from None

    @application.get("/api/documents/{document_id}/voice-vocabulary")
    async def vocabulary(document_id: str):
        try:
            return document_vocabulary(application.state.documents.get(document_id))
        except DocumentError as error:
            raise HTTPException(error.status, error.message) from None

    @application.websocket("/api/voice/transcribe")
    async def transcribe(websocket: WebSocket):
        if not _same_origin(websocket):
            await websocket.close(code=1008)
            return
        await websocket.accept()
        tasks = []
        try:
            config = voice_settings()
            try:
                message = await asyncio.wait_for(websocket.receive(), config.connect_timeout)
            except TimeoutError:
                raise VoiceError("Voice setup timed out. Start recording again.") from None
            if message["type"] == "websocket.disconnect":
                return
            start = _control(message.get("text"))
            if start.get("type") == "cancel":
                return
            if start.get("type") != "start" or not isinstance(start.get("document_id"), str) or not isinstance(start.get("custom_vocabulary", []), list):
                raise VoiceError("Start voice input with a document and a list of custom vocabulary.", 400)
            document = application.state.documents.get(start["document_id"])
            terms = normalized_terms(document_vocabulary(document)["terms"] + start.get("custom_vocabulary", []))
            if len(terms) > GOOGLE_VOCABULARY_LIMIT:
                raise VoiceError("Google accepts at most 1,000 vocabulary phrases. Remove custom words or use a building with fewer room-name hints.", 400)
            session = None
            stopped = asyncio.Event()
            finished = asyncio.Event()

            async def incoming():
                nonlocal session
                while True:
                    message = await websocket.receive()
                    if message["type"] == "websocket.disconnect":
                        return
                    if message.get("bytes") is not None:
                        data = message["bytes"]
                        if session is None or stopped.is_set():
                            raise VoiceError("Audio must be sent after ready and before Stop.", 400)
                        if not data or len(data) % 2:
                            raise VoiceError("Audio must be mono signed 16-bit PCM at 16 kHz.", 400)
                        await session.send_audio(data)
                    else:
                        command = _control(message.get("text"))
                        if command.get("type") == "cancel":
                            return
                        if command.get("type") != "stop":
                            raise VoiceError("Unknown voice control message.", 400)
                        if session is None:
                            return  # Stop during connection is cancellation, no audio was accepted.
                        if not stopped.is_set():
                            stopped.set()
                            await session.end_audio()

            async def outgoing():
                nonlocal session
                async with AsyncExitStack() as stack:
                    try:
                        async with asyncio.timeout(config.connect_timeout):
                            provider = transcription_factory()
                            session = await stack.enter_async_context(provider.connect(terms, config.language_codes))
                    except TimeoutError:
                        raise VoiceError("Google transcription connection timed out. Try recording again.") from None
                    await websocket.send_json({"type": "ready"})
                    async for event in session.events():
                        if event.text:
                            await websocket.send_json({"type": "transcript", "text": event.text, "final": event.final})
                        if event.terminal and stopped.is_set():
                            finished.set()
                            await websocket.send_json({"type": "done"})
                            return
                    raise VoiceError("Google transcription ended before confirming the final transcript. Review the received text or record again.")

            async def finalization_deadline():
                await stopped.wait()
                try:
                    await asyncio.wait_for(finished.wait(), config.finalization_timeout)
                except TimeoutError:
                    raise VoiceError("The final transcript was not confirmed before the timeout. Received text may be incomplete; review it or record again.") from None
                # Let outgoing complete sending done before this watcher can win.
                await asyncio.Future()

            tasks = [asyncio.create_task(incoming()), asyncio.create_task(outgoing()), asyncio.create_task(finalization_deadline())]
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        except (VoiceError, DocumentError) as error:
            with suppress(WebSocketDisconnect, RuntimeError):
                await websocket.send_json({"type": "error", "message": error.message})
        except WebSocketDisconnect:
            pass
        except Exception:
            with suppress(WebSocketDisconnect, RuntimeError):
                await websocket.send_json({"type": "error", "message": "Live transcription failed. Check the server credentials, model access and connection. Received text may be incomplete; you can still type your question."})
        finally:
            await _cancel_tasks(tasks)
            with suppress(WebSocketDisconnect, RuntimeError):
                await websocket.close()

    @application.post("/api/voice/speech")
    async def speech(request: Request):
        if not _same_origin(request):
            raise HTTPException(403, "Use the voice controls from this application.")
        tasks = []
        provider = None
        try:
            config = voice_settings()
            try:
                body = await request.json()
            except (ValueError, UnicodeDecodeError):
                raise VoiceError("Send a valid speech request.", 400) from None
            if not isinstance(body, dict) or not isinstance(body.get("document_id"), str) or not isinstance(body.get("text"), str):
                raise VoiceError("Speech requires a document and answer text.", 400)
            application.state.documents.get(body["document_id"])
            text = body["text"]
            if not text.strip() or len(text) > SPEECH_TEXT_LIMIT:
                raise VoiceError("Spoken answers support 1–6,000 characters. Read the complete written answer instead; it has not been shortened.", 400)
            provider = speech_factory()

            async def generate():
                try:
                    async with asyncio.timeout(config.speech_timeout):
                        return await provider.synthesize(text)
                except TimeoutError:
                    raise VoiceError("Speech generation timed out. The written answer is still available.") from None

            async def disconnected():
                while True:
                    message = await request.receive()
                    if message["type"] == "http.disconnect":
                        return

            generation = asyncio.create_task(generate())
            disconnect = asyncio.create_task(disconnected())
            tasks = [generation, disconnect]
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            if generation in done:
                data = generation.result()
                if not isinstance(data, bytes) or not data:
                    raise VoiceError("Speech generation returned no playable audio. The written answer is still available.")
                return Response(data, media_type="audio/mpeg", headers={"Cache-Control": "no-store"})
            return Response(status_code=204)
        except (VoiceError, DocumentError) as error:
            raise HTTPException(error.status, error.message) from None
        except Exception:
            raise HTTPException(502, "Speech generation failed. The written answer is still available.") from None
        finally:
            await _cancel_tasks(tasks)
            if provider is not None:
                with suppress(Exception):
                    await provider.aclose()
