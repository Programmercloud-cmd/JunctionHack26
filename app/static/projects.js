/* Project organization is metadata only; opening files never starts inference. */
"use strict";
(() => {
  const list=$("home-library-list"),table=list.closest("table"),title=$("home-library-title"),back=$("home-projects-back"),projectName=$("home-project-name");
  const createForm=$("project-create-form"),createName=$("project-create-name"),createButton=$("home-new-project");
  const home=$("home-library"),dropZone=$("project-drop-zone"),dropHint=$("home-drop-hint");
  let editing=null,pending=false,removed=null,deletedProject=null;
  let chats=[],chatScope=null,chatLoadEpoch=0,previewEpoch=0,previewId=null,editingChat=null;
  const chatsBox=$("project-chats"),chatsList=$("project-chat-list"),chatStatus=$("project-chats-status"),previewPanel=$("chat-preview"),previewContent=$("chat-preview-content");
  const node=(tag,text,cls)=>{const element=document.createElement(tag);if(text!=null)element.textContent=text;if(cls)element.className=cls;return element;};
  const button=(text,action,cls="secondary-button")=>{const element=node("button",text,cls);element.type="button";element.addEventListener("click",()=>Promise.resolve(action()).catch(error=>report(error.message)));return element;};
  const report=text=>{$("home-remove-status").textContent=text;};
  const project=id=>(state.buildingScopes||[]).find(item=>item.id===id);
  const owner=p=>p.owner_project_id||p.id;
  const scoped=p=>`/api/projects/${owner(p)}/scopes/${p.scope_id}`;
  const activeScope=()=>project(state.activeBuildingScopeId);
  const effective=session=>session.effective_building_id!==undefined?session.effective_building_id:session.building_id;
  const captureUploadTarget=(p=chatUI.isHome()?project(state.homeProjectId):activeScope())=>p?{id:p.id,owner_project_id:owner(p),scope_id:p.scope_id,source_group_id:p.source_group_id,upload_allowed:p.upload_allowed,upload_reason:p.upload_reason,name:p.name}:null;
  function chooseUpload(p=chatUI.isHome()?project(state.homeProjectId):activeScope()){
    if(!p)throw new Error("Create or choose a Building before uploading drawings.");
    if(!p.upload_allowed)throw new Error(p.upload_reason||"Drawing upload is unavailable for this Building.");
    state.uploadTarget=captureUploadTarget(p);$("file-input").click();
  }
  const documents=p=>(p?.building_ids||[]).map(id=>state.savedBuildings.find(doc=>(doc.building_id||doc.document_id)===id)).filter(Boolean);
  const fileDrag=event=>Array.from(event.dataTransfer?.types||[]).includes("Files");
  const dropProject=event=>{if(!chatUI.isHome())return null;const row=event.target.closest?.("tr[data-project-id]");return project(row?.dataset.projectId||state.homeProjectId);};
  const canDrop=p=>Boolean(p&&p.upload_allowed&&state.health&&!state.busy&&!pending&&!(state.taskAccess?.public_demo&&!state.taskAccess.can_work));
  function clearDrop(){home.querySelectorAll(".project-drop-active").forEach(element=>element.classList.remove("project-drop-active"));}
  for(const type of ["dragenter","dragover"])home.addEventListener(type,event=>{
    if(!fileDrag(event))return;event.preventDefault();const p=dropProject(event),allowed=canDrop(p);event.dataTransfer.dropEffect=allowed?"copy":"none";clearDrop();
    if(allowed)(event.target.closest?.("tr[data-project-id]")||dropZone).classList.add("project-drop-active");
  });
  home.addEventListener("dragleave",event=>{if(!home.contains(event.relatedTarget))clearDrop();});
  home.addEventListener("drop",event=>{
    if(!fileDrag(event))return;event.preventDefault();event.stopPropagation();clearDrop();const p=dropProject(event);
    if(!canDrop(p)){report(p&&!p.upload_allowed?p.upload_reason:state.busy||pending?"Wait for the current upload to finish.":"Choose an editable Building before dropping files.");return;}
    const files=Array.from(event.dataTransfer.files);if(files.length)uploadFile(files,false,captureUploadTarget(p)).catch(error=>report(error.message));
  });
  dropZone.addEventListener("click",()=>$("home-upload").click());
  window.addEventListener("dragend",clearDrop);
  function preview(doc){
    const cell=node("td",null,"home-preview-cell"),page=doc?.pages?.[0];
    if(page?.image_url){const image=node("img");image.src=page.image_url;image.alt=`Preview of ${doc.filename}`;image.loading="lazy";image.className="home-preview";cell.append(image);}
    else{const icon=node("span",doc?.kind==="ifc"?"▧ IFC":"▤","home-preview-placeholder");icon.setAttribute("role","img");icon.setAttribute("aria-label",doc?.kind==="ifc"?"IFC model file":"Empty Building");cell.append(icon);}
    return cell;
  }
  function availability(row,docs){for(const ready of [docs.length>0&&docs.every(doc=>doc.kind!=="ifc"&&doc.interpretation_status==="complete"),docs.some(doc=>doc.has_scene)]){const cell=node("td");if(ready){const check=node("span","✓","home-file-check");check.setAttribute("aria-label","Yes");cell.append(check);}row.append(cell);}}
  async function openFile(p,id,options={}){
    if(id!==p.source_group_id)throw new Error("Choose a drawing from this Building.");
    chatUI.invalidateNavigation();const navigation=chatUI.snapshot().navigation_epoch;const current=()=>chatUI.snapshot().navigation_epoch===navigation&&Boolean(project(p.id));
    if(!canWork()){
      const doc=await request(`/api/buildings/${id}`),prepared=await prepareDocument(doc,"source",options.page??null);
      if(!current())return false;return chatUI.openReadOnlyFile(p,id,{document:doc,prepared,isCurrent:current});
    }
    const saved=await request(scoped(p)+"/chats");if(!current())return false;
    const session=saved.chats.find(item=>item.id===state.activeSessionId&&state.activeBuildingScopeId===p.id)||saved.chats[0]||await request(scoped(p)+"/chats",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({name:"New chat"})});
    if(!current())return false;return openChat(p,session,{...options,isCurrent:current});
  }
  let drawingPending=false;
  function drawingFiles(){
    const p=activeScope(),doc=state.document;if(!p||!doc||doc.document_id!==p.source_group_id)return [];
    const pages=doc.pages||[],files=[];
    const ids=[...new Set([...(doc.sources||[]).map(source=>source.source_id),...pages.map(page=>page.source_id||null)])];
    for(const sourceId of ids){const sourcePages=pages.filter(page=>(page.source_id||null)===sourceId);if(!sourcePages.length)continue;
      const source=(doc.sources||[]).find(item=>item.source_id===sourceId);
      files.push({key:`${doc.document_id}:${sourceId||"original"}`,building_id:doc.document_id,source_id:sourceId,filename:source?.filename||sourcePages[0].source_filename||doc.filename,building_filename:doc.filename,pages:sourcePages,revision_id:doc.revision_id});
    }return files;
  }
  async function inspectDrawing(key){
    if(drawingPending||state.busy||state.sessionOpening)return false;
    const file=drawingFiles().find(item=>item.key===key);if(!file||file.building_id!==state.document?.document_id)return false;
    drawingPending=true;window.dispatchEvent(new CustomEvent("blueprint:workspace"));
    try{return await chatUI.execute({type:"browse_source",page:file.pages[0].page,source_revision_id:file.revision_id});}
    finally{drawingPending=false;window.dispatchEvent(new CustomEvent("blueprint:workspace"));}
  }
  function openProject(p){showFiles(p);}

  function showFiles(p){if(!p)return;if(state.homeProjectId!==p.id){chatScope=null;resetPreview();}state.homeProjectId=p.id;chatUI.showHome();refresh();}
  function showProjects(){state.homeProjectId=null;editing=null;chatScope=null;resetPreview();chatUI.showHome();refresh();}
  async function rename(p,input,open){
    if(editing!==p.id||pending)return;
    const name=input.value.trim();if(!name){input.setCustomValidity("Enter a Building name");input.reportValidity();return;}
    if(name===p.name){editing=null;refresh();return;}
    pending=true;
    try{const updated=await request(scoped(p),{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify({name})});Object.assign(p,updated);Object.assign(project(p.id)||p,updated);await refreshSavedBuildings();editing=null;report("Building name saved.");}
    catch(error){report(error.message);input.focus();}
    finally{pending=false;refresh();}
  }
  function projectRow(p){
    const docs=documents(p),active=docs.find(doc=>(doc.building_id||doc.document_id)===p.active_building_id)||docs[0],row=node("tr");row.dataset.projectId=p.id;row.append(preview(active));
    const cell=row.firstElementChild,openPreview=button("",()=>openProject(p),"home-preview-button");openPreview.setAttribute("aria-label",`Open Building ${p.name}`);openPreview.append(...cell.childNodes);cell.append(openPreview);
    const name=node("th");name.scope="row";const actions=node("div",null,"home-file-actions"),open=button(p.name,()=>openProject(p),"home-file");actions.append(open);
    if(!p.read_only){const edit=button("✎",()=>{editing=p.id;list.dataset.projects="";open.hidden=true;edit.hidden=true;input.hidden=false;input.value=p.name;input.focus();input.select();},"project-rename secondary-button");edit.setAttribute("aria-label",`Rename Building ${p.name}`);
      const input=node("input");input.type="text";input.className="project-name-editor";input.setAttribute("aria-label",`Building name for ${p.name}`);input.hidden=true;
      input.addEventListener("input",()=>input.setCustomValidity(""));input.addEventListener("keydown",event=>{if(event.key==="Enter"){event.preventDefault();rename(p,input,open);}if(event.key==="Escape"){editing=null;refresh();}});input.addEventListener("blur",()=>rename(p,input,open));actions.append(edit,input);
      actions.append(iconButton(`Delete Building ${p.name}`,"M4 7h16M9 7V4h6v3M6 7l1 14h10l1-14M10 10v7m4-7v7",()=>deleteProject(p),"project-delete session-delete"));}
    name.append(actions);row.append(name);
    const files=node("td"),browse=button(`▤ ${docs.reduce((count,doc)=>count+(doc.sources?.length||1),0)}`,()=>showFiles(p),"project-files secondary-button");browse.setAttribute("aria-label",`Drawings in ${p.name}`);browse.title="Open this Building’s drawings and chats";files.append(browse);row.append(files);availability(row,docs);return row;
  }
  async function deleteProject(p){
    if(pending||p.read_only)return;pending=true;refresh();
    try{await request(scoped(p),{method:"DELETE"});deletedProject=p;
      if(state.activeBuildingScopeId===p.id){state.activeBuildingScopeId=null;state.activeProjectId=null;state.activeSessionId=null;state.sessionEpoch=(state.sessionEpoch||0)+1;}
      if(state.homeProjectId===p.id)state.homeProjectId=null;
      editing=null;chatScope=null;resetPreview();await refreshSavedBuildings();report(`${p.name} removed. Saved drawings, models and chats are retained; Undo restores this Building.`);
    }finally{pending=false;refresh();}
  }
  function sourceRows(p){
    const doc=documents(p)[0];if(!doc)return [];
    const sources=doc.sources?.length?doc.sources:[{source_id:null,filename:doc.filename}];
    return sources.map(source=>{
      const row=node("tr");row.dataset.buildingId=doc.building_id||doc.document_id;row.dataset.sourceId=source.source_id||"";
      const first=doc.pages?.find(page=>(page.source_id||null)===(source.source_id||null));row.append(preview({...doc,pages:first?[first]:[]}));
      const name=node("th");name.scope="row";name.append(button(source.filename,()=>openFile(p,p.source_group_id,{page:first?.page}),"home-file"));
      row.append(name);availability(row,[doc]);return row;
    });
  }
  const canWork=()=>!(state.taskAccess?.public_demo&&!state.taskAccess.can_work);
  function iconButton(label,path,action,cls=""){
    const b=button("",action,`session-icon ${cls}`);b.setAttribute("aria-label",label);b.title=label;
    const svg=document.createElementNS("http://www.w3.org/2000/svg","svg");svg.setAttribute("viewBox","0 0 24 24");svg.setAttribute("aria-hidden","true");
    const shape=document.createElementNS(svg.namespaceURI,"path");for(const [key,value]of Object.entries({d:path,fill:"none",stroke:"currentColor","stroke-width":"1.7","stroke-linecap":"round","stroke-linejoin":"round"}))shape.setAttribute(key,value);svg.append(shape);b.append(svg);return b;
  }
  function resetPreview(){previewEpoch++;previewId=null;previewContent.replaceChildren();const empty=node("div",null,"preview-empty");const logo=node("img");logo.className="preview-logo";logo.src="/static/concrete-logo.png";logo.alt="";logo.setAttribute("aria-hidden","true");empty.append(logo,node("strong","Concrete"));previewContent.append(empty);$("chat-preview-title").textContent="Chat preview";$("clear-chat-preview").hidden=true;}
  function previewTurn(message,session){
    const article=node("article",null,`preview-turn preview-${message.role}`);article.append(node("strong",message.role==="user"?"You":"Concrete"),node("p",message.question||message.answer?.answer||message.content||""));
    const answer=message.answer;
    if(answer?.evidence?.length||answer?.model_evidence?.length){
      const details=node("details");details.append(node("summary","Evidence and sources"));
      for(const evidence of answer.evidence||[]){
        const identity=message.document_id||session.building_id,revision=answer.answered_revision_id||message.revision_id;
        const text=`Page ${evidence.page} · ${evidence.label||"Source"}`;
        if(/^[a-f0-9]{64}$/.test(identity||"")&&/^[a-f0-9]{32}$/.test(revision||"")&&Number.isInteger(evidence.page)&&evidence.page>0){
          const source=button(text,()=>{image.hidden=!image.hidden;},"preview-source"),image=node("img");image.alt=evidence.label||"Original source page";image.src=`/api/buildings/${identity}/revisions/${revision}/pages/${evidence.page}`;image.loading="lazy";image.hidden=true;details.append(source,image);
        }else details.append(node("p",text));
        if(evidence.observation)details.append(node("p",evidence.observation));
      }
      for(const evidence of answer.model_evidence||[])details.append(node("p",evidence.label||evidence.global_id||"Original IFC record"));
      article.append(details);
    }
    return article;
  }
  async function previewChat(p,session){
    const token=++previewEpoch;previewId=session.id;$("chat-preview-title").textContent=session.name;$("clear-chat-preview").hidden=false;previewContent.replaceChildren(node("p","Loading saved conversation…"));
    const record=await request(`/api/projects/${owner(p)}/chats/${session.id}`);
    if(token!==previewEpoch||p.id!==state.homeProjectId)return;
    previewContent.replaceChildren();if(!record.messages.length)previewContent.append(node("p","No messages in this chat yet.","preview-note"));
    else for(const message of record.messages)previewContent.append(previewTurn(message,record));
    renderChats(p);
  }
  async function openChat(p,session,options={}){
    p=project(p.id)||p;if(options.isCurrent&&!options.isCurrent())return false;
    chatUI.invalidateNavigation();const navigation=chatUI.snapshot().navigation_epoch,openingEpoch=state.sessionEpoch;
    const current=()=>chatUI.snapshot().navigation_epoch===navigation&&Boolean(project(p.id));
    state.sessionOpening=true;chatUI.syncControls();window.dispatchEvent(new CustomEvent("blueprint:workspace"));
    try{
      const record=await request(`/api/projects/${owner(p)}/chats/${session.id}`);if(!current())return false;
      const id=effective(record);if((id||null)!==(p.source_group_id||null))throw new Error("This chat's Building changed. Refresh the overview before opening it.");
      let doc=null,prepared=null;
      if(id){doc=await request(`/api/buildings/${id}`);prepared=await prepareDocument(doc,"source",options.page??null);if(!current())return false;}
      return await chatUI.openSession(p,record,{...(doc?{document:doc,prepared}:{}),isCurrent:current});
    }finally{if(state.sessionEpoch===openingEpoch)state.sessionOpening=false;chatUI.syncControls();window.dispatchEvent(new CustomEvent("blueprint:workspace"));}
  }
  async function trackTask(job,scope){
    if(!scope?.project_id||job.origin)return job;
    const body={project_id:scope.project_id};
    if(scope.session_id)body.session_id=scope.session_id;
    return request(`/api/jobs/${job.id}/origin`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
  }
  async function openTask(job){
    let origin=job.origin;
    let p=(state.buildingScopes||[]).find(item=>(!origin?.project_id||owner(item)===origin.project_id)&&(item.source_group_id===job.building_id||!job.building_id&&item.scope_id==="shared"));
    if(!p)throw new Error("This task's Building is not currently available.");
    if(!origin){const records=await request(scoped(p)+"/chats");for(const saved of records.chats){const chat=await request(`/api/projects/${owner(p)}/chats/${saved.id}`);const message=chat.messages.find(message=>message.role==="user"&&(message.job_id===job.id||job.request_id&&message.request_id===job.request_id));if(message){origin={project_id:owner(p),session_id:chat.id,message_id:message.id,request_id:message.request_id};job={...job,origin};break;}}}
    if(origin?.session_id){try{const session=await request(`/api/projects/${owner(p)}/chats/${origin.session_id}`);await openChat(p,session);chatUI.focusTaskOrigin(job);return;}catch(error){showFiles(p);report("The initiating chat is unavailable. Saved drawings and the task remain available.");return;}}
    showFiles(p);report("Opened this task's Building. No initiating chat message was recorded for this task.");
  }
  async function newChat(){
    const p=project(state.homeProjectId);if(!p||!canWork()||pending)return;const navigation=chatUI.snapshot().navigation_epoch;pending=true;refresh();
    try{const session=await request(scoped(p)+"/chats",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({name:"New chat"})});chatScope=null;if(navigation===chatUI.snapshot().navigation_epoch)await openChat(p,session);}finally{pending=false;refresh();}
  }
  function renderChats(p){
    if(editingChat)return;
    chatsList.replaceChildren();
    for(const session of chats){
      const row=node("div",null,"project-chat-row");row.setAttribute("role","listitem");row.dataset.sessionId=session.id;row.classList.toggle("preview-selected",previewId===session.id);
      const info=node("div",null,"session-info"),name=button(session.name,()=>openChat(p,session),"session-name"),time=node("time",new Date(session.last_active*1000).toLocaleString());time.dateTime=new Date(session.last_active*1000).toISOString();info.append(name,time);
      row.append(info);
      const preview=iconButton(`Preview ${session.name}`,"M2 12s3-7 10-7 10 7 10 7-3 7-10 7S2 12 2 12m13 0a3 3 0 1 0-6 0 3 3 0 0 0 6 0",()=>previewChat(p,session),"session-preview");row.append(preview);
      const input=node("input");input.type="text";input.hidden=true;input.setAttribute("aria-label",`Chat name for ${session.name}`);let saving=false;
      async function save(){if(editingChat!==session.id||saving)return;const value=input.value.trim();if(!value){input.setCustomValidity("Enter a chat name");input.reportValidity();return;}saving=true;try{await request(`/api/projects/${owner(p)}/chats/${session.id}`,{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify({name:value})});editingChat=null;await loadChats(p);if(previewId===session.id)$("chat-preview-title").textContent=value;}catch(error){report(error.message);}finally{saving=false;}}
      input.addEventListener("input",()=>input.setCustomValidity(""));input.addEventListener("keydown",event=>{if(event.key==="Enter"){event.preventDefault();save();}if(event.key==="Escape"){editingChat=null;renderChats(p);}});input.addEventListener("blur",save);
      row.append(iconButton(`Rename ${session.name}`,"m4 16-1 5 5-1L20 8l-4-4L4 16m10-10 4 4",()=>{editingChat=session.id;name.hidden=true;input.hidden=false;input.value=session.name;input.focus();input.select();},"session-rename"),input);
      row.append(iconButton(`Delete ${session.name}`,"M4 7h16M9 7V4h6v3M6 7l1 14h10l1-14M10 10v7m4-7v7",async()=>{
        await request(`/api/projects/${owner(p)}/chats/${session.id}`,{method:"DELETE"});if(previewId===session.id)resetPreview();if(state.activeSessionId===session.id){state.activeSessionId=null;state.sessionEpoch=(state.sessionEpoch||0)+1;}await loadChats(p);
      },"session-delete"));chatsList.append(row);
    }
    chatStatus.textContent=chats.length?"":"No chats yet. Start a conversation for this Building.";
  }
  async function loadChats(p){
    const token=++chatLoadEpoch;chatStatus.textContent="Loading chats…";
    try{const result=await request(scoped(p)+"/chats");if(token!==chatLoadEpoch||p.id!==state.homeProjectId)return;chats=result.chats||[];renderChats(p);}
    catch(error){if(token===chatLoadEpoch&&p.id===state.homeProjectId)chatStatus.textContent=error.message;}
  }
  $("new-project-chat").addEventListener("click",()=>newChat().catch(error=>report(error.message)));
  $("clear-chat-preview").addEventListener("click",()=>{resetPreview();const p=project(state.homeProjectId);if(p)renderChats(p);});
  $("back-project-overview").addEventListener("click",()=>{const p=activeScope();if(p)showFiles(p);else showProjects();});
  function refresh(){
    const p=project(state.homeProjectId);if(state.homeProjectId&&!p)state.homeProjectId=null;
    const overview=chatUI.isHome()&&Boolean(p);
    document.getElementById("chat-shell").classList.toggle("project-overview",overview);previewPanel.hidden=!overview;chatsBox.hidden=!p;
    const scope=overview?`${p.id}:${p.source_group_id}:${state.taskAccess?.can_work}`:null;
    if(overview&&scope!==chatScope){chatScope=scope;chats=[];editingChat=null;resetPreview();chatsList.replaceChildren();if(canWork())loadChats(p);else chatStatus.textContent="Unlock the workspace to view Building chats.";}
    $("new-project-chat").disabled=!canWork()||pending||Boolean(state.busy);
    const filesMode=Boolean(p),items=filesMode?documents(p):(state.buildingScopes||[]);
    const legacy=(state.projects||[]).some(item=>(item.building_ids||[]).length>1);
    const notice=$("building-scope-notice");notice.hidden=!legacy;notice.textContent="Previously separate drawing groups are shown as separate Buildings. Their chats, models and annotations are preserved.";
    title.textContent=filesMode?"Drawings":"Buildings";back.hidden=!filesMode;projectName.hidden=!filesMode;projectName.textContent=p?.name||"";
    table.setAttribute("aria-label",filesMode?`Drawings in ${p.name}`:"Saved Buildings");$("home-name-column").textContent=filesMode?"Drawing":"Building name";$("home-files-column").hidden=filesMode;
    createButton.hidden=filesMode;createButton.disabled=Boolean(state.taskAccess?.public_demo&&!state.taskAccess.can_work)||pending||Boolean(state.busy);
    dropZone.hidden=!filesMode;dropZone.disabled=!canDrop(p);dropZone.textContent=p&&!p.upload_allowed?p.upload_reason:"Drop drawings here, or click Upload drawings";
    dropHint.hidden=filesMode||!(state.buildingScopes||[]).length;
    $("home-upload").hidden=!filesMode;$("home-upload").disabled=!state.health||Boolean(state.busy)||pending||!p?.upload_allowed;$("home-upload").title=p?.upload_reason||"Add drawings to this Building for every chat";
    const signature=JSON.stringify([state.homeProjectId,items,filesMode?null:state.savedBuildings.map(doc=>[doc.building_id,doc.has_scene,doc.interpretation_status,doc.pages?.[0]?.image_url])]);
    // Metadata polling must not replace a focused project-name editor.
    if(!editing&&list.dataset.projects!==signature){list.replaceChildren(...(filesMode?sourceRows(p):items.map(projectRow)));list.dataset.projects=signature;}
    for(const row of list.rows)for(const control of row.querySelectorAll("button"))control.disabled=Boolean(state.busy)||pending;
    // A running render may keep an older API process alive while static UI updates.
    for(const trash of list.querySelectorAll(".project-delete"))trash.hidden=!state.health?.project_deletion_ready;
    table.hidden=!items.length;$("home-undo-remove").hidden=!removed;$("home-undo-remove").disabled=pending||Boolean(state.busy);
    $("home-undo-project").hidden=!deletedProject;$("home-undo-project").disabled=pending||Boolean(state.busy);
    const status=$("home-library-status");status.textContent=state.busy==="upload"?"Saving original files…":state.savedBuildingsError?"Saved Buildings could not be loaded.":!state.savedBuildingsLoaded?"Loading Buildings…":items.length?"":filesMode?"No drawings yet. Upload drawings for every chat in this Building.":"No Buildings yet. Create a Building to add drawings.";status.hidden=!status.textContent;
    const error=$("home-library-error");error.textContent=$("upload-error").textContent;error.hidden=!error.textContent;
  }
  createButton.addEventListener("click",()=>{createForm.hidden=false;createName.focus();});$("project-create-cancel").addEventListener("click",()=>{createForm.hidden=true;createName.value="";});
  createForm.addEventListener("submit",async event=>{event.preventDefault();if(pending)return;pending=true;try{const p=await request("/api/projects",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({name:createName.value})});createForm.hidden=true;createName.value="";await refreshSavedBuildings();showFiles((state.buildingScopes||[]).find(item=>owner(item)===p.id&&item.scope_id==="shared"));}catch(error){report(error.message);}finally{pending=false;refresh();}});
  back.addEventListener("click",showProjects);$("home-tab").addEventListener("click",()=>{state.homeProjectId=null;editing=null;refresh();});
  $("home-undo-remove").hidden=true;
  $("home-undo-project").addEventListener("click",async()=>{if(!deletedProject||pending)return;pending=true;refresh();try{const p=deletedProject;await request(scoped(p)+"/restore",{method:"POST"});deletedProject=null;await refreshSavedBuildings();report("Building restored with its drawings and chats.");}catch(error){report(error.message);}finally{pending=false;refresh();}});
  window.projectLibrary={refresh,showFiles,showProjects,openFile,openTask,trackTask,drawingFiles,inspectDrawing,drawingBusy:()=>drawingPending,activeScope,captureUploadTarget,chooseUpload,
    showActiveOverview:()=>{const p=activeScope();if(p)showFiles(p);else showProjects();},
    openBuilding:async id=>{const p=(state.buildingScopes||[]).find(item=>item.source_group_id===id&&owner(item)===state.activeProjectId)||(state.buildingScopes||[]).find(item=>item.source_group_id===id);if(!p)throw new Error("Choose the Building that owns this drawing.");return openFile(p,id);},
    onChatSaved:id=>{const p=project(state.homeProjectId);if(p&&owner(p)===id)chatScope=null;}};
  $("chat-shell").addEventListener("drop",event=>{if(chatUI.isHome()||!fileDrag(event))return;event.preventDefault();const p=activeScope();if(!canDrop(p)){setError("upload-error",p?.upload_reason||"Choose an editable Building before dropping drawings.");return;}const files=Array.from(event.dataTransfer.files);if(files.length)uploadFile(files,false,captureUploadTarget(p));});
  document.querySelector(".chat-brand").addEventListener("click",event=>{if(event.defaultPrevented)showProjects();});
  resetPreview();refresh();
})();
