"use strict";

// Public-demo adapter. The server remains the access-control authority. No
// provider request is intercepted or replayed, and codes are never persisted.
(() => {
  let access = null;
  let pending = false;
  const editIds = new Set(["append-sources", "retry-extraction", "generate-scene", "refine-building", "reconstruct-building", "apply-assumptions"]);
  const panel = document.createElement("section");
  panel.id = "access-panel"; panel.className = "access-panel"; panel.hidden = true;
  panel.setAttribute("aria-label", "Demo access");
  panel.innerHTML = '<strong id="access-title">Public examples</strong><p id="access-description"></p><p id="access-shared"></p><form id="access-form" class="access-form"><label for="access-code">Access code<input id="access-code" type="password" autocomplete="off" spellcheck="false" autocapitalize="none"></label><button id="access-unlock" class="secondary-button" type="submit">Unlock workspace</button></form><div class="access-actions"><button id="access-lock" class="text-button" type="button" hidden>Lock workspace</button><button id="access-refresh" class="text-button" type="button">Refresh access</button></div><p id="access-message" class="access-message" role="status" hidden></p><p id="access-model-note" class="access-model-note" hidden>Cached example · read-only model. You can inspect its sources and 3D model, and ask questions after entering the code. Model edits and added sources are unavailable for this example.</p>';
  const picker = document.createElement("div"); picker.className = "access-actions";
  picker.innerHTML = '<label for="access-example-select">Cached examples<select id="access-example-select"><option value="">Choose an example</option></select></label><button id="access-open-example" class="secondary-button" type="button" disabled>Open example</button><button id="access-upload" class="text-button" type="button" hidden>Upload your own sources</button>';
  panel.insertBefore(picker, panel.querySelector("#access-form"));
  if (document.getElementById("chat-scroll")) document.getElementById("chat-scroll").prepend(panel);
  else (document.querySelector(".saved-buildings") || document.querySelector("main")).before(panel);
  const element = id => document.getElementById(id);
  const locked = () => access?.public_demo && !access.can_work;
  const readOnly = () => access?.public_demo && state.document?.read_only_model;
  function message(text = "") { element("access-message").textContent = text; element("access-message").hidden = !text; }
  function restrictControls() {
    if (!access?.public_demo) return;
    for (const id of ["file-input", "upload-label", "question", "ask-button", "welcome-upload", "attach-drawings"]) {
      if (locked() && element(id) && !element(id).disabled) element(id).disabled = true;
    }
    if (locked()) {
      element("drop-zone")?.setAttribute("aria-disabled", "true");
      document.querySelectorAll("[data-question]").forEach(button => { button.disabled = true; });
      if (element("question-help")) element("question-help").textContent = "Inspect cached examples freely. Enter the access code to ask a question or upload your own sources.";
    }
    for (const id of editIds) if ((locked() || readOnly()) && element(id)) element(id).disabled = true;
    if (readOnly() && element("attach-drawings") && !element("attach-drawings").disabled) element("attach-drawings").disabled = true;
    document.querySelectorAll("#assumption-rows input, #assumption-rows select, #assumption-support").forEach(input => {
      input.disabled = Boolean(locked() || readOnly());
    });
    element("access-model-note").hidden = !readOnly();
    element("access-upload").hidden = locked();
    element("access-upload").disabled = Boolean(state.busy);
    element("access-open-example").disabled = Boolean(state.busy) || !element("access-example-select").value;
  }
  function renderAccess() {
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
  uploadFile = async function (input, append = false) {
    if (locked() || (append && readOnly())) {
      message(append && readOnly() ? "This example is read-only. Use Upload your own sources to start a different building." : "Enter the access code, then explicitly upload your sources again.");
      return;
    }
    return originalUpload(input, append);
  };
  function blockAction(event, editing = false) {
    if (!locked() && !(editing && readOnly())) return false;
    event.preventDefault(); event.stopImmediatePropagation();
    message(editing && readOnly() ? "This cached example model is read-only. Model edits and added sources are unavailable." : "Enter the access code, then explicitly submit your action again.");
    if (locked()) element("access-code").focus();
    return true;
  }
  document.addEventListener("click", event => {
    const target = event.target.closest("button, #drop-zone");
    if (!target) return;
    if (editIds.has(target.id)) blockAction(event, true);
    else if (["upload-label", "drop-zone", "welcome-upload", "attach-drawings"].includes(target.id)) blockAction(event, target.id === "attach-drawings" && Boolean(state.document));
  }, true);
  document.addEventListener("submit", event => { if (event.target.id === "question-form") blockAction(event); }, true);
  document.addEventListener("change", event => { if (event.target.id === "file-input") blockAction(event, state.uploadMode === "append"); }, true);
  document.addEventListener("drop", event => { if (event.target.closest(".source-panel, #chat-shell")) blockAction(event, Boolean(state.document)); }, true);
  document.addEventListener("keydown", event => { if (event.target.id === "drop-zone" && ["Enter", " "].includes(event.key)) blockAction(event); }, true);
  element("access-form").addEventListener("submit", async event => {
    event.preventDefault(); if (pending) return;
    let code = element("access-code").value; element("access-code").value = "";
    if (!code) { message("Enter the access code."); return; }
    pending = true; element("access-unlock").disabled = true; message();
    try {
      access = await accessRequest("/api/access/unlock", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({code})});
      code = ""; renderAccess();
      await Promise.allSettled([refreshSavedBuildings(), refreshConversation()]);
    } catch (error) { message(error.message); }
    finally { code = ""; pending = false; element("access-unlock").disabled = false; element("access-lock").disabled = false; }
  });
  element("access-lock").addEventListener("click", async () => {
    if (pending) return; pending = true; element("access-lock").disabled = true;
    try { await accessRequest("/api/access/lock", {method: "POST"}); window.location.reload(); }
    catch (error) { message(error.message); pending = false; element("access-lock").disabled = false; }
  });
  element("access-refresh").addEventListener("click", refreshAccess);
  element("access-example-select").addEventListener("change", restrictControls);
  element("access-open-example").addEventListener("click", () => openBuilding(element("access-example-select").value));
  element("access-upload").addEventListener("click", () => { if (!locked() && !state.busy) { state.uploadMode = "new"; element("file-input").click(); } });
  const initialAccess = refreshAccess();
  // The core's initial list request may already be in flight when this adapter
  // loads. Relabel its options without starting another request.
  const listObserver = new MutationObserver(() => {
    for (const option of element("saved-building-select").options) {
      const building = state.savedBuildings.find(item => (item.building_id || item.document_id) === option.value);
      const label = building?.example_title ? `${building.example_title} · cached example` : null;
      if (label && option.textContent !== label) option.textContent = label;
    }
    const select = element("access-example-select"), examples = state.savedBuildings.filter(item => item.public_example);
    const signature = JSON.stringify(examples.map(item => [item.building_id || item.document_id, item.example_title || item.filename]));
    if (select.dataset.examples !== signature) {
      const selected = select.value; select.replaceChildren(new Option("Choose an example", ""));
      for (const example of examples) select.append(new Option(example.example_title || example.filename, example.building_id || example.document_id));
      select.value = selected; select.dataset.examples = signature; restrictControls();
    }
  });
  listObserver.observe(element("saved-building-select"), {childList: true, subtree: true});
  // The chat controller also refreshes its composer directly after local actions.
  // Reapply only access restrictions when those three controls are re-enabled.
  const controlObserver = new MutationObserver(restrictControls);
  for (const id of ["question", "ask-button", "attach-drawings"]) if (element(id)) controlObserver.observe(element(id), {attributes: true, attributeFilter: ["disabled"]});
})();
