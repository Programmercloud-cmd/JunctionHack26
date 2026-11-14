/* Conversation controller. Existing app.js functions own HTTP operations and evidence. */
"use strict";
(() => {
  const log = $("chat-log"), scroll = $("chat-scroll");
  const ui = {documentId:null, view_mode:"chat", selected_ids:[], focused_id:null, geometry_revision_id:null,
    navigation_epoch:0, highlighting:true, answer_highlighting:true, show_assumptions:false,
    tour:{ids:[],index:-1,running:false}, timer:null, camera:null, entries:new Map(), clarification:null,
    theme:"system", initialScene:true, updatingSelection:false};
  const clone = value => JSON.parse(JSON.stringify(value));
  const element = (tag, text, className) => {const node=document.createElement(tag);if(text!=null)node.textContent=text;if(className)node.className=className;return node;};
  const button = (label, fn, className="chat-inline-button") => {const node=element("button",label,className);node.type="button";node.addEventListener("click",()=>Promise.resolve(fn()).catch(error=>note(error.message,"error:"+crypto.randomUUID())));return node;};
  const jsonPost = (path,data) => request(path,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(data)});
  function entry(key,role="assistant") {
    if(ui.entries.has(key))return ui.entries.get(key);
    const node=element("article",null,`chat-turn chat-${role}`);node.dataset.entry=key;
    node.append(element("p",role==="user"?"You":"Blueprint","chat-role"));log.append(node);ui.entries.set(key,node);
    $("chat-welcome").hidden=true;scroll.scrollTop=scroll.scrollHeight;return node;
  }
  function removeEntry(key){ui.entries.get(key)?.remove();ui.entries.delete(key);}
  function note(message,key="note:"+crypto.randomUUID(),actions=[]){
    const node=entry(key),signature=JSON.stringify([message,actions]);if(node.dataset.note===signature)return node;node.dataset.note=signature;node.replaceChildren(element("p","Blueprint","chat-role"),element("p",message));
    if(actions.length){const controls=element("div",null,"chat-actions");for(const [label,action] of actions)controls.append(button(label,()=>local(action)));node.append(controls);}
    scroll.scrollTop=scroll.scrollHeight;return node;
  }
  function pause(){clearTimeout(ui.timer);ui.timer=null;ui.tour.running=false;}
  function invalidate(){pause();ui.navigation_epoch++;}
  function snapshot(){
    return clone({geometry_revision_id:ui.geometry_revision_id,view_mode:ui.view_mode,selected_ids:ui.selected_ids,focused_id:ui.focused_id,
      camera:state.viewer?.getCameraState()||ui.camera,tour:ui.tour,navigation_epoch:ui.navigation_epoch,highlighting:ui.highlighting,
      answer_highlighting:ui.answer_highlighting,show_assumptions:ui.show_assumptions,floor_id:state.viewer?.floorFilter||null,
      exploded:state.viewer?.exploded||false,cutaway:state.viewer?.cutawayPercent??100});
  }
  function syncControls(){
    $("question").disabled=state.busy==="upload";$("question").placeholder=state.document?"Ask about the drawing, or tell me what to show…":"Ask a question or attach your blueprints…";
    $("ask-button").disabled=state.busy==="upload"||!state.providerReady||!$("question").value.trim();$("ask-label").textContent="Send";
    $("attach-drawings").disabled=state.busy==="upload";
    $("chat-connection").textContent=state.providerReady?`${state.health?.provider_label||"Gemini"} · local workspace`:"Provider unavailable";
    if(state.health&&!state.providerReady)note($("provider-message").textContent||"Configure the selected provider to interpret messages. Saved sources remain available.","provider-setup",[["Check connection",{type:"refresh_health"}]]);
    else removeEntry("provider-setup");
  }
  function applyTheme(choice){
    ui.theme=choice;let theme=choice==="system"?(matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light"):choice;
    document.documentElement.dataset.theme=theme;document.querySelector('meta[name="theme-color"]').content=theme==="dark"?"#121110":"#fbfaf8";
    state.viewer?.setTheme(theme);try{localStorage.setItem("blueprint-theme",choice);}catch{}
  }
  function openWorkspace(mode){
    if(mode!=="source"&&mode!=="model"&&mode!=="concept")return;
    ui.view_mode=mode;$("visual-workspace").hidden=false;$("chat-shell").classList.add("workspace-open");
    setView(mode==="source"?"drawing":mode);$("workspace-title").textContent=mode==="source"?"Original drawing":mode==="concept"?"Concept · display proposals":"Saved model · interpretation";
    $("workspace-status").textContent=mode==="source"?"Original page coordinates":state.document?.review_status?.replaceAll("_"," ")||"";
    requestAnimationFrame(()=>state.viewer?.resize());
  }
  function closeWorkspace(){pause();ui.camera=state.viewer?.getCameraState()||ui.camera;ui.view_mode="chat";$("visual-workspace").hidden=true;$("chat-shell").classList.remove("workspace-open");}
  function syncHighlights(){
    if(!state.viewer)return;
    const navigation=ui.highlighting?ui.selected_ids:[],answer=ui.answer_highlighting?(state.result?.highlight_ids||[]):[];
    state.viewer.setHighlights([...new Set([...navigation,...answer])],Boolean(navigation.length||answer.length));
    state.viewer.setShowAssumptions(ui.show_assumptions);$("highlight-answer").checked=ui.answer_highlighting;$("show-assumptions").checked=ui.show_assumptions;
  }
  function onSelection(record,options={}){
    if(!record)return;ui.focused_id=record.id;
    if(!ui.updatingSelection&&!options.automatic){pause();ui.navigation_epoch++;}
    const node=note(`${record.name||record.id} · ${record.geometry?"modeled "+record.kind:"unresolved; source evidence only"}`,"focused-object",
      [["Original source",{type:"show_source",object_id:record.id,source:record.source,source_revision_id:options.source_revision_id||state.scene?.revision_id}]]);
    if(record.note)node.append(element("p",record.note,"chat-status"));
    if(record.geometry_origin==="inferred")node.append(element("p","Generated geometry is an interpretation, not measured source evidence.","chat-status"));
  }
  function onProposal(record,options={}){
    if(!record||record.kind!=="proposal")return;
    if(!options.automatic)invalidate();
    ui.focused_id=null;
    const node=note(`${record.label} · decorative proposal, not factual source evidence.`,"selected-proposal");
    node.querySelectorAll(".proposal-note,.proposal-source").forEach(item=>item.remove());
    node.append(element("p",record.note||"Styling, placement and dimensions are display choices; excluded from QA and IFC export.","proposal-note"));
    const host=state.scene?.elements.find(item=>item.id===record.host_id);
    if(host?.source){const source=sourceButton(host.source,"Supporting source area · host object",state.scene.revision_id);source.classList.add("proposal-source");node.append(source);}
  }
  function onScene(scene){
    const prior=ui.geometry_revision_id;ui.geometry_revision_id=scene.revision_id||null;
    const ids=new Set(scene.elements.filter(e=>e.geometry&&e.representation!=="unresolved").map(e=>e.id));
    const lost=ui.selected_ids.filter(id=>!ids.has(id));ui.selected_ids=ui.selected_ids.filter(id=>ids.has(id));
    if(prior&&prior!==ui.geometry_revision_id){
      pause();const focused=ui.focused_id;ui.tour.ids=ui.tour.ids.filter(id=>ids.has(id));
      ui.tour.index=focused?ui.tour.ids.indexOf(focused):-1;
      if(focused&&!ids.has(focused))ui.focused_id=null;
      note(lost.length?"Model updated. Some selected objects were removed or became unresolved. Their earlier source links remain available; the tour is paused.":"Model updated. Your camera and surviving selection are preserved.","revision:"+scene.revision_id);
    }
    state.viewer?.setTheme(document.documentElement.dataset.theme||"light");syncHighlights();
    const canvas=state.viewer?.renderer.domElement;
    if(canvas&&!canvas.dataset.chatBound){canvas.dataset.chatBound="true";canvas.addEventListener("pointerdown",invalidate);canvas.addEventListener("wheel",invalidate,{passive:true});}
    if(ui.view_mode==="chat")closeWorkspace();
  }
  function onDocument(doc){
    if(!doc)return;
    if(ui.documentId!==doc.document_id){
      invalidate();ui.documentId=doc.document_id;ui.selected_ids=[];ui.focused_id=null;ui.tour={ids:[],index:-1,running:false};ui.clarification=null;
      ui.geometry_revision_id=state.scene?.revision_id||null;closeWorkspace();
      for(const [key]of ui.entries)if(!key.startsWith("upload:")&&!key.startsWith("provider"))removeEntry(key);
    }
    $("attachment-summary").hidden=false;$("attachment-summary").textContent=`${doc.filename} · ${doc.pages?.length||0} original pages`;
    const active=state.jobs.some(j=>j.kind==="extraction"&&!terminalJob(j));
    const ready=doc.interpretation_status==="complete";
    const message=doc.kind==="ifc"?"Your supplied IFC is ready. Ask about its original records or open the saved model.":ready?"Your drawings are ready. Ask a question from the original sources, or request a model when you want a visual inspection.":active?"Reading your drawings… Originals are saved while the interpretation is validated.":"Original sources are saved. Interpretation is not complete; source-grounded questions remain available.";
    note(message,"source-status",[...(doc.pages?.length?[["Inspect original",{type:"show_source",page:doc.pages[0].page}]]:[]),...(doc.has_scene?[["Open saved model",{type:"show_model"}]]:[]),...(doc.kind!=="ifc"?[["Add related drawings",{type:"attach_sources"}]]:[])]);
    $("workspace-status").textContent=doc.geometry_status==="stale"?"Earlier usable model · newer sources saved":doc.review_status?.replaceAll("_"," ")||"";
    syncControls();
  }
  function onUpload(files,append){invalidate();note(`Reading your drawings… ${files.map(f=>f.name).join(", ")}`,"upload:"+crypto.randomUUID());if(!append)closeWorkspace();}
  function onError(id,message){if(message)note(message,"error:"+id,[["Refresh status",{type:"refresh"}]]);}
  function sourceButton(source,label,revision){return button(label,()=>local({type:"show_source",source,source_revision_id:revision}),"chat-citation");}
  function renderAnswer(answer,key){
    const node=entry(key);node.classList.add("chat-answer");node.replaceChildren(element("p","Blueprint","chat-role"));
    node.append(element("p",({answered:"Source-grounded answer",insufficient:"Insufficient source evidence",unclear:"Source evidence remains unclear",clarification:"Clarify your question"}[answer.status]||answer.status),"chat-status"),element("p",answer.answer));
    for(const evidence of answer.evidence||[])node.append(sourceButton(evidence,evidence.label||`Original page ${evidence.page}`,answer.answered_revision_id));
    for(const evidence of answer.model_evidence||[])node.append(button(evidence.label||evidence.element_id,()=>openNative(evidence.element_id,answer.answered_revision_id,evidence.label),"chat-citation"));
    if(answer.clarification){const actions=element("div",null,"chat-actions");for(const text of answer.clarification.suggestions||[])actions.append(button(text,()=>{state.clarificationReply=node.dataset.messageId||null;submit(text);}));node.append(actions);}
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
      if(existing)continue;
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
        if(message.answer.status==="clarification")state.clarificationReply=message.id;
      }
    }
  }
  function onJobs(jobs){
    const intended=jobs?.find(j=>j.kind==="question"&&j.status==="complete"&&j.answer&&(state.questionRequest?.id?j.request_id===state.questionRequest.id:true));
    for(const job of jobs||[]){
      const key="job:"+job.id,node=entry(key);const signature=JSON.stringify(job);if(node.dataset.jobState===signature)continue;node.dataset.jobState=signature;
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
        if(!ui.entries.has("answer:"+job.id)&&![...ui.entries.values()].some(e=>e.dataset.jobId===job.id)){const result=renderAnswer(job.answer,"answer:"+job.id);result.dataset.answer=signature;result.dataset.jobId=job.id;result.dataset.requestId=job.request_id||"";}
        if(job===intended){state.result=answerForDisplayedRevision(job.answer);syncHighlights();}
      }
    }
  }
  async function openNative(id,revision,label){
    pause();await inspectNativeEvidence({element_id:id,label},revision);
    const node=note("Original supplied IFC record. It describes the supplied model, not as-built reality.");
    const copy=$("native-record-inspector").cloneNode(true);copy.removeAttribute("id");copy.hidden=false;for(const child of copy.querySelectorAll("[id]"))child.removeAttribute("id");node.append(copy);
  }
  function openSource(action){
    pause();ui.camera=state.viewer?.getCameraState()||ui.camera;
    const source=action.source||{page:action.page,bbox:null};const revision=action.source_revision_id||state.document?.revision_id;
    if(source.kind==="ifc")return openNative(action.object_id||source.global_id,revision,action.object_id);
    const index=state.document?.pages.findIndex(page=>page.page===source.page)??-1;
    if(index<0)throw new Error("The referenced original page is not available in this building.");
    state.evidenceRevision=revision;state.pageIndex=index;state.selectedEvidence=null;state.sourceSelection={...source,label:action.label||"Saved source evidence"};
    openWorkspace("source");renderPage();note("Original source region from the saved revision. Its stored bounds have not been tightened.","source-navigation",[["Back to model",{type:"show_model"}]]);
  }
  function alive(context){return context.epoch===ui.navigation_epoch&&context.document_id===state.document?.document_id;}
  async function model(context){
    if(state.scene){openWorkspace("model");if(ui.camera){state.viewer?.setCameraState(ui.camera);ui.camera=null;}return;}
    if(!state.document)throw new Error("Attach drawings or open a saved building first.");
    let job=state.jobs.find(j=>j.kind==="reconstruction"&&!terminalJob(j));
    if(!job){job=await jsonPost(`/api/buildings/${state.document.building_id}/reconstruction`,{base_revision_id:context.revision_id,mode:"reconstruct"});if(!alive(context))return;rememberJob(job);}
    schedulePoll(0);note("Building your model using the saved interpretation. Progress and review outcomes appear here.","pending-model");
    while(alive(context)){
      if(state.scene)openWorkspace("model");
      const current=state.jobs.find(j=>j.id===job.id)||job;
      if(terminalJob(current)){
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
    pause();ui.selected_ids=[...new Set(ids)];ui.focused_id=null;ui.tour={ids:[],index:-1,running:false};reveal(ids);syncHighlights();state.viewer?.frameIds(ids);
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
    const user=ui.entries.get("user:"+context.request_id);if(user)user.dataset.qaRequest=context.request_id;
    let question=action.question;if(action.navigation_reference)question+=`\nNavigation reference (not a factual claim): ${JSON.stringify(action.navigation_reference)}`;
    if(question.length>2000)throw new Error("The question and source reference exceed the existing question length limit. Please shorten the question.");
    const job=await jsonPost("/api/questions",{document_id:context.document_id,revision_id:action.revision_id||context.revision_id,question,request_id:context.request_id,conversation_id:context.document_id,reply_to:state.clarificationReply,clarification_response:state.clarificationReply?action.question:null});
    if(context.document_id!==state.document?.document_id)return;
    state.questionRequest={id:context.request_id,building:context.document_id,pending:!terminalJob(job)};state.clarificationReply=null;rememberJob(job);schedulePoll(0);await refreshConversation();
  }
  function requireModelView(){
    if(!state.viewer||!state.scene)throw new Error("This control needs a saved model. Ask to show a 3D model first; no generation was started.");
    openWorkspace(state.viewer.mode==="concept"?"concept":"model");
  }
  async function execute(action,context){
    switch(action.type){
      case "show_model":return model(context);
      case "select":return select(action);
      case "show_source":return openSource(action);
      case "focused_source":{const object=state.scene?.elements.find(e=>e.id===ui.focused_id);if(!object)throw new Error("Select an object first.");return openSource({object_id:object.id,source:object.source,source_revision_id:state.scene.revision_id});}
      case "close_workspace":return closeWorkspace();
      case "set_camera":if(!state.viewer)throw new Error("Open a model first.");openWorkspace("model");if(action.preset==="top")state.viewer.frameIds(ui.selected_ids.length?ui.selected_ids:[...state.viewer.meshes.keys()],{topDown:true});else if(action.preset==="fit"&&ui.selected_ids.length)state.viewer.frameIds(ui.selected_ids);else state.viewer.fit();return;
      case "tour":return tour(action.command);
      case "set_visibility":if(action.target==="assumptions")ui.show_assumptions=action.enabled;else if(action.target==="answer_highlights")ui.answer_highlighting=action.enabled;else ui.highlighting=action.enabled;syncHighlights();note(`${action.target.replaceAll("_"," ")} ${action.enabled?"shown":"hidden"}.`);return;
      case "set_theme":applyTheme(action.theme);note(`Using ${action.theme} theme.`);return;
      case "set_view":if(action.mode==="source"&&!state.document?.pages?.length){note("This supplied IFC has original records rather than blueprint pages. Inspect its source records from the inventory.","native-source-guidance",[["Inspect original records",{type:"inspect_inventory"}]]);return;}if(action.mode!=="source")await model(context);openWorkspace(action.mode);return;
      case "set_floor":requireModelView();setFloorFilter(action.floor_id||"");note(action.floor_id?"Showing the selected saved floor.":"Showing all saved floors.");return;
      case "set_separation":requireModelView();state.viewer.setExploded(action.enabled);$("explode-floors").checked=action.enabled;updateLayoutNote();note(action.enabled?"Floors separated for inspection; spacing is a display choice.":"Showing saved storey elevations.");return;
      case "set_cutaway":requireModelView();state.viewer.setCutawayPercent(action.percent);$("cutaway-percent").value=action.percent;updateCutawayNote();note($("cutaway-note").textContent);return;
      case "question":return ask(action,context);
      case "refine":case "reconstruct":{
        if(context.revision_id!==state.document?.revision_id)throw new Error("The building revision changed. Resubmit the requested change against the current revision.");
        const body=action.type==="refine"?{base_revision_id:context.revision_id,edits:action.edits,supporting_source_ids:action.supporting_source_ids||[]}:{base_revision_id:context.revision_id,mode:action.mode};
        const job=await jsonPost(`/api/buildings/${context.document_id}/${action.type==="refine"?"refinements":"reconstruction"}`,body);if(context.document_id===state.document?.document_id){rememberJob(job);schedulePoll(0);}return;}
      case "list_saved":await refreshSavedBuildings();{const node=note("Choose a saved building. Reopening reuses saved sources and models.");const controls=element("div",null,"chat-actions");for(const doc of state.savedBuildings)controls.append(button(doc.filename,()=>local({type:"open_saved",building_id:doc.building_id||doc.document_id})));node.append(controls);return;}
      case "open_saved":await openBuilding(action.building_id);return;
      case "new_upload":case "attach_sources":state.uploadMode=action.type==="attach_sources"?"append":"new";$("file-input").click();return;
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
      case "set_comparison":
        if(!action.layer)$("show-comparison").checked=action.enabled;
        if(action.opacity!=null)$("comparison-opacity").value=action.opacity;
        if(action.layer){const input=document.querySelector(`[data-comparison-layer="${action.layer}"]`);if(input)input.checked=action.enabled;}
        openWorkspace("source");renderComparison();
        note($("show-comparison").checked?"Showing actual saved IFC geometry projected onto the original page; this does not establish source accuracy.":"Geometry comparison is hidden. The original source remains available.");return;
      case "help":return note("Ask a source question, show the modeled windows, view from above, tour objects, open original evidence, switch theme, inspect assumptions, set a supplied height, choose a floor, adjust cutaway, compare geometry, add sources, export, or stop an active operation.","help",[["Saved buildings",{type:"list_saved"}],["Attach drawings",{type:"new_upload"}],["Light theme",{type:"set_theme",theme:"light"}],["Dark theme",{type:"set_theme",theme:"dark"}]]);
      default:throw new Error("This action is not supported by the workspace.");
    }
  }
  function download(url){const anchor=element("a");anchor.href=url;anchor.download="";anchor.click();note("Downloading the saved artifact. No reconstruction was requested.");}
  async function local(action){invalidate();const context={epoch:ui.navigation_epoch,document_id:state.document?.document_id,revision_id:state.document?.revision_id,request_id:crypto.randomUUID()};return execute(action,context);}
  async function submit(supplied){
    const display=supplied??$("question").value.trim();if(!display)return;
    invalidate();const captured=snapshot(),context={epoch:ui.navigation_epoch,document_id:state.document?.document_id,revision_id:state.document?.revision_id,request_id:crypto.randomUUID()};
    let message=display;if(ui.clarification){message=`Original request: ${ui.clarification.message}\nUser clarification: ${display}`;ui.clarification=null;}
    const user=entry("user:"+context.request_id,"user");user.dataset.question=message;user.append(element("p",display));$("question").value="";syncControls();
    const pending="routing:"+context.request_id;note("Interpreting your request…",pending);
    try{
      const response=await jsonPost("/api/chat/actions",{message,request_id:context.request_id,document_id:context.document_id||null,revision_id:context.revision_id||null,workspace:captured});
      if(context.epoch!==ui.navigation_epoch||context.document_id!==state.document?.document_id){note("A newer interaction superseded this request. No delayed workspace action was applied.",pending);return;}
      if(response.request_id!==context.request_id||response.document_id!==(context.document_id||null)||response.revision_id!==(context.revision_id||null)||response.geometry_revision_id!==captured.geometry_revision_id||response.navigation_epoch!==captured.navigation_epoch||!["ready","clarification"].includes(response.status))throw new Error("The action response did not match the captured workspace. No action was applied.");
      removeEntry(pending);
      if(response.status==="clarification"){
        ui.clarification={message};const node=note(response.clarification?.message||response.message,"clarification:"+context.request_id);const controls=element("div",null,"chat-actions");for(const suggestion of response.clarification?.suggestions||[])controls.append(button(suggestion,()=>submit(suggestion)));node.append(controls);return;
      }
      for(const action of response.actions||[]){if(context.epoch!==ui.navigation_epoch||context.document_id!==state.document?.document_id)break;await execute(action,context);}
    }catch(error){note(error.message,pending);}
    finally{syncControls();}
  }
  // Reuse the operation adapters without exposing the former toolbar/settings UI.
  $("composer-slot").append($("question-form"));const controls=element("div",null,"composer-controls");
  const attach=button("+ Attach drawings",()=>local({type:state.document?"attach_sources":"new_upload"}));attach.id="attach-drawings";
  controls.append(attach,$("ask-button"));$("question-form").append(controls);
  $("workspace-content").append($("drawing-pane"),$("model-pane"));
  $("question").setAttribute("aria-label","Message Blueprint");$("question").addEventListener("keydown",event=>{if(event.key==="Enter"&&!event.shiftKey){event.preventDefault();$("question-form").requestSubmit();}});
  $("welcome-upload").addEventListener("click",()=>local({type:"new_upload"}));$("welcome-saved").addEventListener("click",()=>local({type:"list_saved"}));
  $("chat-shell").addEventListener("dragover",event=>{event.preventDefault();document.body.classList.add("dragging-files");});
  $("chat-shell").addEventListener("dragleave",event=>{if(!$("chat-shell").contains(event.relatedTarget))document.body.classList.remove("dragging-files");});
  $("chat-shell").addEventListener("drop",event=>{event.preventDefault();document.body.classList.remove("dragging-files");uploadFile(event.dataTransfer.files,Boolean(state.document));});
  $("viewer").addEventListener("wheel",event=>{if(event.ctrlKey||event.metaKey){event.preventDefault();const width=parseFloat($("image-stage").style.width)||100;$("image-stage").style.width=Math.max(100,width*(event.deltaY>0?.9:1.1))+"%";}},{passive:false});
  window.chatUI={snapshot,submit,execute:local,syncControls,syncHighlights,onUpload,onDocument,onScene,onSelection,onProposal,onJobs,onError,mergeConversation,openWorkspace};
  let stored="system";try{stored=localStorage.getItem("blueprint-theme")||"system";}catch{}applyTheme(["light","dark","system"].includes(stored)?stored:"system");
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change",()=>{if(ui.theme==="system")applyTheme("system");});
  syncControls();closeWorkspace();
})();
