"use strict";

// Public-demo adapter. The server remains the access-control authority. No
// provider request is intercepted or replayed, and codes are never persisted.
(() => {
  let access = null;
  let pending = false;
  const editIds = new Set(["append-sources", "attach-drawings", "workspace-attach-sources", "retry-extraction", "generate-scene", "refine-building", "reconstruct-building", "apply-assumptions"]);
  const panel = document.createElement("section");
  panel.id = "access-panel"; panel.className = "access-panel"; panel.hidden = true;
  panel.setAttribute("aria-label", "Demo access");
  panel.innerHTML = '<strong id="access-title">Public examples</strong><p id="access-description"></p><p id="access-shared"></p><form id="access-form" class="access-form"><label for="access-code">Access code<input id="access-code" type="password" autocomplete="off" spellcheck="false" autocapitalize="none"></label><button id="access-unlock" class="secondary-button" type="submit">Unlock workspace</button></form><div class="access-actions"><button id="access-lock" class="text-button" type="button" hidden>Lock workspace</button><button id="access-refresh" class="text-button" type="button">Refresh access</button></div><p id="access-message" class="access-message" role="status" hidden></p><p id="access-model-note" class="access-model-note" hidden>Cached example · read-only model. You can inspect its sources and 3D model, and ask questions after entering the code. Model edits and added sources are unavailable for this example.</p>';
  document.getElementById("home-library").append(panel);
  const element = id => document.getElementById(id);
  const locked = () => access?.public_demo && !access.can_work;
  const readOnly = () => access?.public_demo && state.document?.read_only_model;
  function message(text = "") { element("access-message").textContent = text; element("access-message").hidden = !text; }
  function restrictControls() {
    if (!access?.public_demo) return;
    if (locked()) voice?.disableSpokenAnswers();
    for (const id of ["file-input", "upload-label", "question", "ask-button", "home-upload", "voice-record", "voice-read-answers"]) {
      if (locked() && element(id) && !element(id).disabled) element(id).disabled = true;
    }
    if (locked()) {
      if (voice?.recording) voice.cancelAll();
      element("drop-zone")?.setAttribute("aria-disabled", "true");
      document.querySelectorAll("[data-question]").forEach(button => { button.disabled = true; });
      if (element("question-help")) element("question-help").textContent = "Inspect cached examples freely. Enter the access code to ask a question or upload your own sources.";
    }
    for (const id of editIds) if ((locked() || readOnly()&&(id!=="attach-drawings"||!window.chatUI?.isHome())) && element(id)) element(id).disabled = true;
    document.querySelectorAll("#assumption-rows input, #assumption-rows select, #assumption-support").forEach(input => {
      input.disabled = Boolean(locked() || readOnly());
    });
    element("access-model-note").hidden = !readOnly();

  }
  function renderAccess() {
    state.taskAccess=access;window.activeTasks?.setAccess(access||{});window.chatUI?.refreshTasks();
    panel.hidden = !access?.public_demo;
    if (!access?.public_demo) return;
    element("access-title").textContent = locked() ? "Explore the public examples" : "Workspace unlocked";
    element("access-description").textContent = locked()
      ? "Browse cached drawings, models and source evidence without a code. Uploads, questions and edits require the access code."
      : "You can upload sources and ask questions. Cached example models stay read-only. Unlocking does not retry a previous action; submit it again when ready.";
    element("access-shared").textContent = "Code holders share the same workspace, including uploaded sources and conversations. This is not a private personal workspace.";
    element("access-form").hidden = !locked();
    element("access-lock").hidden = locked();
    element("access-lock").disabled = pending;
    updateControls(); updateAssumptionButton();
  }
  async function accessRequest(path, options = {}) {
    const response = await fetch(path, {credentials: "same-origin", cache: "no-store", ...options});
    const payload = await response.json().catch(() => null);
    if (!response.ok || !payload) throw new Error(typeof payload?.detail === "string" ? payload.detail : "Access could not be checked. Refresh access and try again.");
    return payload;
  }
  async function refreshAccess() {
    try { access = await accessRequest("/api/access"); message(); renderAccess(); }
    catch { if (access?.public_demo) message("Access could not be checked. Refresh access before trying again."); }
  }
  const originalControls = updateControls;
  updateControls = function (...args) { const result = originalControls(...args); restrictControls(); return result; };
  const originalAssumptionButton = updateAssumptionButton;
  updateAssumptionButton = function (...args) { const result = originalAssumptionButton(...args); restrictControls(); return result; };
  const originalConversation = refreshConversation;
  refreshConversation = async function (...args) {
    await initialAccess;
    if (locked()) { state.conversation = []; renderConversation(); setError("conversation-error"); return; }
    return originalConversation(...args);
  };
  const originalUpload = uploadFile;
  uploadFile = async function (input, ...args) {
    await initialAccess;
    if (locked()) {
      message("Enter the access code, then upload the file from Home.");
      return;
    }
    return originalUpload(input, ...args);
  };
  function blockAction(event, editing = false) {
    if (!locked() && !(editing && readOnly())) return false;
    event.preventDefault(); event.stopImmediatePropagation();
    message(editing && readOnly() ? "This cached example model is read-only. Model edits and added sources are unavailable." : "Enter the access code, then explicitly submit your action again.");
    if (locked()) {
      if (!window.chatUI?.isHome()) document.getElementById("home-tab").click();
      element("access-code").focus();
    }
    return true;
  }
  document.addEventListener("click", event => {
    const target = event.target.closest("button, #drop-zone");
    if (!target) return;
    if (editIds.has(target.id)) blockAction(event, target.id!=="attach-drawings"||!window.chatUI?.isHome());
    else if (["home-upload","home-new-project"].includes(target.id)) blockAction(event);
  }, true);
  document.addEventListener("submit", event => { if (event.target.id === "question-form") blockAction(event); }, true);
  document.addEventListener("change", event => { if (event.target.id === "file-input") blockAction(event); }, true);
  document.addEventListener("keydown", event => { if (event.target.id === "drop-zone" && ["Enter", " "].includes(event.key)) blockAction(event); }, true);
  element("access-form").addEventListener("submit", async event => {
    event.preventDefault(); if (pending) return;
    let code = element("access-code").value; element("access-code").value = "";
    if (!code) { message("Enter the access code."); return; }
    pending = true; element("access-unlock").disabled = true; message();
    try {
      access = await accessRequest("/api/access/unlock", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({code})});
      code = ""; renderAccess();
      await Promise.allSettled([refreshSavedBuildings(), refreshConversation(), voice?.checkConfig()]);
    } catch (error) { message(error.message); }
    finally { code = ""; pending = false; element("access-unlock").disabled = false; element("access-lock").disabled = false; }
  });
  element("access-lock").addEventListener("click", async () => {
    if (pending) return; pending = true; element("access-lock").disabled = true;
    try { await accessRequest("/api/access/lock", {method: "POST"}); window.location.reload(); }
    catch (error) { message(error.message); pending = false; element("access-lock").disabled = false; }
  });
  element("access-refresh").addEventListener("click", refreshAccess);
  const initialAccess = refreshAccess();
  const controlObserver = new MutationObserver(restrictControls);
  for (const id of ["question", "ask-button"]) if (element(id)) controlObserver.observe(element(id), {attributes: true, attributeFilter: ["disabled"]});
})();
