"use strict";

// Voice only fills the editable question. Sending it uses the usual composer.
window.BlueprintVoice = class BlueprintVoice {
  constructor(host) {
    this.host = host;
    this.documentId = null;
    this.mic = null;
    this.hold = null;
    this.mode = "idle";
    this.ready = false;
    this.configVersion = 0;
    this.speechReady = false;
    this.speechEnabled = false;
    this.speech = null;
    this.speechToggle = document.getElementById("voice-read-answers");
    this.speechFeedback = document.getElementById("voice-speech-status");
    this.speechErrorMessage = document.getElementById("voice-speech-error");
    this.playAnswer = document.getElementById("voice-play-answer");
    this.speechToggle.addEventListener("click", () => {
      this.speechEnabled = !this.speechEnabled;
      if (!this.speechEnabled) this.stopSpeech();
      this.syncSpeechToggle();
    });
    this.playAnswer.addEventListener("click", () => this.playSpeech(this.speech));
    this.button = document.getElementById("voice-record");
    this.label = document.getElementById("voice-label");
    this.question = document.getElementById("question");
    this.feedback = document.getElementById("voice-status");
    this.errorMessage = document.getElementById("voice-error");

    this.button.addEventListener("pointerdown", (event) => {
      if (event.button !== 0 || !event.isPrimary || !this.canStart()) return;
      event.preventDefault();
      this.button.focus();
      this.button.setPointerCapture(event.pointerId);
      this.hold = {pointer: event.pointerId};
      this.startRecording();
    });
    for (const type of ["pointerup", "pointercancel", "lostpointercapture"]) {
      this.button.addEventListener(type, (event) => {
        if (this.hold?.pointer === event.pointerId) this.releaseHold();
      });
    }

    this.button.addEventListener("keydown", (event) => {
      if (event.key !== " " && event.key !== "Enter") return;
      event.preventDefault();
      if (event.repeat || !this.canStart()) return;
      this.hold = {key: event.key};
      this.startRecording();
    });
    window.addEventListener("keyup", (event) => {
      if (this.hold?.key !== event.key) return;
      event.preventDefault();
      this.releaseHold();
    });
    this.button.addEventListener("contextmenu", (event) => event.preventDefault());
    this.button.addEventListener("blur", () => this.releaseHold());
    window.addEventListener("blur", () => this.releaseHold());
    window.addEventListener("pagehide", () => this.cancelAll());
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) this.releaseHold();
    });

    this.checkConfig();
  }

  get recording() { return Boolean(this.mic); }

  canStart() {
    return !this.button.disabled && !this.mic && !this.hold && !document.hidden;
  }

  releaseHold() {
    if (!this.hold) return;
    this.hold = null;
    if (this.mode === "connecting") {
      this.cancelAll("Hold the button until the microphone is listening.");
    } else if (this.mode === "listening") {
      this.stopRecording();
    }
  }

  status(message, mode = "idle") {
    this.mode = mode;
    this.feedback.textContent = message;
    this.feedback.dataset.state = mode;
    this.button.dataset.state = mode;
    const label = {connecting: "Starting…", listening: "Listening…", finalizing: "Finishing…"};
    this.label.textContent = label[mode] || "Hold to talk";
    this.host.updateControls();
  }

  error(message) {
    this.errorMessage.textContent = message;
    this.errorMessage.hidden = !message;
  }

  syncControls() {
    const state = this.host.state();
    const chatAvailable = window.chatUI?.chatAvailable() ?? Boolean(this.documentId);
    this.button.disabled = !chatAvailable || Boolean(state.busy) || !this.ready;
    this.button.setAttribute("aria-disabled", String(this.button.disabled || this.mode === "finalizing"));
    this.button.title = this.ready
      ? this.documentId ? "Hold to talk" : "Open a blueprint to use voice"
      : "Voice transcription is unavailable";
    this.question.readOnly = this.recording;
    this.syncSpeechToggle();
  }

  syncSpeechToggle() {
    const unavailable = !this.speechReady || !(window.chatUI?.chatAvailable() ?? Boolean(this.documentId));
    this.speechToggle.disabled = unavailable || Boolean(this.host.state().busy);
    this.speechToggle.setAttribute("aria-pressed", String(this.speechEnabled));
    this.speechToggle.title = this.speechReady
      ? this.documentId ? `Read answers aloud: ${this.speechEnabled ? "on" : "off"}` : "Open a blueprint to enable spoken answers"
      : "Spoken answers are unavailable. Check the server’s ElevenLabs API key and voice ID.";
  }

  async checkConfig() {
    const version = ++this.configVersion;
    const config = await this.host.request("/api/voice/config", {}, 10000).catch(() => null);
    if (this.configVersion !== version) return;
    this.ready = Boolean(config?.transcription_ready);
    this.speechReady = Boolean(config?.speech_ready);
    if (!this.speechReady) {
      this.speechEnabled = false;
      this.stopSpeech();
    }
    this.host.updateControls();
  }

  newDocument(id) {
    this.cancelAll();
    this.documentId = id;
    this.error("");
    this.status("");
  }

  async startRecording() {
    this.stopSpeech();
    this.error("");
    const mic = {documentId: this.documentId, base: this.question.value, finals: "", interim: ""};
    this.mic = mic;
    this.status("Starting the microphone…", "connecting");
    try {
      if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia || !window.AudioWorkletNode) {
        this.failRecording(mic, "Voice needs a supported browser on localhost or HTTPS.");
        return;
      }
      const context = new AudioContext();
      mic.context = context;
      await context.resume();
      if (this.mic !== mic) return;
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {channelCount: 1, echoCancellation: true, noiseSuppression: true},
        video: false,
      });
      if (this.mic !== mic) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      mic.stream = stream;
      await context.audioWorklet.addModule("/static/voice-worklet.js");
      if (this.mic !== mic) return;

      const scheme = location.protocol === "https:" ? "wss:" : "ws:";
      const socket = new WebSocket(`${scheme}//${location.host}/api/voice/transcribe`);
      mic.socket = socket;
      socket.onopen = () => {
        if (this.mic !== mic) { socket.close(); return; }
        socket.send(JSON.stringify({type: "start", document_id: mic.documentId}));
      };
      socket.onmessage = (event) => {
        if (this.mic !== mic) return;
        let message;
        try { message = JSON.parse(event.data); } catch (_) {
          this.failRecording(mic, "Transcription returned an unreadable message.");
          return;
        }
        if (message.type === "ready") this.capture(mic);
        else if (message.type === "transcript" && typeof message.text === "string") {
          if (message.final) {
            mic.finals += message.text;
            mic.interim = "";
          } else {
            mic.interim = message.text;
          }
          this.renderTranscript(mic);
        } else if (message.type === "done") {
          this.finishRecording(mic);
        } else if (message.type === "error") {
          this.failRecording(mic, message.message || "Live transcription failed.");
        }
      };
      socket.onerror = () => this.failRecording(mic, "Could not connect to live transcription.");
      socket.onclose = () => this.failRecording(mic, "The connection closed before transcription finished.");
    } catch (error) {
      const messages = {
        NotAllowedError: "Microphone permission was denied. Allow access or type your question.",
        NotFoundError: "No microphone was found. You can still type your question.",
      };
      this.failRecording(mic, messages[error.name] || "The microphone could not start. Check browser permissions.");
    }
  }

  renderTranscript(mic) {
    const received = (mic.finals + mic.interim).trim();
    this.question.value = received ? [mic.base.trimEnd(), received].filter(Boolean).join(" ") : mic.base;
    this.host.updateControls();
  }

  capture(mic) {
    if (this.mic !== mic || !this.hold || mic.node) return;
    try {
      mic.node = new AudioWorkletNode(mic.context, "blueprint-pcm", {
        numberOfInputs: 1,
        numberOfOutputs: 1,
        outputChannelCount: [1],
      });
      mic.source = mic.context.createMediaStreamSource(mic.stream);
      mic.node.port.onmessage = ({data}) => {
        if (data.type === "flushed") mic.flushResolve?.();
        if (data.type === "audio" && this.mic === mic && mic.socket.readyState === WebSocket.OPEN) {
          mic.socket.send(data.buffer);
        }
      };
      mic.source.connect(mic.node);
      mic.node.connect(mic.context.destination); // The worklet outputs silence.
      mic.stream.getAudioTracks().forEach((track) => track.addEventListener("ended", () => {
        if (this.mic === mic && this.mode === "listening") this.releaseHold();
      }));
      this.status("Listening. Release to finish.", "listening");
    } catch (_) {
      this.failRecording(mic, "Audio capture could not start. You can still type your question.");
    }
  }

  async stopRecording() {
    const mic = this.mic;
    this.status("Finalizing the transcript…", "finalizing");
    this.stopCapture(mic);
    let flushTimer;
    // Flush frames already captured before release. The microphone has stopped
    // even if the worklet takes too long to respond.
    await new Promise((resolve) => {
      mic.flushResolve = resolve;
      flushTimer = setTimeout(resolve, 250);
      mic.node.port.postMessage({type: "flush"});
    });
    clearTimeout(flushTimer);
    if (this.mic !== mic) return;
    this.releaseCapture(mic);
    if (mic.socket.readyState === WebSocket.OPEN) {
      mic.socket.send(JSON.stringify({type: "stop"}));
    } else {
      this.failRecording(mic, "The connection closed before transcription finished.");
    }
  }

  stopCapture(mic) {
    mic.source?.disconnect();
    mic.source = null;
    mic.stream?.getTracks().forEach((track) => track.stop());
    mic.stream = null;
  }

  releaseCapture(mic) {
    this.stopCapture(mic);
    mic.flushResolve?.();
    mic.flushResolve = null;
    if (mic.node) {
      mic.node.port.onmessage = null;
      mic.node.disconnect();
      mic.node = null;
    }
    if (mic.context) {
      mic.context.close().catch(() => {});
      mic.context = null;
    }
  }

  releaseMic(mic, cancel = false) {
    this.mic = null;
    this.hold = null;
    this.releaseCapture(mic);
    if (!mic.socket) return;
    const socket = mic.socket;
    socket.onopen = null;
    socket.onmessage = null;
    socket.onerror = null;
    socket.onclose = null;
    if (cancel && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({type: "cancel"}));
    }
    if (socket.readyState < WebSocket.CLOSING) socket.close();
  }

  finishRecording(mic) {
    this.releaseMic(mic);
    this.renderTranscript(mic);
    if (this.question.value.length > this.question.maxLength) {
      this.error("Shorten the transcript before sending it.");
    }
    this.status("Transcript ready. Edit it in the prompt before sending.");
  }

  failRecording(mic, message) {
    if (this.mic !== mic) return;
    this.releaseMic(mic, true);
    this.renderTranscript(mic);
    this.error(message);
    this.status("Transcription stopped.", "error");
  }

  cancelAll(message = "") {
    this.stopSpeech();
    const mic = this.mic;
    if (!mic) return;
    this.releaseMic(mic, true);
    this.renderTranscript(mic);
    this.status(message);
  }

  speechError(message) {
    this.speechErrorMessage.textContent = message;
    this.speechErrorMessage.hidden = !message;
  }

  async answerReady(answer) {
    if (!this.speechReady || !this.speechEnabled || !this.documentId || this.recording || this.host.state().busy === "upload" || window.chatUI?.isHome()) return;
    this.stopSpeech();
    // An explicit null records a preparation failure. Only legacy responses
    // without either speech field can fall back to the written answer.
    const hasPreparedText = Object.hasOwn(answer, "spoken_answer") || Object.hasOwn(answer, "spoken_answer_with_details");
    const spoken = hasPreparedText ? answer.spoken_answer : answer.answer;
    if (typeof spoken !== "string" || !spoken.trim()) {
      this.speechError("Audio is unavailable for this answer.");
      return;
    }
    const speech = {controller: new AbortController(), audio: null, url: null};
    this.speech = speech;
    this.speechFeedback.textContent = "Preparing answer audio.";
    try {
      const response = await fetch("/api/voice/speech", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({document_id: this.documentId, text: spoken}),
        signal: speech.controller.signal,
      });
      if (!response.ok) {
        const error = await response.json().catch(() => null);
        throw new Error(typeof error?.detail === "string" ? error.detail : "Could not prepare answer audio.");
      }
      const blob = await response.blob();
      if (this.speech !== speech) return;
      if (!blob.size || !blob.type.startsWith("audio/")) throw new Error("Could not prepare playable answer audio.");
      speech.url = URL.createObjectURL(blob);
      speech.audio = new Audio(speech.url);
      speech.audio.onended = () => { if (this.speech === speech) this.stopSpeech(); };
      speech.audio.onerror = () => this.failSpeech(speech, "The answer audio could not play.");
      await this.playSpeech(speech);
    } catch (error) {
      this.failSpeech(speech, error instanceof TypeError ? "Could not reach the speech service." : error.message);
    }
  }

  async playSpeech(speech) {
    if (!speech?.audio || this.speech !== speech) return;
    this.playAnswer.hidden = true;
    try {
      await speech.audio.play();
      if (this.speech === speech) this.speechFeedback.textContent = "Reading the answer aloud.";
    } catch (error) {
      if (this.speech !== speech) return;
      if (error.name !== "NotAllowedError") {
        this.failSpeech(speech, "The answer audio could not play.");
        return;
      }
      this.playAnswer.hidden = false;
      this.speechFeedback.textContent = "Answer audio is ready. Press Play answer audio.";
    }
  }

  failSpeech(speech, message) {
    if (this.speech !== speech) return;
    this.stopSpeech();
    this.speechError(message);
  }

  disableSpokenAnswers() {
    if (!this.speechEnabled && !this.speech) return;
    this.speechEnabled = false;
    this.stopSpeech();
    this.syncSpeechToggle();
  }

  stopSpeech() {
    const speech = this.speech;
    this.speech = null;
    speech?.controller.abort();
    if (speech?.audio) {
      speech.audio.onended = null;
      speech.audio.onerror = null;
      speech.audio.pause();
      speech.audio.removeAttribute("src");
      speech.audio.load();
    }
    if (speech?.url) URL.revokeObjectURL(speech.url);
    this.speechFeedback.textContent = "";
    this.speechError("");
    this.playAnswer.hidden = true;
  }
};
