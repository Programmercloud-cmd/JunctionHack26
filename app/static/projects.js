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
  const project=id=>(state.projects||[]).find(item=>item.id===id);
  const documents=p=>(p?.building_ids||[]).map(id=>state.savedBuildings.find(doc=>(doc.building_id||doc.document_id)===id)).filter(Boolean);
  const fileDrag=event=>Array.from(event.dataTransfer?.types||[]).includes("Files");
  const dropProject=event=>{if(!chatUI.isHome())return null;const row=event.target.closest?.("tr[data-project-id]");return project(row?.dataset.projectId||state.homeProjectId);};
  const canDrop=p=>Boolean(p&&!p.read_only&&state.health&&!state.busy&&!pending&&!(state.taskAccess?.public_demo&&!state.taskAccess.can_work));
  function clearDrop(){home.querySelectorAll(".project-drop-active").forEach(element=>element.classList.remove("project-drop-active"));}
  for(const type of ["dragenter","dragover"])home.addEventListener(type,event=>{
    if(!fileDrag(event))return;event.preventDefault();const p=dropProject(event),allowed=canDrop(p);event.dataTransfer.dropEffect=allowed?"copy":"none";clearDrop();
    if(allowed)(event.target.closest?.("tr[data-project-id]")||dropZone).classList.add("project-drop-active");
  });
  home.addEventListener("dragleave",event=>{if(!home.contains(event.relatedTarget))clearDrop();});
  home.addEventListener("drop",event=>{
    if(!fileDrag(event))return;event.preventDefault();event.stopPropagation();clearDrop();const p=dropProject(event);
    if(!canDrop(p)){report(p?.read_only?"This example is read-only. Drop files into an editable project.":state.busy||pending?"Wait for the current upload to finish.":"Choose an editable project before dropping files.");return;}
    const files=Array.from(event.dataTransfer.files);if(files.length)uploadFile(files,false,p.id).catch(error=>report(error.message));
  });
  dropZone.addEventListener("click",()=>$("home-upload").click());
  window.addEventListener("dragend",clearDrop);
  function preview(doc){
    const cell=node("td",null,"home-preview-cell"),page=doc?.pages?.[0];
    if(page?.image_url){const image=node("img");image.src=page.image_url;image.alt=`Preview of ${doc.filename}`;image.loading="lazy";image.className="home-preview";cell.append(image);}
    else{const icon=node("span",doc?.kind==="ifc"?"▧ IFC":"▤","home-preview-placeholder");icon.setAttribute("role","img");icon.setAttribute("aria-label",doc?.kind==="ifc"?"IFC model file":"Empty project");cell.append(icon);}
    return cell;
  }
  function availability(row,docs){for(const ready of [docs.length>0&&docs.every(doc=>doc.kind!=="ifc"&&doc.interpretation_status==="complete"),docs.some(doc=>doc.has_scene)]){const cell=node("td");if(ready){const check=node("span","✓","home-file-check");check.setAttribute("aria-label","Yes");cell.append(check);}row.append(cell);}}
  async function remember(p,id){
    state.activeProjectId=p.id;
    if(!p.read_only&&p.id.length===32){const next=await request(`/api/projects/${p.id}/active-file/${id}`,{method:"PUT"});Object.assign(p,next);Object.assign(project(p.id)||p,next);}
  }
  async function openFile(p,id,options={}){
    if(options.isCurrent&&!options.isCurrent())return false;
    if(!options.document)await remember(p,id);
    if(!canWork())return chatUI.openReadOnlyFile(p,id,options);
    const saved=await request(`/api/projects/${p.id}/chats`);
    if(options.isCurrent&&!options.isCurrent())return false;
    const session=saved.chats.find(item=>item.building_id===id)||await request(`/api/projects/${p.id}/chats`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({building_id:id})});
    if(options.isCurrent&&!options.isCurrent())return false;
    const opened=await openChat(p,session,options);
    if(options.document&&opened&&state.activeProjectId===p.id&&state.document?.document_id===id&&!chatUI.isHome())await remember(p,id);
    return opened;
  }
  let drawingPending=false;
  function drawingFiles(){
    const p=project(state.activeProjectId);if(!p)return [];
    const files=[];
    for(const id of p.building_ids||[]){
      const doc=id===state.document?.document_id?state.document:state.savedBuildings.find(item=>(item.building_id||item.document_id)===id);
      const pages=doc?.pages||[];if(!pages.length)continue;
      const sourceIds=[...new Set([...(doc.sources||[]).map(source=>source.source_id),...pages.map(page=>page.source_id||null)])];
      for(const sourceId of sourceIds){
        const sourcePages=pages.filter(page=>(page.source_id||null)===sourceId);if(!sourcePages.length)continue;
        const source=(doc.sources||[]).find(item=>item.source_id===sourceId);
        files.push({key:`${id}:${sourceId||"original"}`,building_id:id,source_id:sourceId,
          filename:source?.filename||sourcePages[0].source_filename||doc.filename,
          building_filename:doc.filename,pages:sourcePages,revision_id:doc.revision_id});
      }
    }
    return files;
  }
  async function inspectDrawing(key){
    if(drawingPending||pending||state.busy||state.sessionOpening)return false;
    const p=project(state.activeProjectId),file=drawingFiles().find(item=>item.key===key);
    if(!p||!file)return false;
    chatUI.invalidateNavigation();
    const captured={project:p.id,session:state.activeSessionId,sessionEpoch:state.sessionEpoch,documentEpoch:state.epoch,navigationEpoch:chatUI.snapshot().navigation_epoch};
    const current=()=>!chatUI.isHome()&&state.activeProjectId===captured.project&&state.activeSessionId===captured.session&&state.sessionEpoch===captured.sessionEpoch&&state.epoch===captured.documentEpoch&&chatUI.snapshot().navigation_epoch===captured.navigationEpoch&&Boolean(project(p.id)?.building_ids.includes(file.building_id));
    drawingPending=true;pending=true;state.sessionOpening=true;chatUI.syncControls();refresh();window.dispatchEvent(new CustomEvent("blueprint:workspace"));
    try{
      if(file.building_id===state.document?.document_id){
        return await chatUI.execute({type:"browse_source",page:file.pages[0].page,source_revision_id:state.document.revision_id});
      }
      const doc=await request(`/api/buildings/${file.building_id}`);
      if(doc.document_id!==file.building_id||!Array.isArray(doc.pages))throw new Error("That file could not be opened. Your previous view is still open.");
      const page=(doc.pages||[]).find(item=>(item.source_id||null)===file.source_id);
      if(!page)throw new Error("That drawing is no longer available. Your previous view is still open.");
      const prepared=await prepareDocument(doc,"source",page.page);
      if(!current())return false;
      return await openFile(p,file.building_id,{document:doc,prepared,isCurrent:current});
    }finally{drawingPending=false;pending=false;if(state.sessionEpoch===captured.sessionEpoch)state.sessionOpening=false;chatUI.syncControls();refresh();window.dispatchEvent(new CustomEvent("blueprint:workspace"));}
  }
  function openProject(p){showFiles(p);}

  function showFiles(p){if(state.homeProjectId!==p.id){chatScope=null;resetPreview();}state.homeProjectId=p.id;chatUI.showHome();refresh();}
  function showProjects(){state.homeProjectId=null;editing=null;chatScope=null;resetPreview();chatUI.showHome();refresh();}
  async function rename(p,input,open){
    if(editing!==p.id||pending)return;
    const name=input.value.trim();if(!name){input.setCustomValidity("Enter a project name");input.reportValidity();return;}
    if(name===p.name){editing=null;refresh();return;}
    pending=true;
    try{const updated=await request(`/api/projects/${p.id}`,{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify({name})});Object.assign(p,updated);Object.assign(project(p.id)||p,updated);await refreshSavedBuildings();editing=null;report("Project name saved.");}
    catch(error){report(error.message);input.focus();}
    finally{pending=false;refresh();}
  }
  function projectRow(p){
    const docs=documents(p),active=docs.find(doc=>(doc.building_id||doc.document_id)===p.active_building_id)||docs[0],row=node("tr");row.dataset.projectId=p.id;row.append(preview(active));
    const cell=row.firstElementChild,openPreview=button("",()=>openProject(p),"home-preview-button");openPreview.setAttribute("aria-label",`Open project ${p.name}`);openPreview.append(...cell.childNodes);cell.append(openPreview);
    const name=node("th");name.scope="row";const actions=node("div",null,"home-file-actions"),open=button(p.name,()=>openProject(p),"home-file");actions.append(open);
    if(!p.read_only){const edit=button("✎",()=>{editing=p.id;list.dataset.projects="";open.hidden=true;edit.hidden=true;input.hidden=false;input.value=p.name;input.focus();input.select();},"project-rename secondary-button");edit.setAttribute("aria-label",`Rename project ${p.name}`);
      const input=node("input");input.type="text";input.className="project-name-editor";input.setAttribute("aria-label",`Project name for ${p.name}`);input.hidden=true;
      input.addEventListener("input",()=>input.setCustomValidity(""));input.addEventListener("keydown",event=>{if(event.key==="Enter"){event.preventDefault();rename(p,input,open);}if(event.key==="Escape"){editing=null;refresh();}});input.addEventListener("blur",()=>rename(p,input,open));actions.append(edit,input);
      actions.append(iconButton(`Delete project ${p.name}`,"M4 7h16M9 7V4h6v3M6 7l1 14h10l1-14M10 10v7m4-7v7",()=>deleteProject(p),"project-delete session-delete"));}
    name.append(actions);row.append(name);
    const files=node("td"),browse=button(`▤ ${docs.length}`,()=>showFiles(p),"project-files secondary-button");browse.setAttribute("aria-label",`Files in ${p.name}`);browse.title="Browse and upload this project's files in Home";files.append(browse);row.append(files);availability(row,docs);return row;
  }
  async function removeFile(p,doc){pending=true;refresh();try{await request(`/api/projects/${p.id}/files/${doc.building_id||doc.document_id}`,{method:"DELETE"});removed={project_id:p.id,document:doc};await refreshSavedBuildings();report(`${doc.filename} removed from this project. The saved source and model are retained.`);}finally{pending=false;refresh();}}
  async function deleteProject(p){
    if(pending||p.read_only)return;pending=true;refresh();
    try{
      deletedProject=await request(`/api/projects/${p.id}`,{method:"DELETE"});
      if(state.activeProjectId===p.id){state.activeProjectId=null;state.activeSessionId=null;state.sessionEpoch=(state.sessionEpoch||0)+1;}
      if(state.homeProjectId===p.id)state.homeProjectId=null;
      editing=null;chatScope=null;resetPreview();await refreshSavedBuildings();
      report(`${p.name} deleted. Saved files, models and chats are retained; Undo restores the project.`);
    }finally{pending=false;refresh();}
  }
  function fileRow(p,doc){
    const row=node("tr");row.dataset.buildingId=doc.building_id||doc.document_id;row.append(preview(doc));const name=node("th");name.scope="row";const actions=node("div",null,"home-file-actions");actions.append(button(doc.filename,()=>openFile(p,doc.building_id||doc.document_id),"home-file"));
    if(doc.local_file_path){const copy=button("Copy path",async()=>{try{await navigator.clipboard.writeText(doc.local_file_path);$("home-copy-status").textContent="File path copied.";}catch{$("home-copy-status").textContent="Could not copy the file path. Check clipboard access in your browser.";}},"home-copy-path secondary-button");copy.setAttribute("aria-label",`Copy path for ${doc.filename}`);actions.append(copy);}
    if(!p.read_only){const remove=button("Remove",()=>removeFile(p,doc),"home-remove-file secondary-button");remove.setAttribute("aria-label",`Remove ${doc.filename} from project`);actions.append(remove);}
    name.append(actions);row.append(name);availability(row,[doc]);return row;
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
    const record=await request(`/api/projects/${p.id}/chats/${session.id}`);
    if(token!==previewEpoch||p.id!==state.homeProjectId)return;
    previewContent.replaceChildren();if(!record.messages.length)previewContent.append(node("p","No messages in this chat yet.","preview-note"));
    else for(const message of record.messages)previewContent.append(previewTurn(message,record));
    renderChats(p);
  }
  async function openChat(p,session,options={}){
    if(session.building_id&&!p.building_ids.includes(session.building_id))throw new Error("This chat's file was removed from the project. You can still preview the saved conversation.");
    return chatUI.openSession(p,session,options);
  }
  async function trackTask(job,scope){
    if(!scope?.project_id||job.origin)return job;
    const body={project_id:scope.project_id};
    if(scope.session_id)body.session_id=scope.session_id;
    return request(`/api/jobs/${job.id}/origin`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
  }
  async function openTask(job){
    let origin=job.origin;const p=project(origin?.project_id||job.project_id)||(state.projects||[]).find(item=>!origin&&item.building_ids.includes(job.building_id));
    if(!p)throw new Error("This task's project is not currently available.");
    if(!origin){
      const records=await request(`/api/projects/${p.id}/chats`);
      for(const saved of records.chats.filter(chat=>chat.building_id===job.building_id)){
        const chat=await request(`/api/projects/${p.id}/chats/${saved.id}`);
        const message=chat.messages.find(message=>message.role==="user"&&(message.job_id===job.id||job.request_id&&message.request_id===job.request_id));
        if(message){origin={project_id:p.id,session_id:chat.id,message_id:message.id,request_id:message.request_id};job={...job,origin};break;}
      }
    }
    if(origin?.session_id){
      let session;
      try{session=await request(`/api/projects/${p.id}/chats/${origin.session_id}`);}
      catch(error){showFiles(p);report("The initiating chat is unavailable. The project files and saved task remain available.");return;}
      if(!session.building_id||p.building_ids.includes(session.building_id)){
        await openChat(p,session);chatUI.focusTaskOrigin(job);return;
      }
    }
    showFiles(p);
    const row=[...list.rows].find(row=>row.dataset.buildingId===job.building_id);
    if(row){row.classList.add("task-origin-focus");row.scrollIntoView({block:"center"});}
    report("Opened this task's project files. No initiating chat message was recorded for this task.");
  }
  async function newChat(){
    const p=project(state.homeProjectId);if(!p||!canWork()||pending)return;
    pending=true;refresh();
    try{const id=p.building_ids.includes(p.active_building_id)?p.active_building_id:null;
      const session=await request(`/api/projects/${p.id}/chats`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({building_id:id})});chatScope=null;await openChat(p,session);
    }finally{pending=false;refresh();}
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
      async function save(){if(editingChat!==session.id||saving)return;const value=input.value.trim();if(!value){input.setCustomValidity("Enter a chat name");input.reportValidity();return;}saving=true;try{await request(`/api/projects/${p.id}/chats/${session.id}`,{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify({name:value})});editingChat=null;await loadChats(p);if(previewId===session.id)$("chat-preview-title").textContent=value;}catch(error){report(error.message);}finally{saving=false;}}
      input.addEventListener("input",()=>input.setCustomValidity(""));input.addEventListener("keydown",event=>{if(event.key==="Enter"){event.preventDefault();save();}if(event.key==="Escape"){editingChat=null;renderChats(p);}});input.addEventListener("blur",save);
      row.append(iconButton(`Rename ${session.name}`,"m4 16-1 5 5-1L20 8l-4-4L4 16m10-10 4 4",()=>{editingChat=session.id;name.hidden=true;input.hidden=false;input.value=session.name;input.focus();input.select();},"session-rename"),input);
      row.append(iconButton(`Delete ${session.name}`,"M4 7h16M9 7V4h6v3M6 7l1 14h10l1-14M10 10v7m4-7v7",async()=>{
        await request(`/api/projects/${p.id}/chats/${session.id}`,{method:"DELETE"});if(previewId===session.id)resetPreview();if(state.activeSessionId===session.id){state.activeSessionId=null;state.sessionEpoch=(state.sessionEpoch||0)+1;}await loadChats(p);
      },"session-delete"));chatsList.append(row);
    }
    chatStatus.textContent=chats.length?"":"No chats yet. Start a new conversation for this project.";
  }
  async function loadChats(p){
    const token=++chatLoadEpoch;chatStatus.textContent="Loading chats…";
    try{const result=await request(`/api/projects/${p.id}/chats`);if(token!==chatLoadEpoch||p.id!==state.homeProjectId)return;chats=result.chats||[];renderChats(p);}
    catch(error){if(token===chatLoadEpoch&&p.id===state.homeProjectId)chatStatus.textContent=error.message;}
  }
  $("new-project-chat").addEventListener("click",()=>newChat().catch(error=>report(error.message)));
  $("clear-chat-preview").addEventListener("click",()=>{resetPreview();const p=project(state.homeProjectId);if(p)renderChats(p);});
  $("back-project-overview").addEventListener("click",()=>{const p=project(state.activeProjectId);if(p)showFiles(p);else showProjects();});
  function refresh(){
    const p=project(state.homeProjectId);if(state.homeProjectId&&!p)state.homeProjectId=null;
    const overview=chatUI.isHome()&&Boolean(p);
    document.getElementById("chat-shell").classList.toggle("project-overview",overview);previewPanel.hidden=!overview;chatsBox.hidden=!p;
    const scope=overview?`${p.id}:${state.taskAccess?.can_work}`:null;
    if(overview&&scope!==chatScope){chatScope=scope;chats=[];editingChat=null;resetPreview();chatsList.replaceChildren();if(canWork())loadChats(p);else chatStatus.textContent="Unlock the workspace to view project chats.";}
    $("new-project-chat").disabled=!canWork()||pending||Boolean(state.busy);
    const filesMode=Boolean(p),items=filesMode?documents(p):(state.projects||[]);
    title.textContent=filesMode?"Files":"Projects";back.hidden=!filesMode;projectName.hidden=!filesMode;projectName.textContent=p?.name||"";
    table.setAttribute("aria-label",filesMode?`Files in ${p.name}`:"Saved projects");$("home-name-column").textContent=filesMode?"File":"Project name";$("home-files-column").hidden=filesMode;
    createButton.hidden=filesMode;createButton.disabled=Boolean(state.taskAccess?.public_demo&&!state.taskAccess.can_work)||pending||Boolean(state.busy);
    dropZone.hidden=!filesMode;dropZone.disabled=!canDrop(p);dropZone.textContent=p?.read_only?"Read-only example · uploads are unavailable":"Drop files here, or click to choose files";
    dropHint.hidden=filesMode||!(state.projects||[]).length;
    $("home-upload").hidden=!filesMode&&Boolean((state.projects||[]).length);$("home-upload").disabled=!state.health||$("file-input").disabled||Boolean(state.busy)||pending||Boolean(p?.read_only);
    const signature=JSON.stringify([state.homeProjectId,items,filesMode?null:state.savedBuildings.map(doc=>[doc.building_id,doc.has_scene,doc.interpretation_status,doc.pages?.[0]?.image_url])]);
    // Metadata polling must not replace a focused project-name editor.
    if(!editing&&list.dataset.projects!==signature){list.replaceChildren(...items.map(item=>filesMode?fileRow(p,item):projectRow(item)));list.dataset.projects=signature;}
    for(const row of list.rows)for(const control of row.querySelectorAll("button"))control.disabled=Boolean(state.busy)||pending;
    // A running render may keep an older API process alive while static UI updates.
    for(const trash of list.querySelectorAll(".project-delete"))trash.hidden=!state.health?.project_deletion_ready;
    table.hidden=!items.length;$("home-undo-remove").hidden=!removed;$("home-undo-remove").disabled=pending||Boolean(state.busy);
    $("home-undo-project").hidden=!deletedProject;$("home-undo-project").disabled=pending||Boolean(state.busy);
    const status=$("home-library-status");status.textContent=state.busy==="upload"?"Saving original files…":state.savedBuildingsError?"Saved projects could not be loaded.":!state.savedBuildingsLoaded?"Loading projects…":items.length?"":filesMode?"No files in this project yet. Upload a drawing or IFC model.":"No projects yet. Create a project to add your files.";status.hidden=!status.textContent;
    const error=$("home-library-error");error.textContent=$("upload-error").textContent;error.hidden=!error.textContent;
  }
  createButton.addEventListener("click",()=>{createForm.hidden=false;createName.focus();});$("project-create-cancel").addEventListener("click",()=>{createForm.hidden=true;createName.value="";});
  createForm.addEventListener("submit",async event=>{event.preventDefault();if(pending)return;pending=true;try{const p=await request("/api/projects",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({name:createName.value})});createForm.hidden=true;createName.value="";await refreshSavedBuildings();showFiles(p);}catch(error){report(error.message);}finally{pending=false;refresh();}});
  back.addEventListener("click",showProjects);$("home-tab").addEventListener("click",()=>{state.homeProjectId=null;editing=null;refresh();});
  $("home-undo-remove").addEventListener("click",async()=>{if(!removed||pending)return;pending=true;const item=removed;try{await request(`/api/projects/${item.project_id}/files/${item.document.building_id||item.document.document_id}`,{method:"PUT"});removed=null;await refreshSavedBuildings();report("File restored to project.");}catch(error){report(error.message);}finally{pending=false;refresh();}});
  $("home-undo-project").addEventListener("click",async()=>{if(!deletedProject||pending)return;pending=true;refresh();try{await request(`/api/projects/${deletedProject.id}/restore`,{method:"POST"});deletedProject=null;await refreshSavedBuildings();report("Project restored with its files and chats.");}catch(error){report(error.message);}finally{pending=false;refresh();}});
  window.projectLibrary={refresh,showFiles,showProjects,openFile,openTask,trackTask,drawingFiles,inspectDrawing,drawingBusy:()=>drawingPending,
    openBuilding:async id=>{let p=project(state.activeProjectId);if(!p?.building_ids.includes(id))p=(state.projects||[]).find(item=>item.building_ids.includes(id));if(!p)throw new Error("Choose the project that owns this file.");return openFile(p,id);},
    onChatSaved:id=>{if(chatScope?.startsWith(id+":"))chatScope=null;},fileUploaded:async(result,id)=>{await request(`/api/projects/${id}/files/${result.building_id||result.document_id}`,{method:"PUT"});for(const job of result.extraction_jobs||[])await trackTask(job,{project_id:id});}};
  document.querySelector(".chat-brand").addEventListener("click",event=>{if(event.defaultPrevented)showProjects();});
  resetPreview();refresh();
})();
