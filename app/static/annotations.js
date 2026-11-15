/* User-authored source/model marks. Geometry and originals remain unchanged. */
"use strict";
(() => {
  const svgNS="http://www.w3.org/2000/svg";
  const node=(tag,text)=>{const el=document.createElement(tag);if(text!=null)el.textContent=text;return el;};
  const svgNode=tag=>document.createElementNS(svgNS,tag);
  const tools=node("div");tools.id="annotation-tools";tools.className="annotation-tools editor-palette";tools.setAttribute("role","group");tools.setAttribute("aria-label","Drawing tool palette");
  const icons={hammer:'<path d="m14 4 6 6-3 3-3-3-8 10-3-3 10-8-3-3 3-3 3 1Z"/>',point:'<circle cx="12" cy="12" r="5" fill="currentColor" stroke="none"/>',stroke:'<path d="m15 4 5 5M4 20l5-1L21 7a2 2 0 0 0-5-5L4 14l-1 7Z"/>',measurement:'<path d="M15 17V8a5 5 0 0 0-10 0v7a4 4 0 0 0 4 4h12v-7h-6M18 13v3m-9-7h2m-2 4h2"/><circle cx="10" cy="8" r="2"/>',eraser:'<path d="m4 12 9-9 8 8-9 9H7l-5-5a2 2 0 0 1 0-3ZM8 8l8 8M12 20h9"/>',marks:'<path d="M3 3h8l10 10-8 8L3 11Z"/><circle cx="7.5" cy="7.5" r="1"/>',undo:'<path d="m9 5-6 6 6 6M3 11h10a7 7 0 0 1 7 7v2"/>',redo:'<path d="m15 5 6 6-6 6m6-6H11a7 7 0 0 0-7 7v2"/>'};
  function iconButton(label,id,icon){const button=node("button");button.id=id;button.type="button";button.title=label;button.setAttribute("aria-label",label);const svg=svgNode("svg");svg.setAttribute("viewBox","0 0 24 24");svg.setAttribute("aria-hidden","true");svg.innerHTML=icons[icon];button.append(svg);return button;}
  const paletteRow=node("div");paletteRow.className="palette-row";
  const toggle=iconButton("Open drawing tools","annotation-toggle","hammer");toggle.setAttribute("aria-expanded","false");toggle.setAttribute("aria-controls","annotation-tool-row annotation-parameters");
  const toolRow=node("div");toolRow.id="annotation-tool-row";toolRow.className="palette-tool-row";toolRow.setAttribute("role","toolbar");toolRow.setAttribute("aria-label","Drawing tools");toolRow.inert=true;
  const parameters=node("div");parameters.id="annotation-parameters";parameters.className="palette-parameters";parameters.hidden=true;
  const fields=node("div");fields.className="palette-fields";parameters.append(fields);
  paletteRow.append(toolRow,toggle);tools.append(paletteRow,parameters);
  const status=node("p");status.id="annotation-status";status.setAttribute("role","status");
  const attachmentBox=node("div");attachmentBox.id="annotation-attachments";attachmentBox.setAttribute("aria-label","Attached user marks");$("chat-composer").insertBefore(attachmentBox,$("composer-slot"));
  tools.append(status);$("workspace-content").append(tools);
  const modes=new Map();let mode=null,modeFrame=null,gesture=null,rows=[],selected=new Set(),building=null,loadEpoch=0,boundCanvas=null;
  let undoStack=[],redoStack=[],historyFrame=null,busy=false,editEpoch=0;
  let expanded=false,showMarks=false,focusedMark=null;
  function expand(open){expanded=open;tools.classList.toggle("expanded",open);toggle.setAttribute("aria-expanded",String(open));toggle.setAttribute("aria-label",open?"Close drawing tools":"Open drawing tools");toggle.title=open?"Close drawing tools":"Open drawing tools";toolRow.inert=!open;if(!open){showMarks=false;choose(null);}syncParameters();}
  toggle.addEventListener("click",()=>expand(!expanded));
  const sourceOverlay=svgNode("svg");sourceOverlay.id="annotation-overlay";sourceOverlay.setAttribute("viewBox","0 0 1 1");sourceOverlay.setAttribute("preserveAspectRatio","none");sourceOverlay.setAttribute("aria-label","User annotation drawing layer");sourceOverlay.classList.add("user-mark-overlay");$("image-stage").append(sourceOverlay);
  const modelOverlay=svgNode("svg");modelOverlay.id="model-annotation-overlay";modelOverlay.setAttribute("viewBox","0 0 1 1");modelOverlay.setAttribute("preserveAspectRatio","none");modelOverlay.setAttribute("aria-label","User model marks");modelOverlay.classList.add("user-mark-overlay","model-user-marks");$("model-canvas-container").append(modelOverlay);
  function announce(text){status.textContent=text;}
  function choose(next){if((busy||state.sessionOpening||state.busy==="upload")&&next)return;mode=mode===next?null:next;if(next){showMarks=false;focusedMark=null;}modeFrame=mode?currentFrame():null;gesture=null;for(const [key,button] of modes)button.setAttribute("aria-pressed",String(mode===key));state.viewer?.setUserAnnotationMode(Boolean(mode&&chatUI.snapshot().view_mode==="model"));sourceOverlay.classList.toggle("drawing-active",Boolean(mode&&chatUI.snapshot().view_mode==="source"));announce(mode?mode==="eraser"?"Drag over a mark to erase the whole stroke, point or measurement. Undo restores it.":mode==="measurement"?"Enter the measurement, then drag between two endpoints.":mode==="stroke"?"Drag to draw a user mark.":"Click a point to attach to your message.":"Drawing tools are off. Drag the model to orbit, right-drag to pan, or scroll the drawing.");syncParameters();render();}
  for(const [key,label,id] of [["point","Point","annotation-point"],["stroke","Draw","annotation-draw"],["measurement","Measure","annotation-measure"],["eraser","Eraser","annotation-eraser"]]){const b=iconButton(label,id,key);b.setAttribute("aria-pressed","false");b.addEventListener("click",()=>choose(key));toolRow.append(b);modes.set(key,b);}
  const marks=iconButton("Saved marks","annotation-marks","marks");marks.setAttribute("aria-pressed","false");marks.addEventListener("click",()=>{const next=!showMarks;choose(null);showMarks=next;syncParameters();if(next)announce("Choose a saved tag to highlight its mark. Attach it separately to your next message.");});toolRow.append(marks);
  const undo=iconButton("Undo","annotation-undo","undo"),redo=iconButton("Redo","annotation-redo","redo");undo.addEventListener("click",()=>travel(false));redo.addEventListener("click",()=>travel(true));toolRow.append(undo,redo);
  const clear=node("button","Clear attachments");clear.id="annotation-clear";clear.type="button";clear.addEventListener("click",()=>{selected.clear();mode=null;choose(null);renderChips();announce("Attachments cleared. Saved tags remain in the palette.");});
  function inputField(label,id,type){const wrap=node("label",label);const field=node(type==="select"?"select":"input");field.id=id;field.setAttribute("aria-label",label);if(type!=="select")field.type=type;wrap.append(field);fields.append(wrap);return field;}
  const value=inputField("Measurement value","annotation-value","number");value.min="0";value.step="any";
  const unit=inputField("Measurement unit","annotation-unit","select");for(const item of ["m","mm","cm","ft","in"])unit.append(new Option(item,item));
  const floor=inputField("Measurement floor","annotation-floor","select");floor.append(new Option("Choose floor",""));
  const label=inputField("Mark label","annotation-label","text");label.placeholder="Optional note";
  const saved=node("div");saved.id="annotation-saved";saved.className="palette-saved-marks";saved.setAttribute("aria-label","Saved tags in this drawing");parameters.append(saved);
  const attachSaved=node("button","Attach highlighted mark");attachSaved.id="annotation-attach-saved";attachSaved.type="button";attachSaved.addEventListener("click",()=>{if(focusedMark){selected.add(focusedMark);renderChips();render();announce("Highlighted user mark attached to the next message.");}});
  const markActions=node("div");markActions.className="palette-mark-actions";markActions.append(attachSaved,clear);parameters.append(markActions);
  function syncParameters(){
    const drawing=["point","stroke","measurement"].includes(mode);parameters.hidden=!expanded||!drawing&&!showMarks;fields.hidden=!drawing;saved.hidden=markActions.hidden=!showMarks;marks.setAttribute("aria-pressed",String(showMarks));
    for(const field of [value,unit,floor])field.parentElement.hidden=mode!=="measurement"||field===floor&&currentFrame().space!=="source";
    label.parentElement.hidden=!drawing;attachSaved.disabled=!focusedMark||selected.has(focusedMark);clear.disabled=!selected.size;
  }
  async function focusMark(row){
    const scope=loadEpoch,edit=editEpoch,id=building;chatUI.invalidateNavigation?.();choose(null);focusedMark=row.id;showMarks=true;
    try{
      if(row.space==="source"&&row.page!==currentFrame().page)await chatUI.execute({type:"browse_source",page:row.page,source_revision_id:row.revision_id});
      if(scope!==loadEpoch||edit!==editEpoch||id!==building)return;
      if(row.space==="model"){if(state.viewer.floorFilter&&state.viewer.floorFilter!==row.floor_id)state.viewer.setFloorFilter("");state.viewer.frameIds([...new Set(row.point_object_ids||[row.object_id])]);}
      renderChips();syncParameters();render();announce(`Highlighted ${row.label||row.kind}.`);
      if(row.space==="source"){const target=sourceOverlay.querySelector(`[data-annotation-id="${row.id}"]`)?.getBoundingClientRect(),viewer=$("viewer"),bounds=viewer.getBoundingClientRect();if(target)viewer.scrollBy({left:target.x+target.width/2-bounds.x-bounds.width/2,top:target.y+target.height/2-bounds.y-bounds.height/2});}
    }catch(error){announce(error.message);}
  }
  function currentFrame(){const view=chatUI.snapshot().view_mode,source=chatUI.sourceView();return {document_id:state.document?.document_id,revision_id:view==="source"?source.revision_id:state.scene?.revision_id,page:view==="source"?source.page:null,space:view==="source"?"source":"model",view};}
  function sameFrame(a,b){return ["document_id","revision_id","page","space","view"].every(key=>a[key]===b[key]);}
  function syncHistory(){const blocked=busy||state.sessionOpening||state.busy==="upload"||Boolean(state.document?.read_only_model);undo.disabled=blocked||!undoStack.length;redo.disabled=blocked||!redoStack.length;for(const b of modes.values())b.disabled=Boolean(blocked);}
  function pushHistory(command){undoStack.push(command);redoStack=[];syncHistory();}
  async function setActive(command,active){
    const id=building,token=loadEpoch,scope=editEpoch;
    const result=await request(`/api/buildings/${id}/annotations`,{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify({revision_id:command.revision_id,annotation_ids:command.ids,active})});
    if(token!==loadEpoch||id!==building)return false;
    for(const row of result.annotations){const index=rows.findIndex(item=>item.id===row.id);if(index>=0)rows[index]=row;else rows.push(row);if(!active||scope!==editEpoch)selected.delete(row.id);else if(command.attached.includes(row.id))selected.add(row.id);}
    renderChips();render();return scope===editEpoch;
  }
  async function travel(forward){if(busy||state.sessionOpening||state.busy==="upload")return;const from=forward?redoStack:undoStack,to=forward?undoStack:redoStack,command=from.at(-1);if(!command)return;choose(null);busy=true;syncHistory();try{if(await setActive(command,forward?command.active:!command.active)){from.pop();to.push(command);announce(forward?"Redone.":"Undone.");}}catch(error){announce(error.message);}finally{busy=false;syncHistory();}}
  const liveRows=()=>rows.filter(row=>!row.deleted);
  const projected=row=>row.space==="source"?row.points:row.points.map((point,index)=>state.viewer?.projectUserAnchor(row.point_object_ids?.[index]||row.object_id,point));
  function pointDistance(p,a,b){const dx=b[0]-a[0],dy=b[1]-a[1],n=dx*dx+dy*dy,t=n?Math.max(0,Math.min(1,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/n)):0;return Math.hypot(p[0]-a[0]-t*dx,p[1]-a[1]-t*dy);}
  function segmentDistance(a,b,c,d){const cross=(p,q,r)=>(q[0]-p[0])*(r[1]-p[1])-(q[1]-p[1])*(r[0]-p[0]);if(cross(a,b,c)*cross(a,b,d)<=0&&cross(c,d,a)*cross(c,d,b)<=0&&[0,1].every(i=>Math.max(Math.min(a[i],b[i]),Math.min(c[i],d[i]))<=Math.min(Math.max(a[i],b[i]),Math.max(c[i],d[i]))))return 0;return Math.min(pointDistance(a,c,d),pointDistance(b,c,d),pointDistance(c,a,b),pointDistance(d,a,b));}
  function eraseAt(event){const frame=gesture,bounds=(frame.space==="source"?sourceOverlay:modelOverlay).getBoundingClientRect(),point=[event.clientX-bounds.left,event.clientY-bounds.top],previous=frame.last||point;frame.last=point;
    for(const row of liveRows()){if(row.revision_id!==frame.revision_id||row.space!==frame.space||row.space==="source"&&row.page!==frame.page)continue;const points=projected(row);if(!points.every(Boolean))continue;const pixels=points.map(p=>[p[0]*bounds.width,p[1]*bounds.height]);if(pixels.length===1?pointDistance(pixels[0],previous,point)<=10:pixels.slice(1).some((p,i)=>segmentDistance(previous,point,pixels[i],p)<=10))frame.erase_ids.add(row.id);}render();}
  function pointAt(event,frame,anchorId){if(frame.space==="source"){const bounds=sourceOverlay.getBoundingClientRect();if(!bounds.width||!bounds.height)return null;return {point:[Math.max(0,Math.min(1,(event.clientX-bounds.left)/bounds.width)),Math.max(0,Math.min(1,(event.clientY-bounds.top)/bounds.height))]};}return state.viewer?.pickUserAnchor(event,anchorId);}
  function begin(event){if(!mode||busy||state.sessionOpening||state.busy==="upload"||event.button!==0)return;const frame=currentFrame();if(!frame.document_id||!["source","model"].includes(frame.view))return;event.preventDefault();event.stopImmediatePropagation();chatUI.invalidateNavigation?.();if(mode==="eraser"){gesture={...frame,kind:mode,points:[],erase_ids:new Set(),pointer:event.pointerId};event.currentTarget.setPointerCapture(event.pointerId);eraseAt(event);return;}const anchor=pointAt(event,frame);if(!anchor){announce("Choose a visible object in the saved model.");return;}gesture={...frame,kind:mode,points:[anchor.point],point_object_ids:anchor.object_id?[anchor.object_id]:[],object_id:anchor.object_id||null,floor_id:anchor.floor_id||floor.value||null,pointer:event.pointerId};event.currentTarget.setPointerCapture(event.pointerId);render();}
  function move(event){if(!gesture||gesture.pointer!==event.pointerId)return;event.preventDefault();event.stopImmediatePropagation();if(!sameFrame(gesture,currentFrame())){gesture=null;choose(null);return;}if(gesture.kind==="eraser"){eraseAt(event);return;}const anchor=pointAt(event,gesture,gesture.object_id);if(!anchor)return;if(gesture.kind==="measurement"){gesture.points=[gesture.points[0],anchor.point];if(anchor.object_id)gesture.point_object_ids=[gesture.point_object_ids[0],anchor.object_id];}else if(gesture.kind==="stroke"){gesture.points.push(anchor.point);if(anchor.object_id)gesture.point_object_ids.push(anchor.object_id);}render();}
  async function finish(event){
    if(!gesture||gesture.pointer!==event.pointerId)return;
    event.preventDefault();event.stopImmediatePropagation();
    if(gesture.kind==="eraser")eraseAt(event);
    const draft=gesture;gesture=null;
    if(!sameFrame(draft,currentFrame())){choose(null);announce("The view changed; draw your mark again on the intended revision.");return;}
    if(draft.kind==="eraser"){
      const command={ids:[...draft.erase_ids],revision_id:draft.revision_id,active:false,attached:[...draft.erase_ids].filter(id=>selected.has(id))};
      choose(null);if(!command.ids.length){announce("No mark touched. Drag the eraser across a saved stroke, point or measurement.");return;}
      busy=true;syncHistory();
      try{if(await setActive(command,false)){pushHistory(command);announce(`Erased ${command.ids.length} mark(s). Undo restores them.`);}}
      catch(error){announce(error.message);render();}finally{busy=false;syncHistory();}return;
    }
    const anchor=pointAt(event,draft,draft.object_id);
    if(draft.kind==="measurement"&&anchor){draft.points=[draft.points[0],anchor.point];if(anchor.object_id)draft.point_object_ids=[draft.point_object_ids[0],anchor.object_id];}
    if(draft.kind==="stroke"&&anchor){draft.points.push(anchor.point);if(anchor.object_id)draft.point_object_ids.push(anchor.object_id);}
    const body={revision_id:draft.revision_id,kind:draft.kind,space:draft.space,points:draft.points,label:label.value};
    if(draft.space==="source"){
      const page=chatUI.sourceView().pages.find(p=>p.page===draft.page);
      Object.assign(body,{page:draft.page,source_id:page?.source_id||null,source_page:page?.source_page||null,floor_id:floor.value||null});
    }else Object.assign(body,{object_id:draft.object_id,point_object_ids:draft.point_object_ids,floor_id:draft.floor_id});
    if(draft.kind==="measurement"){
      body.value=Number(value.value);body.unit=unit.value;
      if(!value.value||!Number.isFinite(body.value)||body.value<=0){choose(null);announce("Enter a positive measurement value, then draw its endpoints again.");return;}
      if(draft.space==="source"&&!body.floor_id){choose(null);announce("Choose the floor for this measurement before drawing its endpoints.");return;}
    }
    choose(null);busy=true;syncHistory();const token=loadEpoch,scope=editEpoch;
    try{
      const row=await request(`/api/buildings/${draft.document_id}/annotations`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
      if(token!==loadEpoch||draft.document_id!==state.document?.document_id)return;
      rows.push(row);if(scope!==editEpoch){renderChips();render();return;}const current=row.revision_id===(row.space==="source"?state.document?.revision_id:state.scene?.revision_id);
      if(current){selected.add(row.id);pushHistory({ids:[row.id],revision_id:row.revision_id,active:true,attached:[row.id]});}
      renderChips();render();announce(current?"User mark saved and attached. It is not an observation from the original drawing.":"User mark saved on the earlier revision and left detached because the building changed.");
    }catch(error){announce(error.message);}finally{busy=false;syncHistory();}
  }
  function cancel(event){if(gesture?.pointer===event.pointerId){gesture=null;choose(null);}}
  function bind(target){target.addEventListener("pointerdown",begin,true);target.addEventListener("pointermove",move,true);target.addEventListener("pointerup",finish,true);target.addEventListener("pointercancel",cancel,true);}
  bind(sourceOverlay);
  function drawMark(overlay,row,points,active=false){if(!points?.length)return;const group=svgNode("g");group.dataset.annotationId=row.id||"draft";group.classList.toggle("attached",active);group.classList.toggle("tag-highlight",row.id===focusedMark);if(row.kind==="point"){const circle=svgNode("circle");circle.setAttribute("cx",points[0][0]);circle.setAttribute("cy",points[0][1]);circle.setAttribute("r","0.008");group.append(circle);}else{const line=svgNode("polyline");line.setAttribute("points",points.map(p=>p.join(",")).join(" "));group.append(line);}if(row.kind==="measurement"&&row.value!=null&&points.length===2){const text=svgNode("text");text.setAttribute("x",(points[0][0]+points[1][0])/2);text.setAttribute("y",(points[0][1]+points[1][1])/2-.012);text.textContent=`${row.value} ${row.unit} · user`;group.append(text);}overlay.append(group);}
  function render(){sourceOverlay.replaceChildren();modelOverlay.replaceChildren();const frame=currentFrame();for(const row of liveRows()){if(gesture?.erase_ids?.has(row.id))continue;if(row.revision_id!==frame.revision_id||row.space!==frame.space||row.space==="source"&&row.page!==frame.page)continue;if(row.space==="source")drawMark(sourceOverlay,row,row.points,selected.has(row.id));else {const points=row.points.map((point,index)=>state.viewer?.projectUserAnchor(row.point_object_ids?.[index]||row.object_id,point));if(points.every(Boolean))drawMark(modelOverlay,row,points,selected.has(row.id));}}if(gesture){if(gesture.space==="source")drawMark(sourceOverlay,gesture,gesture.points,true);else {const points=gesture.points.map((point,index)=>state.viewer?.projectUserAnchor(gesture.point_object_ids?.[index]||gesture.object_id,point));if(points.every(Boolean))drawMark(modelOverlay,gesture,points,true);}}}
  function renderChips(){
    const attached=rows.filter(row=>selected.has(row.id)&&!row.deleted),attachmentSignature=JSON.stringify(attached);
    if(attachmentBox.dataset.signature!==attachmentSignature){
      attachmentBox.dataset.signature=attachmentSignature;attachmentBox.replaceChildren();
      for(const id of selected){const row=rows.find(item=>item.id===id);if(!row||row.deleted)continue;const b=node("button",`${row.kind==="measurement"?`${row.value} ${row.unit}`:row.label||row.kind} · user input ×`);b.type="button";b.dataset.annotationId=id;b.addEventListener("click",()=>{selected.delete(id);renderChips();render();});attachmentBox.append(b);}
    }
    const frame=currentFrame();
    const available=liveRows().filter(row=>row.revision_id===frame.revision_id&&row.space===frame.space);
    if(!available.some(row=>row.id===focusedMark))focusedMark=null;
    const signature=JSON.stringify([frame.document_id,frame.revision_id,frame.space,available]);
    if(saved.dataset.signature!==signature){
      saved.dataset.signature=signature;saved.replaceChildren();
      for(const row of available){const b=node("button");b.type="button";b.dataset.annotationId=row.id;b.setAttribute("aria-pressed",String(row.id===focusedMark));b.append(node("span",row.label||`${row.kind}${row.value?` ${row.value} ${row.unit}`:""}`));if(row.space==="source")b.append(node("small",`Page ${row.page}`));b.addEventListener("click",()=>focusMark(row));saved.append(b);}
      if(!available.length)saved.append(node("p","No saved tags in this view yet."));
    }
    for(const button of saved.querySelectorAll("button"))button.setAttribute("aria-pressed",String(button.dataset.annotationId===focusedMark));
    syncParameters();
  }
  function syncFloors(){const options=new Map();const source=chatUI.sourceView();for(const item of state.scene?.floors||[])if(item.source?.page===source.page)options.set(item.id,item.label);for(const item of state.assumptionRows||[])if(item.scope?.floor_id&&item.source?.page===source.page)options.set(item.scope.floor_id,(item.label||item.scope.floor_id).split(":")[0]);const signature=JSON.stringify([...options]);if(floor.dataset.options===signature)return;const previous=floor.value;floor.replaceChildren(new Option("Choose floor",""));for(const [id,text]of options)floor.append(new Option(text,id));floor.value=options.has(previous)?previous:"";floor.dataset.options=signature;}
  async function refresh(){const frame=currentFrame();const nextHistoryFrame=JSON.stringify([frame.document_id,state.document?.revision_id,state.scene?.revision_id]);if(historyFrame!==nextHistoryFrame){undoStack=[];redoStack=[];historyFrame=nextHistoryFrame;}syncHistory();tools.hidden=!frame.document_id||!["source","model"].includes(frame.view);sourceOverlay.hidden=frame.view!=="source";modelOverlay.hidden=frame.view!=="model";if(mode&&(!["source","model"].includes(frame.view)||modeFrame&&!sameFrame(modeFrame,frame)))choose(null);if(state.viewer?.renderer.domElement!==boundCanvas){boundCanvas=state.viewer?.renderer.domElement;if(boundCanvas)bind(boundCanvas);}if(!modelOverlay.isConnected)$("model-canvas-container").append(modelOverlay);state.viewer?.setUserAnnotationMode(Boolean(mode&&frame.view==="model"));syncFloors();if(building!==frame.document_id){building=frame.document_id;rows=[];selected.clear();renderChips();const token=++loadEpoch;if(building)try{const data=await request(`/api/buildings/${building}/annotations`);if(token!==loadEpoch)return;rows=data.annotations||[];renderChips();render();}catch(error){if(token===loadEpoch)announce(error.message);}}let stale=false;for(const id of selected){const row=rows.find(item=>item.id===id);if(row&&row.revision_id!==(row.space==="source"?state.document?.revision_id:state.scene?.revision_id)){selected.delete(id);stale=true;}}renderChips();if(stale){announce("The building revision changed. Earlier marks remain saved on their original revision and were detached.");}render();}
  $("model-canvas-container").addEventListener("blueprint:camera",render);
  $("page-image").addEventListener("load",refresh);
  window.addEventListener("blueprint:workspace",refresh);
  document.addEventListener("keydown",event=>{if(!(event.ctrlKey||event.metaKey)||event.altKey||tools.hidden||event.target.closest("input,textarea,[contenteditable=true]"))return;if(event.key.toLowerCase()==="z"){event.preventDefault();travel(event.shiftKey);}else if(event.key.toLowerCase()==="y"){event.preventDefault();travel(true);}});
  new ResizeObserver(render).observe($("image-stage"));
  window.blueprintAnnotations={detach:()=>{editEpoch++;selected.clear();focusedMark=null;showMarks=false;undoStack=[];redoStack=[];mode=null;choose(null);renderChips();syncHistory();},selectedIds:()=>[...selected],refresh,rows:()=>structuredClone(rows)};
  refresh();
})();
