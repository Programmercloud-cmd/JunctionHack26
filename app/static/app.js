"use strict";

const $ = (id) => document.getElementById(id);
const state = { document: null, pageIndex: 0, selectedEvidence: null, sourceSelection: null, result: null, busy: null, providerReady: false, health: null, requestVersion: 0, scene: null, viewer: null, selectedElement: null, selectedComparison: null, view: "drawing", epoch:0, jobs:[], savedBuildings:[], pollTimer:null, pollingEpoch:null, questionRequest:null, askSubmitting:false, reconstructionSubmitting:false, conversation:[], clarificationReply:null, assumptionRows:[], assumptionEdits:new Map(), evidenceRevision:null };
let voice = null;
const suggestions = Array.from(document.querySelectorAll("[data-question]"));

function announce(message) { $("announcer").textContent = message; }
function setError(id, message = "") { $(id).textContent = message; $(id).hidden = !message; window.chatUI?.onError(id,message);if(id==="upload-error")window.workspaceControls?.showStatus(message); }
function updateControls() {
  const busy = Boolean(state.busy);
  const recording = Boolean(voice?.recording);
  $("file-input").disabled = busy;
  $("upload-label").disabled = busy;
  $("append-sources").disabled=busy||!state.document;
  $("retry-extraction").disabled=busy||!state.document||!state.providerReady;
  $("upload-label").classList.toggle("is-disabled", busy);
  $("drop-zone").setAttribute("aria-disabled", String(busy));
  $("question").disabled = !state.document || busy || recording;
  suggestions.forEach((button) => { button.disabled = !state.document || busy || recording; });
  $("ask-button").disabled = !state.document || !state.providerReady || busy || recording || state.askSubmitting || !$("question").value.trim();
  $("ask-label").textContent = state.busy === "ask" ? "Inspecting drawing…" : "Ask the drawing";
  $("upload-progress").hidden = state.busy !== "upload";
  $("ask-progress").hidden = state.busy !== "ask" && !state.questionRequest?.pending;
  $("question-help").textContent = !state.document ? "Upload a drawing to get started." : !state.providerReady ? `You can preview the drawing. Configure ${state.health?.provider_label || "the selected provider"} to ask questions.` : "Answers are limited to the supplied drawing.";
  $("previous-page").disabled = !state.document || state.pageIndex === 0;
  $("next-page").disabled = !state.document || state.pageIndex >= displayPages().length - 1;
  $("character-count").textContent = `${$("question").value.length} / 2000`;
  $("question-form").setAttribute("aria-busy", String(state.busy === "ask"));
  $("source-heading").closest("section").setAttribute("aria-busy", String(state.busy === "upload"));
  $("generate-scene").hidden = !state.document || state.document.kind === "ifc" || Boolean(state.scene);
  $("generate-scene").disabled = busy || !state.providerReady || state.reconstructionSubmitting || state.jobs.some(j=>j.kind==="reconstruction"&&!terminalJob(j));
  const progressive=Boolean(state.document?.building_id&&state.document?.revision_id),native=state.document?.kind==="ifc"&&!state.scene?.derived;
  $("building-progress").hidden=!progressive;
  $("refine-building").hidden=!state.scene||native;$("reconstruct-building").hidden=native;
  for(const id of ["refine-building","reconstruct-building"])$(id).disabled=busy||!state.providerReady||state.reconstructionSubmitting||state.jobs.some(j=>j.kind==="reconstruction"&&!terminalJob(j));
  $("open-building").disabled=busy||!$("saved-building-select").value;
  $("show-model").disabled = !state.scene;
  $("show-concept").disabled = !state.viewer || !state.scene?.elements.some(e=>e.geometry);
  $("show-drawing").hidden = state.document?.kind === "ifc";
  $("scene-progress").hidden = state.busy !== "scene";
  voice?.syncControls();
  window.chatUI?.syncControls();
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
    $("provider-banner").hidden = state.providerReady;
    if (!state.providerReady) {
      $("provider-title").textContent = `${providerLabel} is not configured yet`;
      $("provider-message").textContent = `Upload and preview drawings now. To enable answers, set ${health.credential_env || "GEMINI_API_KEY"} in the server’s .env.local file and restart the server. Keep the key out of the browser.`;
    }
    if (health.limits) $("upload-limits").textContent = `JPG, PNG, SVG, DXF · ${health.limits.max_upload_mb} MB each · PDF ${health.limits.max_pages} pages per file · IFC ${health.limits.max_ifc_mb || 25} MB · DWG requires a converter`;
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
  state.nativeEvidenceToken=(state.nativeEvidenceToken || 0)+1;$("native-record-inspector").hidden=true;
  state.result = null;
  state.selectedEvidence = null;
  state.sourceSelection = null;
  if (state.viewer) state.viewer.setHighlights([], $("highlight-answer").checked);
  $("result").hidden = true;
  $("answer-empty").hidden = false;
  $("evidence-overlay").hidden = true;
  setError("ask-error");
}

async function uploadFromNativePicker() {
  if (state.busy || !window.chatUI?.isHome()) return;
  setError("upload-error");
  state.busy = "upload";
  updateControls();
  try {
    const result = await request("/api/documents/native-picker", {method: "POST"}, 320000);
    if (!result.cancelled) {
      await refreshSavedBuildings();
      announce("Original file saved.");
    }
  } catch (error) {
    await refreshSavedBuildings();
    setError("upload-error", error.message);
  } finally {
    state.busy = null;
    updateControls();
  }
}

async function uploadFile(input) {
  const files = Array.from(input?.name ? [input] : input || []);
  if (!files.length || state.busy || (window.chatUI && !window.chatUI.isHome())) return;
  setError("upload-error");
  if (files.length !== 1) {
    setError("upload-error", "Choose one file to upload.");
    return;
  }
  const [file] = files;
  const maxMB = /\.ifc$/i.test(file.name) ? (state.health?.limits?.max_ifc_mb || 25) : (state.health?.limits?.max_upload_mb || 10);
  if (file.size > maxMB * 1024 * 1024) {
    setError("upload-error", `${file.name} exceeds the ${maxMB} MB per-file limit.`);
    return;
  }
  if (!/\.(jpe?g|png|pdf|ifc|svg|dxf|dwg)$/i.test(file.name)) {
    setError("upload-error", "Choose JPG, PNG, PDF, SVG, DXF or IFC. DWG needs an available converter.");
    return;
  }
  voice?.cancelAll();
  state.busy="upload";const version=++state.requestVersion;updateControls();
  window.chatUI?.onUpload();
  const form = new FormData();
  form.append("files", file);
  // Desktop file pickers may provide a path. Standard browser uploads only provide a name.
  if (typeof file.path === "string" && file.path) form.append("original_path", file.path);
  try {
    const result = await request("/api/documents", {method:"POST", body:form});
    if (version !== state.requestVersion) return;
    if (!result.document_id || !Array.isArray(result.pages)) throw new Error("The server did not return a usable source document.");
    await refreshSavedBuildings();
    announce("Original file saved.");
  } catch (error) {
    setError("upload-error", error.message);
  } finally {
    state.busy = null;
    updateControls();
  }
}

function terminalJob(job) {return ["complete","needs_attention","failed","budget_exhausted","stopped","interrupted"].includes(job.status);}
function progressiveDocument() {return Boolean(state.document?.building_id&&state.document?.revision_id);}
function schedulePoll(delay=1000) {
  clearTimeout(state.pollTimer);
  const epoch=state.epoch;
  state.pollTimer=setTimeout(()=>{if(epoch===state.epoch)refreshBuilding();},delay);
}
async function refreshSavedBuildings() {
  $("refresh-buildings").disabled=true;
  state.savedBuildingsError = false;
  try {
    const result=await request("/api/buildings",{},15000);state.savedBuildings=result.buildings || [];
    const selected=$("saved-building-select").value || state.document?.building_id || "";
    $("saved-building-select").replaceChildren(new Option("Choose a saved building", ""));
    for(const item of state.savedBuildings)$("saved-building-select").append(new Option(`${item.filename} · ${item.has_scene?"model available":"source available"}`,item.building_id||item.document_id));
    $("saved-building-select").value=selected;
    $("saved-buildings-note").textContent=`${state.savedBuildings.length} saved ${state.savedBuildings.length===1?"building":"buildings"}`;
  }catch(error){state.savedBuildingsError = true;$("saved-buildings-note").textContent="Saved building list unavailable. Existing uploads remain usable.";}
  finally{state.savedBuildingsLoaded = true;$("refresh-buildings").disabled=false;updateControls();}
}
async function activateDocument(result, workspaceMode = null) {
  // Preload the initial view before replacing the building. Keep the old
  // drawing and model if an original or saved scene cannot be retrieved.
  const sceneUrl=result.scene_url||(result.kind==="ifc"?`/api/documents/${result.document_id}/scene`:null);
  let stagedScene=null,stagedSceneError=null;
  if(workspaceMode){
    const page=result.pages?.[0];
    if(page&&(workspaceMode==="source"||!sceneUrl)){
      const url=new URL(page.image_url,location.origin);
      if(url.origin!==location.origin)throw new Error("The page preview URL is invalid.");
      const image=new Image();image.src=url.href;
      try{await image.decode();}catch{throw new Error("The blueprint preview could not be loaded. Your previous view is still open.");}
    }
    if(sceneUrl){
      try{stagedScene=await request(sceneUrl);}
      catch(error){if(!page||workspaceMode!=="source")throw error;stagedSceneError=error;}
    }
  }
  clearTimeout(state.pollTimer);state.epoch++;state.jobs=result.jobs || [];state.questionRequest=null;state.askSubmitting=false;state.reconstructionSubmitting=false;
  clearScene();state.document=result;voice?.newDocument(result.document_id);state.pageIndex=0;state.conversation=[];state.clarificationReply=null;state.assumptionEdits.clear();state.evidenceRevision=null;resetAnswer();setError("building-poll-error");
  $("filename").textContent=result.filename;$("filename").title=result.filename;
  $("page-count").textContent=result.kind==="ifc"?"IFC model":`${result.pages.length} ${result.pages.length===1?"page":"pages"}`;
  $("document-warnings").textContent=(result.warnings || []).join(" ");$("document-warnings").hidden=!$("document-warnings").textContent;
  $("drop-zone").hidden=true;$("document-view").hidden=false;$("upload-label").textContent="Open other files";$("zoom").value="100";setDrawingFit("width");
  if(result.kind==="ifc"){
    setView("model");await loadScene(stagedScene||await request(sceneUrl));
    suggestions[0].dataset.question="How many windows are in this IFC model?";suggestions[0].textContent="Count windows";
    suggestions[1].dataset.question="How many rooms are in this IFC model?";suggestions[1].textContent="Count rooms";
  }else{
    setView("drawing");renderPage();
    suggestions[0].dataset.question="What labeled spaces are shown on this drawing?";suggestions[0].textContent="Identify spaces";
    suggestions[1].dataset.question="What dimensions are explicitly shown?";suggestions[1].textContent="Inspect dimensions";
    if(stagedScene||(!workspaceMode&&sceneUrl))await loadScene(stagedScene||await request(sceneUrl));
  }
  renderSourceList();renderBuildingStatus();renderJobs();updateControls();
  window.chatUI?.onDocument(result,workspaceMode);
  if(stagedSceneError)setError("scene-error",stagedSceneError.message);
  if(progressiveDocument()){await Promise.allSettled([refreshConversation(),refreshAssumptions()]);schedulePoll(0);}
}
async function openBuilding(id, workspaceMode = null) {
  if(!id||state.busy)return;
  if(id===state.document?.building_id){await refreshBuilding();return;}
  voice?.cancelAll();
  state.busy="upload";const version=++state.requestVersion;updateControls();setError("upload-error");
  try{const result=await request(`/api/buildings/${id}`);if(version===state.requestVersion){await activateDocument(result,workspaceMode);announce(`Opened saved building ${result.filename}. No new reconstruction was started.`);}}
  catch(error){if(version===state.requestVersion)setError("upload-error",error.message);}
  finally{if(version===state.requestVersion){state.busy=null;updateControls();}}
}
function renderBuildingStatus() {
  if(!progressiveDocument())return;
  const document=state.document,labels={source_available:"Source available",source_only:"Source only · no supported floor model",preview_unreviewed:"Preview · not yet reviewed",reviewing:"Preview · review in progress",preview_reviewing:"Preview · review in progress",reviewed_no_action:"Reviewed · no actionable finding",needs_attention:"Needs attention",available:"Model available"};
  const latest=state.jobs.find(job=>["reconstruction","extraction","refinement"].includes(job.kind));
  let statusLabel=labels[document.review_status] || (document.review_status || "available").replaceAll("_"," ");
  if(latest&&!terminalJob(latest))statusLabel=`${state.scene?"Model available":"Source available"} · ${latest.kind==="extraction"?"source interpretation":latest.phase==="reviewing"||latest.phase==="checking_revision"?"review":"reconstruction"} in progress`;
  else if(latest&&latest.status!=="complete"&&document.review_status!=="source_only"){
    const terminalLabels={failed:"processing failed",stopped:"review stopped",budget_exhausted:"processing budget exhausted",interrupted:"processing interrupted",needs_attention:"needs attention"};
    statusLabel=`${state.scene?"Model retained":"Source retained"} · ${terminalLabels[latest.status] || latest.status}`;
  }else if(["preview_reviewing","reviewing"].includes(document.review_status))statusLabel="Preview available · review not completed";
  $("building-review-status").textContent=`${statusLabel} · revision ${document.revision_number}`;
  if(state.scene&&document.has_scene&&state.scene.revision_number!==document.revision_number)$("building-review-status").textContent+=` · displayed model revision ${state.scene.revision_number}`;
  $("source-only-note").hidden=Boolean(state.scene);
  $("source-only-note").textContent="Original sources are available for questions, including while interpretation runs. Generate 3D is optional; it reuses saved interpretation.";
  $("unsupported-views").replaceChildren();
  for(const view of document.unresolved_views || []){
    const row=window.document.createElement("div");row.className="unsupported-view";
    const label=window.document.createElement("strong"),reason=window.document.createElement("p"),button=window.document.createElement("button");
    label.textContent=`${view.label} · ${view.view_type || "unresolved view"}`;reason.textContent=view.reason || "Retained as source evidence; no unsupported floor geometry was invented.";
    button.type="button";button.className="text-button";button.textContent="Inspect original source ↗";button.addEventListener("click",()=>showSourceRegion(view.source,view.label));
    row.append(label,reason,button);$("unsupported-views").append(row);
  }
  $("unsupported-views").hidden=!$("unsupported-views").childElementCount;
}
function rememberJob(job) {
  if(job.building_id!==state.document?.building_id)return;
  state.jobs=[job,...state.jobs.filter(j=>j.id!==job.id)];renderBuildingStatus();renderJobs();updateControls();
}
function renderJobRecovery(row, job) {
  for(const value of job.submitted_values || []){
    const item=document.createElement("p");item.className="job-submitted-value";
    const scope=[value.scope?.floor_id,value.scope?.object_id].filter(Boolean).join(" / ");
    item.textContent=`Submitted input (user-provided; see outcome above): ${(value.property || "value").replaceAll("_"," ")}${scope?` · ${scope}`:""} = ${nativeValue(value.value)}${value.unit?` ${value.unit}`:""}${value.reason?`. ${value.reason}`:""}`;
    row.append(item);
  }
  if(!job.recovery_events?.length)return;
  const history=document.createElement("section"),title=document.createElement("strong");history.className="job-recovery";
  title.textContent="Recovery history";history.append(title);
  for(const event of job.recovery_events){
    const item=document.createElement("div"),heading=document.createElement("p"),detail=document.createElement("p");item.className="job-recovery-event";
    const labels={rejection:"Correction rejected",authorization:"Additional target review",stopped:"Recovery stopped"};
    heading.textContent=`${event.attempt?`Attempt ${event.attempt} · `:""}${labels[event.kind] || "Recovery update"}`;
    detail.textContent=event.message || "";item.append(heading,detail);
    if(event.kind==="rejection"&&event.feedback){
      const feedback=event.feedback,reason=document.createElement("p"),expected=document.createElement("p");
      reason.textContent=[feedback.code,feedback.target_id?`Target ${feedback.target_id}`:"",feedback.explanation].filter(Boolean).join(" · ");
      expected.textContent=feedback.expected_contract?`Required correction: ${feedback.expected_contract}`:"";item.append(reason,expected);
    }
    if(event.kind==="authorization"){
      const sourceRevision=event.base_revision_id || job.base_revision_id;
      for(const decision of event.decisions || []){
        const entry=document.createElement("div"),outcome=document.createElement("p"),reason=document.createElement("p");entry.className="job-target-decision";
        const labels={approved:"Approved correction target",denied:"Denied",unclear:"Unclear · not authorized"};
        outcome.textContent=`${labels[decision.decision] || "Not authorized"} · target ${decision.target_id}${decision.issue_id?` · issue ${decision.issue_id}`:""}`;
        reason.textContent=decision.reason || "";entry.append(outcome,reason);
        if(decision.evidence&&typeof sourceRevision==="string"&&/^[a-f0-9]{32}$/i.test(sourceRevision)){
          const source=document.createElement("button");source.type="button";source.className="text-button job-target-source";source.textContent="Inspect reviewed target in original source ↗";
          source.addEventListener("click",()=>showSourceRegion(decision.evidence,`Reviewed target ${decision.target_id}`,sourceRevision));entry.append(source);
        }
        item.append(entry);
      }
      for(const request of event.requests || [])if(!(event.decisions || []).some(decision=>decision.request_id===request.request_id)){
        const pending=document.createElement("p");pending.textContent=`Requested target ${request.target_id} · no authorization decision recorded`;item.append(pending);
      }
      const note=document.createElement("p");note.textContent="Target approval permits a proposed correction; it does not mean a change was applied or accepted.";item.append(note);
    }
    history.append(item);
  }
  row.append(history);
}
function renderJobs() {
  const open=new Set([...$("building-jobs").querySelectorAll("details[open]")].map(d=>d.dataset.jobId));
  const historyWasOpen=Boolean($("past-jobs")?.open);
  $("building-jobs").replaceChildren();
  const history=document.createElement("details"),historyTitle=document.createElement("summary");history.id="past-jobs";history.open=historyWasOpen;history.append(historyTitle);
  const latestReconstruction=state.jobs.find(j=>j.kind==="reconstruction")?.id,latestQuestion=state.jobs.find(j=>j.kind==="question")?.id;
  let historyCount=0;
  for(const job of state.jobs){
    const row=document.createElement("details"),summary=document.createElement("summary"),title=document.createElement("strong"),status=document.createElement("span"),message=document.createElement("p");
    row.className="job-row";row.dataset.jobId=job.id;row.dataset.status=job.status;row.open=open.has(job.id)||!terminalJob(job);
    title.textContent=job.kind==="question"?`Question · ${job.question || "source inspection"}`:({extraction:"Source interpretation",refinement:"Apply and refine",reconstruction:"Reconstruction"}[job.kind]||job.kind);
    status.className="job-status";status.textContent=`${job.status.replaceAll("_"," ")} · ${job.phase.replaceAll("_"," ")}`;
    message.textContent=job.message || "";summary.append(title,status);
    if(!terminalJob(job)){
      const stop=document.createElement("button");stop.type="button";stop.className="text-button job-stop";stop.textContent="Stop";stop.dataset.jobId=job.id;
      stop.addEventListener("click",async event=>{event.preventDefault();stop.disabled=true;const epoch=state.epoch;try{const stopped=await request(`/api/jobs/${job.id}/stop`,{method:"POST"});if(epoch===state.epoch){rememberJob(stopped);schedulePoll(0);}}catch(error){if(epoch===state.epoch)setError("building-poll-error",error.message);}finally{stop.disabled=false;}});summary.append(stop);
    }
    row.append(summary,message);
    if(["failed","budget_exhausted"].includes(job.status)&&typeof job.diagnostic_message==="string"&&job.diagnostic_message.trim()){
      const diagnostic=document.createElement("p");diagnostic.className="job-diagnostic";
      // The server publishes a sanitized diagnostic separately from provider internals.
      diagnostic.textContent=`Failure detail: ${job.diagnostic_message}`;row.append(diagnostic);
    }
    renderJobRecovery(row,job);
    for(const issue of job.issues || []){
      const item=document.createElement("div"),heading=document.createElement("strong"),detail=document.createElement("p"),source=document.createElement("button");item.className="job-issue";
      heading.textContent=`${issue.category} · ${issue.discrepancy}`;detail.textContent=[issue.evidence,issue.uncertainty,issue.proposed_action].filter(Boolean).join(" ");
      source.type="button";source.className="text-button";source.textContent="Inspect finding in source ↗";source.addEventListener("click",()=>showSourceRegion(issue.source,issue.discrepancy));item.append(heading,detail,source);row.append(item);
    }
    if(terminalJob(job)&&job.id!==latestReconstruction&&job.id!==latestQuestion){history.append(row);historyCount++;}
    else $("building-jobs").append(row);
  }
  if(historyCount){historyTitle.textContent=`Past jobs (${historyCount})`;$("building-jobs").append(history);}
  const question=state.jobs.find(j=>j.kind==="question"&&j.request_id===state.questionRequest?.id&&j.building_id===state.questionRequest?.building);
  if(question&&state.questionRequest.pending){
    $("ask-progress-label").textContent=question.message || "Inspecting the source";
    if(terminalJob(question)){
      state.questionRequest.pending=false;
      if(question.status==="complete"&&question.answer){
        renderResult(question.answer,true);
        if(!window.chatUI||window.chatUI.isLatestSubmission(question.request_id))voice?.answerReady(question.answer);
        refreshConversation();
      }
      else{setError("ask-error",question.message || "Question stopped without a confirmed answer.");$("answer-empty").hidden=false;}
    }
  }
  window.chatUI?.onJobs(state.jobs);
}
async function refreshBuilding() {
  if(!progressiveDocument())return;
  const epoch=state.epoch,id=state.document.building_id;
  if(state.pollingEpoch===epoch)return;
  state.pollingEpoch=epoch;
  try{
    const result=await request(`/api/buildings/${id}`,{},15000);
    if(epoch!==state.epoch||id!==state.document?.building_id)return;
    // A metadata response can precede a newly submitted job. Retain that local job
    // until the server's next snapshot contains it, so polling cannot stop early.
    const jobs=result.jobs || [];
    state.jobs=[...jobs,...state.jobs.filter(j=>!terminalJob(j)&&!jobs.some(next=>next.id===j.id))];
    if(result.has_scene&&(!state.scene || (result.geometry_revision_id || result.revision_id)!==state.scene.revision_id)){
      const scene=await request(result.scene_url || `/api/documents/${id}/scene`);
      if(epoch!==state.epoch||id!==state.document?.building_id)return;
      await loadScene(scene);
    }
    if(epoch!==state.epoch)return;
    const revisionChanged=state.document.revision_id!==result.revision_id;
    state.document=result;
    if(revisionChanged){renderSourceList();refreshAssumptions();if(!state.evidenceRevision)renderPage();}
    const savedOption=[...$("saved-building-select").options].find(option=>option.value===id);
    if(savedOption)savedOption.textContent=`${result.filename} · ${result.has_scene?"model available":"source available"}`;
    const catalogIndex=state.savedBuildings.findIndex(item=>(item.building_id||item.document_id)===id);
    if(catalogIndex>=0)state.savedBuildings[catalogIndex]={...state.savedBuildings[catalogIndex],has_scene:result.has_scene,interpretation_status:result.interpretation_status};
    renderBuildingStatus();renderJobs();setError("building-poll-error");updateControls();
    window.chatUI?.onDocument(state.document);
  }catch(error){if(epoch===state.epoch)setError("building-poll-error",`${error.message} The displayed model remains available. Use Refresh status to retry.`);}
  finally{
    if(state.pollingEpoch===epoch)state.pollingEpoch=null;
    if(epoch===state.epoch&&state.jobs.some(job=>!terminalJob(job)))schedulePoll();
  }
}
async function startReconstruction(mode) {
  if(!state.document||!state.providerReady||state.reconstructionSubmitting)return;
  const epoch=state.epoch,document=state.document;setError("scene-error");state.reconstructionSubmitting=true;updateControls();
  try{
    if(progressiveDocument()){
      const job=await request(`/api/buildings/${document.building_id}/reconstruction`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({base_revision_id:document.revision_id,mode})});
      if(epoch===state.epoch){rememberJob(job);schedulePoll(0);}
    }else{
      state.busy="scene";$("scene-progress-text").textContent="Interpreting source plans and generating the model…";updateControls();
      const scene=await request(`/api/documents/${document.document_id}/scene`,{method:"POST",headers:{"Content-Type":"application/json"},body:"{}"});
      if(epoch===state.epoch)await loadScene(scene);
    }
  }catch(error){if(epoch===state.epoch)setError("scene-error",error.message);}
  finally{if(epoch===state.epoch){state.reconstructionSubmitting=false;if(state.busy==="scene")state.busy=null;updateControls();}}
}

function displayPages() {
  const sourceView=window.chatUI?.sourceView();
  return state.evidenceRevision&&sourceView?.revision_id===state.evidenceRevision?sourceView.pages:state.document?.pages||[];
}
let drawingFit = "width";

function updateDrawingFit() {
  if (!drawingFit) return;
  const stage = $("image-stage");
  if (drawingFit === "width") {
    stage.style.width = "100%";
    return;
  }
  const viewer = $("viewer");
  const image = $("page-image");
  const styles = getComputedStyle(viewer);
  const height = viewer.clientHeight - parseFloat(styles.paddingTop) - parseFloat(styles.paddingBottom);
  if (height > 0 && image.complete && image.naturalWidth && image.naturalHeight) {
    stage.style.width = `${Math.floor(height * image.naturalWidth / image.naturalHeight)}px`;
  }
}

function setDrawingFit(mode) {
  drawingFit = mode;
  updateDrawingFit();
  window.workspaceControls?.syncDrawingFit();
}

function setDrawingZoom(width) {
  setDrawingFit(null);
  $("image-stage").style.width = width;
}

function renderPage() {
  const pages=displayPages(),page=pages[state.pageIndex];
  if (!page) return;
  $("page-label").textContent = `${page.source_filename || state.document.filename} · page ${page.source_page || page.page} (${state.pageIndex+1}/${pages.length})${state.evidenceRevision?" · source revision":""}`;
  $("page-image").alt = `${page.source_filename || "Original drawing"}, page ${page.source_page || page.page}`;
  // Only load normalized page previews from this application.
  const preview=state.evidenceRevision?`/api/buildings/${state.document.building_id}/revisions/${state.evidenceRevision}/pages/${page.page}`:page.image_url;
  const url = new URL(preview, window.location.origin);
  if (url.origin !== window.location.origin) { setError("upload-error", "The page preview URL is invalid."); return; }
  $("page-image").width = page.width;
  $("page-image").height = page.height;
  $("page-image").src = url.href;
  $("viewer").scrollTo(0, 0);
  renderOverlay();
  renderComparison();
  renderInventory();
  updateControls();
}

function renderOverlay() {
  const evidence = state.sourceSelection || (state.selectedEvidence === null ? null : state.result?.evidence?.[state.selectedEvidence]);
  const page = displayPages()[state.pageIndex];
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
  $("overlay-number").textContent = "Source";
  overlay.hidden = false;
  $("viewer-caption").textContent = `${state.sourceSelection ? "Saved source region" : `Reference ${state.selectedEvidence + 1}`} · Page ${evidence.page} · ${evidence.label}`;
  $("viewer").scrollTo({ left: Math.max(0, overlay.offsetLeft + overlay.offsetWidth / 2 - $("viewer").clientWidth / 2), top: Math.max(0, overlay.offsetTop + overlay.offsetHeight / 2 - $("viewer").clientHeight / 2), behavior: "instant" });
}

function selectEvidence(index) {
  const evidence = state.result?.evidence?.[index];
  if (!evidence || !state.document) return;
  const pageIndex = state.document.pages.findIndex((page) => page.page === evidence.page);
  if (pageIndex === -1) return;
  state.evidenceRevision=state.result?.answered_revision_id || null;
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

function answerForDisplayedRevision(result) {
  if(result.display_revision_id && state.scene?.revision_id && result.display_revision_id!==state.scene.revision_id && result.highlight_ids?.length)return {...result,highlight_ids:[],review_note:[result.review_note,"The displayed model belongs to a different revision from this answer’s mapping. Original citations remain available; object highlights await a new source check."].filter(Boolean).join(" ")};
  return result;
}
function renderResult(result, preserveView = false) {
  result=answerForDisplayedRevision(result);
  state.result = result;
  updateControls();
  state.selectedEvidence = null;
  state.sourceSelection = null;
  $("answer-empty").hidden = true;
  $("result").hidden = false;
  const labels = { clarification:"Clarify your question", answered: "Supported by the inspected source", insufficient: "Missing information", unclear: "Unable to resolve confidently" };
  const headings = { clarification:"A quick clarification", answered: "Answer", insufficient: "The supplied drawing is not enough", unclear: "This needs a closer look" };
  $("result-status").textContent = labels[result.status] || "Inspection result";
  $("result-status").className = `result-status ${["answered", "insufficient", "unclear", "clarification"].includes(result.status) ? result.status : "unclear"}`;
  $("result-heading").textContent = headings[result.status] || "Inspection result";
  const pages = Array.isArray(result.inspected_pages) ? result.inspected_pages : [];
  $("result-scope").textContent = state.document?.kind === "ifc" ? "Supplied IFC source records" : `Inspected ${pages.length === 1 ? "page" : "pages"} ${pages.join(", ") || "not reported"}`;
  $("answer-text").textContent = result.clarification?.message || result.answer || "No answer was returned.";
  $("clarification-options").replaceChildren();
  if(result.status==="clarification")for(const suggestion of result.clarification?.suggestions||[]){
    const button=document.createElement("button");button.type="button";button.textContent=suggestion;
    button.addEventListener("click",()=>{$("question").value=suggestion;updateControls();$("question-form").requestSubmit();});
    $("clarification-options").append(button);
  }
  $("support-summary").textContent=result.support_summary || (result.status==="clarification"?"Clarifying intent; no source-sufficiency judgment has been made.":"");
  $("supported-calculations").replaceChildren();
  for(const calculation of result.calculation_results || result.calculations || []){
    const line=document.createElement("p");
    line.textContent=typeof calculation==="string"?calculation:`${calculation.method || calculation.operation || "Supported calculation"}: ${calculation.value ?? "unresolved"}${calculation.unit?` ${calculation.unit}`:""}`;
    $("supported-calculations").append(line);
    for(const operand of calculation.operands || []){
      const input=document.createElement("p");input.className="calculation-input";input.textContent=`Input: ${operand.value} ${operand.unit || ""}${operand.label?` · ${operand.label}`:""}`;
      if(Number.isInteger(operand.evidence_index)){const link=document.createElement("button");link.type="button";link.className="text-button";link.textContent="Inspect input source ↗";link.addEventListener("click",()=>selectEvidence(operand.evidence_index));input.append(link);}
      $("supported-calculations").append(input);
    }
  }
  for(const value of result.user_value_attributions || []){
    const line=document.createElement("p");line.textContent=`Provided by user: ${(value.property||"value").replaceAll("_"," ")} = ${typeof value.value==="object"?JSON.stringify(value.value):value.value}${value.unit?` ${value.unit}`:""}. This value is not observed in the original drawing.`;$("supported-calculations").append(line);
  }
  $("evidence-checks").open=result.status!=="clarification";
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
  updateHighlights(preserveView);
  $("answer-review-note").textContent=result.review_note || "";$("answer-review-note").hidden=!result.review_note;
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
  addDetail("Evidence check", "Gemini Decisions");
  addDetail("Inspection passes", String(result.inspection_passes ?? 0));
  if(result.answered_revision_id)addDetail("Answered revision",result.answered_revision_id);
  if (state.health?.model) addDetail("Answer model", state.health.model);
  if (Number.isFinite(result.usage?.latency_ms)) addDetail("Time", `${(result.usage.latency_ms / 1000).toFixed(1)} s`);
  if (Number.isFinite(result.usage?.input_tokens)) addDetail("Input tokens", result.usage.input_tokens.toLocaleString());
  if (Number.isFinite(result.usage?.output_tokens)) addDetail("Output tokens", result.usage.output_tokens.toLocaleString());
  renderOverlay();
  announce(`${labels[result.status] || "Inspection complete"}. ${result.answer || ""}`);
  window.chatUI?.syncHighlights();
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
  state.selectedComparison = null;
  $("comparison-controls").hidden = true;
  $("comparison-overlay").setAttribute("hidden", "");
  $("comparison-overlay").replaceChildren();
  $("show-comparison").checked = false;
  $("comparison-selection").hidden = true;
  $("comparison-floor-select").replaceChildren(new Option("All floors on this page", ""));
  $("model-inventory").hidden = true;
  $("inventory-details").open = false;
  $("no-model-geometry").hidden = true;
  $("revision-notice").hidden = true;$("concept-selection").hidden=true;$("fit-model").textContent="Reset view";state.selectedProposal=null;
  $("unresolved-model-notice").hidden = true;
  $("model-canvas-container").hidden = false;
  setError("scene-error");
}

function syncViewerControls(snapshot) {
  if(!snapshot)return;
  $("floor-select").value=snapshot.floor_filter || "";$("explode-floors").checked=snapshot.exploded;
  $("cutaway-percent").value=snapshot.cutaway_percent ?? 100;updateCutawayNote();updateLayoutNote();renderFloorDetails();renderInventory();
  const selected=$("concept-proposal-select").value;
  $("concept-proposal-select").replaceChildren(new Option("Select a proposal", ""));
  for(const record of snapshot.concept_records || [])if(record.kind==="proposal")$("concept-proposal-select").append(new Option(`Proposal · ${record.label}`,record.id));
  $("concept-proposal-select").value=selected;
}
function inspectProposal(record, options = {}) {
  state.selectedProposal=record;$("element-inspector").hidden=true;
  $("concept-selection").hidden=false;$("concept-selection-name").textContent=`Proposal · ${record.label}`;
  $("concept-selection-note").textContent=record.note;
  $("concept-support-source").hidden=!state.scene?.elements.some(e=>e.id===record.host_id&&e.source.kind==="image");
  $("concept-proposal-select").value=record.id;announce(`Selected decorative proposal: ${record.label}. This is not source evidence.`);
  window.chatUI?.onProposal(record, options);
}
function setView(view) {
  if(view==="concept"&&!state.viewer)return;
  state.view=view;const concept=view==="concept",model=view==="model"||concept;
  document.body.classList.toggle("concept-mode",concept);
  $("drawing-pane").hidden=view!=="drawing";$("model-pane").hidden=!model;
  $("show-model").setAttribute("aria-pressed",String(view==="model"));$("show-concept").setAttribute("aria-pressed",String(concept));
  $("show-drawing").setAttribute("aria-pressed",String(view==="drawing"));
  $("model-caption").textContent=concept?"Drag to orbit · click source objects or amber-outlined proposals to inspect their meaning.":"Drag to orbit · scroll to zoom · right-drag to pan · click an object to inspect its source.";
  if(model&&state.viewer){state.viewer.resize();syncViewerControls(state.viewer.setMode(concept?"concept":"inspection"));requestAnimationFrame(()=>state.viewer?.resize());}
  renderInventory();
}

async function loadScene(scene) {
  if (scene.document_id !== state.document?.document_id) return;
  const updating=Boolean(state.viewer&&state.scene?.document_id===scene.document_id);
  if(updating&&(!scene.revision_id||scene.revision_id===state.scene.revision_id))return;
  const oldSceneRevision=state.scene?.revision_id;
  const oldView=state.view, oldSelected=state.selectedElement, oldProposal=state.selectedProposal, oldComparison=$("comparison-floor-select").value;
  let prepared=null;
  if(updating){try{prepared=state.viewer.prepareRevision(scene);state.viewer.commitRevision(prepared);}catch(error){setError("scene-error","The model update could not be published. The previous usable revision remains available.");return;}}
  state.scene = scene;
  const unscaled = scene.units !== "m" || (scene.floors || []).some((floor) => floor.scale_status !== "known");
  $("scene-badge").textContent = unscaled ? "Approximate · unscaled" : scene.derived ? "Calibrated footprints · assumed heights" : "IFC geometry · metres";
  $("scene-badge").classList.toggle("unscaled", unscaled);
  const count = scene.elements.filter((element) => element.geometry).length;
  $("no-model-geometry").textContent = "No 3D geometry was reconstructed. Inspect the unresolved source items below.";
  $("no-model-geometry").hidden = count > 0;
  $("model-canvas-container").hidden = count === 0;
  $("scene-summary").textContent = scene.derived ? `${scene.floors.length} interpreted floor diagrams · ${count} rendered objects. Generated geometry is a visualization, never factual source evidence. ${unscaled ? "Scale is unknown on one or more floors; relative display units cannot establish dimensions or compare physical floor sizes." : "Footprints use cited source calibration; heights and wall thicknesses remain display assumptions."}` : `${scene.elements.length} source elements · ${count} rendered${scene.source_page ? ` · source page ${scene.source_page}` : ""}. ${unscaled ? "Horizontal geometry is inferred; heights and thicknesses are assumptions in relative units." : "Coordinates and properties come from the supplied IFC. Room volumes appear when selected or highlighted."}`;
  const unknownFloors = (scene.floors || []).filter((floor) => floor.scale_status !== "known");
  if (scene.derived && unknownFloors.length && unknownFloors.every((floor) => floor.assumptions?.some((assumption) => assumption.property === "page_extent") && !floor.assumptions.some((assumption) => assumption.property === "panel_extent"))) {
    $("scene-summary").textContent += " Uncalibrated diagrams preserve drawing proportions on each source page; this does not establish physical scale or equal drawing scales. Relationships across pages or independently resized diagrams remain schematic.";
  }
  if(!updating) $("explode-floors").checked = Boolean(scene.derived && scene.floors.length > 1 && (scene.layout === "schematic" || scene.floors.some((floor) => floor.alignment_status !== "supported")));
  renderFloors();
  $("comparison-controls").hidden = !scene.derived;
  $("comparison-floor-select").replaceChildren(new Option("All floors on this page", ""));
  for (const floor of scene.floors || []) $("comparison-floor-select").append(new Option(`${floor.label} · p. ${floor.source.page}`, floor.id));
  renderComparison();
  renderInventory();
  $("scene-warnings").textContent = (scene.warnings || []).join(" ");
  $("scene-warnings").hidden = !$("scene-warnings").textContent;
  $("element-select").replaceChildren(new Option("Select a source object", ""));
  scene.elements.forEach((element) => $("element-select").append(new Option(`${element.kind} · ${element.name || element.id}${element.geometry ? "" : " (no mesh)"}`, element.id)));
  if(!updating)setView("model");
  try {
    const {BlueprintViewer} = await import("/static/viewer.js");
    if(!updating){
      state.viewer = new BlueprintViewer($("model-canvas-container"), {onSelect: inspectElement,onUnresolvedSelect: openUnresolvedAnnotation,onProposalSelect: inspectProposal});
      window.blueprintViewer = state.viewer;state.viewer.loadScene(scene);
      if ($("explode-floors").checked) state.viewer.setExploded(true);
      state.viewer.setShowAssumptions($("show-assumptions").checked);
    } else {
      syncViewerControls(state.viewer.getSnapshot());
      if((scene.floors || []).some(f=>f.id===oldComparison))$("comparison-floor-select").value=oldComparison;
      $("fit-model").textContent="Fit updated model";
      const changes=state.viewer.getSnapshot().revision_changes;
      $("revision-notice").hidden=false;
      $("revision-notice").textContent=changes.removed_selection||changes.unresolved_selection?"Model updated. The selected object was removed or is now unresolved; its previous source evidence remains available below.":"Model updated. Your view is preserved; use Fit updated model if you want new framing.";
      if(oldSelected){const current=scene.elements.find(e=>e.id===oldSelected.id);inspectElement(current || oldSelected,{automatic:true,source_revision_id:current?scene.revision_id:oldSceneRevision});if(!current)$("element-geometry-note").textContent="Removed in the current revision. Original source evidence retained; no replacement object was selected.";}
      if(oldProposal){const record=state.viewer.concept?.records.get(oldProposal.id);if(record)inspectProposal(record,{automatic:true});else{$("concept-selection").hidden=true;state.selectedProposal=null;}}
      setView(oldView);
    }
    if(updating&&state.result){state.result=answerForDisplayedRevision(state.result);$("answer-review-note").textContent=state.result.review_note || "";$("answer-review-note").hidden=!state.result.review_note;}
    updateHighlights(updating);
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
  window.chatUI?.onScene(scene);
}

function updateHighlights(preserveView = false) {
  if(window.chatUI){window.chatUI.syncHighlights();return;}
  const ids = Array.isArray(state.result?.highlight_ids) ? state.result.highlight_ids : [];
  if (!preserveView && state.viewer?.mode !== "concept" && $("floor-select").value && ids.some((id) => state.scene?.elements.some((element) => element.id === id && element.storey_id !== $("floor-select").value))) setFloorFilter("");
  state.viewer?.setHighlights(ids, $("highlight-answer").checked);
  $("highlight-note").hidden = !state.scene || !state.result;
  if (!state.scene || !state.result) return;
  const missingMeshes = ids.filter((id) => state.scene.elements.some((element) => element.id === id && !element.geometry)).length;
  $("highlight-note").textContent = ids.length ? `${ids.length} ${state.scene.derived ? "interpreted objects" : "source elements"} linked to this answer.${missingMeshes ? ` ${missingMeshes} have no renderable geometry; inspect their source records below.` : ""}` : "This answer has no reliable 3D mapping. Use its source evidence; no model objects have been highlighted.";
  if($("floor-select").value && ids.some(id=>state.scene.elements.some(e=>e.id===id&&e.storey_id!==$("floor-select").value)))$("highlight-note").textContent+=" Linked objects are on another floor. Your view is preserved; choose All floors or inspect the source evidence to locate them.";
}

function setFloorFilter(id) {
  $("floor-select").value = id;
  state.viewer?.setFloorFilter(id);
  renderFloorDetails();
  updateCutawayNote();
  renderInventory();
}

function revealEvidenceFloor(evidence) {
  if (!$("floor-select").value && !$("comparison-floor-select").value) return;
  const [l,t,r,b] = evidence.bbox || [];
  const matches = (state.scene?.floors || []).filter((floor) => {
    const [fl,ft,fr,fb] = floor.source.bbox || [];
    return floor.source.page === evidence.page && l >= fl && t >= ft && r <= fr && b <= fb;
  });
  const id = matches.length === 1 ? matches[0].id : "";
  // Source navigation leaves the 3D camera and selected floor unchanged.
  if ($("comparison-floor-select").value) $("comparison-floor-select").value = id;
}

function showSourceRegion(source, label, revision=null) {
  if(!source||source.kind==="ifc")return;
  state.evidenceRevision=revision;
  const index = state.document?.pages.findIndex((page) => page.page === source.page) ?? -1;
  if (index < 0) return;
  revealEvidenceFloor(source);
  state.sourceSelection = {...source,label};
  state.selectedEvidence = null;
  state.pageIndex = index;
  $("comparison-floor-select").value = "";
  setView("drawing");
  renderPage();
  announce(`Showing original source region for ${label}, page ${source.page}.`);
  window.chatUI?.openWorkspace("source");
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
    if(floor.source?.kind!=="image"&&!floor.source?.page)continue;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "floor-source-link";
    button.dataset.floorId = floor.id;
    button.textContent = `${floor.label} · original p. ${floor.source.page} ↗`;
    button.addEventListener("click", () => showSourceRegion(floor.source, floor.label));
    $("floor-source-links").append(button);
  }
  $("floor-source-links").hidden=!$("floor-source-links").childElementCount;
  updateCutawayNote();
  $("download-ifc").hidden = true;$("download-ifc").textContent=scene.derived?"Download derived IFC ↗":"Download source IFC ↗";
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
  if ($("explode-floors").checked) lines.push("Exploded view adds display spacing to the model’s storey elevations. It does not change source geometry.");
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
    inspectorRow(facts, "Scale", !state.scene.derived?"Supplied IFC units":floor.scale_status === "known" ? "Source-calibrated footprint" : "Unknown · relative display units");
    inspectorRow(facts,"Base elevation",`${floor.base_elevation ?? 0} · ${floor.elevation_basis || "display reference"}`);
    inspectorRow(facts,"Cutaway height reference",`${floor.reference_height ?? "Unavailable"} · ${floor.reference_height_basis || "not supplied"}`);
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

const comparisonColors = {spaces:"#347c57",walls:"#cf472e",openings:"#087cb4",features:"#7b4db1",unresolved:"#a56300"};
const svgNamespace = "http://www.w3.org/2000/svg";

function comparisonElement(id) { return state.scene?.elements.find((element) => element.id === id); }

function openUnresolvedAnnotation({floor,elements,floorLevel}) {
  if (floorLevel) {
    showSourceRegion(floor.source,`${floor.label} · unresolved items; precise locations not established`);
    $("comparison-floor-select").value=floor.id;
    state.selectedComparison=null;
    $("comparison-selection").hidden=false;
    $("comparison-selection-name").textContent=`${floor.label}: ${elements.length} unresolved ${elements.length===1 ? "item" : "items"}`;
    $("comparison-selection-detail").textContent="Only the floor source region is available; no precise object location or geometry is established. Review the individual uncertainty reasons in the source inventory below.";
    $("comparison-inspect").hidden=true;
  } else {
    showSourceRegion(elements[0].source,elements[0].name);
    selectComparison(elements[0].id);
  }
  $("show-comparison").checked=true;
  renderComparison();
  renderInventory();
  $("viewer").scrollIntoView({behavior:"smooth",block:"nearest"});
}

function selectComparison(id) {
  const element = comparisonElement(id);
  if (!element) return;
  state.selectedComparison = id;
  $("comparison-selection").hidden = false;
  $("comparison-inspect").hidden = false;
  $("comparison-selection-name").textContent = element.name || id;
  const entries = (state.scene.comparison || []).filter((entry) => entry.element_id === id);
  const methods = [...new Set(entries.map((entry) => entry.method))].join("; ");
  $("comparison-selection-detail").textContent = `${element.representation || (element.geometry ? "reconstructed" : "unresolved")} · ${element.semantic_type || element.kind}. ${element.note || ""}${methods ? ` Comparison: ${methods}.` : ""}${element.geometry ? "" : " Source region only; no geometry is implied."}`;
  renderComparison();
  announce(`Selected comparison item ${element.name || id}. ${element.geometry ? "" : "Unresolved source region; no generated geometry."}`);
}

function renderComparison() {
  const overlay = $("comparison-overlay");
  overlay.replaceChildren();
  const enabled = Boolean(state.scene?.derived && $("show-comparison").checked && (!state.evidenceRevision||state.evidenceRevision===state.scene.revision_id));
  $("comparison-options").hidden = !enabled;
  overlay.toggleAttribute("hidden", !enabled);
  if (!enabled) return;
  const page = displayPages()[state.pageIndex]?.page;
  const floor = $("comparison-floor-select").value;
  const layers = new Set([...document.querySelectorAll("[data-comparison-layer]:checked")].map((input) => input.dataset.comparisonLayer));
  const entries = (state.scene.comparison || []).filter((entry) => entry.page === page && (!floor || entry.floor_id === floor) && layers.has(entry.layer));
  const order = ["spaces","walls","openings","features","unresolved"];
  entries.sort((a,b) => order.indexOf(a.layer)-order.indexOf(b.layer));
  const opacity = Number($("comparison-opacity").value) / 100;
  $("comparison-opacity-value").textContent = `${Math.round(opacity*100)}%`;
  for (const entry of entries) {
    const element = comparisonElement(entry.element_id);
    if (!element) continue;
    const group = document.createElementNS(svgNamespace,"g");
    group.dataset.elementId = element.id;
    group.dataset.layer = entry.layer;
    group.classList.add("comparison-item");
    group.setAttribute("tabindex","0");
    group.setAttribute("role","button");
    group.setAttribute("aria-label",`${element.name} · ${entry.layer === "unresolved" ? "unresolved source region" : `${entry.layer} comparison`}`);
    group.setAttribute("aria-pressed",String(state.selectedComparison === element.id));
    group.setAttribute("stroke",comparisonColors[entry.layer] || comparisonColors.features);
    const appendPath = (paths, closed) => {
      const valid = paths.filter((points) => points.length >= (closed ? 3 : 2) && points.every((point) => point.length === 2 && point.every(Number.isFinite)));
      if (!valid.length) return;
      const path = document.createElementNS(svgNamespace,"path");
      path.setAttribute("d",valid.map((points) => `M${points.map((point) => point.join(",")).join(" L")}${closed ? " Z" : ""}`).join(" "));
      path.setAttribute("fill",closed ? comparisonColors[entry.layer] : "none");
      path.setAttribute("fill-opacity",String(opacity*.42));
      path.setAttribute("stroke-opacity",String(opacity));
      path.setAttribute("fill-rule","evenodd");
      path.setAttribute("vector-effect","non-scaling-stroke");
      path.setAttribute("stroke-width",state.selectedComparison === element.id ? "3" : "1.6");
      group.append(path);
    };
    if (entry.layer === "unresolved") {
      const [l,t,r,b] = element.source.bbox;
      appendPath([[[l,t],[r,t],[r,b],[l,b]]],true);
      group.classList.add("comparison-unresolved");
    } else {
      appendPath(entry.polygons || [],true);
      appendPath(entry.lines || [],false);
    }
    if (!group.childElementCount) continue;
    const title = document.createElementNS(svgNamespace,"title");
    title.textContent = `${element.name} · ${entry.layer === "unresolved" ? "Source region only; no reconstructed geometry" : entry.method}`;
    group.append(title);
    group.addEventListener("click",() => selectComparison(element.id));
    group.addEventListener("keydown",(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); selectComparison(element.id); } });
    overlay.append(group);
  }
  $("comparison-note").textContent = entries.length ? "Actual IFC geometry mapped back to this original page. Walls are display sections through assumed opening heights, not measured elevations. Dashed amber boxes identify unresolved source regions, not generated shapes." : "No comparison paths are available for these page, floor and layer selections. This does not establish that the original drawing has no features.";
}

function renderInventory() {
  const panel = $("model-inventory");
  panel.hidden = !state.scene?.derived;
  if (panel.hidden) { $("unresolved-model-notice").hidden=true; return; }
  const floor = $(state.view === "drawing" ? "comparison-floor-select" : "floor-select").value;
  const page = displayPages()[state.pageIndex]?.page;
  const elements = state.scene.elements.filter((element) => (!floor || element.storey_id === floor) && (state.view !== "drawing" || element.source.page === page));
  const modelUnresolved=state.scene.elements.filter((element)=>(element.representation === "unresolved" || !element.geometry) && (!$("floor-select").value || element.storey_id === $("floor-select").value));
  $("unresolved-model-notice").hidden=!modelUnresolved.length;
  $("unresolved-model-count").textContent=`${modelUnresolved.length} unresolved source ${modelUnresolved.length===1 ? "item" : "items"}${$("floor-select").value ? " on this floor" : ""}`;
  const counts = {reconstructed:0,schematic:0,unresolved:0};
  for (const element of elements) counts[element.representation || (element.geometry ? "reconstructed" : "unresolved")]++;
  $("inventory-counts").textContent = `${counts.reconstructed} reconstructed · ${counts.schematic} schematic · ${counts.unresolved} unresolved${state.view === "drawing" ? ` · page ${page}` : ""}${floor ? " · selected floor" : ""}.`;
  const kinds = new Map();
  for (const element of elements) { const kind = element.semantic_type || element.kind; kinds.set(kind,(kinds.get(kind) || 0)+1); }
  $("inventory-kind-counts").textContent = [...kinds].map(([kind,count]) => `${kind}: ${count}`).join(" · ");
  $("inventory-items").replaceChildren();
  for (const element of elements) {
    const button = document.createElement("button");
    button.type = "button"; button.className = "inventory-source-item"; button.dataset.elementId = element.id;
    button.textContent = `${element.name} · ${element.semantic_type || element.kind} · ${element.representation || (element.geometry ? "reconstructed" : "unresolved")} · p. ${element.source.page} ↗`;
    button.addEventListener("click",() => { showSourceRegion(element.source,element.name); $("show-comparison").checked = true; selectComparison(element.id); });
    $("inventory-items").append(button);
  }
  $("unresolved-items").replaceChildren();
  for (const element of elements.filter((item) => item.representation === "unresolved" || !item.geometry)) {
    const button = document.createElement("button"), label = document.createElement("strong"), reason = document.createElement("span");
    button.type = "button"; button.className = "unresolved-item"; button.dataset.elementId = element.id;
    label.textContent = `${element.name} · ${element.semantic_type || element.kind} · p. ${element.source.page}`;
    reason.textContent = element.note || "No renderable geometry; inspect the original source region.";
    button.append(label,reason);
    button.addEventListener("click",() => { showSourceRegion(element.source,element.name); $("show-comparison").checked = true; selectComparison(element.id); });
    $("unresolved-items").append(button);
  }
}

function inspectElement(element, options = {}) {
  state.selectedProposal=null;$("concept-selection").hidden=true;
  state.selectedElement = element;
  if (state.viewer && $("floor-select").value !== state.viewer.floorFilter) { $("floor-select").value = state.viewer.floorFilter; renderFloorDetails(); renderInventory(); }
  $("element-select").value = element.id;
  $("element-inspector").hidden = false;
  $("element-name").textContent = element.name || element.id;
  $("element-origin").textContent = element.geometry_origin === "inferred" ? "Geometry: inferred interpretation of the source image." : "Geometry: extracted from the supplied IFC model.";
  $("element-geometry-note").textContent = element.geometry ? `${element.kind} · ${element.ifc_type || "image reconstruction"}` : "This source element has no renderable geometry. Its properties are still available and it remains in the source catalog.";
  $("element-identity").replaceChildren();
  inspectorRow($("element-identity"), "Element ID", element.id);
  if (state.scene?.derived) {
    inspectorRow($("element-identity"), "Representation", element.representation || "reconstructed");
    if (element.semantic_type) inspectorRow($("element-identity"), "Interpreted feature", element.semantic_type);
    if (element.environment && element.environment !== "unknown") inspectorRow($("element-identity"), "Environment", `${element.environment} · source interpretation`);
  }
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
  if (element.representation === "unresolved") $("element-geometry-note").textContent = `Unresolved source item. ${element.note || "No reliable geometry was reconstructed."}`;
  else if (element.representation === "schematic") $("element-geometry-note").textContent = `${element.kind} · schematic symbol; its displayed dimensions are not source measurements.`;
  $("element-properties").replaceChildren();
  for (const property of element.properties || []) inspectorRow($("element-properties"), `${property.name}${property.origin === "derived" ? " (derived)" : ""}`, `${property.value ?? "Not specified"}${property.unit ? ` ${property.unit}` : ""}`);
  if (!element.properties?.length) inspectorRow($("element-properties"), "Properties", "No additional properties provided.");
  $("element-assumptions").replaceChildren();
  for (const assumption of element.assumptions || []) inspectorRow($("element-assumptions"), assumption.property, `${assumption.value}${assumption.unit ? ` ${assumption.unit}` : ""} — ${assumption.reason}`);
  const conceptRecord=state.viewer?.concept?.records.get(element.id);
  if(conceptRecord)inspectorRow($("element-assumptions"),"Concept presentation",conceptRecord.note);
  $("element-assumptions-section").hidden = !element.assumptions?.length && !conceptRecord;
  $("element-source").hidden = element.source.kind !== "image";
  announce(`Selected ${element.name || element.id}. Source properties are available below the model.`);
  window.chatUI?.onSelection(element, options);
}

function selectModelElement(id) {
  const element = state.scene?.elements.find((item) => item.id === id);
  if (!element) return;
  if(state.view!=="concept")setView("model");
  if (state.viewer) state.viewer.select(id); else inspectElement(element);
}

function ifcReference(reference) {
  if(!reference)return "Source reference not provided";
  return [reference.ifc_type,reference.global_id?`GlobalId ${reference.global_id}`:null,reference.step_id?`STEP #${reference.step_id}`:null].filter(Boolean).join(" · ") || JSON.stringify(reference);
}
function nativeValue(value) {return typeof value==="object"?JSON.stringify(value):String(value ?? "Not supplied");}
async function inspectNativeEvidence(item, revisionOverride = null) {
  const building=state.document?.building_id,revision=revisionOverride || state.result?.answered_revision_id || state.scene?.revision_id || state.document?.revision_id;
  const epoch=state.epoch,token=state.nativeEvidenceToken=(state.nativeEvidenceToken || 0)+1;
  if(state.scene?.elements.some(element=>element.id===item.element_id&&element.geometry))selectModelElement(item.element_id);
  $("native-record-inspector").hidden=false;$("native-record-name").textContent=item.label || "Original IFC record";$("native-record-note").textContent="Loading the original source record from the answered revision…";
  $("native-record-identity").replaceChildren();$("native-record-values").replaceChildren();$("native-record-coverage").textContent="";
  if(!building||!revision){$("native-record-note").textContent="A saved source revision is needed to inspect the full original record. The existing model remains available.";return;}
  try{
    const payload=await request(`/api/buildings/${encodeURIComponent(building)}/revisions/${encodeURIComponent(revision)}/evidence/${encodeURIComponent(item.element_id)}`);
    if(epoch!==state.epoch||token!==state.nativeEvidenceToken)return;
    if(payload.source_kind!=="ifc"||payload.building_id!==building||payload.revision_id!==revision||payload.record?.id!==item.element_id)throw new Error("The source record did not match this citation's building and revision.");
    const record=payload.record;
    $("native-record-name").textContent=record.name || record.ifc_type || record.id;
    $("native-record-note").textContent=`Original supplied IFC record from the answered revision. ${record.geometry_available?"Source geometry is available.":"This record has no viewer geometry; its original properties remain evidence."} Values describe the supplied model, not a survey of the built building.`;
    inspectorRow($("native-record-identity"),"Record ID",record.id);inspectorRow($("native-record-identity"),"IFC type",record.ifc_type);
    inspectorRow($("native-record-identity"),"Original reference",ifcReference(record.source));inspectorRow($("native-record-identity"),"Answered revision",revision);
    for(const [name,value]of Object.entries(record.values || {})){
      const details=document.createElement("details"),summary=document.createElement("summary"),provenance=document.createElement("p");details.open=name===item.property_name;
      summary.textContent=`${name}: ${nativeValue(value.value)}${value.unit?` ${value.unit}`:""}`;
      provenance.textContent=[`Provenance: ${value.provenance || "not specified"}`,ifcReference(value.source || record.source),value.owner?`Owner: ${ifcReference(value.owner)}`:"",value.method || ""].filter(Boolean).join(" · ");
      details.append(summary,provenance);$("native-record-values").append(details);
    }
    if(!Object.keys(record.values || {}).length)$("native-record-values").textContent="No extracted values are available for this source record.";
    $("native-record-coverage").textContent=JSON.stringify({coverage:payload.coverage,record_limitations:record.missing || []},null,2);
  }catch(error){if(epoch===state.epoch&&token===state.nativeEvidenceToken)$("native-record-note").textContent=`${error.message} No source property was invented.`;}
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
    const native=state.document?.kind==="ifc"&&!state.scene?.derived;
    button.disabled=!item.element_id || (!native&&!state.scene?.elements.some(element=>element.id===item.element_id));
    button.addEventListener("click",()=>native?inspectNativeEvidence(item):selectModelElement(item.element_id));
    $("model-evidence-list").append(button);
  }
}

function renderSourceList() {
  $("source-list").replaceChildren();
  $("page-count").textContent=state.document?.kind==="ifc"?"IFC model":`${state.document?.pages.length||0} pages`;
  for(const source of state.document?.sources || []){
    const row=document.createElement("div");row.className="source-file";
    const label=document.createElement("strong"),note=document.createElement("span");
    label.textContent=source.filename;note.textContent=`${source.kind || "source"} · ${source.pages?.length || 0} pages · ${source.interpretation_status || "original preserved"}`;
    row.append(label,note);
    const pageIndex=state.document.pages.findIndex(page=>page.source_id===source.source_id);
    if(pageIndex>=0){const open=document.createElement("button");open.type="button";open.className="text-button";open.textContent="Open source ↗";open.addEventListener("click",()=>{state.pageIndex=pageIndex;state.evidenceRevision=null;state.sourceSelection=null;state.selectedEvidence=null;setView("drawing");renderPage();});row.append(open);}
    const original=document.createElement("a");original.className="text-button";original.textContent="Download original";original.download=source.filename;original.href=`/api/buildings/${state.document.building_id}/sources/${encodeURIComponent(source.source_id)}/original`;row.append(original);
    $("source-list").append(row);
  }
}

function updateCutawayNote() {
  const percent=Number($("cutaway-percent").value);$("cutaway-value").textContent=`${percent}%`;
  const scene=state.scene;if(!scene){$("cutaway-note").textContent="";return;}
  const floors=(scene.floors||[]).filter(f=>!$("floor-select").value||f.id===$("floor-select").value);
  const references=floors.map(f=>`${f.label}: ${Number.isFinite(f.reference_height)?f.reference_height:"unavailable"} ${scene.units==="m"?"m":"display units"} (${f.reference_height_basis || "display extent; not a source measurement"})`);
  $("cutaway-note").textContent=`0% clips at the storey base; 100% shows full geometry. ${$("floor-select").value?"Selected floor":"All floors: the same percentage applies separately to each storey"}. ${references.join("; ")}${scene.uncontained_reference&&!$("floor-select").value?` Uncontained geometry uses a separate scene reference: ${scene.uncontained_reference.basis}.`:""}`;
}

async function refreshConversation() {
  if(!progressiveDocument() || (state.document.sources?.length || 0) > 1)return;
  const epoch=state.epoch,id=state.document.building_id;
  try{
    const payload=await request(`/api/buildings/${id}/conversation`,{},15000);if(epoch!==state.epoch)return;
    state.conversation=payload.messages || [];renderConversation();setError("conversation-error");
  }catch(error){if(epoch===state.epoch)setError("conversation-error",`Conversation history is unavailable: ${error.message}`);}
}
function renderConversation() {
  if(window.chatUI){window.chatUI.mergeConversation(state.conversation);return;}
  const container=$("conversation");container.replaceChildren();
  const latestAssistant=[...state.conversation].reverse().find(m=>m.answer);
  state.clarificationReply=latestAssistant?.answer?.status==="clarification"?latestAssistant.id:null;
  for(const message of state.conversation){
    const item=document.createElement("article");item.className=`chat-message ${message.role==="user"?"chat-user":"chat-assistant"}`;item.dataset.messageId=message.id;
    const name=document.createElement("strong"),text=document.createElement("p");name.textContent=message.role==="user"?"You":message.answer?.status==="clarification"?"Clarification":"Blueprint QA";
    text.textContent=message.answer?.clarification?.message || message.answer?.answer || message.question || message.content || "";item.append(name,text);
    if(message.answer){
      const open=document.createElement("button");open.type="button";open.className="text-button";open.textContent="Evidence and checks ↗";
      open.addEventListener("click",()=>{renderResult(message.answer,true);state.clarificationReply=message.answer.status==="clarification"?message.id:null;$("result").scrollIntoView({block:"nearest",behavior:"smooth"});});item.append(open);
      for(const [i,evidence] of (message.answer.evidence||[]).entries()){
        const link=document.createElement("button");link.type="button";link.className="chat-citation";link.textContent=`${evidence.label} · p. ${evidence.source_page || evidence.page} ↗`;
        link.addEventListener("click",()=>{renderResult(message.answer,true);selectEvidence(i);});item.append(link);
      }
      if(message.answer.status==="clarification")for(const suggestion of message.answer.clarification?.suggestions||[]){
        const button=document.createElement("button");button.type="button";button.className="chat-citation";button.textContent=suggestion;
        button.addEventListener("click",()=>{state.clarificationReply=message.id;$("question").value=suggestion;updateControls();$("question-form").requestSubmit();});item.append(button);
      }
    }
    container.append(item);
  }
  if(state.conversation.length)$("answer-empty").hidden=true;
}

async function refreshAssumptions() {
  if(!progressiveDocument())return;
  const epoch=state.epoch,id=state.document.building_id;
  try{
    const payload=await request(`/api/buildings/${id}/assumptions`,{},15000);if(epoch!==state.epoch)return;
    // Keep unsent edits pinned to the revision the user actually inspected.
    if(!state.assumptionEdits.size)state.assumptionsRevision=payload.revision_id;
    state.assumptionDataRevision=payload.revision_id;state.assumptionRows=payload.rows || [];renderAssumptions();setError("assumption-error");window.dispatchEvent(new CustomEvent("blueprint:workspace"));
  }catch(error){if(epoch===state.epoch)setError("assumption-error",error.message);}
}
function renderAssumptions() {
  const container=$("assumption-rows");container.replaceChildren();
  const groups=["observed","inferred","display_assumption","unknown","user_provided"];
  for(const provenance of [...groups,...new Set(state.assumptionRows.map(r=>r.provenance).filter(p=>!groups.includes(p)))]){
    const rows=state.assumptionRows.filter(r=>r.provenance===provenance);if(!rows.length)continue;
    const section=document.createElement("section"),title=document.createElement("h4");title.textContent=provenance.replaceAll("_"," ");section.append(title);
    for(const row of rows){
      const item=document.createElement("div");item.className="assumption-row";item.dataset.assumptionId=row.id;
      const label=document.createElement("label"),reason=document.createElement("small");label.textContent=row.label || row.property;reason.textContent=row.reason || "";item.append(label,reason);
      if(row.source){const source=document.createElement("button");source.type="button";source.className="text-button";source.textContent="Locate source ↗";source.addEventListener("click",()=>{if(row.scope?.object_id&&state.scene?.elements.some(e=>e.id===row.scope.object_id))state.viewer?.select(row.scope.object_id);showSourceRegion(row.source,row.label || row.property);});item.append(source);}
      if(row.editable&&["calibration","stair_connection"].includes(row.property)){
        item.append(structuredAssumptionEditor(row));
      }else if(row.editable){
        const input=document.createElement("input"),unit=document.createElement("input");input.id=`assumption-${row.id}`;label.htmlFor=input.id;
        const edit=state.assumptionEdits.get(row.id);const current=edit?edit.value:row.value;
        input.value=current==null?"":typeof current==="object"?JSON.stringify(current):String(current);
        input.type=["floor_height","display_height"].includes(row.property)?"number":"text";
        if(input.type==="number"){input.step="any";input.min="0";}
        input.placeholder=row.property==="calibration"?'{"length": 5, "segment": [[0.1,0.1],[0.5,0.1]]}':row.property==="stair_connection"?'{"target_floor_id":"…"}':"Provide missing value";
        unit.value=edit?.unit ?? row.unit ?? "";unit.setAttribute("aria-label",`${row.label || row.property} units`);unit.placeholder="units";unit.className="assumption-unit";
        const update=()=>{state.assumptionEdits.set(row.id,{property:row.property,scope:row.scope||{},value:input.value,unit:unit.value||null,source:row.source||null,reason:"Provided through assumptions panel"});updateAssumptionButton();};
        input.addEventListener("input",update);unit.addEventListener("input",update);item.append(input,unit);
      }else{const value=document.createElement("span");value.textContent=`${row.value==null?"Unknown":typeof row.value==="object"?JSON.stringify(row.value):row.value}${row.unit?` ${row.unit}`:""}`;item.append(value);}
      section.append(item);
    }
    container.append(section);
  }
  if(!state.assumptionRows.length)container.textContent="Source interpretation has not supplied any grouped inputs yet. Originals remain available for questions.";
  const selected=new Set([...$("assumption-support").selectedOptions].map(o=>o.value));
  $("assumption-support").replaceChildren();
  for(const source of state.document?.sources||[]){const option=new Option(source.filename,source.source_id);option.selected=selected.has(source.source_id);$("assumption-support").append(option);}
  updateAssumptionButton();
}
function structuredAssumptionEditor(row) {
  const group=document.createElement("div");group.className="structured-input";
  const saved=state.assumptionEdits.get(row.id),current=saved?.value || row.value || {};
  const base={property:row.property,scope:row.scope||{},source:row.source||null,reason:"Provided through assumptions panel"};
  if(row.property==="stair_connection"){
    const select=document.createElement("select");select.setAttribute("aria-label",`${row.label}: destination floor`);select.append(new Option("Choose destination floor", ""));
    for(const floor of state.assumptionRows.filter(r=>r.property==="floor_height"&&r.scope?.floor_id!==row.scope?.floor_id&&r.provenance!=="user_provided"))select.append(new Option(floor.label.replace(/: storey height$/, ""),floor.scope.floor_id));
    select.value=current.target_floor_id || "";
    const target=document.createElement("input");target.placeholder="Target stair ID (optional)";target.setAttribute("aria-label","Target stair ID (optional)");target.value=current.target_feature_id||"";
    const update=()=>{state.assumptionEdits.set(row.id,{...base,value:{target_floor_id:select.value,...(target.value?{target_feature_id:target.value}:{})},unit:null});updateAssumptionButton();};select.addEventListener("change",update);target.addEventListener("input",update);group.append(select,target);
  }else{
    const inputs=[];
    for(const [i,name] of ["Known distance","Start X (0–1)","Start Y (0–1)","End X (0–1)","End Y (0–1)"].entries()){
      const label=document.createElement("label"),input=document.createElement("input");label.textContent=name;input.type="number";input.step="any";input.setAttribute("aria-label",`${row.label}: ${name}`);
      input.value=(i===0?current.length:current.segment?.[Math.floor((i-1)/2)]?.[(i-1)%2])??"";inputs.push(input);label.append(input);group.append(label);
    }
    const unit=document.createElement("input");unit.value=saved?.unit??row.unit??"m";unit.setAttribute("aria-label",`${row.label} units`);group.append(unit);
    const note=document.createElement("small");note.textContent="Endpoints use original page coordinates: 0 at the left/top, 1 at the right/bottom. A known vertical height does not calibrate this distance.";group.append(note);
    const update=()=>{const values=inputs.map(i=>i.value===""?null:Number(i.value));state.assumptionEdits.set(row.id,{...base,value:{length:values[0],segment:[[values[1],values[2]],[values[3],values[4]]]},unit:unit.value});updateAssumptionButton();};
    for(const input of [...inputs,unit])input.addEventListener("input",update);
  }
  return group;
}
function updateAssumptionButton() {
  $("apply-assumptions").disabled=!state.assumptionEdits.size||state.applyingAssumptions;
  $("assumption-edit-count").textContent=state.assumptionEdits.size?`${state.assumptionEdits.size} pending edits · supplied values retain user provenance`:"";
}
async function applyAssumptions() {
  if(!state.document||!state.assumptionEdits.size||state.applyingAssumptions)return;
  const epoch=state.epoch;state.applyingAssumptions=true;updateAssumptionButton();setError("assumption-error");
  try{
    const edits=[...state.assumptionEdits.values()].map(edit=>{
      const copy={...edit};
      if(["floor_height","display_height"].includes(edit.property)){copy.value=Number(edit.value);if(!Number.isFinite(copy.value)||copy.value<=0)throw new Error("Heights must be positive finite values with explicit units.");}
      if(["calibration","stair_connection"].includes(edit.property)&&typeof edit.value==="string"){try{copy.value=JSON.parse(edit.value);}catch{throw new Error("Complete the source-linked input fields before applying.");}}
      return copy;
    });
    const job=await request(`/api/buildings/${state.document.building_id}/refinements`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({base_revision_id:state.assumptionsRevision,edits,supporting_source_ids:[...$("assumption-support").selectedOptions].map(o=>o.value)})});
    if(epoch!==state.epoch)return;state.assumptionEdits.clear();rememberJob(job);schedulePoll(0);
  }catch(error){if(epoch===state.epoch)setError("assumption-error",error.message);}
  finally{state.applyingAssumptions=false;updateAssumptionButton();}
}
$("retry-extraction").addEventListener("click",async()=>{const epoch=state.epoch;try{const payload=await request(`/api/buildings/${state.document.building_id}/extraction`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({retry:true})});if(epoch===state.epoch){for(const job of payload.jobs||[])rememberJob(job);schedulePoll(0);}}catch(error){if(epoch===state.epoch)setError("building-poll-error",error.message);}});
$("apply-assumptions").addEventListener("click",applyAssumptions);

$("generate-scene").addEventListener("click",()=>startReconstruction("reconstruct"));
$("refine-building").addEventListener("click",()=>startReconstruction("refine"));
$("reconstruct-building").addEventListener("click",()=>startReconstruction("reconstruct"));
$("refresh-building").addEventListener("click",()=>refreshBuilding());
$("refresh-buildings").addEventListener("click",refreshSavedBuildings);
$("saved-building-select").addEventListener("change",updateControls);
$("open-building").addEventListener("click",()=>openBuilding($("saved-building-select").value));
$("show-drawing").addEventListener("click", () => setView("drawing"));
$("show-model").addEventListener("click", () => setView("model"));
$("show-concept").addEventListener("click",()=>setView("concept"));
$("cutaway-percent").addEventListener("input",()=>{state.viewer?.setCutawayPercent(Number($("cutaway-percent").value));updateCutawayNote();});
$("concept-proposal-select").addEventListener("change",()=>{const record=state.viewer?.concept?.records.get($("concept-proposal-select").value);if(record){state.viewer.selectedProposalId=record.id;state.viewer.applyAppearance();inspectProposal(record);}});
$("concept-support-source").addEventListener("click",()=>{const host=state.scene?.elements.find(e=>e.id===state.selectedProposal?.host_id);if(host)showSourceRegion(host.source,`Supporting area for proposal: ${state.selectedProposal.label}`);});
$("highlight-answer").addEventListener("change", updateHighlights);
$("show-assumptions").addEventListener("change", () => state.viewer?.setShowAssumptions($("show-assumptions").checked));
$("fit-model").addEventListener("click", () => state.viewer?.fit());
$("review-unresolved").addEventListener("click",() => {
  $("unresolved-items").scrollIntoView({behavior:"smooth",block:"nearest"});
  $("unresolved-items").querySelector("button")?.focus({preventScroll:true});
});
$("floor-select").addEventListener("change", () => setFloorFilter($("floor-select").value));
$("show-comparison").addEventListener("change",renderComparison);
$("comparison-opacity").addEventListener("input",renderComparison);
document.querySelectorAll("[data-comparison-layer]").forEach((input) => input.addEventListener("change",renderComparison));
$("comparison-floor-select").addEventListener("change",() => {
  const floor = state.scene?.floors.find((item) => item.id === $("comparison-floor-select").value);
  if (floor) { state.pageIndex = state.document.pages.findIndex((page) => page.page === floor.source.page); renderPage(); }
  else { renderComparison(); renderInventory(); }
});
$("comparison-inspect").addEventListener("click",() => selectModelElement(state.selectedComparison));
$("explode-floors").addEventListener("change", () => { state.viewer?.setExploded($("explode-floors").checked); updateLayoutNote(); });
$("element-select").addEventListener("change", () => selectModelElement($("element-select").value));
$("element-source").addEventListener("click", () => {
  const element = state.selectedElement;
  if (!element || element.source.kind !== "image") return;
  showSourceRegion(element.source, element.name);
});

$("question-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if(window.chatUI){window.chatUI.submit();return;}
  const question=$("question").value.trim();
  if(!question||!state.document||state.busy||state.askSubmitting||!state.providerReady||voice?.recording)return;
  voice?.cancelAll();
  resetAnswer();$("answer-empty").hidden=true;
  const epoch=state.epoch,building=state.document.document_id;
  if(state.document.building_id&&state.document.revision_id){
    const requestId=crypto.randomUUID();state.questionRequest={id:requestId,building,pending:true};state.askSubmitting=true;updateControls();
    try {
      const job=await request("/api/questions",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({document_id:building,question,revision_id:state.document.revision_id,request_id:requestId,conversation_id:state.document.building_id,reply_to:state.clarificationReply,clarification_response:state.clarificationReply?question:null})});
      if(epoch===state.epoch&&state.questionRequest?.id===requestId){rememberJob(job);if($("question").value.trim()===question)$("question").value="";state.clarificationReply=null;refreshConversation();schedulePoll(0);}
    }catch(error){if(epoch===state.epoch&&state.questionRequest?.id===requestId){state.questionRequest.pending=false;setError("ask-error",error.message);$("answer-empty").hidden=false;}}
    finally{if(epoch===state.epoch){state.askSubmitting=false;updateControls();}}
    return;
  }
  state.busy="ask";const version=++state.requestVersion;updateControls();
  try{const result=await request("/api/ask",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({document_id:building,question})});if(version===state.requestVersion){renderResult(result);voice?.answerReady(result);}}
  catch(error){if(version===state.requestVersion){setError("ask-error",error.message);$("answer-empty").hidden=false;announce("The request failed. No answer was confirmed.");}}
  finally{state.busy=null;updateControls();}
});

$("file-input").addEventListener("change", (event) => {
  const files = Array.from(event.target.files);
  event.target.value = "";
  uploadFile(files);
});
$("question").addEventListener("input", updateControls);
suggestions.forEach((button) => button.addEventListener("click", () => { $("question").value = button.dataset.question; updateControls(); $("question").focus(); }));
function changePage(direction) {
  if (!state.document) return;
  const pages=displayPages(),index=state.pageIndex+direction;
  if(index<0||index>=pages.length)return;
  if(window.chatUI)return window.chatUI.execute({type:"browse_source",page:pages[index].page,source_revision_id:window.chatUI.sourceView().revision_id}).catch(error=>setError("upload-error",error.message));
  state.evidenceRevision=null;state.pageIndex=index;$("comparison-floor-select").value="";renderPage();
}
$("previous-page").addEventListener("click", () => changePage(-1));
$("next-page").addEventListener("click", () => changePage(1));
$("viewer").addEventListener("keydown", (event) => { if (event.key === "ArrowLeft" || event.key === "ArrowRight") { event.preventDefault(); changePage(event.key === "ArrowLeft" ? -1 : 1); } });
$("zoom").addEventListener("change", () => setDrawingZoom(`${Number($("zoom").value)}%`));
$("page-image").addEventListener("error", () => setError("upload-error", "The drawing preview could not be loaded. Try uploading the file again."));
$("page-image").addEventListener("load", () => {
  updateDrawingFit();
  renderOverlay();
});
new ResizeObserver(updateDrawingFit).observe($("viewer"));
$("refresh-health").addEventListener("click", checkHealth);
voice = new window.BlueprintVoice({state: () => state, request, updateControls});
updateControls();
checkHealth();
refreshSavedBuildings();
