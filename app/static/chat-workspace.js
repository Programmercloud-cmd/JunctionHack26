/* Conversation controller. Existing app.js functions own HTTP operations and evidence. */
"use strict";
(() => {
  const log = $("chat-log"), scroll = $("chat-scroll");
  const homeTab = $("home-tab"), detailsTab = $("details-tab");
  const debugQuestionJobs = new Set();
  const ui = {documentId:null, activeTab:"home", view_mode:"chat", selected_ids:[], focused_id:null, geometry_revision_id:null,
    navigation_epoch:0, highlighting:true, answer_highlighting:true, show_assumptions:false,
    tour:{ids:[],index:-1,running:false}, timer:null, camera:null, entries:new Map(), clarification:null,
    theme:"system", initialScene:true, updatingSelection:false, inspection:null, pageCatalogs:new Map(), sourceCatalog:null, sourcePages:new Map(), submitOrder:0, latestQuestionOrder:0, latestSubmissionId:null};
  const clone = value => JSON.parse(JSON.stringify(value));
  const element = (tag, text, className) => {const node=document.createElement(tag);if(text!=null)node.textContent=text;if(className)node.className=className;return node;};
  const button = (label, fn, className="chat-inline-button") => {const node=element("button",label,className);node.type="button";node.addEventListener("click",()=>Promise.resolve(fn()).catch(error=>note(error.message,"error:"+crypto.randomUUID())));return node;};
  const jsonPost = (path,data) => request(path,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(data)});
  function entry(key,role="assistant") {
    if(ui.entries.has(key))return ui.entries.get(key);
    const node=element("article",null,`chat-turn chat-${role}`);node.dataset.entry=key;
    node.append(element("p",role==="user"?"You":"Blueprint","chat-role"));log.append(node);ui.entries.set(key,node);
    // Provider setup is status, not a conversation: cached buildings must stay
    // discoverable before a document is open even when inference is unavailable.
    if(key!=="provider-setup" && (ui.activeTab === "details" || !key.startsWith("job:")))scroll.scrollTop=scroll.scrollHeight;
    return node;
  }
  function removeEntry(key){ui.entries.get(key)?.remove();ui.entries.delete(key);}
  function note(message,key="note:"+crypto.randomUUID(),actions=[]){
    const node=entry(key),signature=JSON.stringify([message,actions]);if(node.dataset.note===signature)return node;node.dataset.note=signature;node.replaceChildren(element("p","Blueprint","chat-role"),element("p",message));
    if(actions.length){const controls=element("div",null,"chat-actions");for(const [label,action] of actions)controls.append(button(label,()=>local(action)));node.append(controls);}
    if(key!=="provider-setup")scroll.scrollTop=scroll.scrollHeight;return node;
  }
  function changed(){window.dispatchEvent(new CustomEvent("blueprint:workspace"));}
  function inspection(){return ui.inspection?clone(ui.inspection):null;}
  function sourceView(){
    const catalog=ui.sourceCatalog?.revision_id===state.evidenceRevision?ui.sourceCatalog:null;
    const pages=catalog?.pages||state.document?.pages||[];
    return clone({pages,revision_id:catalog?.revision_id||state.document?.revision_id||null,page:pages[state.pageIndex]?.page??pages[0]?.page??null});
  }
  function contextNow(){return {epoch:ui.navigation_epoch,document_epoch:state.epoch,document_id:state.document?.document_id,revision_id:state.document?.revision_id,request_id:crypto.randomUUID(),reply_to:state.clarificationReply,order:++ui.submitOrder};}
  function sameDocument(context){return context.document_epoch===state.epoch&&context.document_id===state.document?.document_id;}
  function pause(){clearTimeout(ui.timer);ui.timer=null;ui.tour.running=false;}
  function invalidate(){pause();ui.navigation_epoch++;}
  function snapshot(){
    return clone({geometry_revision_id:ui.geometry_revision_id,view_mode:ui.view_mode,selected_ids:ui.selected_ids,focused_id:ui.focused_id,
      camera:state.viewer?.getCameraState()||ui.camera,tour:ui.tour,navigation_epoch:ui.navigation_epoch,highlighting:ui.highlighting,
      answer_highlighting:ui.answer_highlighting,show_assumptions:ui.show_assumptions,floor_id:state.viewer?.floorFilter||null,
      exploded:state.viewer?.exploded||false,cutaway:state.viewer?.cutawayPercent??100});
  }
  function syncControls(){
    syncTabs();
    syncLibrary();
    $("chat-composer").hidden = !chatAvailable();
    $("question").disabled=state.busy==="upload" || !chatAvailable();$("question").placeholder=state.document?"Ask about the drawing, or tell me what to show…":"Ask a question or attach your blueprints…";
    $("ask-button").disabled=!chatAvailable()||state.busy==="upload"||!state.providerReady||Boolean(voice?.recording)||!$("question").value.trim();$("ask-label").textContent="Send";
    $("chat-connection").textContent=state.providerReady?`${state.health?.provider_label||"Gemini"} · local workspace`:"Provider unavailable";
    if(state.health&&!state.providerReady)note($("provider-message").textContent||"Configure the selected provider to interpret messages. Saved sources remain available.","provider-setup",[["Check connection",{type:"refresh_health"}]]);
    else removeEntry("provider-setup");
  }
  function applyTheme(choice){
    ui.theme=choice;let theme=choice==="system"?(matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light"):choice;
    document.documentElement.dataset.theme=theme;document.querySelector('meta[name="theme-color"]').content=theme==="dark"?"#121110":"#fbfaf8";
    state.viewer?.setTheme(theme);try{localStorage.setItem("blueprint-theme",choice);}catch{}changed();
  }
  function syncWorkspaceStatus(){
    if(ui.view_mode==="source"){$("workspace-status").textContent="Original page coordinates · saved source revision";return;}
    // The existing status renderer accounts for retained previews and terminal
    // review outcomes; the document revision alone can still say "reviewing".
    renderBuildingStatus();
    $("workspace-status").textContent=$("building-review-status").textContent||"";
  }
  function syncTabs() {
    const onDetails = ui.activeTab === "details";
    homeTab.setAttribute("aria-selected", String(!onDetails));
    detailsTab.setAttribute("aria-selected", String(onDetails));
    homeTab.tabIndex = onDetails ? -1 : 0;
    detailsTab.tabIndex = onDetails ? 0 : -1;
    detailsTab.disabled = !onDetails;
    $("home-library").hidden = onDetails;
    $("details-panel").hidden = !onDetails;
    $("visual-workspace").hidden = !onDetails;
    $("chat-shell").classList.toggle("workspace-open", onDetails);
  }
  function chatAvailable() {
    return Boolean(state.document && (state.document.sources?.length || 0) <= 1);
  }
  function openLibraryFile(id) {
    if (state.busy || ui.activeTab !== "home") return;
    if (id === (state.document?.building_id || state.document?.document_id)) {
      showDetails();
      return;
    }
    return openBuilding(id, "source");
  }
  function syncLibrary() {
    const list = $("home-library-list");
    const items = state.savedBuildings;
    const signature = JSON.stringify(items.map(doc => [
      doc.building_id || doc.document_id, doc.example_title || doc.filename, doc.kind, doc.interpretation_status, doc.has_scene, doc.sources?.length,
    ]));
    if (list.dataset.catalog !== signature) {
      list.replaceChildren();
      for (const doc of items) {
        const row = element("tr");
        const file = element("th");
        file.scope = "row";
        const open = button(doc.example_title || doc.filename, () => openLibraryFile(doc.building_id || doc.document_id), "home-file");
        if ((doc.sources?.length || 0) > 1) open.append(element("span", "File group · View only", "home-file-note"));
        file.append(open);
        row.append(file);
        const interpretationReady = doc.kind !== "ifc" && doc.interpretation_status === "complete";
        for (const available of [interpretationReady, doc.has_scene]) {
          const cell = element("td");
          if (available) {
            const check = element("span", "✓", "home-file-check");
            check.setAttribute("aria-hidden", "true");
            cell.append(check, element("span", "Yes", "sr-only"));
          }
          row.append(cell);
        }
        list.append(row);
      }
      list.dataset.catalog = signature;
    }
    list.closest("table").hidden = items.length === 0;
    list.querySelectorAll("button").forEach(open => { open.disabled = Boolean(state.busy); });
    $("home-upload").disabled = $("file-input").disabled || Boolean(state.busy);
    const status = $("home-library-status");
    status.textContent = state.busy === "upload" ? "Opening file…" : state.savedBuildingsError
      ? "Saved files could not be loaded."
      : !state.savedBuildingsLoaded ? "Loading files…"
      : items.length ? "" : "No saved files yet.";
    status.hidden = !status.textContent;
    const error = $("home-library-error");
    error.textContent = $("upload-error").textContent;
    error.hidden = !error.textContent;
  }
  function showHome() {
    if (ui.activeTab === "details") {
      voice?.cancelAll();
      invalidate();
    }
    ui.activeTab = "home";
    syncTabs();
    changed();
    window.scrollTo(0, 0);
  }
  function showDetails() {
    if (!state.document) return;
    ui.activeTab = "details";
    if (ui.view_mode === "chat") {
      if (state.document.pages?.length) {
        // Rendering a saved drawing does not start reconstruction.
        openWorkspace("source");
      } else {
        switchModel();
      }
      return;
    }
    syncTabs();
    scroll.scrollTop = scroll.scrollHeight;
    window.scrollTo(0, 0);
    requestAnimationFrame(() => state.viewer?.resize());
    changed();
  }
  function openWorkspace(mode){
    if(ui.activeTab !== "details" || (mode!=="source"&&mode!=="model"&&mode!=="concept"))return;
    ui.view_mode=mode;
    syncTabs();
    scroll.scrollTop = scroll.scrollHeight;
    setView(mode==="source"?"drawing":mode);$("workspace-title").textContent=mode==="source"?"Original drawing":mode==="concept"?"Concept · display proposals":"Saved model · interpretation";
    syncWorkspaceStatus();
    window.scrollTo(0, 0);
    requestAnimationFrame(()=>state.viewer?.resize());changed();
  }
  function closeWorkspace() {
    pause();
    ui.camera = state.viewer?.getCameraState() || ui.camera;
    ui.view_mode = "chat";
    ui.activeTab = "home";
    syncTabs();
    changed();
  }
  function syncHighlights(){
    changed();if(!state.viewer)return;
    const navigation=ui.highlighting?ui.selected_ids:[],answer=ui.answer_highlighting?(state.result?.highlight_ids||[]):[];
    state.viewer.setHighlights([...new Set([...navigation,...answer])],Boolean(navigation.length||answer.length));
    state.viewer.setSelectionHighlightEnabled(ui.highlighting);
    state.viewer.setShowAssumptions(ui.show_assumptions);$("highlight-answer").checked=ui.answer_highlighting;$("show-assumptions").checked=ui.show_assumptions;
  }
  function onSelection(record,options={}){
    if(!record)return;ui.focused_id=record.id;
    const revision=options.source_revision_id||state.scene?.revision_id;
    const prior=ui.inspection;
    ui.inspection={record:clone(record),source_revision_id:revision,proposal:null,units:prior?.source_revision_id===revision?prior.units:state.scene?.units,
      floor:clone(prior?.source_revision_id===revision&&prior.record?.id===record.id?prior.floor:state.scene?.floors?.find(f=>f.id===record.storey_id)||null),
      removed:Boolean(state.scene&&revision!==state.scene.revision_id&&!state.scene.elements.some(item=>item.id===record.id))};
    if(!ui.updatingSelection&&!options.automatic){pause();ui.navigation_epoch++;}
    const node=note(`${record.name||record.id} · ${record.geometry?"modeled "+record.kind:"unresolved; source evidence only"}`,"focused-object",
      [["Original source",{type:"show_source",object_id:record.id,source:record.source,source_revision_id:options.source_revision_id||state.scene?.revision_id}]]);
    if(record.note)node.append(element("p",record.note,"chat-status"));
    if(record.geometry_origin==="inferred")node.append(element("p","Generated geometry is an interpretation, not measured source evidence.","chat-status"));changed();
  }
  function onProposal(record,options={}){
    if(!record||record.kind!=="proposal")return;
    if(!options.automatic)invalidate();
    ui.focused_id=null;
    const node=note(`${record.label} · decorative proposal, not factual source evidence.`,"selected-proposal");
    node.querySelectorAll(".proposal-note,.proposal-source").forEach(item=>item.remove());
    node.append(element("p",record.note||"Styling, placement and dimensions are display choices; excluded from QA and IFC export.","proposal-note"));
    const host=state.scene?.elements.find(item=>item.id===record.host_id);
    ui.inspection={record:null,proposal:clone(record),host:clone(host||null),source_revision_id:state.scene?.revision_id,removed:false};
    if(host?.source){const source=sourceButton(host.source,"Supporting source area · host object",state.scene.revision_id);source.classList.add("proposal-source");node.append(source);}changed();
  }
  function onScene(scene){
    const prior=ui.geometry_revision_id;ui.geometry_revision_id=scene.revision_id||null;
    const ids=new Set(scene.elements.filter(e=>e.geometry&&e.representation!=="unresolved").map(e=>e.id));
    const lost=ui.selected_ids.filter(id=>!ids.has(id));ui.selected_ids=ui.selected_ids.filter(id=>ids.has(id));
    if(prior&&prior!==ui.geometry_revision_id){
      pause();const focused=ui.focused_id;ui.tour.ids=ui.tour.ids.filter(id=>ids.has(id));
      ui.tour.index=focused?ui.tour.ids.indexOf(focused):-1;
      if(focused&&!ids.has(focused))ui.focused_id=null;
      if(ui.inspection?.record&&!scene.elements.some(item=>item.id===ui.inspection.record.id))ui.inspection.removed=true;
      note(lost.length?"Model updated. Some selected objects were removed or became unresolved. Their earlier source links remain available; the tour is paused.":"Model updated. Your camera and surviving selection are preserved.","revision:"+scene.revision_id);
    }
    state.viewer?.setTheme(document.documentElement.dataset.theme||"light");syncHighlights();
    const canvas=state.viewer?.renderer.domElement;
    if(canvas&&!canvas.dataset.chatBound){canvas.dataset.chatBound="true";canvas.addEventListener("pointerdown",invalidate);canvas.addEventListener("wheel",invalidate,{passive:true});}
    if(ui.view_mode==="chat")closeWorkspace();
  }
  function onDocument(doc,workspaceMode=null){
    if(!doc)return;
    if(ui.documentId!==doc.document_id){
      invalidate();
      $("question").value = "";
      ui.documentId=doc.document_id;ui.selected_ids=[];ui.focused_id=null;ui.tour={ids:[],index:-1,running:false};ui.clarification=null;
      ui.geometry_revision_id=state.scene?.revision_id||null;ui.inspection=null;ui.pageCatalogs.clear();ui.sourcePages.clear();ui.sourceCatalog=null;ui.latestSubmissionId=null;closeWorkspace();ui.camera=null;
      for(const [key]of ui.entries)if(key!=="provider-setup")removeEntry(key);
    }
    if(doc.revision_id)ui.pageCatalogs.set(doc.revision_id,clone(doc.pages||[]));
    changed();$("attachment-summary").hidden=false;$("attachment-summary").textContent=`${doc.filename} · ${doc.pages?.length||0} original pages`;
    const active=state.jobs.some(j=>j.kind==="extraction"&&!terminalJob(j));
    const ready=doc.interpretation_status==="complete";
    const message=doc.kind==="ifc"?"Your supplied IFC is ready. Ask about its original records or open the saved model.":ready?"Your drawings are ready. Ask a question from the original sources, or request a model when you want a visual inspection.":active?"Reading your drawings… Originals are saved while the interpretation is validated.":"Original sources are saved. Interpretation is not complete; source-grounded questions remain available.";
    note(message,"source-status",[...(doc.pages?.length?[["Inspect original",{type:"show_source",page:doc.pages[0].page}]]:[]),...(doc.has_scene?[["Open saved model",{type:"show_model"}]]:[])]);
    if(workspaceMode){
      ui.activeTab = "details";
      if(doc.pages?.length&&(workspaceMode==="source"||!state.viewer))openWorkspace("source");
      else switchModel();
    }
    if (!chatAvailable()) note("This file group is view only. Open an individual file from Home to chat.","single-file");
    syncWorkspaceStatus();
    syncControls();
  }
  function onUpload() { invalidate(); }
  function onError(id,message) {
    if (id === "upload-error") {
      syncLibrary();
      if (ui.activeTab === "details" && message) note(message, "error:"+id);
    } else if (message) {
      note(message, "error:"+id, [["Refresh status",{type:"refresh"}]]);
    }
  }
  function sourceButton(source,label,revision){return button(label,()=>local({type:"show_source",source,source_revision_id:revision}),"chat-citation");}
  function renderAnswer(answer,key){
    const node=entry(key);node.classList.add("chat-answer");node.replaceChildren(element("p","Blueprint","chat-role"));
    node.append(element("p",({answered:"Source-grounded answer",insufficient:"Insufficient source evidence",unclear:"Source evidence remains unclear",clarification:"Clarify your question"}[answer.status]||answer.status),"chat-status"),element("p",answer.answer));
    for(const evidence of answer.evidence||[])node.append(sourceButton(evidence,evidence.label||`Original page ${evidence.page}`,answer.answered_revision_id));
    for(const evidence of answer.model_evidence||[])node.append(button(evidence.label||evidence.element_id,()=>openNative(evidence.element_id,answer.answered_revision_id,evidence.label),"chat-citation"));
    if(answer.clarification){const actions=element("div",null,"chat-actions");for(const text of answer.clarification.suggestions||[])actions.append(button(text,async()=>{
      const context=contextNow();if(!node.dataset.messageId)await refreshConversation();
      if(!sameDocument(context))return;
      if(!node.dataset.messageId)throw new Error("This clarification is still being saved. Refresh its conversation before replying.");
      state.clarificationReply=node.dataset.messageId;return submit(text,null);
    }));node.append(actions);}
    const detail=element("details"),summary=element("summary","Evidence and checks");detail.append(summary);
    for(const text of [answer.support_summary,answer.review_note,...(answer.missing_information||[]),answer.next_action])if(text)detail.append(element("p",text));
    if(answer.proposal)detail.append(element("p",`Proposal, not source fact: ${answer.proposal.text}`));
    for(const calc of answer.calculation_results||[])detail.append(element("p",`${calc.label||calc.expression||"Calculation"}: ${calc.result??calc.value??"See source inputs"} ${calc.unit||""}`));
    for(const attribution of answer.user_value_attributions||[])detail.append(element("p",typeof attribution==="string"?attribution:JSON.stringify(attribution)));
    const mappedIds=answerForDisplayedRevision(answer).highlight_ids||[];
    if(answer.status==="answered"&&state.scene&&((answer.evidence||[]).length||(answer.model_evidence||[]).length)&&!mappedIds.length)
      detail.append(element("p","This answer has no reliable 3D mapping. Original source evidence remains available; no object highlight was invented."));
    if(state.viewer?.floorFilter&&mappedIds.some(id=>state.scene?.elements.some(item=>item.id===id&&item.storey_id!==state.viewer.floorFilter)))
      detail.append(element("p","Linked objects are on another floor. Your view is preserved; show all floors or inspect the original source evidence to locate them."));
    detail.append(element("p",`Evidence sufficiency: ${answer.gate?.decision||"not assessed for clarification"}. Sufficiency and review do not guarantee answer correctness.`));node.append(detail);return node;
  }
  function mergeConversation(messages){
    for(const message of messages||[]){
      const existing=[...ui.entries.values()].find(node=>node.dataset.messageId===message.id);
      if(existing){
        if(message.answer){if(message.job_id)existing.dataset.jobId=message.job_id;if(message.request_id)existing.dataset.requestId=message.request_id;}
        continue;
      }
      const key="server:"+message.id;
      if(message.role==="user"){
        const local=[...ui.entries.values()].find(node=>node.classList.contains("chat-user")&&!node.dataset.messageId&&node.dataset.qaRequest&&
          (message.request_id?node.dataset.qaRequest===message.request_id:node.dataset.question===message.question));
        if(local){local.dataset.messageId=message.id;continue;}
        const node=entry(key,"user");node.dataset.question=message.question;node.dataset.messageId=message.id;node.append(element("p",message.question));
      }else if(message.answer){
        const signature=JSON.stringify(message.answer);
        const local=[...ui.entries.values()].find(node=>node.classList.contains("chat-answer")&&!node.dataset.messageId&&
          (message.job_id?node.dataset.jobId===message.job_id:message.request_id?node.dataset.requestId===message.request_id:node.dataset.answer===signature));
        const node=local||renderAnswer(message.answer,key);node.dataset.answer=signature;node.dataset.messageId=message.id;
        if(message.job_id)node.dataset.jobId=message.job_id;if(message.request_id)node.dataset.requestId=message.request_id;
        const requestId=message.request_id||state.jobs.find(job=>job.id===message.job_id)?.request_id;
        const latest=state.questionRequest?.id;
        // Historical/concurrent answers may be displayed, but cannot claim
        // the next free-text message after a newer submission.
        if((!ui.latestSubmissionId&&!latest)||(requestId&&requestId===latest&&requestId===ui.latestSubmissionId))state.clarificationReply=message.answer.status==="clarification"?message.id:null;
      }
    }
  }
  function onJobs(jobs){
    syncWorkspaceStatus();
    const intended=jobs?.find(j=>j.kind==="question"&&j.status==="complete"&&j.answer&&(state.questionRequest?.id?j.request_id===state.questionRequest.id:true));
    for(const job of jobs||[]){
      const {debug_hydrogen_outputs: debugOutputs, ...jobState} = job;
      if(terminalJob(job) && debugQuestionJobs.delete(job.id) && job.status==="complete"){
        for(const output of debugOutputs || []) console.log(output);
      }
      if(terminalJob(job)&&ui.entries.get("pending-model")?.dataset.modelJobId===job.id)removeEntry("pending-model");
      const key="job:"+job.id,node=entry(key);const signature=JSON.stringify(jobState);if(node.dataset.jobState===signature)continue;node.dataset.jobState=signature;
      node.classList.add("chat-operational");node.replaceChildren(element("p",({extraction:"Reading your drawings…",question:"Inspecting source",refinement:"Reviewing your submitted changes",reconstruction:"Building the saved model"}[job.kind]||"Operation"),"chat-role"));
      const status=element("p",`${(job.status||"").replaceAll("_"," ")} · ${(job.phase||"").replaceAll("_"," ")}`,"chat-status");status.dataset.status=job.status;node.append(status,element("p",job.message||""));
      if(!terminalJob(job))node.append(button("Stop this operation",()=>local({type:"stop_job",job_id:job.id})));
      if(terminalJob(job)&&job.kind!=="question")node.append(element("p",job.status==="complete"?"Operation completed; consult the review outcome and remaining issues.":state.scene?"The usable saved model remains available. This outcome is not a source-sufficiency judgment.":"Original sources remain saved. No usable model has been confirmed.","chat-status"));
      if(job.diagnostic_message)node.append(element("p",job.diagnostic_message));
      if(job.submitted_values?.length){
        const detail=element("details");detail.append(element("summary","User-provided values · submitted; see outcome"));
        for(const value of job.submitted_values){
          const scope=[value.scope?.floor_id?`floor ${value.scope.floor_id}`:"",value.scope?.object_id?`object ${value.scope.object_id}`:""].filter(Boolean).join(" · ");
          detail.append(element("p",`${value.property}${scope?` · ${scope}`:""}: ${typeof value.value==="object"?JSON.stringify(value.value):value.value} ${value.unit||""}`));
          detail.append(element("p","Provided by user, not observed in the original source. Submission does not establish that this value was applied."));
          if(value.reason)detail.append(element("p",value.reason));
        }
        node.append(detail);
      }
      for(const recovery of job.recovery_events||[]){
        const detail=element("details");detail.append(element("summary",`Recovery · ${recovery.kind||"review"}`));
        if(recovery.message)detail.append(element("p",recovery.message));
        if(recovery.feedback){const feedback=recovery.feedback;detail.append(element("p",[feedback.code,feedback.target_id?`Target ${feedback.target_id}`:"",feedback.explanation].filter(Boolean).join(" · ")));if(feedback.expected_contract)detail.append(element("p",`Required correction: ${feedback.expected_contract}`));}
        const revision=recovery.base_revision_id??job.base_revision_id;
        for(const decision of recovery.decisions||[]){
          const label={approved:"Approved correction target",denied:"Denied",unclear:"Unclear · not authorized"}[decision.decision]||"Not authorized";
          detail.append(element("p",`${label} · target ${decision.target_id}${decision.issue_id?` · issue ${decision.issue_id}`:""}`),element("p",decision.reason||""));
          if(decision.evidence&&typeof revision==="string"&&/^[a-f0-9]{32}$/i.test(revision))detail.append(sourceButton(decision.evidence,"Inspect reviewed target in original source",revision));
        }
        for(const pending of recovery.requests||[])if(!(recovery.decisions||[]).some(d=>d.request_id===pending.request_id))detail.append(element("p",`Requested target ${pending.target_id} · no authorization decision recorded`));
        if(recovery.kind==="authorization")detail.append(element("p","Target approval permits a proposed correction; it does not mean a change was applied or accepted."));
        node.append(detail);
      }
      for(const issue of job.issues||[]){const detail=element("details");detail.append(element("summary",issue.discrepancy||issue.category||"Unresolved finding"),element("p",[issue.evidence,issue.uncertainty,issue.proposed_action].filter(Boolean).join(" ")));if(issue.source)detail.append(sourceButton(issue.source,"Finding in source",job.base_revision_id));node.append(detail);}
      if(job.answer&&job.status==="complete"){
        node.hidden=true;const signature=JSON.stringify(job.answer);
        const restored=[...ui.entries.values()].find(e=>e.classList.contains("chat-answer")&&(e.dataset.jobId===job.id||(job.request_id&&e.dataset.requestId===job.request_id)));
        if(restored){restored.dataset.jobId=job.id;restored.dataset.requestId=job.request_id||restored.dataset.requestId||"";}
        else if(!ui.entries.has("answer:"+job.id)){const result=renderAnswer(job.answer,"answer:"+job.id);result.dataset.answer=signature;result.dataset.jobId=job.id;result.dataset.requestId=job.request_id||"";}
        if(job===intended){state.result=answerForDisplayedRevision(job.answer);syncHighlights();}
      }
    }
  }
  async function openNative(id,revision,label,context=contextNow()){
    if(!sameDocument(context))return;
    pause();await inspectNativeEvidence({element_id:id,label},revision);
    if(!sameDocument(context))return;
    const node=note("Original supplied IFC record. It describes the supplied model, not as-built reality.");
    const copy=$("native-record-inspector").cloneNode(true);copy.removeAttribute("id");copy.hidden=false;for(const child of copy.querySelectorAll("[id]"))child.removeAttribute("id");node.append(copy);
  }
  async function openSource(action,context=contextNow()){
    if(!sameDocument(context))return;
    const revision=action.source_revision_id||context.revision_id;
    const available=revision===state.document?.revision_id?state.document.pages:(ui.pageCatalogs.get(revision)||[]);
    const source=action.source||{page:action.page??ui.sourcePages.get(revision)??available[0]?.page,bbox:null};
    if(source.kind==="ifc")return openNative(action.object_id||source.global_id,revision,action.object_id,context);
    if(!Number.isInteger(source.page)){
      note("This supplied IFC has original records rather than blueprint pages. Inspect its source records from the inventory.","native-source-guidance",[["Inspect original records",{type:"inspect_inventory"}]]);return;
    }
    let pages=available;
    if(!pages.some(page=>page.page===source.page)){
      if(available.length)throw new Error("The referenced original page is not available in this saved revision.");
      // An old citation can outlive the locally cached page catalog. Keep only
      // that exact known page; never borrow page names or bounds from CURRENT.
      pages=[{page:source.page,source_id:source.source_id||null,source_page:source.source_page||source.page,source_filename:"Saved original"}];
    }
    const url=`/api/buildings/${context.document_id}/revisions/${revision}/pages/${source.page}`;
    const image=await new Promise((resolve,reject)=>{const preview=new Image();preview.onload=()=>resolve(preview);preview.onerror=()=>reject(new Error("The original page could not be loaded. Your previous view is retained; try the page again."));preview.src=url;});
    if(!sameDocument(context)||context.epoch!==ui.navigation_epoch)return;
    pause();if(ui.view_mode!=="source")ui.camera=state.viewer?.getCameraState()||ui.camera;
    pages=clone(pages);const index=pages.findIndex(page=>page.page===source.page);
    pages[index].width=image.naturalWidth;pages[index].height=image.naturalHeight;
    ui.sourceCatalog={revision_id:revision,pages};ui.sourcePages.set(revision,source.page);
    state.evidenceRevision=revision;state.pageIndex=index;state.selectedEvidence=null;state.sourceSelection={...source,label:action.label||(source.bbox?"Saved source evidence":"Whole original page")};
    openWorkspace("source");renderPage();changed();
    note(source.bbox?"Original source region from the saved revision. Its stored bounds have not been tightened.":"Original drawing page. Choose any supplied page above; this whole-page view does not add an evidence region.","source-navigation",[["Back to model",{type:"switch_model"}]]);
  }
  function alive(context){return sameDocument(context)&&context.epoch===ui.navigation_epoch;}
  function switchModel(){
    if(state.scene&&!state.viewer){openWorkspace("model");return;}
    if(!state.scene&&state.document?.has_scene){
      openWorkspace("model");$("no-model-geometry").hidden=false;$("no-model-geometry").textContent="The saved 3D model could not be loaded. Reopen this blueprint to try again or browse its original sources.";return;
    }
    if(!state.scene||!state.viewer){
      openWorkspace("model");$("no-model-geometry").hidden=false;$("no-model-geometry").textContent="No saved 3D model. Use Build model in the conversation to request reconstruction; switching views does not generate geometry.";
      note("No saved 3D model is available. Original drawings remain available; building a model is a separate operation.","no-saved-model",[["Build model",{type:"show_model"}]]);return;
    }
    $("no-model-geometry").hidden=Boolean(state.viewer.meshes.size);openWorkspace("model");if(ui.camera){state.viewer.setCameraState(ui.camera);ui.camera=null;}changed();
  }
  async function model(context){
    if(state.scene){switchModel();return;}
    if(!state.document)throw new Error("Attach drawings or open a saved building first.");
    let job=state.jobs.find(j=>j.kind==="reconstruction"&&!terminalJob(j));
    if(!job){job=await jsonPost(`/api/buildings/${state.document.building_id}/reconstruction`,{base_revision_id:context.revision_id,mode:"reconstruct"});if(!alive(context))return;rememberJob(job);}
    schedulePoll(0);const progress=note("Building your model using the saved interpretation. Progress and review outcomes appear here.","pending-model");progress.dataset.modelJobId=job.id;
    while(alive(context)){
      if(state.scene)openWorkspace("model");
      const current=state.jobs.find(j=>j.id===job.id)||job;
      if(terminalJob(current)){
        removeEntry("pending-model");
        if(current.status!=="complete")throw new Error(`${current.message||"Model generation did not complete."} Dependent selection was not applied.`);
        await refreshBuilding();
        if(!alive(context))break;
        // A status poll may already be fetching the completed job's scene.
        // refreshBuilding deliberately returns early in that case; wait for
        // that same poll rather than misreporting an absent model.
        if(!state.scene&&state.pollingEpoch===state.epoch){await new Promise(resolve=>setTimeout(resolve,250));continue;}
        if(!state.scene)throw new Error("The operation completed without renderable model geometry. Original sources remain available.");
        removeEntry("pending-model");openWorkspace("model");return;
      }
      await new Promise(resolve=>setTimeout(resolve,250));
    }
    throw new Error("A newer interaction superseded the pending model selection. The operation may continue in the background.");
  }
  function reveal(ids){const floors=new Set(ids.map(id=>state.scene?.elements.find(e=>e.id===id)?.storey_id).filter(Boolean));setFloorFilter(floors.size===1?[...floors][0]:"");}
  function select(action){
    let ids=action.ids||[],unresolved=action.unresolved_ids||[];
    if(action.deferred){const selector=action.selector||{};let matches=state.scene?.elements||[];
      if(selector.kind)matches=matches.filter(e=>e.kind===selector.kind);
      if(selector.floor)matches=matches.filter(e=>e.storey_id===selector.floor);
      if(selector.label)matches=matches.filter(e=>(e.name||"").toLowerCase()===selector.label.toLowerCase());
      if(selector.label&&matches.length>1)throw new Error("That label matches more than one modeled object. Select a specific object.");
      ids=matches.filter(e=>e.geometry&&e.representation!=="unresolved").map(e=>e.id);unresolved=matches.filter(e=>!e.geometry||e.representation==="unresolved").map(e=>e.id);
    }
    const known=new Map((state.scene?.elements||[]).map(e=>[e.id,e]));
    if(ids.some(id=>!known.get(id)?.geometry||known.get(id)?.representation==="unresolved"))throw new Error("Selection no longer matches the saved model. Refresh and select again.");
    pause();ui.selected_ids=[...new Set(ids)];ui.focused_id=null;ui.inspection=null;state.selectedElement=null;state.selectedProposal=null;
    state.viewer?.clearSelection();ui.tour={ids:[],index:-1,running:false};reveal(ids);syncHighlights();state.viewer?.frameIds(ids);
    const node=note(`${ids.length} modeled ${action.selector?.kind||"object"}${ids.length===1?"":"s"} selected. ${unresolved.length} matching records have no renderable geometry. These are saved interpretation records, not a complete count of real objects.`,"selection",[["Show individually",{type:"tour",command:"start"}],["View from above",{type:"set_camera",preset:"top"}],["Hide workspace",{type:"close_workspace"}]]);
    for(const id of unresolved){const object=known.get(id);if(object?.source)node.append(sourceButton(object.source,`${object.name||id} · source only`,state.scene.revision_id));}
  }
  function focusTour(index){
    if(index<0){note("You are at the first selected object.","tour-status");return;}
    if(index>=ui.tour.ids.length){pause();note("Tour complete. All selected modeled objects have been visited.","tour-status",[["Start again",{type:"tour",command:"start"}]]);return;}
    const id=ui.tour.ids[index];reveal([id]);ui.updatingSelection=true;let result;
    try{result=state.viewer?.focusObject(id);}finally{ui.updatingSelection=false;}
    if(!result?.focused_id){pause();throw new Error(result?.note||"This tour object no longer has renderable geometry.");}
    ui.tour.index=index;ui.focused_id=id;syncHighlights();
    note(`Object ${index+1} of ${ui.tour.ids.length}. ${result.note}`,"tour-status",[["Pause",{type:"tour",command:"pause"}],["Previous",{type:"tour",command:"previous"}],["Next",{type:"tour",command:"next"}],["Original source",{type:"focused_source"}]]);
  }
  function scheduleTour(){clearTimeout(ui.timer);if(ui.tour.running)ui.timer=setTimeout(()=>{if(ui.tour.running){focusTour(ui.tour.index+1);scheduleTour();}},5000);}
  function tour(command){
    if(command==="pause"){pause();note("Tour paused. The focused object is retained.","tour-status",[["Resume",{type:"tour",command:"resume"}],["Next",{type:"tour",command:"next"}]]);return;}
    if(command==="start"){if(!ui.selected_ids.length)throw new Error("Select modeled objects before starting a tour.");ui.tour={ids:[...ui.selected_ids],index:-1,running:true};openWorkspace("model");focusTour(0);scheduleTour();return;}
    if(!ui.tour.ids.length)throw new Error("No tour is available. Select objects and ask to see them individually.");
    openWorkspace("model");if(command==="next"||command==="previous"){pause();focusTour(ui.tour.index+(command==="next"?1:-1));return;}
    ui.tour.running=true;focusTour(Math.max(0,ui.tour.index));scheduleTour();
  }
  async function ask(action,context){
    if(!sameDocument(context)||context.questionDispatched)return;
    context.questionDispatched=true;
    const user=ui.entries.get("user:"+context.request_id);if(user)user.dataset.qaRequest=context.request_id;
    let question=action.question;if(action.navigation_reference)question+=`\nNavigation reference (not a factual claim): ${JSON.stringify(action.navigation_reference)}`;
    if(question.length>2000)throw new Error("The question and source reference exceed the existing question length limit. Please shorten the question.");
    const job=await jsonPost("/api/questions",{document_id:context.document_id,revision_id:action.revision_id||context.revision_id,question,request_id:context.request_id,conversation_id:context.document_id,reply_to:context.reply_to,clarification_response:context.reply_to?action.question:null});
    if(!sameDocument(context))return;
    if(context.order>=ui.latestQuestionOrder){ui.latestQuestionOrder=context.order;state.questionRequest={id:context.request_id,building:context.document_id,pending:true};}
    if(state.clarificationReply===context.reply_to)state.clarificationReply=null;
    debugQuestionJobs.add(job.id);
    rememberJob(job);schedulePoll(0);await refreshConversation();
  }
  function requireModelView(){
    if(!state.viewer||!state.scene)throw new Error("This control needs a saved model. Ask to show a 3D model first; no generation was started.");
    openWorkspace(state.viewer.mode==="concept"?"concept":"model");
  }
  async function execute(action,context){
    switch(action.type){
      case "show_model":return model(context);
      case "select":return select(action);
      case "show_source":return openSource(action,context);
      case "browse_source":return openSource({page:action.page,source_revision_id:action.source_revision_id||context.revision_id},context);
      case "switch_model":return switchModel();
      case "return_selection":{
        if(!state.viewer||!state.scene)throw new Error("No saved model is available to frame.");
        const ids=ui.focused_id?[ui.focused_id]:ui.selected_ids;
        if(!ids.length)throw new Error("Select a modeled object to return to it. Original evidence for unresolved objects remains available.");
        switchModel();const result=state.viewer.frameIds(ids);if(!result.framed_ids.length)throw new Error("This selection has no renderable geometry. Use Show in original.");return;}
      case "focused_source":{const selected=ui.inspection,object=selected?.record||selected?.host;if(!object?.source)throw new Error("Select an object with a stored original reference first.");return openSource({object_id:object.id,source:object.source,source_revision_id:selected.source_revision_id},context);}
      case "close_workspace":return closeWorkspace();
      case "set_camera":if(!state.viewer)throw new Error("Open a model first.");openWorkspace("model");if(action.preset==="top")state.viewer.frameIds(ui.selected_ids.length?ui.selected_ids:[...state.viewer.meshes.keys()],{topDown:true});else if(action.preset==="fit"&&ui.selected_ids.length)state.viewer.frameIds(ui.selected_ids);else state.viewer.fit();return;
      case "tour":return tour(action.command);
      case "set_visibility":if(action.target==="assumptions")ui.show_assumptions=action.enabled;else if(action.target==="answer_highlights")ui.answer_highlighting=action.enabled;else ui.highlighting=action.enabled;syncHighlights();note(`${action.target.replaceAll("_"," ")} ${action.enabled?"shown":"hidden"}.`);return;
      case "set_theme":applyTheme(action.theme);note(`Using ${action.theme} theme.`);return;
      case "set_view":if(action.mode==="source")return openSource({},context);await model(context);if(alive(context))openWorkspace(action.mode);return;
      case "set_floor":requireModelView();setFloorFilter(action.floor_id||"");note(action.floor_id?"Showing the selected saved floor.":"Showing all saved floors.");return;
      case "set_separation":requireModelView();state.viewer.setExploded(action.enabled);$("explode-floors").checked=action.enabled;updateLayoutNote();note(action.enabled?"Floors separated for inspection; spacing is a display choice.":"Showing saved storey elevations.");return;
      case "set_cutaway":requireModelView();state.viewer.setCutawayPercent(action.percent);$("cutaway-percent").value=action.percent;updateCutawayNote();note($("cutaway-note").textContent);return;
      case "question":return ask(action,context);
      case "refine":case "reconstruct":{
        if(!sameDocument(context)||context.revision_id!==state.document?.revision_id)throw new Error("The building revision changed. Resubmit the requested change against the current revision.");
        const body=action.type==="refine"?{base_revision_id:context.revision_id,edits:action.edits,supporting_source_ids:action.supporting_source_ids||[]}:{base_revision_id:context.revision_id,mode:action.mode};
        const job=await jsonPost(`/api/buildings/${context.document_id}/${action.type==="refine"?"refinements":"reconstruction"}`,body);if(sameDocument(context)){rememberJob(job);schedulePoll(0);}return;}
      case "list_saved": case "open_saved": case "load_workspace_blueprint":
      case "new_upload": case "attach_sources":
        return note("Open Home to choose or upload a file.", "home-file-navigation");
      case "download_ifc":if(!state.scene?.ifc_url&&!state.document?.has_scene)throw new Error("No saved IFC is available.");return download(state.scene?.ifc_url||`/api/documents/${context.document_id}/model.ifc`);
      case "download_source":return download(`/api/buildings/${context.document_id}/sources/${action.source_id}/original`);
      case "retry_extraction":{const response=await jsonPost(`/api/buildings/${context.document_id}/extraction`,{retry:true});for(const job of response.jobs||[])rememberJob(job);schedulePoll(0);return;}
      case "stop_job":{const job=await request(`/api/jobs/${action.job_id}/stop`,{method:"POST"});rememberJob(job);schedulePoll(0);return;}
      case "refresh":await refreshBuilding();await refreshConversation();return;
      case "refresh_health":return checkHealth();
      case "inspect_assumptions":await refreshAssumptions();{const node=note("Observed information, interpretations, display assumptions and user-provided values remain distinct. Tell me a value and its floor to submit a reviewed refinement.");for(const row of state.assumptionRows){const part=element("div",null,"chat-assumption-row");part.append(element("strong",row.label||row.property),element("p",`${row.provenance}: ${row.value===null?"unknown":typeof row.value==="object"?JSON.stringify(row.value):row.value} ${row.unit||""}`),element("p",row.reason));if(row.source)part.append(sourceButton(row.source,"Original evidence",state.document.revision_id));node.append(part);}return;}
      case "inspect_inventory":{const node=note("Saved interpretation inventory. This does not establish complete extraction of the original drawings.");for(const object of state.scene?.elements||[]){const part=element("div",null,"chat-inventory-row");part.append(element("strong",object.name||object.id),element("p",`${object.kind} · ${object.geometry?object.representation:"unresolved, no mesh"}`));if(object.source)part.append(sourceButton(object.source,"Original evidence",state.scene.revision_id));if(object.geometry)part.append(button("Focus",()=>local({type:"focus_id",id:object.id})));node.append(part);}
        const proposals=[...(state.viewer?.concept?.records.values()||[])].filter(record=>record.kind==="proposal");
        if(proposals.length){const section=element("section",null,"chat-proposals");section.append(element("strong","Decorative proposals · not factual source evidence"),element("p","These display proposals are separate from the source-object inventory and excluded from factual counts, QA and IFC exports."));
          for(const proposal of proposals){const row=element("div",null,"chat-inventory-row");row.append(element("p",proposal.label),button("Inspect proposal",()=>inspectProposal(proposal)));section.append(row);}node.append(section);}
        return;}
      case "focus_id":openWorkspace("model");ui.updatingSelection=true;try{state.viewer?.focusObject(action.id);}finally{ui.updatingSelection=false;}ui.focused_id=action.id;return;
      case "set_comparison":{
        const enabled=action.layer?$("show-comparison").checked:action.enabled;
        if(enabled){
          if(!state.scene?.derived||!state.scene.revision_id)throw new Error("Comparison needs a saved drawing-derived model and its original source revision.");
          const revision=state.scene.revision_id;
          if(ui.view_mode!=="source"||state.evidenceRevision!==revision){
            const catalog=revision===state.document?.revision_id?state.document.pages:ui.pageCatalogs.get(revision);
            const pages=catalog?.map(page=>page.page)||[...new Set([...(state.scene.comparison||[]).map(item=>item.page),...(state.scene.floors||[]).map(floor=>floor.source?.page),state.scene.source_page].filter(page=>Number.isInteger(page)&&page>0))];
            const current=sourceView().page,page=pages.includes(current)?current:pages[0];
            if(!page)throw new Error("No stored original page is associated with this saved model. The current view is retained.");
            const source=state.evidenceRevision===revision&&state.sourceSelection?.page===page?state.sourceSelection:undefined;
            await openSource({page,source,source_revision_id:revision},context);
            if(!alive(context))return;
            if(state.scene?.revision_id!==revision)throw new Error("The model revision changed while opening its original. Request comparison again against the updated model.");
          }
        }
        if(!action.layer)$("show-comparison").checked=action.enabled;
        if(action.opacity!=null)$("comparison-opacity").value=action.opacity;
        if(action.layer){const input=document.querySelector(`[data-comparison-layer="${action.layer}"]`);if(input)input.checked=action.enabled;}
        openWorkspace("source");renderComparison();
        note($("show-comparison").checked?"Showing actual saved IFC geometry projected onto the original page; this does not establish source accuracy.":"Geometry comparison is hidden. The original source remains available.");return;
      }
      case "help":return note("Ask a source question, show the modeled windows, view from above, tour objects, open original evidence, switch theme, inspect assumptions, set a supplied height, choose a floor, adjust cutaway, compare geometry, export, or stop an active operation.","help",[["Light theme",{type:"set_theme",theme:"light"}],["Dark theme",{type:"set_theme",theme:"dark"}]]);
      default:throw new Error("This action is not supported by the workspace.");
    }
  }
  function download(url){const anchor=element("a");anchor.href=url;anchor.download="";anchor.click();note("Downloading the saved artifact. No reconstruction was requested.");}
  async function local(action){if(!["set_visibility","set_theme","inspect_assumptions","inspect_inventory","refresh_health","load_workspace_blueprint"].includes(action.type))invalidate();const context=contextNow();try{return await execute(action,context);}finally{changed();}}
  async function submit(supplied,clarificationContext=undefined){
    const display=supplied??$("question").value.trim();if(!display||voice?.recording||!chatAvailable()||ui.activeTab!=="details")return;
    voice?.cancelAll();
    invalidate();const captured=snapshot(),context=contextNow();
    const clarifying=clarificationContext===undefined?ui.clarification:clarificationContext;ui.clarification=null;
    let message=display;if(clarifying)message=`Original request: ${clarifying.message}\nUser clarification: ${display}`;
    ui.latestSubmissionId=context.request_id;
    if(state.clarificationReply===context.reply_to)state.clarificationReply=null;
    const user=entry("user:"+context.request_id,"user");user.dataset.question=message;user.append(element("p",display));$("question").value="";syncControls();
    const pending="routing:"+context.request_id;note("Interpreting your request…",pending);
    try{
      const response=await jsonPost("/api/chat/actions",{message,request_id:context.request_id,document_id:context.document_id||null,revision_id:context.revision_id||null,workspace:captured});
      if(response.request_id!==context.request_id||response.document_id!==(context.document_id||null)||response.revision_id!==(context.revision_id||null)||response.geometry_revision_id!==captured.geometry_revision_id||response.navigation_epoch!==captured.navigation_epoch||!["ready","clarification"].includes(response.status))throw new Error("The action response did not match the captured workspace. No action was applied.");
      if(!sameDocument(context))return;
      removeEntry(pending);
      if(response.status==="clarification"){
        if(ui.latestSubmissionId===context.request_id)ui.clarification={message};
        const node=note(response.clarification?.message||response.message,"clarification:"+context.request_id),controls=element("div",null,"chat-actions");
        for(const suggestion of response.clarification?.suggestions||[])controls.append(button(suggestion,()=>{if(sameDocument(context))return submit(suggestion,{message});}));
        node.append(controls);return;
      }
      // Factual work is independent of delayed viewer effects. All question
      // actions preserve the server-resolved submission context, even in mixed
      // batches whose navigation became stale while the user explored.
      const actions=response.actions||[];
      for(const action of actions.filter(action=>action.type==="question")){
        if(!sameDocument(context))return;
        await execute(action,context);
      }
      let navigationSkipped=false;
      for(const action of actions.filter(action=>action.type!=="question")){
        if(!sameDocument(context))return;
        const persistent=["refine","reconstruct","retry_extraction","stop_job"].includes(action.type);
        if(!persistent&&context.epoch!==ui.navigation_epoch){navigationSkipped=true;continue;}
        if(persistent&&context.revision_id!==state.document?.revision_id)throw new Error("The building revision changed. Resubmit the requested change against the current revision.");
        await execute(action,context);
      }
      if(navigationSkipped&&!actions.some(action=>action.type==="question"))note("Your current view was kept. The delayed navigation was not applied.",pending);
    }catch(error){if(sameDocument(context))note(error.message,pending);}
    finally{syncControls();changed();}
  }
  // Reuse the operation adapters without exposing the former toolbar/settings UI.
  $("composer-slot").append($("question-form"));
  const controls=element("div",null,"composer-controls");
  controls.append($("ask-button"));
  $("question-form").append(controls);
  $("workspace-content").append($("drawing-pane"),$("model-pane"));
  $("question").setAttribute("aria-label","Message Blueprint");$("question").addEventListener("keydown",event=>{if(event.key==="Enter"&&!event.shiftKey){event.preventDefault();$("question-form").requestSubmit();}});
  homeTab.addEventListener("click", showHome);
  document.querySelector(".chat-brand").addEventListener("click", (event) => {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    showHome();
  });
  for (const tab of [homeTab, detailsTab]) {
    tab.addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      const target = event.key === "Home" || detailsTab.disabled ? homeTab
        : event.key === "End" || tab === homeTab ? detailsTab : homeTab;
      target.focus();
      target.click();
    });
  }
  $("home-upload").addEventListener("click", () => {
    if (!state.busy && ui.activeTab === "home") $("file-input").click();
  });
  for (const type of ["dragover", "drop"]) {
    $("chat-shell").addEventListener(type, (event) => {
      if (event.dataTransfer.types.includes("Files")) event.preventDefault();
    });
  }
  $("viewer").addEventListener("wheel",event=>{if(event.ctrlKey||event.metaKey){event.preventDefault();const width=parseFloat($("image-stage").style.width)||100;$("image-stage").style.width=Math.max(100,width*(event.deltaY>0?.9:1.1))+"%";}},{passive:false});
  function isLatestSubmission(requestId) { return ui.latestSubmissionId === requestId; }
  window.chatUI={chatAvailable,isHome:()=>ui.activeTab==="home",isLatestSubmission,snapshot,inspection,sourceView,submit,execute:local,syncControls,syncHighlights,onUpload,onDocument,onScene,onSelection,onProposal,onJobs,onError,mergeConversation,openWorkspace};
  let stored="system";try{stored=localStorage.getItem("blueprint-theme")||"system";}catch{}applyTheme(["light","dark","system"].includes(stored)?stored:"system");
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change",()=>{if(ui.theme==="system")applyTheme("system");});
  syncControls();closeWorkspace();
})();
