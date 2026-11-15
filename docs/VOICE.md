# Voice setup and use

Set `GEMINI_API_KEY` in `.env.local` and start the app with `bash scripts/dev.sh`. The microphone needs browser permission and a secure context (localhost or HTTPS). Optional settings include `GEMINI_TRANSCRIPTION_MODEL`, `VOICE_LANGUAGE_CODES`, `VOICE_CONNECT_TIMEOUT_SECONDS` and `VOICE_FINALIZATION_TIMEOUT_SECONDS`; see `.env.example`. Configuration readiness does not verify provider access.

1. Upload or open a saved drawing or IFC. When available, names from the saved model help recognition.
2. The microphone icon starts muted. Click it to unmute and start recording. With the button focused, Space or Enter also toggles recording. Wait for the listening indicator, then speak.
3. Click the icon again to mute and finish transcription. Review or edit the text in the prompt, then send it. Dictation never sends a question automatically.

On first use, the browser may ask you to allow microphone access. Muting during startup cancels that recording; a late microphone stream is stopped. Moving focus within the page keeps recording, while hiding the page mutes it and navigating to another session cancels it. If the connection fails or finalization times out, review any received text before sending.

The app forwards audio to Google for recognition while recording and does not persist the audio. Provider retention follows your account settings. Saved model names are recognition hints and may contain errors.

Set `ELEVENLABS_API_KEY` and `ELEVENLABS_VOICE_ID` in the server environment and restart the server to enable spoken replies (`.env.local` for local development). Credentials stay server-side; the browser receives readiness only. The hackathon agentic deployment uses the user's explicitly authorized shared ElevenLabs key and existing voice. Visitors with workspace access use that configuration rather than entering personal keys. The timed access window and existing access-code policy remain authoritative.

Open any Building chat, including one without drawings, and click the **speaker icon beside the microphone** to turn on **Read answers aloud**. The toggle starts off. New normal replies, clarification questions and technical answers then play through ElevenLabs; saved history and progress messages are not replayed. Turn it off to stop playback. Starting a new request, recording, navigating Home/another chat or uploading sources cancels pending/current audio. If browser autoplay is blocked, **Play answer audio** plays the already-generated audio without another synthesis request. Voice failure leaves the written reply usable. See [spoken-answer behavior](SPOKEN_ANSWERS.md) for technical-answer presentation.
