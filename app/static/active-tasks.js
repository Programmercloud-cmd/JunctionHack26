/* Presentation of existing authorized jobs only. No requests, queue or inference. */
"use strict";
(() => {
  const root=document.getElementById('active-tasks'),list=document.getElementById('active-task-list'),history=document.getElementById('task-history-list'),count=document.getElementById('active-task-count'),empty=document.getElementById('active-task-empty'),historyBox=document.getElementById('task-history');
  document.getElementById("chat-shell").append(root);
  const cards=new Map(),activeGroups=new Map(),historyGroups=new Map();let context={},access={can_work:false},jobs=[],selected=null,timer=null;
  const terminal=job=>['complete','needs_attention','failed','budget_exhausted','stopped','interrupted'].includes(job.status);
  const node=(tag,text,cls)=>{const e=document.createElement(tag);if(text!=null)e.textContent=text;if(cls)e.className=cls;return e;};
  const kind=job=>({extraction:'Source interpretation',question:'Source QA',agent:'Chat request',refinement:'Refinement',reconstruction:'3D reconstruction',render:'Hydrogen rendering'}[job.kind]||'Background task');
  function outcome(job){
    if(['queued','running','stopping'].includes(job.status))return ['running',job.status==='queued'?'Waiting in queue':job.status==='stopping'?'Stopping':'In progress','◷'];
    if(job.status==='stopped')return ['stopped','Stopped','■'];
    if(['failed','interrupted'].includes(job.status))return ['failed',job.status==='interrupted'?'Interrupted by restart':'Operational failure','!'];
    if(['needs_attention','budget_exhausted'].includes(job.status)||job.issues?.length||(['reconstruction','refinement'].includes(job.kind)&&(job.result_summary?.unresolved_objects>0||job.result_summary?.usable_model===false))){
      const prefix=job.status==='budget_exhausted'?'Budget exhausted':job.status==='complete'?'Review completed':'Needs attention';
      const retained=['question','agent'].includes(job.kind)?'chat request needs attention':job.kind==='extraction'?'source interpretation needs attention':job.result_summary?.usable_model===false?'no usable 3D model':job.result_summary?.usable_model===true?job.result_summary.unresolved_objects>0?'partial model retained':'usable model retained':'retained-model state not recorded';
      return ['attention',`${prefix} · ${retained}`,'!'];
    }
    if(job.status!=='complete')return ['attention','Status not recorded','?'];
    return ['complete',job.kind==='extraction'?'Interpretation saved':job.kind==='agent'?'Chat request completed':job.kind==='question'?'Source QA completed':'Review completed','✓'];
  }
  function sourceButton(ref,job,label){
    if(!ref?.source||typeof ref.source_revision_id!=='string'||!/^[a-f0-9]{32}$/i.test(ref.source_revision_id))return null;
    const b=node('button',label||ref.label||'Inspect original source','task-source chat-citation');b.type='button';
    b.addEventListener('click',async()=>{b.disabled=true;try{await context.onSource?.({...ref,building_id:job.building_id});}catch(error){message(job.id,error.message);}finally{b.disabled=false;}});return b;
  }
  function addSource(parent,source,revision,job,label){const b=sourceButton({source,source_revision_id:revision},job,label);if(b)parent.append(b);}
  function detail(parent,title){const d=node('details',null,'task-detail');d.append(node('summary',title));parent.append(d);return d;}
  function render(job){
    let card=cards.get(job.id);const fresh=!card;if(!card){card=node('details',null,'task-card');card.dataset.taskId=job.id;cards.set(job.id,card);}
    const open=card.open,wasTerminal=card.dataset.terminal==='true',opened=new Set([...card.querySelectorAll('details[open]')].map(d=>d.querySelector('summary')?.textContent)),signature=JSON.stringify([job,context.building_id,context.usable_revision_id,access.can_work]);if(card.dataset.snapshot===signature)return card;
    card.dataset.snapshot=signature;card.replaceChildren();const [tone,label,icon]=outcome(job);card.dataset.tone=tone;card.dataset.status=job.status;card.dataset.terminal=String(terminal(job));
    const summary=node('summary'),title=node('span',null,'task-title');title.append(node('strong',kind(job)),node('span',`${icon} ${label}`,'task-outcome'));
    summary.append(title,node('span',(job.phase||'Stage not recorded').replaceAll('_',' '),'task-phase'));
    summary.setAttribute('aria-label',`Open ${kind(job)} in ${job.project_label||'its project'}`);
    const openTask=async()=>{if(summary.dataset.opening)return;summary.dataset.opening='true';try{await context.onOpen?.(job);if(mobile.matches)collapse(true);if(terminal(job))await context.onDismiss?.(job);}catch(error){message(job.id,error.message);}finally{delete summary.dataset.opening;}};
    summary.addEventListener('click',event=>{event.preventDefault();openTask();});
    card.onclick=event=>{if(!event.target.closest('button,a,summary,input,select,.task-detail'))openTask();};
    const inspect=node('button','⋯','task-inspect');inspect.type='button';inspect.setAttribute('aria-label','Show task details');inspect.title='Show task details';inspect.addEventListener('click',event=>{event.preventDefault();event.stopPropagation();card.open=!card.open;});summary.append(inspect);
    if(job.initiating_message||job.original_message)summary.append(node('span',job.initiating_message||job.original_message,'task-request'));
    if(terminal(job)&&access.can_work){const remove=node('button',null,'task-dismiss');remove.type='button';remove.setAttribute('aria-label',`Remove ${kind(job)} from recent activity`);remove.title='Remove from recent activity';
      remove.innerHTML='<svg viewBox="0 0 24 24" width="17" height="17" aria-hidden="true"><path d="M4 7h16M9 7V4h6v3M6 7l1 14h10l1-14M10 10v7m4-7v7" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>';
      remove.addEventListener('click',async event=>{event.preventDefault();event.stopPropagation();remove.disabled=true;try{await context.onDismiss?.(job);}catch(error){message(job.id,error.message);remove.disabled=false;}});summary.append(remove);
    }card.append(summary);
    card.append(node('p',job.building_label||job.filename||`Building ${job.building_id}`,'task-building'));
    const clock=node('p',null,'task-elapsed');clock.dataset.started=Number.isFinite(job.created_at)?String(job.created_at*1000):'';
    if(terminal(job)&&Number.isFinite(job.updated_at))clock.dataset.finished=String(job.updated_at*1000);card.append(clock);
    if(job.message)card.append(node('p',job.message,'task-message'));
    const retained=typeof job.result_summary==='string'?job.result_summary:job.result_summary?.message;
    if(retained)card.append(node('p',retained,'task-retained'));
    if(job.result_summary?.usable_model===false)card.append(node('p','No usable 3D model was recorded for this task.','task-retained'));
    else if(job.result_summary?.usable_model===true)card.append(node('p',job.result_summary.usable_revision_id?`Recorded usable model revision: ${job.result_summary.usable_revision_id}`:'A usable model is recorded; its revision was not recorded.','task-retained'));
    else if(job.building_id===context.building_id)card.append(node('p',context.has_scene&&context.usable_revision_id?`Currently available model revision: ${context.usable_revision_id}. Its relationship to this older task was not recorded.`:'No currently renderable 3D model is confirmed. This task did not record its retained-model state.','task-retained'));
    if(job.result_summary?.originals_saved)card.append(node('p','Original sources are saved.','task-retained'));
    if(job.result_summary?.interpretation_saved)card.append(node('p',`Saved interpretation${job.result_summary.interpretation_revision_id?' revision '+job.result_summary.interpretation_revision_id:''} remains available.`,'task-retained'));
    if(job.diagnostic_message)card.append(node('p',job.diagnostic_message,'task-message'));
    if(job.diagnostic_id)card.append(node('p',`Diagnostic reference: ${job.diagnostic_id}`,'task-revision'));
    if(job.revision_id)card.append(node('p',`Recorded revision reference: ${job.revision_id}`,'task-revision'));
    if(job.status==='interrupted')card.append(node('p','This task was interrupted; it has not automatically resumed. Saved sources and previous usable results remain available.'));
    if(job.status==='stopped')card.append(node('p','An in-flight provider call may finish, but this stopped task cannot publish a replacement.'));
    if(job.status==='complete')card.append(node('p',['question','agent'].includes(job.kind)?'Its answer and source citations remain in the conversation.':'Completion does not guarantee reconstruction fidelity. Inspect the original source and remaining findings.','task-caveat'));
    if(!terminal(job)&&access.can_work){const b=node('button','Stop task','task-stop');b.type='button';b.addEventListener('click',async event=>{event.preventDefault();b.disabled=true;try{await context.onStop?.(job);}catch(error){message(job.id,error.message);}finally{b.disabled=false;}});card.append(b);}
    const budget=detail(card,'Budget and attempts');
    if(Number.isFinite(job.config?.job_seconds))budget.append(node('p',`Configured task budget: ${job.config.job_seconds} s`));
    else budget.append(node('p',job.kind==='render'?'Continues until both reviewers agree or you interrupt it; no total or round limit.':'Task budget was not recorded.'));
    budget.append(node('p',Number.isInteger(job.correction_attempts_used)?`Correction attempts used: ${job.correction_attempts_used}`:'Correction attempts used: not recorded.'));
    if(Number.isInteger(job.config?.patch_attempts))budget.append(node('p',`Configured correction allowance: ${job.config.patch_attempts}`));
    for(const vote of job.reviewer_votes||[])card.append(node('p',`${vote.role==='reviewer'?'Reviewer':`Reviewer ${vote.reviewer}`}: ${vote.satisfied?'satisfied':'refinement requested'} · ${vote.candidate_supported?'source-supported':'support unresolved'}`));
    const recorded=detail(card,'Recorded activity');
    if(job.events?.length){for(const event of job.events){const row=node('div',null,'task-event');const at=Number.isFinite(event.at)?new Date(event.at*1000).toLocaleTimeString():'Time not recorded';row.append(node('strong',`${at} · ${(event.phase||event.kind||'Recorded event').replaceAll('_',' ')}`),node('p',event.summary||'Summary not recorded.'));if(Number.isInteger(event.attempt))row.append(node('p',`Correction attempt ${event.attempt}`));recorded.append(row);}}
    else recorded.append(node('p','Earlier stage history was not recorded. The current saved status and timestamps are shown above.'));
    if(job.submitted_values?.length){const d=detail(card,'User-provided values · submitted; see outcome');for(const value of job.submitted_values){d.append(node('p',`${value.property||'Value'}${value.scope?.object_id?' · object '+value.scope.object_id:value.scope?.floor_id?' · floor '+value.scope.floor_id:''}: ${typeof value.value==='object'?'Structured user input':String(value.value)} ${value.unit||''}`),node('p','Provided by user, not observed in the original drawing. Submission does not establish that this value was applied.'));if(value.reason)d.append(node('p',value.reason));}}
    for(const conflict of job.conflicts||[]){const d=detail(card,'Input conflict · original evidence retained');d.append(node('p',typeof conflict==='string'?conflict:conflict.message||conflict.reason||conflict.property||'A conflict was recorded; inspect its source before treating a supplied value as factual.'));}
    for(const event of job.recovery_summaries||job.recovery_events||[]){const d=detail(card,`Recovery · ${event.kind||'review'}`);if(event.message||event.summary)d.append(node('p',event.message||event.summary));const feedback=event.feedback;if(feedback){d.append(node('p',[feedback.code,feedback.target_id?`Target ${feedback.target_id}`:'',feedback.explanation].filter(Boolean).join(' · ')));if(feedback.expected_contract)d.append(node('p',`Required correction: ${feedback.expected_contract}`));}
      for(const decision of event.decisions||[]){const label={approved:'Approved correction target',denied:'Denied',unclear:'Unclear · not authorized'}[decision.decision]||'Not authorized';d.append(node('p',`${label} · target ${decision.target_id||'not recorded'}`),node('p',decision.reason||'No reason recorded'));addSource(d,decision.evidence,event.base_revision_id||job.base_revision_id,job,'Inspect reviewed target in original source');}
      for(const request of event.requests||[])if(!(event.decisions||[]).some(d=>d.request_id===request.request_id))d.append(node('p',`Requested target ${request.target_id} · no authorization decision recorded`));
      if(event.kind==='authorization')d.append(node('p','Target approval permits a proposed correction; it does not mean a change was applied or accepted.'));
      for(const ref of event.sources||[]){const b=sourceButton(ref,job);if(b)d.append(b);}
    }
    for(const issue of job.issues||[]){const d=detail(card,issue.discrepancy||issue.category||'Remaining finding');d.append(node('p',[issue.evidence,issue.uncertainty,issue.proposed_action].filter(Boolean).join(' ')));addSource(d,issue.source,issue.source_revision_id||job.base_revision_id,job,'Finding in original source');}
    for(const ref of job.sources||[]){const b=sourceButton(ref,job);if(b)card.append(b);}
    for(const d of card.querySelectorAll('details'))if(opened.has(d.querySelector('summary')?.textContent))d.open=true;
    card.open=terminal(job)&&!wasTerminal?false:open||fresh&&!terminal(job);return card;
  }
  function message(id,text){const card=cards.get(id);if(card){let e=card.querySelector('.task-error');if(!e){e=node('p',null,'task-error');e.setAttribute('role','alert');card.append(e);}e.textContent=text;}}
  function clocks(){let running=false;for(const e of root.querySelectorAll('.task-elapsed')){if(!e.dataset.started){e.textContent='Elapsed time was not recorded.';continue;}const end=e.dataset.finished?Number(e.dataset.finished):Date.now();e.textContent=`Elapsed ${Math.max(0,(end-Number(e.dataset.started))/1000).toFixed(1)} s`;if(!e.dataset.finished)running=true;}if(!running&&timer){clearInterval(timer);timer=null;}if(running&&!timer)timer=setInterval(clocks,1000);}
  function group(parent,map,key,label){
    let entry=map.get(key);if(!entry){const section=node('section',null,'task-project-group');section.dataset.projectId=key;const title=node('h3',label),body=node('div',null,'task-project-items');section.append(title,body);entry={section,title,body};map.set(key,entry);parent.append(section);}entry.title.textContent=label;return entry;
  }
  function update(next,options={}){
    context={...context,...options};if(typeof options.can_work==='boolean')access.can_work=options.can_work;
    jobs=(next||[]).filter(job=>!terminal(job)||!job.activity_dismissed);
    const visible=new Set(jobs.map(job=>job.id));for(const [id,card]of cards)if(!visible.has(id)){card.remove();cards.delete(id);}
    const live=new Set(),past=new Set(),orders=new Map(),groupOrders=new Map();
    for(const job of [...jobs].sort((a,b)=>(b.created_at||0)-(a.created_at||0))){
      const ended=terminal(job),parent=ended?history:list,map=ended?historyGroups:activeGroups,key=job.project_id||job.origin?.project_id||`file:${job.building_id}`;
      (ended?past:live).add(key);const section=group(parent,map,key,job.project_label||job.building_label||'Saved project'),card=render(job);
      const position=orders.get(section.body)||0;orders.set(section.body,position+1);
      if(section.body.children[position]!==card)section.body.insertBefore(card,section.body.children[position]||null);
      if(position===0){const order=groupOrders.get(parent)||0;groupOrders.set(parent,order+1);if(parent.children[order]!==section.section)parent.insertBefore(section.section,parent.children[order]||null);}
    }
    for(const [map,keys]of [[activeGroups,live],[historyGroups,past]])for(const [key,entry]of map)if(!keys.has(key)){entry.section.remove();map.delete(key);}
    const active=jobs.filter(job=>!terminal(job)).length;count.textContent=String(active);empty.hidden=jobs.length>0;historyBox.hidden=!jobs.some(terminal);
    if(selected&&cards.get(selected)?.parentElement?.closest('#task-history-list'))historyBox.open=true;clocks();
  }
  function focus(id){collapse(false);selected=id;const card=cards.get(id);if(card){card.open=true;if(card.parentElement?.closest('#task-history-list'))historyBox.open=true;card.scrollIntoView({block:'nearest'});card.querySelector('summary')?.focus();}root.classList.add('tasks-emphasized');}
  function reset(building_id){context.building_id=building_id;selected=null;root.classList.remove('tasks-emphasized');}
  function setAccess(value){access={...access,...value};if(value.public_demo&&!value.can_work){jobs=[];for(const card of cards.values())card.remove();cards.clear();}update(jobs,{can_work:Boolean(access.can_work)});}
  const toggle=document.getElementById('active-task-toggle'),mobile=matchMedia('(max-width:700px)');
  let savedCollapse=null;try{const saved=localStorage.getItem('concrete-tasks-collapsed');if(saved!==null)savedCollapse=saved==='true';}catch{}
  function collapse(value,persist=false){
    root.querySelector('.task-scroll').hidden=value;toggle.setAttribute('aria-expanded',String(!value));toggle.setAttribute('aria-label',value?'Expand active tasks':'Collapse active tasks');toggle.title=value?'Expand active tasks':'Collapse active tasks';
    toggle.innerHTML=`<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path d="${value?'m14 5-7 7 7 7':'m10 5 7 7-7 7'}" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
    root.classList.toggle('tasks-collapsed',value);document.getElementById('chat-shell').classList.toggle('tasks-collapsed',value);
    if(persist){savedCollapse=value;try{localStorage.setItem('concrete-tasks-collapsed',String(value));}catch{}}
  }
  toggle.addEventListener('click',()=>collapse(toggle.getAttribute('aria-expanded')==='true',true));
  mobile.addEventListener('change',()=>{if(savedCollapse===null)collapse(mobile.matches);});
  const header=document.querySelector('.chat-header');new ResizeObserver(()=>root.style.setProperty('--task-rail-top',header.offsetHeight+'px')).observe(header);
  collapse(savedCollapse??mobile.matches);
  window.activeTasks={update,focus,reset,setAccess};window.addEventListener('pagehide',()=>{clearInterval(timer);timer=null;});window.addEventListener('pageshow',clocks);clocks();
})();
