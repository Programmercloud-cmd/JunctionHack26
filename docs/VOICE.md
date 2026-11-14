# Voice setup and use

Set `GEMINI_API_KEY` in `.env.local` and start the app with `bash scripts/dev.sh`. The microphone needs browser permission and a secure context (localhost or HTTPS). Optional settings include `GEMINI_TRANSCRIPTION_MODEL`, `VOICE_LANGUAGE_CODES`, `VOICE_CONNECT_TIMEOUT_SECONDS` and `VOICE_FINALIZATION_TIMEOUT_SECONDS`; see `.env.example`. Configuration readiness does not verify provider access.

1. Upload or open a saved drawing or IFC. When available, names from the saved model help recognition.
2. Hold the microphone button beside the prompt. With the button focused, you can also hold Space or Enter. Wait for the listening indicator, then speak.
3. Release to finish transcription. Review or edit the text in the prompt, then send it. Dictation never sends a question automatically.

On first use, the browser may ask you to allow microphone access. After granting permission, hold the button again if the original press ended. If the connection fails or finalization times out, review any received text before sending.

The app forwards audio to Google for recognition while recording and does not persist the audio. Provider retention follows your account settings. Saved model names are recognition hints and may contain errors.

Set `ELEVENLABS_API_KEY` and `ELEVENLABS_VOICE_ID` in `.env.local` and restart the server to enable spoken answers. Open a blueprint and choose **Read answers aloud** beside the microphone before sending a question. New answers play through ElevenLabs while the toggle is on. Turn it off to stop playback. See [spoken-answer behavior](SPOKEN_ANSWERS.md) for how answers are prepared for speech.
