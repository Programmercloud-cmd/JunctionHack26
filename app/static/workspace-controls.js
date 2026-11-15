/* Immediate navigation and read-only provenance presentation. The chat controller
   owns view/selection state; existing operations and saved evidence retain authority. */
"use strict";
(() => {
  const node = (tag, text, cls) => {const el=document.createElement(tag);if(text!=null)el.textContent=text;if(cls)el.className=cls;return el;};
  const navigation=$("workspace-navigation"), tools=$("workspace-tools"), summary=$("selection-evidence");
  const workspace = $("visual-workspace");
  const details = $("details-panel");
  const fullscreen = $("workspace-fullscreen");
  const divider = $("chat-divider");
  const content=$("workspace-content");
  function iconControl(label,id,path){
    const button=node("button");button.id=id;button.type="button";button.title=label;button.setAttribute("aria-label",label);
    const svg=document.createElementNS("http://www.w3.org/2000/svg","svg");svg.setAttribute("viewBox","0 0 24 24");svg.setAttribute("aria-hidden","true");
    svg.innerHTML=`<path d="${path}" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>`;button.append(svg);return button;
  }
  const rail=node("div",null,"workspace-icon-rail");rail.setAttribute("aria-label","Files and view settings");content.append(rail);
  const panels=[];
  function drawer(label,id,icon){
    const toggle=iconControl(label,id+"-toggle",icon),panel=node("section",null,"workspace-popover");panel.id=id;panel.hidden=true;panel.setAttribute("aria-label",label);
    toggle.setAttribute("aria-controls",id);toggle.setAttribute("aria-expanded","false");rail.append(toggle);content.append(panel);panels.push([toggle,panel]);
    toggle.addEventListener("click",()=>{const open=panel.hidden;for(const [button,other]of panels){other.hidden=true;button.setAttribute("aria-expanded","false");}panel.hidden=!open;toggle.setAttribute("aria-expanded",String(open));});
    panel.append(node("h3",label));return panel;
  }
  const filePanel=drawer("Files","workspace-files","M3 7h7l2 2h9v11H3ZM3 7V4h7l2 3M7 12h10m-10 4h7");
  const viewPanel=drawer("View settings","workspace-view","M2 12s3-7 10-7 10 7 10 7-3 7-10 7S2 12 2 12Zm13 0a3 3 0 1 0-6 0 3 3 0 0 0 6 0");
  const evidenceToggle=iconControl("Evidence and supplied values","workspace-evidence-toggle","m9 4 8 8-8 8");evidenceToggle.setAttribute("aria-controls","workspace-tools");evidenceToggle.setAttribute("aria-expanded","false");workspace.append(evidenceToggle);
  tools.hidden=true;tools.setAttribute("aria-label","Evidence and supplied values");
  const evidenceHeader=node("header",null,"evidence-drawer-heading"),evidenceClose=iconControl("Close evidence panel","workspace-evidence-close","m6 6 12 12M6 18 18 6");evidenceHeader.append(node("h3","Evidence and supplied values"),evidenceClose);tools.append(evidenceHeader);
  const nativeRecord=node("section",null,"workspace-native-record");nativeRecord.id="workspace-native-record";nativeRecord.hidden=true;nativeRecord.setAttribute("aria-label","Original IFC record");tools.append(nativeRecord);
  function showEvidence(open){tools.hidden=!open;evidenceToggle.setAttribute("aria-expanded",String(open));}
  function showNativeRecord(record){nativeRecord.replaceChildren(record);nativeRecord.hidden=false;showEvidence(true);nativeRecord.scrollIntoView({block:"nearest"});}
  evidenceToggle.addEventListener("click",()=>showEvidence(tools.hidden));evidenceClose.addEventListener("click",()=>{showEvidence(false);evidenceToggle.focus();});
  document.addEventListener("click",event=>{for(const [toggle,panel]of panels)if(!panel.hidden&&!panel.contains(event.target)&&!toggle.contains(event.target)){panel.hidden=true;toggle.setAttribute("aria-expanded","false");}});
  document.addEventListener("keydown",event=>{if(event.key!=="Escape")return;for(const [toggle,panel]of panels)if(!panel.hidden){panel.hidden=true;toggle.setAttribute("aria-expanded","false");toggle.focus();}if(!tools.hidden){showEvidence(false);evidenceToggle.focus();}});

  function syncFullscreen() {
    const active = document.fullscreenElement === workspace || workspace.classList.contains("workspace-expanded");
    fullscreen.classList.toggle("is-fullscreen",active);
    const view = chatUI.snapshot().view_mode === "source" ? "blueprint" : "3D model";
    fullscreen.setAttribute("aria-label", active ? "Exit full screen" : `Full screen: ${view}`);
    fullscreen.title=active?"Exit full screen":"Full screen";
  }

  fullscreen.addEventListener("click", async () => {
    if (document.fullscreenElement === workspace) {
      await document.exitFullscreen();
    } else if (workspace.classList.contains("workspace-expanded")) {
      workspace.classList.remove("workspace-expanded");
    } else {
      try {
        await workspace.requestFullscreen();
      } catch {
        if (!workspace.hidden) workspace.classList.add("workspace-expanded");
      }
    }
    syncFullscreen();
  });
  document.addEventListener("fullscreenchange", syncFullscreen);
  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && workspace.classList.contains("workspace-expanded")) {
      workspace.classList.remove("workspace-expanded");
      syncFullscreen();
      fullscreen.focus();
    }
  });

  function resizeChat(percent) {
    const width = Math.round(Math.max(25, Math.min(65, percent)));
    details.style.setProperty("--chat-width", `${width}%`);
    divider.setAttribute("aria-valuenow", String(width));
  }

  divider.addEventListener("pointerdown", event => {
    if (event.button !== 0 || !event.isPrimary) return;
    divider.setPointerCapture(event.pointerId);
    divider.focus();
  });
  divider.addEventListener("pointermove", event => {
    if (!divider.hasPointerCapture(event.pointerId)) return;
    const bounds = details.getBoundingClientRect();
    resizeChat((event.clientX - bounds.left) / bounds.width * 100);
  });
  divider.addEventListener("keydown", event => {
    const current = $("chat-column").offsetWidth / details.clientWidth * 100;
    const widths = {ArrowLeft: current - 3, ArrowRight: current + 3, Home: 25, End: 65};
    if (!Object.hasOwn(widths, event.key)) return;
    event.preventDefault();
    resizeChat(widths[event.key]);
  });
  new ResizeObserver(() => {
    if (details.clientWidth) {
      divider.setAttribute("aria-valuenow", String(Math.round($("chat-column").offsetWidth / details.clientWidth * 100)));
    }
  }).observe($("chat-column"));

  const status=node("p",null,"workspace-control-status");status.id="workspace-control-status";status.setAttribute("role","status");status.hidden=true;
  function showStatus(message){status.textContent=message;status.hidden=!message;}
  async function act(action){showStatus("");try{await chatUI.execute(action);}catch(error){showStatus(error.message);}finally{refresh();}}
  function control(label,action,id){const b=node("button",label);b.type="button";if(id)b.id=id;b.addEventListener("click",()=>act(typeof action==="function"?action():action));return b;}
  const tabs=node("div",null,"workspace-nav-buttons");
  const sources=node("button","Drawings");sources.id="workspace-blueprints";sources.type="button";
  const drawingPicker=node("section",null,"drawing-file-picker");drawingPicker.id="drawing-file-picker";drawingPicker.hidden=true;drawingPicker.setAttribute("aria-label","Building drawings");
  sources.setAttribute("aria-controls",drawingPicker.id);sources.setAttribute("aria-expanded","false");
  function setDrawingPicker(open){drawingPicker.hidden=!open;sources.setAttribute("aria-expanded",String(open));}
  sources.addEventListener("click",async()=>{
    const open=drawingPicker.hidden;showStatus("");
    try{if(open)showEvidence(false);if(state.document?.pages?.length&&chatUI.snapshot().view_mode!=="source")await chatUI.execute({type:"browse_source"});}
    catch(error){showStatus(error.message);}finally{refresh();setDrawingPicker(open);}
  });
  document.addEventListener("click",event=>{if(!drawingPicker.hidden&&!drawingPicker.contains(event.target)&&!sources.contains(event.target))setDrawingPicker(false);});
  document.addEventListener("keydown",event=>{if(event.key==="Escape"&&!drawingPicker.hidden){setDrawingPicker(false);sources.focus();}});
  async function inspectDrawing(key){showStatus("");setDrawingPicker(false);try{await projectLibrary.inspectDrawing(key);}catch(error){showStatus(error.message);}finally{refresh();}}
  function fileArrow(id,label,path){const b=iconControl(label,id,path);b.className="drawing-file-arrow";b.querySelector("svg").setAttribute("preserveAspectRatio","none");b.addEventListener("click",()=>{
    const files=projectLibrary.drawingFiles(),index=currentDrawingIndex(files),offset=id==="drawing-previous-file"?-1:1;
    if(index>=0&&files[index+offset])inspectDrawing(files[index+offset].key);
  });return b;}
  const previousFile=fileArrow("drawing-previous-file","Previous drawing file","m17 3-12 9 12 9");
  const nextFile=fileArrow("drawing-next-file","Next drawing file","m7 3 12 9-12 9");
  $("drawing-pane").insertBefore(previousFile,$("viewer"));$("drawing-pane").append(nextFile);
  function currentDrawingIndex(files){const view=chatUI.sourceView(),page=view.pages.find(item=>item.page===view.page);return files.findIndex(item=>item.building_id===state.document?.document_id&&(item.source_id||null)===(page?.source_id||null));}

  const model=control("3D Model",{type:"switch_model"},"workspace-model");
  const concept=control("Concept",{type:"switch_concept"},"workspace-concept");
  const selection=control("Return to selection",{type:"return_selection"},"workspace-return-selection");
  tabs.append(sources,model,concept);navigation.append(tabs,drawingPicker);
  const actions=node("div",null,"workspace-actions");
  const exportIfc=control("Download IFC",{type:"download_ifc"},"workspace-download-ifc");
  const sourceFiles=node("select");sourceFiles.id="workspace-download-source-choice";sourceFiles.setAttribute("aria-label","Original source to download");
  const exportSource=control("Download original",()=>({type:"download_source",source_id:sourceFiles.value}),"workspace-download-source");
  actions.append(exportIfc,sourceFiles,exportSource);filePanel.append(actions);
  const inputs=$("assumptions-panel");inputs.querySelector("summary").textContent="Supplied values and corrections";tools.append(inputs);
  const themeLabel=node("label",null,"workspace-theme");themeLabel.append(node("span","Theme"));
  const theme=node("select");theme.id="workspace-theme";theme.setAttribute("aria-label","Colour theme");
  for(const value of ["system","light","dark"])theme.append(new Option(value[0].toUpperCase()+value.slice(1),value));
  try{theme.value=localStorage.getItem("blueprint-theme")||"system";}catch{}
  theme.addEventListener("change",()=>act({type:"set_theme",theme:theme.value}));themeLabel.append(theme);document.querySelector(".app-header-controls").append(themeLabel);

  content.append(status);

  const pages=node("div",null,"workspace-pages");pages.id="workspace-pages";
  const previous=control("←",()=>pageAction(-1),"workspace-previous-page");previous.setAttribute("aria-label","Previous supplied page");
  const next=control("→",()=>pageAction(1),"workspace-next-page");next.setAttribute("aria-label","Next supplied page");
  const pageLabel=node("label","Original source");pageLabel.htmlFor="workspace-page";
  const pageSelect=node("select");pageSelect.id="workspace-page";pageSelect.setAttribute("aria-label","Supplied drawing and page");
  pageSelect.addEventListener("change",()=>act({type:"browse_source",page:Number(pageSelect.value),source_revision_id:chatUI.sourceView().revision_id}));
  pages.append(pageLabel,previous,pageSelect,next);viewPanel.append(pages);
  const fitControls = node("div", null, "workspace-fit");
  fitControls.setAttribute("role", "group");
  fitControls.setAttribute("aria-label", "Drawing fit");
  const fitButtons = new Map();
  for (const [mode, label] of [["width", "Fit to width"], ["height", "Fit to height"]]) {
    const fit = node("button", label);
    fit.type = "button";
    fit.addEventListener("click", () => {
      setDrawingFit(mode);
      $("viewer").scrollTo(0, 0);
    });
    fitButtons.set(mode, fit);
    fitControls.append(fit);
  }
  viewPanel.append(fitControls);
  const floorLabel=node("label","Floor","workspace-floor-control"),floorSelect=node("select");floorSelect.id="workspace-floor";floorSelect.setAttribute("aria-label","Model floor");floorLabel.append(floorSelect);viewPanel.append(floorLabel);
  floorSelect.addEventListener("change",()=>act({type:"set_floor",floor_id:floorSelect.value||null}));

  function syncDrawingFit() {
    for (const [mode, fit] of fitButtons) {
      fit.setAttribute("aria-pressed", String(drawingFit === mode));
    }
  }

  function pageAction(delta){const view=chatUI.sourceView(),index=view.pages.findIndex(p=>p.page===view.page);return {type:"browse_source",page:view.pages[index+delta]?.page,source_revision_id:view.revision_id};}

  const toggles=node("div",null,"workspace-toggles");const checks={};
  for(const [target,label] of [["answer_highlights","Answer highlights"],["navigation_highlights","Selection highlight"],["assumptions","Assumption overlays"]]){
    const wrap=node("label"),input=node("input");input.type="checkbox";input.id="workspace-"+target;input.addEventListener("change",()=>act({type:"set_visibility",target,enabled:input.checked}));wrap.append(input,node("span",label));toggles.append(wrap);checks[target]=input;
  }
  viewPanel.append(toggles,selection);
  const legend=node("details",null,"provenance-legend");legend.id="provenance-legend";legend.append(node("summary","Evidence legend · what the model can and cannot establish"));
  const legendRows=[
    ["Observation","Marked as observed in the saved source evidence; a link does not validate every property."],
    ["Interpretation","Extracted or inferred from supplied sources; generated shape and placement are not original measurements."],
    ["Derivation","Calculated from specified inputs. Generated geometry is not an original measurement."],
    ["User-provided","Supplied by a user, not observed in the original drawing."],
    ["Display assumption","Height, placement or styling chosen for visualization; not factual evidence."],
    ["Unresolved / unknown","No reliable geometry or supported value. ? markers retain original source regions."],
    ["Proposal","Decorative suggestion, excluded from factual QA, counts and IFC exports."]
  ];
  const list=node("dl");for(const [label,meaning] of legendRows)list.append(node("dt",label),node("dd",meaning));legend.append(list,node("p","Assumption overlay: amber surfaces contain assumed properties; A markers identify them on selected or highlighted objects. Selection/answer colours can override the amber tint. Hiding this overlay never hides the evidence summary."));tools.append(legend);

  const labels={observed:"Source observation",source:"Supplied property",supplied:"Supplied property",calculated:"Derivation",derived:"Derivation",inferred:"Interpretation",interpretation:"Interpretation",display_assumption:"Display assumption",user_provided:"User-provided",unknown:"Unknown / unresolved"};
  const valueText=value=>value==null?"Not established":typeof value==="object"?JSON.stringify(value):String(value);
  function propertyRow(parent,name,value,unit,provenance,reason){
    const item=node("div",null,"evidence-property"),title=node("div",null,"evidence-property-heading");
    title.append(node("strong",name.replaceAll("_"," ")),node("span",labels[provenance]||"Provenance not established","provenance-tag"));
    item.append(title,node("p",valueText(value)+(unit?` ${unit}`:"")));if(reason)item.append(node("p",reason,"property-basis"));parent.append(item);
  }
  let rendered="",selectionCollapsed=false;
  try{selectionCollapsed=localStorage.getItem("concrete-selection-collapsed")==="true";}catch{}
  const selectionPanel=summary,selectionToggle=node("button",null,"selection-collapse-toggle"),selectionLabel=node("span"),selectionBody=node("div");
  selectionToggle.id="selection-evidence-toggle";selectionToggle.type="button";selectionToggle.setAttribute("aria-controls","selection-evidence-content");selectionBody.id="selection-evidence-content";
  const chevron=node("span","⌄","selection-chevron");chevron.setAttribute("aria-hidden","true");selectionToggle.append(selectionLabel,chevron);selectionPanel.append(selectionToggle,selectionBody);
  function syncSelectionCollapse(){selectionBody.hidden=selectionCollapsed;selectionPanel.classList.toggle("collapsed",selectionCollapsed);selectionToggle.setAttribute("aria-expanded",String(!selectionCollapsed));selectionToggle.title=selectionCollapsed?"Expand component details":"Collapse component details";requestAnimationFrame(()=>state.viewer?.resize());}
  selectionToggle.addEventListener("click",()=>{selectionCollapsed=!selectionCollapsed;try{localStorage.setItem("concrete-selection-collapsed",String(selectionCollapsed));}catch{}syncSelectionCollapse();});
  function renderEvidence(){
    const inspected=chatUI.inspection?.()||{},record=inspected.record,proposal=inspected.proposal;
    const revision=inspected.source_revision_id||null;
    const signature=JSON.stringify([inspected,state.assumptionDataRevision,state.assumptionRows,state.scene?.revision_id]);if(signature===rendered)return;rendered=signature;
    selectionBody.replaceChildren();
    selectionPanel.hidden = !record && !proposal;
    if (selectionPanel.hidden) return;
    selectionLabel.textContent=proposal?.label||record.name||record.id;syncSelectionCollapse();
    const summary=selectionBody;
    const title=node("div",null,"selection-heading");
    if(proposal){
      title.append(node("span","Non-factual proposal","provenance-tag"));summary.append(title,node("p",proposal.note||"Decorative display choice, not source evidence."),node("p","Excluded from factual QA, source counts and IFC exports.","property-basis"));
      if(inspected.host?.source)summary.append(control("Show host in original",{type:"show_source",source:inspected.host.source,source_revision_id:revision,object_id:inspected.host.id}));return;
    }
    const missing=!record.geometry||record.representation==="unresolved";
    title.append(node("span",inspected.removed?"Earlier revision · no current geometry":missing?"Unresolved · no mesh":record.representation==="schematic"?"Schematic representation":"Selected object","provenance-tag"));summary.append(title);
    const source=record.source;
    if(source)summary.append(control(source.kind==="ifc"?"Show original record":"Show in original",{type:"show_source",source,source_revision_id:revision,object_id:record.id},"selection-show-original"));
    summary.append(node("p",`${source?.kind==="ifc"?"Supplied IFC record":source?.page?`Original page ${source.source_page||source.page}`:"No source association"} · revision ${revision||"unavailable"}`,"selection-source"));
    const native=source?.kind==="ifc"&&!state.scene?.derived;
    propertyRow(summary,"Presence",native?"Present in the supplied IFC":record.evidence_basis==="observed"?"Recorded as depicted in the source":record.evidence_basis==="display_assumption"?"Not established by the source":"Interpreted from the source",null,native?"source":record.evidence_basis||"unknown",native?"Describes the supplied model, not guaranteed as-built reality.":"Source-linked presence does not establish height, dimensions or placement. The saved interpretation remains fallible.");
    if(record.note)summary.append(node("p",record.note,"property-basis"));
    const details=node("details",null,"selected-property-details");details.open=true;details.append(node("summary","Properties and their evidence"));
    for(const p of record.properties||[])propertyRow(details,p.name,p.value,p.unit,p.origin==="derived"?"derived":native?"source":"interpretation",p.origin==="derived"?"Derived value; its validity depends on its inputs. See original evidence for support.":native?"Property retained from the supplied IFC.":"Property retained in a generated interpretation, not independently verified source evidence.");
    for(const a of record.assumptions||[])propertyRow(details,a.property,a.value,a.unit,"display_assumption",a.reason);
    const floor=inspected.floor||(state.scene?.revision_id===revision?state.scene.floors?.find(f=>f.id===record.storey_id):null);
    if(floor){
      const elevationAssumed=floor.assumptions?.some(a=>["elevation","base_elevation","floor_elevation"].includes(a.property));
      propertyRow(details,"Floor placement",floor.base_elevation,inspected.units||(state.scene?.revision_id===revision?state.scene.units:null),elevationAssumed?"display_assumption":native?"source":"interpretation",floor.elevation_basis||"Stored building placement, separate from source coordinates and viewer spacing.");
      for(const m of floor.measurements||[])propertyRow(details,`Floor · ${m.label}`,m.value,m.unit,m.status==="observed"?"observed":"unknown",m.note);
      for(const a of floor.assumptions||[])propertyRow(details,`Floor · ${a.property}`,a.value,a.unit,"display_assumption",a.reason);
    }
    if(state.assumptionDataRevision===revision){
      for(const r of state.assumptionRows||[]){const scope=r.scope||{};if(scope.object_id?scope.object_id!==record.id:!scope.floor_id||scope.floor_id!==record.storey_id)continue;
        propertyRow(details,`${scope.object_id?"Object":"Floor"} · ${r.label||r.property}`,r.value,r.unit,r.provenance,r.reason);
      }
    }else if(state.assumptionDataRevision){details.append(node("p","Current input rows belong to another revision and are not applied to this selected object. The stored object assumptions above remain pinned to its evidence.","property-basis"));}
    if(!(record.properties?.length||record.assumptions?.length))details.append(node("p","No additional property evidence is stored for this object. Missing provenance does not establish a fact.","property-basis"));
    details.append(node("p",`Stable object ID: ${record.id}`,"selection-source"));summary.append(details);
  }
  let controlsVisit=null,controlsView=null;
  function refresh(){
    if(!window.chatUI)return;const snap=chatUI.snapshot();navigation.hidden=!state.document;
    const visit=JSON.stringify([state.document?.document_id,state.activeSessionId]);
    if(visit!==controlsVisit){controlsVisit=visit;showEvidence(false);setDrawingPicker(false);showStatus("");nativeRecord.replaceChildren();nativeRecord.hidden=true;for(const [button,panel]of panels){panel.hidden=true;button.setAttribute("aria-expanded","false");}}
    actions.hidden=!state.document;inputs.hidden=!state.document||state.document.kind==="ifc";

    exportIfc.disabled=!state.document?.has_scene;
    concept.disabled=!state.scene?.elements.some(e=>e.geometry);
    concept.setAttribute("aria-pressed",String(snap.view_mode==="concept"));
    const sourcesSignature=JSON.stringify(state.document?.sources||[]);
    if(sourceFiles.dataset.sources!==sourcesSignature){sourceFiles.replaceChildren();for(const source of state.document?.sources||[])sourceFiles.append(new Option(source.filename,source.source_id));sourceFiles.dataset.sources=sourcesSignature;}
    sourceFiles.hidden=sourceFiles.options.length<2;exportSource.disabled=!sourceFiles.value;
    try{const choice=localStorage.getItem("blueprint-theme");if(["system","light","dark"].includes(choice))theme.value=choice;}catch{}
    sources.setAttribute("aria-pressed",String(snap.view_mode==="source"));model.setAttribute("aria-pressed",String(snap.view_mode==="model"));
    sources.title=state.document?.pages?.length?"Choose a drawing from this Building":"Original IFC records";
    if(controlsView!==snap.view_mode){controlsView=snap.view_mode;setDrawingPicker(false);}
    const drawingFiles=window.projectLibrary?.drawingFiles()||[],drawingIndex=currentDrawingIndex(drawingFiles),drawingBusy=Boolean(window.projectLibrary?.drawingBusy()||state.busy||state.sessionOpening);
    sources.disabled=model.disabled=drawingBusy;concept.disabled=drawingBusy||!state.scene?.elements.some(e=>e.geometry);
    const drawingSignature=JSON.stringify([drawingFiles,drawingIndex,drawingBusy]);
    if(drawingPicker.dataset.catalog!==drawingSignature){
      drawingPicker.dataset.catalog=drawingSignature;drawingPicker.replaceChildren();
      if(!drawingFiles.length)drawingPicker.append(node("p","No drawing pages in this Building. Use 3D Model to inspect supplied IFC records.","drawing-picker-empty"));
      for(const [index,file]of drawingFiles.entries()){
        const choice=node("button",null,"drawing-file-choice");choice.type="button";choice.dataset.drawingKey=file.key;choice.disabled=drawingBusy;
        choice.setAttribute("aria-current",index===drawingIndex?"true":"false");choice.title=file.filename;
        choice.append(node("span",file.filename),node("small",`${file.pages.length} ${file.pages.length===1?"page":"pages"}${file.building_filename!==file.filename?` · ${file.building_filename}`:""}`));
        choice.addEventListener("click",()=>inspectDrawing(file.key));drawingPicker.append(choice);
      }
    }
    previousFile.hidden=nextFile.hidden=snap.view_mode!=="source"||!drawingFiles.length;
    previousFile.disabled=drawingBusy||drawingIndex<=0;nextFile.disabled=drawingBusy||drawingIndex<0||drawingIndex===drawingFiles.length-1;
    previousFile.title=drawingIndex>0?`Previous drawing: ${drawingFiles[drawingIndex-1].filename}`:"First drawing file";
    nextFile.title=drawingIndex>=0&&drawingIndex<drawingFiles.length-1?`Next drawing: ${drawingFiles[drawingIndex+1].filename}`:"Last drawing file";

    selection.disabled=!(snap.focused_id?state.viewer?.meshes.has(snap.focused_id):snap.selected_ids.some(id=>state.viewer?.meshes.has(id)));
    selection.title=selection.disabled?"No renderable selection. Use Show in original for source-only objects.":"Frame the current selection without changing its source";
    checks.answer_highlights.checked=snap.answer_highlighting;checks.navigation_highlights.checked=snap.highlighting;checks.assumptions.checked=snap.show_assumptions;
    const floors=state.scene?.floors||[],floorSignature=JSON.stringify(floors.map(item=>[item.id,item.label]));
    if(floorSelect.dataset.catalog!==floorSignature){floorSelect.replaceChildren(new Option("All floors",""));for(const item of floors)floorSelect.append(new Option(item.label||item.id,item.id));floorSelect.dataset.catalog=floorSignature;}
    floorSelect.value=snap.floor_id||"";floorSelect.disabled=!state.viewer||!floors.length;floorLabel.hidden=!floors.length;
    const view=chatUI.sourceView?.()||{pages:[],revision_id:null,page:null};pages.hidden=snap.view_mode!=="source"||!view.pages.length;
    const signature=JSON.stringify([view.pages,view.revision_id]);if(pageSelect.dataset.catalog!==signature){pageSelect.replaceChildren();for(const p of view.pages)pageSelect.append(new Option(`${p.source_filename||state.document?.filename||"Saved source"} · page ${p.source_page||p.page}`,String(p.page)));pageSelect.dataset.catalog=signature;}
    pageSelect.value=String(view.page);const index=view.pages.findIndex(p=>p.page===view.page);previous.disabled=index<=0;next.disabled=index<0||index===view.pages.length-1;
    if (workspace.hidden && workspace.classList.contains("workspace-expanded")) {
      workspace.classList.remove("workspace-expanded");
    }
    syncFullscreen();
    fitControls.hidden = pages.hidden;
    syncDrawingFit();
    renderEvidence();
  }
  window.workspaceControls={refresh,showStatus,syncDrawingFit,showNativeRecord};window.addEventListener("blueprint:workspace",refresh);refresh();
})();
