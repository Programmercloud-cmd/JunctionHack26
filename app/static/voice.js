"use strict";

// Voice is an input/output adapter. Only the existing Ask flow produces answers.
window.BlueprintVoice = class BlueprintVoice {
  constructor(host) {
    this.host = host;
    this.config = {};
    this.documentId = null;
    this.vocabulary = {terms: [], rooms: [], warnings: []};
    this.aliases = [];
    this.lastSubmitted = null;
    this.mic = null;
    this.micVersion = 0;
    this.speechVersion = 0;
    this.vocabularyVersion = 0;
    this.speechController = null;
    this.audio = null;
    this.audioUrl = null;
    this.mode = "idle";
    this.el = (id) => document.getElementById(id);
    this.el("voice-record").addEventListener("click", () => this.startRecording());
    this.el("voice-stop-recording").addEventListener("click", () => this.stopRecording());
    this.el("voice-cancel").addEventListener("click", () => this.cancelRecording("Recording cancelled. Review any received text."));
    this.el("voice-read").addEventListener("click", () => this.readAnswer());
    this.el("voice-stop-speech").addEventListener("click", () => this.stopSpeech());
    this.el("voice-play").addEventListener("click", () => this.playAudio(this.speechVersion));
    this.el("voice-add-alias").addEventListener("click", () => this.addAlias());
    this.el("voice-apply-aliases").addEventListener("click", () => this.previewAliases(this.el("question").value));
    this.el("voice-refresh").addEventListener("click", () => this.checkConfig());
    this.el("voice-auto-read").addEventListener("change", () => { if (!this.el("voice-auto-read").checked) this.stopSpeech(); });
    this.el("voice-technical-details").addEventListener("change", () => {
      this.stopSpeech(false);
      if (!this.recording) this.status("Reading preference updated. Press Read answer to listen.", "idle");
    });
    window.addEventListener("pagehide", () => this.cancelAll());
    this.checkConfig();
  }

  get recording() { return Boolean(this.mic); }
  status(message, mode = this.mode) {
    this.mode = mode;
    this.el("voice-status").textContent = message;
    this.el("voice-status").dataset.state = mode;
    this.host.updateControls();
  }
  error(message) {
    this.el("voice-error").textContent = message;
    this.el("voice-error").hidden = !message;
  }
  syncControls() {
    const state = this.host.state();
    const active = Boolean(state.document) && !state.busy;
    const recording = this.recording;
    this.el("voice-record").disabled = !active || recording || !this.config.transcription_ready;
    this.el("voice-stop-recording").hidden = !recording || this.mode !== "listening";
    this.el("voice-cancel").hidden = !recording;
    const speechAvailable = this.speechText(state.result) !== null;
    this.el("voice-read").disabled = !active || !speechAvailable || !this.config.speech_ready;
    this.el("voice-speech-unavailable").hidden = !state.result || speechAvailable;
    this.el("voice-technical-details").disabled = !this.config.speech_ready;
    this.el("voice-stop-speech").hidden = !this.speechController && !this.audio;
    this.el("voice-custom-terms").disabled = !active || recording;
    this.el("voice-alias-name").disabled = !active || recording;
    this.el("voice-alias-target").disabled = !active || recording || !this.vocabulary.rooms.length;
    this.el("voice-add-alias").disabled = !active || recording || !this.vocabulary.rooms.length;
    this.el("voice-apply-aliases").disabled = !active || recording || !this.aliases.length;
    this.el("voice-auto-read").disabled = !this.config.speech_ready || Boolean(state.result && !speechAvailable);
    for (const button of this.el("voice-alias-list").querySelectorAll("button")) button.disabled = recording || !active;
  }
  async checkConfig() {
    this.el("voice-refresh").disabled = true;
    try {
      this.config = await this.host.request("/api/voice/config", {}, 10000);
      const missing = [];
      if (!this.config.transcription_ready) missing.push("Live transcription needs server configuration.");
      if (!this.config.speech_ready) missing.push("Answer audio needs server configuration.");
      this.el("voice-setup").textContent = missing.length ? `${missing.join(" ")} You can still type questions.` : "Google transcription and ElevenLabs audio are configured; service access is checked when used.";
    } catch (_) {
      this.config = {};
      this.el("voice-setup").textContent = "Voice setup could not be checked. You can still type questions.";
    } finally {
      this.el("voice-refresh").disabled = false;
      this.host.updateControls();
    }
  }
  newDocument(id) {
    this.cancelAll();
    this.documentId = id;
    this.aliases = [];
    this.vocabulary = {terms: [], rooms: [], warnings: []};
    this.el("voice-custom-terms").value = "";
    this.el("voice-alias-name").value = "";
    this.el("voice-original").hidden = true;
    this.el("voice-alias-preview").hidden = true;
    this.error("");
    this.renderVocabulary();
    this.status("Ready for a spoken question.", "idle");
    this.refreshVocabulary();
  }
  async refreshVocabulary() {
    const id = this.documentId;
    const version = ++this.vocabularyVersion;
    if (!id) return;
    try {
      const result = await this.host.request(`/api/documents/${encodeURIComponent(id)}/voice-vocabulary`, {}, 10000);
      if (id !== this.documentId || version !== this.vocabularyVersion) return;
      this.vocabulary = result;
      this.renderVocabulary();
    } catch (_) {
      if (id !== this.documentId || version !== this.vocabularyVersion) return;
      this.el("voice-vocabulary-note").textContent = "Room hints could not be loaded. Custom words can still be supplied.";
    }
  }
  canonical(room) { return room.floor_label ? `${room.name} (${room.floor_label})` : room.name; }
  normalize(value) { return value.normalize("NFC").trim().replace(/\s+/gu, " ").toLocaleLowerCase(); }
  targetAvailable(room) {
    const canonical = this.normalize(this.canonical(room));
    return Boolean(room.name.trim()) && this.vocabulary.rooms.filter((item) => this.normalize(this.canonical(item)) === canonical).length === 1;
  }
  renderVocabulary() {
    const select = this.el("voice-alias-target");
    const selected = select.value;
    select.replaceChildren(new Option("Choose a room…", ""));
    for (const room of this.vocabulary.rooms) {
      const option = new Option(this.canonical(room), room.id);
      option.disabled = !this.targetAvailable(room);
      if (option.disabled) option.textContent += " · ambiguous name; type a clarification";
      select.append(option);
    }
    if ([...select.options].some((option) => option.value === selected && !option.disabled)) select.value = selected;
    this.el("voice-vocabulary-note").textContent = `${this.vocabulary.terms.length} building vocabulary hints. ${(this.vocabulary.warnings || []).join(" ")}`;
    this.el("voice-building-terms").textContent = this.vocabulary.terms.join(" · ");
    this.renderAliases();
    this.host.updateControls();
  }
  addAlias() {
    const alias = this.el("voice-alias-name").value.normalize("NFC").trim().replace(/\s+/gu, " ");
    const room = this.vocabulary.rooms.find((item) => item.id === this.el("voice-alias-target").value);
    if (!alias || !room || !this.targetAvailable(room)) { this.error("Enter an easy phrase and choose a room with an unambiguous name and floor."); return; }
    if (this.aliases.some((item) => this.normalize(item.alias) === this.normalize(alias))) { this.error("That alias already exists. Remove it before assigning it to another room."); return; }
    this.aliases.push({alias, roomId: room.id});
    this.el("voice-alias-name").value = "";
    this.error("");
    this.renderAliases();
    this.host.updateControls();
  }
  renderAliases() {
    const list = this.el("voice-alias-list");
    list.replaceChildren();
    for (const item of this.aliases) {
      const room = this.vocabulary.rooms.find((room) => room.id === item.roomId);
      const row = document.createElement("li");
      const text = document.createElement("span");
      text.textContent = `${item.alias} → ${room ? this.canonical(room) : "Room unavailable"}`;
      const remove = document.createElement("button");
      remove.type = "button"; remove.className = "text-button";
      remove.textContent = "Remove"; remove.setAttribute("aria-label", `Remove alias ${item.alias}`);
      remove.addEventListener("click", () => { this.aliases = this.aliases.filter((entry) => entry !== item); this.renderAliases(); this.host.updateControls(); });
      row.append(text, remove); list.append(row);
    }
  }
  applyAliases(text) {
    const items = this.aliases.map((item) => ({...item, room: this.vocabulary.rooms.find((room) => room.id === item.roomId)}));
    if (items.some((item) => !item.room || !this.targetAvailable(item.room))) throw new Error("An alias points to an unavailable or ambiguous room. Remove it or edit the question yourself.");
    if (!items.length) return {text, changed: false};
    items.sort((a,b) => b.alias.length - a.alias.length);
    // Protect canonical room references so previewing twice cannot expand an
    // alias embedded inside its own replacement (e.g. plant -> plant room).
    const canonical = new Set(items.map((item) => this.normalize(this.canonical(item.room))));
    const alternatives = [...items.map((item) => this.canonical(item.room)), ...items.map((item) => item.alias.normalize("NFC"))];
    alternatives.sort((a,b) => b.length - a.length);
    const escaped = alternatives.map((value) => value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
    const pattern = new RegExp(`(?<![\\p{L}\\p{N}\\p{M}_])(?:${escaped.join("|")})(?![\\p{L}\\p{N}\\p{M}_])`, "giu");
    let changed = false;
    const output = text.normalize("NFC").replace(pattern, (match) => {
      if (canonical.has(this.normalize(match))) return match;
      const item = items.find((item) => this.normalize(item.alias) === this.normalize(match));
      if (!item) return match;
      changed = true;
      return this.canonical(item.room);
    });
    return {text: output, changed};
  }
  previewAliases(text) {
    try {
      const result = this.applyAliases(text);
      this.el("question").value = result.text;
      this.el("voice-alias-preview").hidden = !result.changed;
      this.el("voice-alias-preview").textContent = result.changed ? "Room aliases were expanded in the question above. Review the room and floor before asking." : "";
      if (result.changed) this.showOriginal(text);
      if (result.text.length > 2000) this.error("The question exceeds 2,000 characters. Shorten the editable text before asking; no text was discarded.");
      this.host.updateControls();
    } catch (error) { this.error(error.message); }
  }
  showOriginal(text) {
    this.el("voice-original-text").textContent = text;
    this.el("voice-original").hidden = !text;
  }
  customTerms() {
    return [...this.el("voice-custom-terms").value.split(/\r?\n/u).map((item) => item.trim()).filter(Boolean), ...this.aliases.flatMap((item) => {
      const room = this.vocabulary.rooms.find((room) => room.id === item.roomId);
      return room ? [item.alias, room.name, this.canonical(room)] : [item.alias];
    })];
  }

  questionSubmitted(question) { this.lastSubmitted = question.trim(); }

  async startRecording() {
    if (!this.documentId || this.recording || this.host.state().busy || !this.config.transcription_ready) return;
    this.stopSpeech(false);
    this.error("");
    this.el("voice-alias-preview").hidden = true;
    const version = ++this.micVersion;
    const draft = this.el("question").value.trim();
    const mic = {version, documentId: this.documentId, base: draft === this.lastSubmitted ? "" : draft, finals: "", interim: "", completed: false};
    this.mic = mic;
    this.status("Connecting microphone and live transcription…", "connecting");
    try {
      if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia || !window.AudioWorkletNode) throw new Error("Microphone capture requires a supported browser on localhost or HTTPS. Type your question instead.");
      const context = new AudioContext();
      mic.context = context;
      await context.resume();
      if (!this.isCurrent(mic)) return;
      const stream = await navigator.mediaDevices.getUserMedia({audio: {channelCount: 1, echoCancellation: true, noiseSuppression: true}, video: false});
      if (!this.isCurrent(mic)) { stream.getTracks().forEach((track) => track.stop()); return; }
      mic.stream = stream;
      await context.audioWorklet.addModule("/static/voice-worklet.js");
      if (!this.isCurrent(mic)) return;
      const socket = new WebSocket(`${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/api/voice/transcribe`);
      mic.socket = socket;
      socket.binaryType = "arraybuffer";
      socket.onopen = () => {
        if (!this.isCurrent(mic)) { socket.close(); return; }
        socket.send(JSON.stringify({type: "start", document_id: mic.documentId, custom_vocabulary: this.customTerms()}));
      };
      socket.onmessage = (event) => {
        if (!this.isCurrent(mic)) return;
        let message;
        try { message = JSON.parse(event.data); } catch (_) { this.failRecording(mic, "The transcription service returned an unreadable message. Review the received text."); return; }
        if (message.type === "ready") this.capture(mic);
        else if (message.type === "transcript" && typeof message.text === "string") {
          if (message.final) { mic.finals += message.text; mic.interim = ""; }
          else mic.interim = message.text;
          this.renderTranscript(mic);
        } else if (message.type === "done") this.finishRecording(mic);
        else if (message.type === "error") this.failRecording(mic, typeof message.message === "string" ? message.message : "Live transcription failed. Review the received text.");
      };
      socket.onerror = () => this.failRecording(mic, "Live transcription could not connect. You can edit the question and try again.");
      socket.onclose = () => { if (this.isCurrent(mic)) this.failRecording(mic, "Transcription ended before completion. Review the received text before asking."); };
    } catch (error) {
      const message = error.name === "NotAllowedError" ? "Microphone permission was denied. Allow microphone access or type your question." : error.name === "NotFoundError" ? "No microphone was found. Type your question instead." : error.message.startsWith("Microphone capture requires") ? error.message : "The microphone could not start. Check browser permissions or type your question.";
      this.failRecording(mic, message);
    }
  }
  isCurrent(mic) { return this.mic === mic && mic.version === this.micVersion && mic.documentId === this.documentId; }
  join(a,b) { return [a.trim(),b.trim()].filter(Boolean).join(" "); }
  renderTranscript(mic, includeInterim = true) {
    const received = mic.finals + (includeInterim ? mic.interim : "");
    this.el("question").value = this.join(mic.base, received);
    this.showOriginal(received);
    this.host.updateControls();
  }
  capture(mic) {
    if (!this.isCurrent(mic) || mic.node) return;
    try {
      mic.node = new AudioWorkletNode(mic.context, "blueprint-pcm", {numberOfInputs: 1, numberOfOutputs: 1, outputChannelCount: [1]});
      mic.source = mic.context.createMediaStreamSource(mic.stream);
      mic.node.port.onmessage = ({data}) => {
        if (data.type === "flushed") { mic.flushResolve?.(); return; }
        if (data.type === "audio" && this.isCurrent(mic) && mic.socket?.readyState === WebSocket.OPEN) mic.socket.send(data.buffer);
      };
      mic.source.connect(mic.node);
      mic.node.connect(mic.context.destination); // Worklet outputs silence; microphone is never played back.
      mic.stream.getAudioTracks().forEach((track) => track.addEventListener("ended", () => { if (this.isCurrent(mic) && this.mode === "listening") this.stopRecording(); }));
      this.status("Listening… Press Stop when your question is complete.", "listening");
    } catch (_) { this.failRecording(mic, "Audio capture could not start. Type your question instead."); }
  }
  async stopRecording() {
    const mic = this.mic;
    if (!mic || this.mode !== "listening") return;
    this.status("Finalizing the transcript…", "finalizing");
    mic.source?.disconnect();
    if (mic.node) {
      await new Promise((resolve) => { mic.flushResolve = resolve; mic.node.port.postMessage({type: "flush"}); });
    }
    if (!this.isCurrent(mic)) return;
    this.releaseCapture(mic);
    if (mic.socket?.readyState === WebSocket.OPEN) mic.socket.send(JSON.stringify({type: "stop"}));
    else this.failRecording(mic, "The connection ended before the final transcript. Review the received text.");
  }
  releaseCapture(mic) {
    mic.flushResolve?.(); mic.flushResolve = null;
    mic.stream?.getTracks().forEach((track) => track.stop());
    mic.source?.disconnect(); mic.source = null;
    mic.node?.disconnect(); mic.node = null;
    if (mic.context) { mic.context.close().catch(() => {}); mic.context = null; }
  }
  releaseMic(mic, cancel = false) {
    this.releaseCapture(mic);
    if (mic.socket) {
      mic.socket.onmessage = null; mic.socket.onerror = null; mic.socket.onclose = null;
      if (mic.socket.readyState === WebSocket.OPEN && cancel) mic.socket.send(JSON.stringify({type: "cancel"}));
      if (mic.socket.readyState < WebSocket.CLOSING) mic.socket.close();
      mic.socket = null;
    }
  }
  finishRecording(mic) {
    if (!this.isCurrent(mic)) return;
    this.renderTranscript(mic, false);
    this.mic = null;
    this.releaseMic(mic);
    this.previewAliases(this.el("question").value);
    this.status("Transcript ready. Review the question, then send it.", "idle");
    this.el("question").focus();
  }
  failRecording(mic, message) {
    if (!this.isCurrent(mic)) return;
    this.renderTranscript(mic);
    this.mic = null;
    this.releaseMic(mic, true);
    this.error(`${message} Received text may be incomplete.`);
    this.status("Transcription stopped. Review or type your question.", "error");
  }
  cancelRecording(message = "Recording cancelled.") {
    const mic = this.mic;
    ++this.micVersion;
    this.mic = null;
    if (mic) { this.renderTranscript(mic); this.releaseMic(mic, true); }
    this.status(message, "idle");
  }
  cancelAll() {
    this.cancelRecording();
    this.stopSpeech(false);
  }
  speechText(result) {
    if (!result) return null;
    const field = this.el("voice-technical-details").checked ? "spoken_answer_with_details" : "spoken_answer";
    // Only genuinely older responses may use the written text. Explicit null
    // means preparation failed; never bypass that failure with raw metadata.
    const prepared = Object.hasOwn(result, "spoken_answer") || Object.hasOwn(result, "spoken_answer_with_details");
    const text = prepared ? result[field] : result.answer;
    return typeof text === "string" && text.trim() ? text : null;
  }
  answerReady() {
    this.host.updateControls();
    if (this.el("voice-auto-read").checked) this.readAnswer();
  }
  async readAnswer() {
    const state = this.host.state();
    if (!state.result?.answer || !this.documentId || !this.config.speech_ready) return;
    const answer = this.speechText(state.result);
    if (answer === null) {
      this.error("Spoken answer preparation is unavailable. The written answer and evidence remain on screen.");
      return;
    }
    this.cancelRecording();
    this.stopSpeech(false);
    this.error("");
    const version = ++this.speechVersion;
    const documentId = this.documentId;
    const controller = new AbortController();
    this.speechController = controller;
    this.status("Generating answer audio…", "synthesizing");
    try {
      const response = await fetch("/api/voice/speech", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({document_id: documentId, text: answer}), signal: controller.signal});
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(typeof body?.detail === "string" ? body.detail : "Answer audio could not be generated. The text and evidence remain available.");
      }
      const blob = await response.blob();
      if (version !== this.speechVersion || documentId !== this.documentId) return;
      if (!blob.size || !blob.type.startsWith("audio/")) throw new Error("The speech service returned no playable audio. The text remains available.");
      this.speechController = null;
      this.audioUrl = URL.createObjectURL(blob);
      this.audio = new Audio(this.audioUrl);
      this.audio.onended = () => { if (version === this.speechVersion) this.stopSpeech(); };
      this.audio.onerror = () => {
        if (version !== this.speechVersion) return;
        this.stopSpeech(false);
        this.error("The generated audio could not play. Read the answer and evidence below.");
        this.status("Audio unavailable.", "error");
      };
      await this.playAudio(version);
    } catch (error) {
      if (version !== this.speechVersion || error.name === "AbortError") return;
      this.speechController = null;
      this.error(error instanceof TypeError ? "Could not reach the speech service. The text and evidence remain available." : error.message);
      this.status("Answer audio unavailable.", "error");
    }
  }
  async playAudio(version) {
    if (!this.audio || version !== this.speechVersion) return;
    const audio = this.audio;
    try {
      await audio.play();
      if (version !== this.speechVersion) { audio.pause(); return; }
      this.el("voice-play").hidden = true;
      this.status("Reading answer…", "speaking");
    } catch (_) {
      if (version !== this.speechVersion) return;
      this.el("voice-play").hidden = false;
      this.status("Audio is ready. Press Play audio to listen.", "idle");
    }
  }
  stopSpeech(announce = true) {
    ++this.speechVersion;
    this.speechController?.abort(); this.speechController = null;
    if (this.audio) { this.audio.onended = null; this.audio.onerror = null; this.audio.pause(); this.audio.removeAttribute("src"); this.audio.load(); this.audio = null; }
    if (this.audioUrl) URL.revokeObjectURL(this.audioUrl);
    this.audioUrl = null;
    this.el("voice-play").hidden = true;
    if (announce) this.status("Answer audio stopped.", "idle");
    else this.host.updateControls();
  }
};
