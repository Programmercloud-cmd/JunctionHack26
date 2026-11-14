"use strict";

const $ = (id) => document.getElementById(id);
const state = { document: null, pageIndex: 0, selectedEvidence: null, sourceSelection: null, result: null, busy: null, providerReady: false, health: null, requestVersion: 0, scene: null, viewer: null, selectedElement: null, view: "drawing" };
let voice = null;
const suggestions = Array.from(document.querySelectorAll("[data-question]"));

function announce(message) { $("announcer").textContent = message; }
function setError(id, message = "") { $(id).textContent = message; $(id).hidden = !message; }
function updateControls() {
  const busy = Boolean(state.busy);
  $("file-input").disabled = busy;
  $("upload-label").disabled = busy;
  $("upload-label").classList.toggle("is-disabled", busy);
  $("drop-zone").setAttribute("aria-disabled", String(busy));
  $("question").disabled = !state.document || busy || Boolean(voice?.recording);
  suggestions.forEach((button) => { button.disabled = !state.document || busy || Boolean(voice?.recording); });
  $("ask-button").disabled = !state.document || !state.providerReady || busy || Boolean(voice?.recording) || !$("question").value.trim() || $("question").value.length > 2000;
  $("ask-label").textContent = state.busy === "ask" ? "Inspecting drawing…" : "Ask the drawing";
  $("upload-progress").hidden = state.busy !== "upload";
  $("ask-progress").hidden = state.busy !== "ask";
  $("question-help").textContent = !state.document ? "Upload a drawing to get started." : !state.providerReady ? `You can preview the drawing. Configure ${state.health?.provider_label || "the selected provider"} to ask questions.` : "Answers are limited to the supplied drawing.";
  $("previous-page").disabled = !state.document || state.pageIndex === 0;
  $("next-page").disabled = !state.document || state.pageIndex >= state.document.pages.length - 1;
  $("character-count").textContent = `${$("question").value.length} / 2000`;
  $("question-form").setAttribute("aria-busy", String(state.busy === "ask"));
  $("source-heading").closest("section").setAttribute("aria-busy", String(state.busy === "upload"));
  $("generate-scene").hidden = !state.document || state.document.kind === "ifc" || Boolean(state.scene);
  $("generate-scene").disabled = busy || !state.providerReady;
  $("show-model").disabled = !state.scene;
  $("show-drawing").hidden = state.document?.kind === "ifc";
  $("scene-progress").hidden = state.busy !== "scene";
  voice?.syncControls();
}

async function request(path, options = {}, timeout = 180000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const response = await fetch(path, { ...options, signal: controller.signal });
    const data = await response.json().catch(() => null);
    if (!response.ok) {
      let message = "The request could not be completed. Please try again.";
      if (typeof data?.detail === "string") message = data.detail;
      else if (Array.isArray(data?.detail)) message = data.detail.map((item) => item.msg || "Invalid input").join(". ");
      throw new Error(message);
    }
    if (!data) throw new Error("The server returned an unreadable response. Please try again.");
    return data;
  } catch (error) {
    if (error.name === "AbortError") throw new Error("The request timed out. No answer was confirmed. Please try again.");
    if (error instanceof TypeError) throw new Error("Could not reach the local server. Check that it is running and try again.");
    throw error;
  } finally { clearTimeout(timer); }
}

async function checkHealth() {
  $("refresh-health").disabled = true;
  try {
    const health = await request("/api/health", {}, 10000);
    state.health = health;
    state.providerReady = health.provider_ready === true;
    const providerLabel = health.provider_label || "Gemini";
    $("connection-label").textContent = state.providerReady ? `${providerLabel} configured` : "Setup needed";
    $("provider-mode").hidden = health.provider !== "openai";
    $("provider-mode").textContent = "OpenAI development pipeline · structured evidence check. Final demo uses Gemini.";
    $("provider-banner").hidden = state.providerReady;
    if (!state.providerReady) {
      $("provider-title").textContent = `${providerLabel} is not configured yet`;
      $("provider-message").textContent = `Upload and preview drawings now. To enable answers, set ${health.credential_env || "GEMINI_API_KEY"} in the server’s .env.local file and restart the server. Keep the key out of the browser.`;
    }
    if (health.limits) $("upload-limits").textContent = `JPG, PNG, PDF · ${health.limits.max_upload_mb} MB / ${health.limits.max_pages} pages · IFC · ${health.limits.max_ifc_mb || 25} MB`;
  } catch (error) {
    state.providerReady = false;
    $("connection-label").textContent = "Server unavailable";
    $("provider-banner").hidden = false;
    $("provider-title").textContent = "Could not check the application setup";
    $("provider-message").textContent = error.message;
  } finally {
    $("refresh-health").disabled = false;
    updateControls();
  }
}

function resetAnswer() {
  voice?.stopSpeech(false);
  state.result = null;
  state.selectedEvidence = null;
  state.sourceSelection = null;
  if (state.viewer) state.viewer.setHighlights([], $("highlight-answer").checked);
  $("result").hidden = true;
  $("answer-empty").hidden = false;
  $("evidence-overlay").hidden = true;
  setError("ask-error");
}

async function uploadFile(file) {
  if (!file || state.busy) return;
  setError("upload-error");
  const isIfc = /\.ifc$/i.test(file.name);
  const maxMB = isIfc ? (state.health?.limits?.max_ifc_mb || 25) : (state.health?.limits?.max_upload_mb || 10);
  if (file.size > maxMB * 1024 * 1024) { setError("upload-error", `This file is too large. Choose a file up to ${maxMB} MB.`); return; }
  if (!/\.(jpe?g|png|pdf|ifc)$/i.test(file.name)) { setError("upload-error", "Choose a JPG, PNG, PDF floor plan, or IFC model."); return; }
  voice?.cancelAll();
  state.busy = "upload";
  const version = ++state.requestVersion;
  updateControls();
  const form = new FormData();
  form.append("file", file);
  try {
    const result = await request("/api/documents", { method: "POST", body: form }, isIfc ? 180000 : 60000);
    if (version !== state.requestVersion) return;
    if (!result.document_id || !Array.isArray(result.pages) || (result.kind !== "ifc" && !result.pages.length)) throw new Error("The server did not return a usable source document.");
    clearScene();
    state.document = result;
    voice?.newDocument(result.document_id);
    state.pageIndex = 0;
    resetAnswer();
    $("filename").textContent = result.filename || file.name;
    $("filename").title = result.filename || file.name;
    $("page-count").textContent = result.kind === "ifc" ? "IFC model" : `${result.pages.length} ${result.pages.length === 1 ? "page" : "pages"}`;
    $("document-warnings").textContent = Array.isArray(result.warnings) ? result.warnings.join(" ") : "";
    $("document-warnings").hidden = !$("document-warnings").textContent;
    $("drop-zone").hidden = true;
    $("document-view").hidden = false;
    $("upload-label").textContent = "Replace file";
    $("zoom").value = "100";
    $("image-stage").style.width = "100%";
    if (result.kind === "ifc") {
      setView("model");
      await loadScene(await request(result.scene_url || `/api/documents/${result.document_id}/scene`));
      suggestions[0].dataset.question = "How many windows are in this IFC model?";
      suggestions[0].textContent = "Count windows";
      suggestions[1].dataset.question = "How many rooms are in this IFC model?";
      suggestions[1].textContent = "Count rooms";
    } else {
      setView("drawing");
      renderPage();
      suggestions[0].dataset.question = "How many bedrooms are shown on this floor plan?";
      suggestions[0].textContent = "Count bedrooms";
      suggestions[1].dataset.question = "What is the floor area of the largest room?";
      suggestions[1].textContent = "Measure a room";
      if (result.scene_url) await loadScene(await request(result.scene_url));
    }
    announce(`Uploaded ${result.filename || file.name}. Source ready.`);
  } catch (error) { setError("upload-error", error.message); }
  finally {
    state.busy = null;
    $("file-input").value = "";
    updateControls();
  }
}

function renderPage() {
  if (!state.document?.pages.length) return;
  const page = state.document.pages[state.pageIndex];
  $("page-label").textContent = `Page ${page.page} of ${state.document.pages.length}`;
  $("page-image").alt = `${state.document.filename}, page ${page.page}`;
  // Only load normalized page previews from this application.
  const url = new URL(page.image_url, window.location.origin);
  if (url.origin !== window.location.origin) { setError("upload-error", "The page preview URL is invalid."); return; }
  $("page-image").width = page.width;
  $("page-image").height = page.height;
  $("page-image").src = url.href;
  $("viewer").scrollTo(0, 0);
  renderOverlay();
  updateControls();
}

function renderOverlay() {
  const evidence = state.sourceSelection || (state.selectedEvidence === null ? null : state.result?.evidence?.[state.selectedEvidence]);
  const page = state.document?.pages[state.pageIndex];
  const overlay = $("evidence-overlay");
  overlay.hidden = true;
  $("viewer-caption").textContent = "Select an evidence reference to locate it on the drawing.";
  if (!evidence || evidence.page !== page?.page || !Array.isArray(evidence.bbox) || !$("page-image").complete || !$("page-image").naturalWidth) return;
  const [left, top, right, bottom] = evidence.bbox;
  if (![left, top, right, bottom].every(Number.isFinite) || left < 0 || top < 0 || right > 1 || bottom > 1 || left >= right || top >= bottom) return;
  overlay.style.left = `${left * 100}%`;
  overlay.style.top = `${top * 100}%`;
  overlay.style.width = `${(right - left) * 100}%`;
  overlay.style.height = `${(bottom - top) * 100}%`;
  $("overlay-number").textContent = state.sourceSelection ? "Source" : String(state.selectedEvidence + 1);
  overlay.hidden = false;
  $("viewer-caption").textContent = `${state.sourceSelection ? "Model source region" : `Reference ${state.selectedEvidence + 1}`} · Page ${evidence.page} · ${evidence.label}`;
  $("viewer").scrollTo({ left: Math.max(0, overlay.offsetLeft + overlay.offsetWidth / 2 - $("viewer").clientWidth / 2), top: Math.max(0, overlay.offsetTop + overlay.offsetHeight / 2 - $("viewer").clientHeight / 2), behavior: "instant" });
}

function selectEvidence(index) {
  const evidence = state.result?.evidence?.[index];
  if (!evidence || !state.document) return;
  const pageIndex = state.document.pages.findIndex((page) => page.page === evidence.page);
  if (pageIndex === -1) return;
  state.selectedEvidence = index;
  state.sourceSelection = null;
  state.pageIndex = pageIndex;
  revealEvidenceFloor(evidence);
  setView("drawing");
  document.querySelectorAll(".evidence-item").forEach((button, i) => button.setAttribute("aria-pressed", String(i === index)));
  renderPage();
  $("viewer").focus({ preventScroll: true });
  $("viewer").scrollIntoView({ behavior: "smooth", block: "nearest" });
  announce(`Showing evidence ${index + 1}, ${evidence.label}, on page ${evidence.page}.`);
}

function addDetail(label, value) {
  const term = document.createElement("dt");
  const description = document.createElement("dd");
  term.textContent = label;
  description.textContent = value;
  $("run-details-list").append(term, description);
}

function renderResult(result) {
  state.result = result;
  state.selectedEvidence = null;
  state.sourceSelection = null;
  $("answer-empty").hidden = true;
  $("result").hidden = false;
  const labels = { answered: "Supported by the inspected source", insufficient: "Missing information", unclear: "Unable to resolve confidently" };
  const headings = { answered: "Answer", insufficient: "The supplied drawing is not enough", unclear: "This needs a closer look" };
  $("result-status").textContent = labels[result.status] || "Inspection result";
  $("result-status").className = `result-status ${["answered", "insufficient", "unclear"].includes(result.status) ? result.status : "unclear"}`;
  $("result-heading").textContent = headings[result.status] || "Inspection result";
  const pages = Array.isArray(result.inspected_pages) ? result.inspected_pages : [];
  $("result-scope").textContent = state.document?.kind === "ifc" ? "Supplied IFC source records" : `Inspected ${pages.length === 1 ? "page" : "pages"} ${pages.join(", ") || "not reported"}`;
  $("answer-text").textContent = result.answer || "No answer was returned.";
  $("evidence-list").replaceChildren();
  const evidence = Array.isArray(result.evidence) ? result.evidence : [];
  $("evidence-section").hidden = evidence.length === 0;
  evidence.forEach((item, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "evidence-item";
    button.setAttribute("aria-pressed", "false");
    button.setAttribute("aria-label", `Show evidence ${index + 1}: ${item.label}, page ${item.page}`);
    const number = document.createElement("span");
    number.className = "evidence-number";
    number.textContent = String(index + 1);
    const copy = document.createElement("span");
    copy.className = "evidence-copy";
    const label = document.createElement("strong");
    label.textContent = item.label;
    const observation = document.createElement("p");
    observation.textContent = item.observation;
    copy.append(label, observation);
    const page = document.createElement("span");
    page.className = "evidence-page";
    page.textContent = `p. ${item.page} ↗`;
    button.append(number, copy, page);
    button.addEventListener("click", () => selectEvidence(index));
    $("evidence-list").append(button);
  });
  renderModelEvidence(result.model_evidence || []);
  updateHighlights();
  $("missing-list").replaceChildren();
  const missing = Array.isArray(result.missing_information) ? result.missing_information : [];
  $("missing-section").hidden = missing.length === 0;
  missing.forEach((text) => { const item = document.createElement("li"); item.textContent = text; $("missing-list").append(item); });
  $("next-section").hidden = !result.next_action;
  $("next-text").textContent = result.next_action || "";
  $("proposal-section").hidden = !result.proposal;
  $("proposal-text").textContent = result.proposal?.text || "";
  $("proposal-basis").textContent = result.proposal?.basis === "reference" ? `Reference: ${result.proposal.reference || "not supplied"}. This does not establish a fact about your building.` : "Basis: explicit assumption. Confirm against building documentation before using it.";
  $("run-details-list").replaceChildren();
  addDetail("Source support decision", result.gate?.decision || "Not reported");
  addDetail("Provider", state.health?.provider_label || "Gemini");
  addDetail("Evidence check", state.health?.gate_kind === "structured_classification" ? "Structured classification (no confidence score)" : "Gemini Decisions");
  addDetail("Inspection passes", String(result.inspection_passes || 1));
  if (state.health?.model) addDetail("Answer model", state.health.model);
  if (Number.isFinite(result.usage?.latency_ms)) addDetail("Time", `${(result.usage.latency_ms / 1000).toFixed(1)} s`);
  if (Number.isFinite(result.usage?.input_tokens)) addDetail("Input tokens", result.usage.input_tokens.toLocaleString());
  if (Number.isFinite(result.usage?.output_tokens)) addDetail("Output tokens", result.usage.output_tokens.toLocaleString());
  renderOverlay();
  announce(`${labels[result.status] || "Inspection complete"}. ${result.answer || ""}`);
}

function clearScene() {
  state.viewer?.dispose();
  state.viewer = null;
  window.blueprintViewer = null;
  state.scene = null;
  state.selectedElement = null;
  $("model-canvas-container").replaceChildren();
  $("element-inspector").hidden = true;
  $("element-select").replaceChildren(new Option("Choose an element…", ""));
  $("scene-summary").textContent = "";
  $("scene-badge").textContent = "";
  $("highlight-note").hidden = true;
  $("scene-warnings").hidden = true;
  $("floor-select").replaceChildren(new Option("All floors", ""));
  $("floor-controls").hidden = true;
  $("floor-source-links").replaceChildren();
  $("floor-source-links").hidden = true;
  $("floor-details").hidden = true;
  $("floor-details").open = false;
  $("explode-floors").checked = false;
  $("explode-control").hidden = true;
  $("layout-note").hidden = true;
  $("download-ifc").hidden = true;
  $("download-ifc").removeAttribute("href");
  setError("scene-error");
}

function setView(view) {
  state.view = view;
  $("drawing-pane").hidden = view !== "drawing";
  $("model-pane").hidden = view !== "model";
  $("show-model").setAttribute("aria-pressed", String(view === "model"));
  $("show-drawing").setAttribute("aria-pressed", String(view === "drawing"));
  if (view === "model") requestAnimationFrame(() => state.viewer?.resize());
}

async function loadScene(scene) {
  if (state.scene?.document_id === scene.document_id) return;
  if (scene.document_id !== state.document?.document_id) return;
  state.scene = scene;
  voice?.refreshVocabulary();
  const unscaled = scene.units !== "m" || (scene.floors || []).some((floor) => floor.scale_status !== "known");
  $("scene-badge").textContent = unscaled ? "Approximate · unscaled" : scene.derived ? "Calibrated footprints · assumed heights" : "IFC geometry · metres";
  $("scene-badge").classList.toggle("unscaled", unscaled);
  const count = scene.elements.filter((element) => element.geometry).length;
  $("scene-summary").textContent = scene.derived ? `${scene.floors.length} interpreted floor diagrams · ${count} rendered objects. Generated geometry is a visualization, never factual source evidence. ${unscaled ? "Scale is unknown on one or more floors; relative display units cannot establish dimensions or compare physical floor sizes." : "Footprints use cited source calibration; heights and wall thicknesses remain display assumptions."}` : `${scene.elements.length} source elements · ${count} rendered${scene.source_page ? ` · source page ${scene.source_page}` : ""}. ${unscaled ? "Horizontal geometry is inferred; heights and thicknesses are assumptions in relative units." : "Coordinates and properties come from the supplied IFC. Room volumes appear when selected or highlighted."}`;
  $("explode-floors").checked = Boolean(scene.derived && scene.floors.length > 1 && (scene.layout === "schematic" || scene.floors.some((floor) => floor.alignment_status !== "supported")));
  renderFloors();
  $("scene-warnings").textContent = (scene.warnings || []).join(" ");
  $("scene-warnings").hidden = !$("scene-warnings").textContent;
  scene.elements.forEach((element) => $("element-select").append(new Option(`${element.kind} · ${element.name || element.id}${element.geometry ? "" : " (no mesh)"}`, element.id)));
  setView("model");
  try {
    const {BlueprintViewer} = await import("/static/viewer.js");
    state.viewer = new BlueprintViewer($("model-canvas-container"), {onSelect: inspectElement});
    window.blueprintViewer = state.viewer;
    state.viewer.loadScene(scene);
    if ($("explode-floors").checked) state.viewer.setExploded(true);
    state.viewer.setShowAssumptions($("show-assumptions").checked);
    updateHighlights();
  } catch (error) {
    $("model-canvas-container").replaceChildren();
    const notice = document.createElement("p");
    notice.className = "model-error";
    notice.textContent = "The interactive model could not start. This view requires WebGL 2. You can still inspect source records using the element list and ask questions.";
    $("model-canvas-container").append(notice);
    state.viewer?.dispose();
    state.viewer = null;
    window.blueprintViewer = null;
  }
  updateControls();
}

function updateHighlights() {
  const ids = Array.isArray(state.result?.highlight_ids) ? state.result.highlight_ids : [];
  if ($("floor-select").value && ids.some((id) => state.scene?.elements.some((element) => element.id === id && element.storey_id !== $("floor-select").value))) setFloorFilter("");
  state.viewer?.setHighlights(ids, $("highlight-answer").checked);
  $("highlight-note").hidden = !state.scene || !state.result;
  if (!state.scene || !state.result) return;
  const missingMeshes = ids.filter((id) => state.scene.elements.some((element) => element.id === id && !element.geometry)).length;
  $("highlight-note").textContent = ids.length ? `${ids.length} ${state.scene.derived ? "interpreted objects" : "source elements"} linked to this answer.${missingMeshes ? ` ${missingMeshes} have no renderable geometry; inspect their source records below.` : ""}` : "This answer has no reliable 3D mapping. Use its source evidence; no model objects have been highlighted.";
}

function setFloorFilter(id) {
  $("floor-select").value = id;
  state.viewer?.setFloorFilter(id);
  renderFloorDetails();
}

function revealEvidenceFloor(evidence) {
  if (!$("floor-select").value) return;
  const [l,t,r,b] = evidence.bbox || [];
  const matches = (state.scene?.floors || []).filter((floor) => {
    const [fl,ft,fr,fb] = floor.source.bbox || [];
    return floor.source.page === evidence.page && l >= fl && t >= ft && r <= fr && b <= fb;
  });
  setFloorFilter(matches.length === 1 ? matches[0].id : "");
}

function showSourceRegion(source, label) {
  const index = state.document?.pages.findIndex((page) => page.page === source.page) ?? -1;
  if (index < 0) return;
  revealEvidenceFloor(source);
  state.sourceSelection = {...source,label};
  state.selectedEvidence = null;
  state.pageIndex = index;
  setView("drawing");
  renderPage();
  announce(`Showing original source region for ${label}, page ${source.page}.`);
}

function renderFloors() {
  const scene = state.scene;
  const floors = scene.floors || [];
  $("floor-controls").hidden = !floors.length && !scene.ifc_url;
  $("floor-select").disabled = !floors.length;
  $("floor-select").replaceChildren(new Option("All floors", ""));
  $("floor-source-links").replaceChildren();
  $("floor-source-links").hidden = !floors.length;
  $("explode-control").hidden = floors.length < 2;
  for (const floor of floors) {
    $("floor-select").append(new Option(floor.label, floor.id));
    const button = document.createElement("button");
    button.type = "button";
    button.className = "floor-source-link";
    button.dataset.floorId = floor.id;
    button.textContent = `${floor.label} · original p. ${floor.source.page} ↗`;
    button.addEventListener("click", () => showSourceRegion(floor.source, floor.label));
    $("floor-source-links").append(button);
  }
  $("download-ifc").hidden = true;
  if (scene.ifc_url) {
    const url = new URL(scene.ifc_url, window.location.origin);
    if (url.origin === window.location.origin && url.pathname.startsWith("/api/documents/")) {
      $("download-ifc").href = url.href;
      $("download-ifc").hidden = false;
    }
  }
  updateLayoutNote();
  renderFloorDetails();
}

function updateLayoutNote() {
  const scene = state.scene;
  if (!scene) return;
  const schematic = scene.layout === "schematic" || (scene.floors || []).some((floor) => floor.alignment_status !== "supported");
  const lines = [];
  if (scene.derived && schematic) lines.push("Schematic floor arrangement — source alignment is unknown. This is not an aligned building.");
  if ($("explode-floors").checked) lines.push("Vertical separation is for viewing only; it is not storey elevation.");
  $("layout-note").textContent = lines.join(" ");
  $("layout-note").hidden = !lines.length;
}

function renderFloorDetails() {
  const floors = (state.scene?.floors || []).filter((floor) => !$("floor-select").value || floor.id === $("floor-select").value);
  $("floor-details").hidden = !floors.length;
  const content = $("floor-details-content");
  content.replaceChildren();
  for (const floor of floors) {
    const title = document.createElement("h4"), facts = document.createElement("dl");
    title.textContent = floor.label;
    inspectorRow(facts, "Scale", floor.scale_status === "known" ? "Source-calibrated footprint" : "Unknown · relative display units");
    inspectorRow(facts, "Floor order", floor.order ?? "Unknown · diagram order is display only");
    inspectorRow(facts, "Display rotation", `${floor.rotation_degrees}° · original source unchanged`);
    inspectorRow(facts, "Alignment", floor.alignment_status === "supported" ? "Supported by a source anchor" : "Unknown · schematic arrangement");
    for (const observation of floor.observations || []) inspectorRow(facts, "Source interpretation", observation);
    if (floor.calibration) inspectorRow(facts, "Calibration reference", `${floor.calibration.length_m} m · ${floor.calibration.note}`);
    for (const measurement of floor.measurements || []) {
      inspectorRow(facts, measurement.label, measurement.status === "observed" ? `${measurement.value} ${measurement.unit} · ${measurement.note}` : `Unknown · ${measurement.note}`);
      if (measurement.source) {
        const link = document.createElement("button");
        link.type = "button"; link.className = "floor-source-link";
        link.textContent = `Inspect ${measurement.label} in source ↗`;
        link.addEventListener("click", () => showSourceRegion(measurement.source, measurement.label));
        const reference = document.createElement("dd"); reference.append(link); facts.append(document.createElement("dt"),reference);
      }
    }
    content.append(title,facts);
    if (floor.assumptions?.length) {
      const assumptions = document.createElement("dl"); assumptions.className = "floor-assumptions";
      for (const assumption of floor.assumptions) inspectorRow(assumptions, `${assumption.property} · assumption`, `${assumption.value}${assumption.unit ? ` ${assumption.unit}` : ""} — ${assumption.reason}`);
      content.append(assumptions);
    }
  }
}

function inspectorRow(container, name, value) {
  const dt = document.createElement("dt"), dd = document.createElement("dd");
  dt.textContent = name;
  dd.textContent = String(value ?? "Not specified");
  container.append(dt,dd);
}

function inspectElement(element) {
  state.selectedElement = element;
  if (state.viewer && $("floor-select").value !== state.viewer.floorFilter) { $("floor-select").value = state.viewer.floorFilter; renderFloorDetails(); }
  $("element-select").value = element.id;
  $("element-inspector").hidden = false;
  $("element-name").textContent = element.name || element.id;
  $("element-origin").textContent = element.geometry_origin === "inferred" ? "Geometry: inferred interpretation of the source image." : "Geometry: extracted from the supplied IFC model.";
  $("element-geometry-note").textContent = element.geometry ? `${element.kind} · ${element.ifc_type || "image reconstruction"}` : "This source element has no renderable geometry. Its properties are still available and it remains in the source catalog.";
  $("element-identity").replaceChildren();
  inspectorRow($("element-identity"), "Element ID", element.id);
  if (element.source.kind === "ifc") {
    inspectorRow($("element-identity"), "IFC GlobalId", element.source.global_id);
    inspectorRow($("element-identity"), "STEP entity", `#${element.source.step_id}`);
    if (element.storey_id) inspectorRow($("element-identity"), "Storey ID", element.storey_id);
  } else {
    inspectorRow($("element-identity"), "Source page", element.source.page);
    if (element.storey_id) inspectorRow($("element-identity"), "Floor", state.scene.floors?.find((floor) => floor.id === element.storey_id)?.label || element.storey_id);
    if (state.scene.derived) inspectorRow($("element-identity"), "Interpretation basis", element.evidence_basis === "observed" ? "Depicted in source · model interpretation" : element.evidence_basis === "display_assumption" ? "Display assumption · not a source fact" : "Inferred · not an observed source fact");
    if (element.note) inspectorRow($("element-identity"), "Interpretation note", element.note);
  }
  $("element-properties").replaceChildren();
  for (const property of element.properties || []) inspectorRow($("element-properties"), `${property.name}${property.origin === "derived" ? " (derived)" : ""}`, `${property.value ?? "Not specified"}${property.unit ? ` ${property.unit}` : ""}`);
  if (!element.properties?.length) inspectorRow($("element-properties"), "Properties", "No additional properties provided.");
  $("element-assumptions").replaceChildren();
  for (const assumption of element.assumptions || []) inspectorRow($("element-assumptions"), assumption.property, `${assumption.value}${assumption.unit ? ` ${assumption.unit}` : ""} — ${assumption.reason}`);
  $("element-assumptions-section").hidden = !element.assumptions?.length;
  $("element-source").hidden = element.source.kind !== "image";
  announce(`Selected ${element.name || element.id}. Source properties are available below the model.`);
}

function selectModelElement(id) {
  const element = state.scene?.elements.find((item) => item.id === id);
  if (!element) return;
  setView("model");
  if (state.viewer) state.viewer.select(id); else inspectElement(element);
}

function renderModelEvidence(items) {
  $("model-evidence-list").replaceChildren();
  $("model-evidence-section").hidden = !items.length;
  for (const item of items) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "model-evidence-item";
    button.dataset.elementId = item.element_id || "";
    const title = document.createElement("strong"), observation = document.createElement("span"), reference = document.createElement("span");
    title.textContent = item.label;
    observation.textContent = item.observation;
    reference.textContent = item.element_id ? `${item.property_name ? `${item.property_name} · ` : ""}${item.element_id}` : "Complete supplied IFC catalog";
    button.append(title,observation,reference);
    button.disabled = !item.element_id || !state.scene?.elements.some((element) => element.id === item.element_id);
    button.addEventListener("click", () => selectModelElement(item.element_id));
    $("model-evidence-list").append(button);
  }
}

$("generate-scene").addEventListener("click", async () => {
  if (!state.document || state.document.kind === "ifc" || state.scene || state.busy || !state.providerReady) return;
  voice?.cancelAll();
  state.busy = "scene";
  const version = ++state.requestVersion;
  setError("scene-error");
  $("scene-progress-text").textContent = "Interpreting all pages and floor-plan panels. Building an approximate model with source links and explicit assumptions…";
  updateControls();
  try {
    const scene = await request(`/api/documents/${state.document.document_id}/scene`, {method:"POST",headers:{"Content-Type":"application/json"},body:"{}"},180000);
    if (version === state.requestVersion) await loadScene(scene);
  } catch (error) { setError("scene-error", error.message); }
  finally { state.busy = null; updateControls(); }
});
$("show-drawing").addEventListener("click", () => setView("drawing"));
$("show-model").addEventListener("click", () => setView("model"));
$("highlight-answer").addEventListener("change", updateHighlights);
$("show-assumptions").addEventListener("change", () => state.viewer?.setShowAssumptions($("show-assumptions").checked));
$("fit-model").addEventListener("click", () => state.viewer?.fit());
$("floor-select").addEventListener("change", () => setFloorFilter($("floor-select").value));
$("explode-floors").addEventListener("change", () => { state.viewer?.setExploded($("explode-floors").checked); updateLayoutNote(); });
$("element-select").addEventListener("change", () => selectModelElement($("element-select").value));
$("element-source").addEventListener("click", () => {
  const element = state.selectedElement;
  if (!element || element.source.kind !== "image") return;
  showSourceRegion(element.source, element.name);
});

$("question-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const question = $("question").value.trim();
  if (!question || question.length > 2000 || !state.document || state.busy || !state.providerReady || voice?.recording) return;
  voice?.cancelAll();
  voice?.questionSubmitted(question);
  resetAnswer();
  $("answer-empty").hidden = true;
  state.busy = "ask";
  const version = ++state.requestVersion;
  updateControls();
  try {
    const result = await request("/api/ask", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ document_id: state.document.document_id, question }) });
    if (version !== state.requestVersion) return;
    renderResult(result);
    voice?.answerReady();
  } catch (error) {
    setError("ask-error", error.message);
    $("answer-empty").hidden = false;
    announce("The request failed. No answer was confirmed.");
  } finally { state.busy = null; updateControls(); }
});

$("file-input").addEventListener("change", (event) => uploadFile(event.target.files[0]));
$("upload-label").addEventListener("click", () => { if (!state.busy) $("file-input").click(); });
$("drop-zone").addEventListener("click", () => { if (!state.busy) $("file-input").click(); });
$("drop-zone").addEventListener("keydown", (event) => { if ((event.key === "Enter" || event.key === " ") && !state.busy) { event.preventDefault(); $("file-input").click(); } });
const sourcePanel = $("source-heading").closest("section");
sourcePanel.addEventListener("dragover", (event) => { event.preventDefault(); if (!state.busy) $("drop-zone").classList.add("drag-over"); });
sourcePanel.addEventListener("dragleave", (event) => { if (!sourcePanel.contains(event.relatedTarget)) $("drop-zone").classList.remove("drag-over"); });
sourcePanel.addEventListener("drop", (event) => { event.preventDefault(); $("drop-zone").classList.remove("drag-over"); if (!state.busy) { if (event.dataTransfer.files.length > 1) setError("upload-error", "Choose one drawing file at a time."); else uploadFile(event.dataTransfer.files[0]); } });
$("question").addEventListener("input", updateControls);
suggestions.forEach((button) => button.addEventListener("click", () => { $("question").value = button.dataset.question; updateControls(); $("question").focus(); }));
function changePage(direction) { if (!state.document) return; const index = state.pageIndex + direction; if (index < 0 || index >= state.document.pages.length) return; state.pageIndex = index; renderPage(); }
$("previous-page").addEventListener("click", () => changePage(-1));
$("next-page").addEventListener("click", () => changePage(1));
$("viewer").addEventListener("keydown", (event) => { if (event.key === "ArrowLeft" || event.key === "ArrowRight") { event.preventDefault(); changePage(event.key === "ArrowLeft" ? -1 : 1); } });
$("zoom").addEventListener("change", () => { $("image-stage").style.width = `${Number($("zoom").value)}%`; });
$("page-image").addEventListener("error", () => setError("upload-error", "The drawing preview could not be loaded. Try uploading the file again."));
$("page-image").addEventListener("load", renderOverlay);
$("refresh-health").addEventListener("click", checkHealth);
voice = new window.BlueprintVoice({state: () => state, request, updateControls});
updateControls();
checkHealth();
