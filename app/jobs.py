"""Small in-process runner for revision-safe reconstruction and reviewed questions."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import json
import threading
import time
from time import monotonic
import uuid

from .building import BuildingDescription,BUILDING_PROMPT
from .documents import DocumentError, resolve_reference
from .provider import ProviderError,configured_number,settings
from .identities import assign_identities,assign_replacement_identities
from .ifc_generate import generate_ifc
from .ifc_artifact import load_artifact
from .reasoning import build_reasoning
from .revisions import (apply_patch,apply_enrichment,needs_geometry,regression_findings,description_hash,normalize_views,
    PatchRejection,validate_target_requests,authorize_targets,proposal_fingerprint)
from .review_schema import ReconstructionReview
from .revision_delta import build_revision_delta,validate_candidate_review
from .service import ask
from .highlights import validated_highlights

PRIOR_CANDIDATE_PREFIX="Previously reported on a separate candidate with unchanged source description and target representations; verify against originals. "

TERMINAL={"complete","needs_attention","failed","budget_exhausted","stopped","interrupted"}


class JobStopped(Exception):pass
class JobBudget(Exception):pass


def pipeline_config():
    config=settings()
    return {"pipeline_version":"progressive-v1","provider":config["name"],"model":config["model"],
        "reconstruction_model":config["reconstruction_model"],"decision_model":config["decision_model"],
        "prompt_sha256":hashlib.sha256(BUILDING_PROMPT.encode()).hexdigest(),
        "reconstruction_call_seconds":configured_number("RECONSTRUCTION_CALL_SECONDS",300),
        "reconstruction_max_tokens":configured_number("RECONSTRUCTION_MAX_TOKENS",65536,integer=True),
        "reconstruction_review_seconds":configured_number("RECONSTRUCTION_REVIEW_SECONDS",120),
        "reconstruction_review_tokens":configured_number("RECONSTRUCTION_REVIEW_TOKENS",16384,integer=True),
        "temperature":0,"reconstruction_thinking_level":"high" if config["name"]=="gemini" else None,
        "schema_sha256":hashlib.sha256(json.dumps(BuildingDescription.model_json_schema(),sort_keys=True).encode()).hexdigest(),
        "job_seconds":configured_number("RECONSTRUCTION_JOB_SECONDS",900),
        "patch_attempts":configured_number("RECONSTRUCTION_PATCH_ATTEMPTS",2,integer=True)}


class JobRunner:
    def __init__(self,store,provider_factory):
        self.store=store;self.provider_factory=provider_factory
        self.executor=ThreadPoolExecutor(max_workers=2,thread_name_prefix="building")
        self.lock=threading.RLock();self.jobs={};self.events={};self.futures={};self.active={};self.deadlines={};self.closing=False;self.source_locks={}
        for building in store.list():
            for job in store.saved_jobs(building["building_id"]):self.jobs[job["id"]]=job

    def close(self):
        self.closing=True
        for identity,job in list(self.jobs.items()):
            if job["status"] not in TERMINAL:
                self.events.get(identity,threading.Event()).set()
                self._update(identity,status="interrupted",phase="interrupted",message="Application stopped; usable revision retained.")
        self.executor.shutdown(wait=False,cancel_futures=True)

    def _bind_provider(self,identity,provider):
        provider.provider_calls=[]
        provider.diagnostic_stage=lambda:self.jobs[identity].get("phase","provider")
        provider.diagnostic_callback=lambda:self._update(identity,provider_calls=deepcopy(provider.provider_calls))
        return provider

    def _review_candidate(self,identity,provider,document,description,scene,**kwargs):
        """Persist a completed candidate privately before asking for publication review."""
        folder=self.store.directory(document.id)/"diagnostics"/(identity+"-candidate-"+uuid.uuid4().hex)
        folder.mkdir(parents=True,exist_ok=False)
        previous=kwargs.get("previous_description")
        def record_map(value):
            result={}
            for floor in value.floors if value else []:
                result[floor.persistent_id]=floor.model_dump(mode="json")
                for collection in ("rooms","boundaries","openings","features","unresolved"):
                    result.update({item.persistent_id:item.model_dump(mode="json") for item in getattr(floor,collection)})
            return result
        before=record_map(previous);after=record_map(description)
        audit={"job_id":identity,"stage":self.jobs[identity].get("phase"),"status":"awaiting_review",
            "revision_id":document.revision_id,"base_revision_id":document.parent_revision_id,
            "description_sha256":description_hash(description),
            "previous_description_sha256":description_hash(previous) if previous else None,
            "changed_ids":sorted(k for k in after if k is not None and before.get(k)!=after[k]),
            "removed_ids":sorted(k for k in before if k is not None and k not in after)}
        for name,value in (("description.json",description.model_dump(mode="json")),("scene.json",scene.model_dump(mode="json")),
                           ("pipeline.json",self.jobs[identity].get("config",{})),("audit.json",audit)):
            (folder/name).write_text(json.dumps(value,ensure_ascii=False,allow_nan=False))
        if document.ifc_bytes:(folder/"model.ifc").write_bytes(document.ifc_bytes)
        entry={"candidate":str(folder.relative_to(self.store.directory(document.id))),"revision_id":document.revision_id,
            "stage":audit["stage"],"status":"awaiting_review"}
        entries=deepcopy(self.jobs[identity].get("review_candidates",[]));entries.append(entry)
        self._update(identity,review_candidates=entries)
        try:
            review=ReconstructionReview.model_validate(provider.review_reconstruction(document,description,scene,**kwargs))
            # Keep the returned assessment distinct from our publication decision.
            # This is private response data, never a provider request or reasoning trace.
            (folder/"review-response.json").write_text(review.model_dump_json())
            audit["returned_candidate_supported"]=review.candidate_supported
            known_ids=set(before)|set(after)
            for issue in review.issues:
                resolve_reference(document,issue.source.page,issue.source.source_id,issue.source.source_page)
                if any(identity not in known_ids for identity in issue.object_ids):
                    raise DocumentError("Review finding references an unknown source object identity.",422)
            context=kwargs.get("change_context")
            if context is not None:
                # Missing/unclear delta assessment never becomes publication permission.
                blockers=validate_candidate_review(review,context)
                audit["delta_blockers"]=blockers
                resolved,resolution_failures=self._resolved_findings(document,review,kwargs.get("previous_review"),context)
                blockers+=resolution_failures
                if blockers:
                    review=review.model_copy(update={"candidate_supported":False})
                review=self._carry_findings(review,kwargs.get("previous_review"),resolved if not blockers else ())
            audit["status"]="reviewed";audit["candidate_supported"]=review.candidate_supported
            (folder/"review.json").write_text(review.model_dump_json())
            return review
        except Exception:
            audit["status"]="review_failed"
            raise
        finally:
            (folder/"audit.json").write_text(json.dumps(audit,ensure_ascii=False,allow_nan=False))
            entry["status"]=audit["status"]
            if "candidate_supported" in audit:entry["candidate_supported"]=audit["candidate_supported"]
            self._update(identity,review_candidates=entries)

    @staticmethod
    def _carry_findings(review,previous,resolved=()):
        """A limited refinement review cannot silently erase existing fidelity findings."""
        def key(issue):
            value=issue.model_dump(mode="json");value.pop("id",None)
            # Ignore only our repeated provenance annotation, never substantive
            # reviewer uncertainty. Saved historical reviews remain untouched.
            while value["uncertainty"].startswith(PRIOR_CANDIDATE_PREFIX):
                value["uncertainty"]=value["uncertainty"][len(PRIOR_CANDIDATE_PREFIX):]
            return json.dumps(value,sort_keys=True)
        issues=[];seen=set();ids=set()
        candidates=[(issue,False)for issue in review.issues]
        if previous:candidates.extend((issue,True)for issue in previous.issues)
        for issue,is_previous in candidates:
            if is_previous and issue.id in resolved:continue
            fingerprint=key(issue)
            if fingerprint in seen:continue
            retained=issue.model_copy(deep=True)
            if retained.id in ids:
                retained.id="retained:"+retained.id+":"+hashlib.sha256(fingerprint.encode()).hexdigest()[:12]
            issues.append(retained);seen.add(fingerprint);ids.add(retained.id)
        return review.model_copy(update={"issues":issues})

    @staticmethod
    def _resolved_findings(document,review,previous,context):
        """Retiring an old finding requires an explicit source-linked changed result."""
        assessment=review.candidate_assessment
        if assessment is None:return set(),[]
        prior={issue.id:issue for issue in previous.issues} if previous else {}
        active={issue.id for issue in review.issues};seen=set();resolved=set();failures=[]
        changed={item["id"] for item in context.get("object_changes",[])}
        changed.update(item["floor_id"] for item in context.get("frame_changes",[]))
        elements={element.id:element for element in document.scene.elements}
        floors={floor.id:floor for floor in document.scene.floors}
        def touches(a,b):
            return a.page==b.page and min(a.bbox[2],b.bbox[2])>=max(a.bbox[0],b.bbox[0]) and min(a.bbox[3],b.bbox[3])>=max(a.bbox[1],b.bbox[1])
        for resolution in assessment.issue_resolutions:
            issue=prior.get(resolution.issue_id)
            valid=issue is not None and resolution.issue_id not in seen and resolution.issue_id not in active and bool(resolution.reason.strip())
            seen.add(resolution.issue_id)
            try:resolve_reference(document,resolution.evidence.page,resolution.evidence.source_id,resolution.evidence.source_page)
            except DocumentError:valid=False
            if issue:
                affected=set(issue.object_ids)&changed
                if not issue.object_ids:
                    affected={key for key in changed if key in elements and touches(elements[key].source,issue.source)}
                related=[elements[key].source if key in elements else floors[key].source for key in affected if key in elements or key in floors]
                valid=valid and touches(issue.source,resolution.evidence) and any(touches(source,resolution.evidence)for source in related)
                # One repaired member cannot hide other still-unresolved members.
                valid=valid and all(key not in elements or elements[key].geometry is not None for key in issue.object_ids)
                if context.get("pure_height_change") and issue.category!="display":valid=False
            if valid:resolved.add(resolution.issue_id)
            else:failures.append("A prior finding resolution lacks a supported complete source-linked change: "+resolution.issue_id)
        return resolved,failures

    def _baseline_review(self,document):
        """Carry only source/identity-valid findings attributable to this baseline."""
        directory=self.store.directory(document.id)
        folder=directory/"revisions"/document.revision_id
        previous=None
        elements={e.id:e.model_dump(mode="json")for e in document.scene.elements} if document.scene else {}
        floors={f.id:f.model_dump(mode="json")for f in document.scene.floors} if document.scene else {}
        known=set(elements)|set(floors)
        def horizontal_representation(element):
            value={key:deepcopy(element.get(key))for key in ("source","storey_id","representation","geometry_origin",
                "evidence_basis","name","semantic_type","environment")}
            geometry=deepcopy(element.get("geometry"))
            if geometry:
                if geometry.get("type")=="mesh":
                    positions=geometry.get("positions",[])
                    geometry["positions"]=[positions[index:index+2]for index in range(0,len(positions),3)]
                else:
                    for key in ("center","size"):
                        if geometry.get(key):geometry[key]=geometry[key][:2]
            value["geometry"]=geometry
            return value
        def valid(issue):
            try:resolve_reference(document,issue.source.page,issue.source.source_id,issue.source.source_page)
            except DocumentError:return False
            return all(identity in known for identity in issue.object_ids)
        path=folder/"review.json"
        if path.exists():
            info=json.loads((folder/"revision.json").read_text())
            if hashlib.sha256(path.read_bytes()).hexdigest()!=info["hashes"].get("review.json"):
                raise DocumentError("Saved revision review failed integrity validation.",422)
            saved=ReconstructionReview.model_validate_json(path.read_text())
            previous=saved.model_copy(update={"issues":[issue for issue in saved.issues if valid(issue)]})
        # Job.issues can describe a REJECTED candidate. Mere base-revision equality
        # is not evidence that its defects existed in the published model.
        for job in self.for_building(document.id):
            if document.revision_id not in (job.get("base_revision_id"),job.get("revision_id")):continue
            for entry in job.get("review_candidates",[]):
                candidate=(directory/entry["candidate"]).resolve()
                if not candidate.is_relative_to(directory.resolve()):continue
                try:
                    audit=json.loads((candidate/"audit.json").read_text())
                    if audit.get("status")!="reviewed":continue
                    exact=entry.get("revision_id")==document.revision_id
                    if not exact and audit.get("base_revision_id")!=document.revision_id:continue
                    description=json.loads((candidate/"description.json").read_text())
                    if description!=document.description.model_dump(mode="json"):continue
                    scene=json.loads((candidate/"scene.json").read_text())
                    candidate_elements={e["id"]:e for e in scene["elements"]}
                    candidate_floors={f["id"]:f for f in scene["floors"]}
                    if set(candidate_elements)!=set(elements) or set(candidate_floors)!=set(floors):continue
                    saved=ReconstructionReview.model_validate_json((candidate/"review.json").read_text())
                except (OSError,ValueError,KeyError):continue
                retained=[]
                for issue in saved.issues:
                    if not valid(issue):continue
                    if not exact:
                        if issue.category=="display":continue
                        # Explicit target defects can be carried only when the
                        # complete target representation is unchanged, not just XY.
                        if any((elements.get(key) or floors.get(key))!=(candidate_elements.get(key) or candidate_floors.get(key))for key in issue.object_ids):continue
                        if not issue.object_ids:
                            if issue.category!="extraction":continue
                            # A region-only finding must not import a candidate's
                            # changed plan geometry under the name of a baseline gap.
                            if any(horizontal_representation(elements[key])!=horizontal_representation(candidate_elements[key])for key in elements):continue
                        issue=issue.model_copy(deep=True)
                        if not issue.uncertainty.startswith(PRIOR_CANDIDATE_PREFIX):
                            issue.uncertainty=PRIOR_CANDIDATE_PREFIX+issue.uncertainty
                    retained.append(issue)
                saved=saved.model_copy(update={"issues":retained})
                previous=self._carry_findings(previous or saved,saved)
        return previous

    @staticmethod
    def _geometry_loss_feedback(before,after,failures):
        """Only completed same-identity mesh losses are recoverable here.

        Diagnostics never authorize another target or excuse a geometry loss.
        Mixed frame/missing-object failures retain their existing terminal path.
        """
        if before.scene is None or after.scene is None:return None
        old={element.id:element for element in before.scene.elements}
        new={element.id:element for element in after.scene.elements}
        lost=sorted(key for key in old.keys()&new.keys() if old[key].geometry and not new[key].geometry)
        expected={"Previously renderable object became unresolved/unrenderable: "+key for key in lost}
        if not lost or set(failures)!=expected:return None
        return {"code":"geometry_regression",
            "explanation":"Proposed geometry made previously renderable objects unresolved.",
            "expected_contract":"Correct the identified geometry using original evidence and existing reviewed authority. "
                "Preserve other usable objects; request any additional target explicitly. Do not pad, snap or invent geometry to bypass validation.",
            "geometry_losses":[{"target_id":key,"floor_id":new[key].storey_id,
                "before_representation":old[key].representation,"after_representation":new[key].representation,
                "candidate_diagnostic":new[key].note}for key in lost]}

    def _recovery_event(self,identity,**event):
        events=deepcopy(self.jobs[identity].get("recovery_events",[]));events.append(event)
        self._update(identity,recovery_events=events)

    def _unresolved_correction(self,identity,review,message):
        # Do not publish a new revision merely to label a rejected/no-op proposal.
        self._update(identity,status="needs_attention",phase="complete",message=message,
                     issues=[issue.model_dump()for issue in review.issues])

    def _update(self,identity,**fields):
        with self.lock:
            job=self.jobs[identity]
            # A shutdown/stop token cannot be resurrected by an in-flight provider result.
            if job["status"] in {"interrupted","stopped"} and fields.get("status") not in {"interrupted","stopped"}:
                return
            if (self.events.get(identity) and self.events[identity].is_set()
                    and fields.get("status") not in {"interrupted","stopped"}):
                return
            job.update(fields,updated_at=time.time())
            self.store.save_job(job["building_id"],deepcopy(job))

    def get(self,identity):
        with self.lock:
            if identity not in self.jobs:raise DocumentError("Job not found.",404)
            return deepcopy(self.jobs[identity])

    def for_building(self,building_id):
        with self.lock:
            return sorted([deepcopy(j)for j in self.jobs.values()if j["building_id"]==building_id],key=lambda j:j["created_at"],reverse=True)

    def _new(self,document,kind,request_id=None):
        identity=uuid.uuid4().hex
        job={"id":identity,"building_id":document.id,"kind":kind,"request_id":request_id,
            "base_revision_id":document.revision_id,"revision_id":document.revision_id,
            "revision_number":document.revision_number,"status":"queued","phase":"queued",
            "message":"Waiting to process.","created_at":time.time(),"updated_at":time.time(),"issues":[],"attempts":[]}
        self.jobs[identity]=job;self.events[identity]=threading.Event()
        self.store.save_job(document.id,job)
        return identity

    def reconstruct(self,building_id,base_revision_id=None,mode="refine"):
        document=self.store.get(building_id)
        if document.kind=="ifc" and document.scene and not document.scene.derived:
            raise DocumentError("Genuine IFC uses its supplied records and geometry; it is not reconstructed or rewritten.",422)
        if base_revision_id and base_revision_id!=document.revision_id:
            raise DocumentError("The building revision changed; refresh before starting another review.",409)
        with self.lock:
            active=self.active.get(building_id)
            if active and self.jobs[active]["status"] not in TERMINAL:
                return self.get(active)
            identity=self._new(document,"reconstruction")
            self.active[building_id]=identity
            self.futures[identity]=self.executor.submit(self._reconstruct,identity,document.snapshot(),mode)
            return self.get(identity)

    def extract(self,building_id,source_ids=None,*,retry=False):
        document=self.store.get(building_id)
        wanted=set(source_ids) if source_ids else {s["source_id"] for s in document.sources}
        available={s["source_id"]:s for s in document.sources}
        if not wanted<=set(available):raise DocumentError("Extraction source does not belong to this building.",422)
        result=[]
        if document.description is not None and document.interpretation_status=="complete":return result
        with self.lock:
            for source_id in sorted(wanted):
                if available[source_id]["kind"]=="ifc" or source_id in document.source_interpretations:continue
                previous=[j for j in self.jobs.values() if j["building_id"]==building_id and j["kind"]=="extraction" and j.get("source_id")==source_id]
                active=next((j for j in previous if j["status"] not in TERMINAL),None)
                if active:result.append(deepcopy(active));continue
                if previous and not retry:continue
                identity=self._new(document,"extraction");self.jobs[identity]["source_id"]=source_id
                self._update(identity,source_id=source_id)
                self.futures[identity]=self.executor.submit(self._extract,identity,source_id)
                result.append(self.get(identity))
        return result

    def _source_interpretation(self,identity,source_id,provider,deadline):
        with self.lock:source_lock=self.source_locks.setdefault(source_id,threading.Lock())
        with source_lock:
            self._check(identity,deadline)
            document=self.store.get(self.jobs[identity]["building_id"])
            if source_id in document.source_interpretations:return document
            cached=self.store.cached_interpretation(source_id)
            if cached is None:
                source=self.store.source_document(document,source_id)
                self._update(identity,status="running",phase="extraction_provider",message="Extracting source-linked interpretation; 3D is optional.")
                output=provider.extract_interpretation(source,include_geometry=False)
                self._check(identity,deadline)
                self._update(identity,phase="interpretation_validation",message="Validating and saving source interpretation.")
                cached=normalize_views(BuildingDescription.model_validate(output))
                from .revisions import _validate_all_sources,_provided_fields
                _validate_all_sources(source,cached.model_dump(mode="json"))
                if _provided_fields(cached.model_dump(mode="json")):
                    raise DocumentError("Source extraction cannot invent user-provided provenance.",422)
                self.store.save_interpretation(source_id,cached)
            self._check(identity,deadline)
            current=self.store.merge_interpretation(document.id,source_id,cached,job_guard=lambda:self._valid(identity) and monotonic()<self.deadlines.get(identity,float("inf")))
            self._update(identity,revision_id=current.revision_id,revision_number=current.revision_number)
            return current

    def _extract(self,identity,source_id):
        provider=None
        try:
            config=pipeline_config();self._update(identity,config=config)
            deadline=monotonic()+config["job_seconds"];self.deadlines[identity]=deadline
            self._check(identity,deadline)
            # Cache reuse does not construct a credential-requiring provider.
            cached=self.store.cached_interpretation(source_id)
            if cached is not None:
                current=self.store.merge_interpretation(self.jobs[identity]["building_id"],source_id,cached,job_guard=lambda:self._valid(identity) and monotonic()<self.deadlines.get(identity,float("inf")))
            else:
                self._update(identity,status="running",phase="extraction_provider",message="Preparing source interpretation.")
                provider=self._bind_provider(identity,self.provider_factory());provider.request_deadline=deadline
                current=self._source_interpretation(identity,source_id,provider,deadline)
            self._check(identity,deadline)
            self._update(identity,status="complete",phase="complete",message="Source interpretation saved. Ask questions now or explicitly generate 3D.",
                revision_id=current.revision_id,revision_number=current.revision_number,interpretation_status=current.interpretation_status)
        except JobStopped:self._update(identity,status="stopped",phase="stopped",message="Extraction stopped; original sources remain saved.")
        except JobBudget:self._update(identity,status="budget_exhausted",phase="complete",message="Extraction execution budget reached; original sources remain saved.")
        except Exception as error:self._failure(identity,error,provider)
        finally:
            if provider:
                self._update(identity,usage=provider.usage.model_dump() if hasattr(provider,"usage") else {})
                provider.close()

    def refine_inputs(self,building_id,request):
        from .user_inputs import prepare_inputs
        document=self.store.get(building_id)
        candidate,submitted,needs_model,conflicts,changes=prepare_inputs(document,request)
        with self.lock:
            active=self.active.get(building_id)
            if active and self.jobs[active]["status"] not in TERMINAL:
                raise DocumentError("Another geometry/refinement job is active; stop it or apply after it completes.",409)
            identity=self._new(document,"refinement")
            self.active[building_id]=identity
            self._update(identity,submitted_values=submitted,conflicts=conflicts)
            self.futures[identity]=self.executor.submit(self._refine_inputs,identity,document.snapshot(),candidate,submitted,needs_model,conflicts,changes)
            return self.get(identity)

    def question(self,request,*,pinned_document=None):
        from .conversation import question_context,user_message
        document=pinned_document or self.store.get(request.document_id)
        if document.id!=request.document_id:raise DocumentError("Pinned question source does not match the request.",409)
        if request.revision_id and request.revision_id!=document.revision_id:
            raise DocumentError("The building updated before this question started; refresh its revision and ask again.",409)
        with self.lock:
            if request.request_id:
                prior=next((j for j in self.jobs.values() if j["kind"]=="question" and j["building_id"]==document.id and j.get("request_id")==request.request_id),None)
                if prior:
                    if prior.get("base_revision_id")!=document.revision_id:
                        raise DocumentError("This question request ID belongs to another revision; start a new question request.",409)
                    return self.get(prior["id"])
            context=question_context(self.store,document,request)
            identity=self._new(document,"question",request.request_id)
            message=user_message(document,request,identity)
            self.store.append_conversation(document.id,message)
            snapshot=document.snapshot();snapshot.conversation_context=context
            self._update(identity,question=request.question,user_message_id=message["id"],conversation_id=document.id)
            self.futures[identity]=self.executor.submit(self._question,identity,snapshot,request.question,pinned_document is not None)
            return self.get(identity)

    def stop(self,identity):
        job=self.get(identity)
        if job["status"] in TERMINAL:return job
        # Same lock as publication gives stop/publication a defined order.
        with self.lock:
            with self.store.lock:
                self.events[identity].set()
            self._update(identity,status="stopped",phase="stopped",message="Stopped. An in-flight request may finish, but cannot publish another result.")
        return self.get(identity)

    def _valid(self,identity):
        job=self.jobs[identity]
        return not self.closing and not self.events[identity].is_set() and (
            job["kind"] not in {"reconstruction","refinement"} or self.active.get(job["building_id"])==identity)

    def _check(self,identity,deadline):
        if not self._valid(identity):raise JobStopped()
        if monotonic()>=deadline:raise JobBudget()

    def _publish(self,identity,candidate,base,*,status,review=None,config=None):
        result=self.store.commit(candidate,base,status=status,review=review,config=config,
                                 job_guard=lambda:self._valid(identity) and monotonic()<self.deadlines.get(identity,float("inf")))
        self._update(identity,revision_id=result.revision_id,revision_number=result.revision_number,
                     model_available=bool(result.scene and any(e.geometry for e in result.scene.elements)))
        return result

    def _geometry(self,candidate):
        candidate.geometry_status="available";candidate.geometry_revision_id=candidate.revision_id
        try:candidate.ifc_bytes=generate_ifc(candidate.description,candidate)
        except Exception as error:
            error.error_stage="ifc_generation"
            raise
        try:
            restored=load_artifact(candidate.ifc_bytes,candidate.id)
            if restored is None:raise DocumentError("Generated IFC lost original drawing provenance.",422)
            candidate.scene=restored[0]
        except Exception as error:
            error.error_stage="ifc_reopening"
            raise
        candidate.reasoning=build_reasoning(candidate)

    def _finish_review(self,identity,current,review,config,status,message):
        updated=self.store.prepare(current)
        current=self._publish(identity,updated,current.revision_id,status=status,review=review,config=config)
        self._update(identity,status="complete" if status=="reviewed_no_action" else "needs_attention",
            phase="complete",message=message,issues=[i.model_dump()for i in review.issues])

    def _reconstruct(self,identity,current,mode):
        provider=None
        try:
            config=pipeline_config();self._update(identity,config=config);deadline=monotonic()+config["job_seconds"]
            self.deadlines[identity]=deadline
            self._check(identity,deadline)
            self._update(identity,status="running",phase="provider_setup",message="Preparing requested geometry processing.")
            provider=self._bind_provider(identity,self.provider_factory());provider.request_deadline=deadline
            review=None
            modern=callable(getattr(provider,"extract_interpretation",None))
            if modern:
                while True:
                    pending=[] if current.description is not None and current.interpretation_status=="complete" else [source for source in current.sources if source["kind"]!="ifc" and source["source_id"] not in current.source_interpretations]
                    if not pending:break
                    for source in pending:
                        current=self._source_interpretation(identity,source["source_id"],provider,deadline)
                if current.description is None:
                    raise DocumentError("No saved drawing interpretation is available to generate geometry.",422)
                if not current.description.floors:
                    self._update(identity,status="needs_attention",phase="complete",message="Source interpretation is saved; no floor-plan geometry is established by these views.")
                    return
                if not current.scene or current.geometry_status=="stale" or mode=="reconstruct" or needs_geometry(current.description):
                    candidate=current.snapshot()
                    if needs_geometry(current.description):
                        self._update(identity,status="running",phase="geometry_enrichment",message="Adding only missing source-supported geometry to the saved interpretation.")
                        patch=provider.enrich_geometry(current)
                        self._check(identity,deadline)
                        candidate,changes=apply_enrichment(current,patch)
                    else:changes={}
                    candidate=self.store.prepare(candidate)
                    self._update(identity,status="running",phase="ifc_generation",message="Generating IFC locally from saved interpretation.")
                    self._geometry(candidate);self._check(identity,deadline)
                    if current.scene:
                        failures=regression_findings(current,candidate,changes)
                        if failures:
                            path=self.store.save_candidate(candidate,None,failures,config)
                            self._update(identity,status="needs_attention",phase="complete",message="Candidate lost usable geometry; previous model and saved interpretation retained.",attempts=[{"candidate":path,"accepted":False,"findings":failures}]);return
                        self._update(identity,phase="checking_revision",message="Checking candidate against original sources and prior geometry.")
                        prior=self._baseline_review(current)
                        context=build_revision_delta(current,candidate,[],changes)
                        context["prior_findings"]=[i.model_dump(mode="json")for i in prior.issues] if prior else []
                        review=ReconstructionReview.model_validate(self._review_candidate(identity,provider,candidate,candidate.description,candidate.scene,
                            previous_description=current.description,previous_scene=current.scene,previous_review=prior,
                            previous_user_values=current.user_values,change_context=context))
                        if not review.candidate_supported:
                            path=self.store.save_candidate(candidate,review,"Candidate not supported by source review.",config)
                            self._update(identity,status="needs_attention",phase="complete",message="Candidate not supported; previous model retained.",attempts=[{"candidate":path,"accepted":False}]);return
                    current=self._publish(identity,candidate,current.revision_id,status="preview_reviewing",config=config)
                    self._update(identity,phase="reviewing",message="Preview · review in progress")
            else:
                review=None
                self._update(identity,status="running",phase="describing" if not current.scene or mode=="reconstruct" else "reviewing",
                             message="Describing original source." if not current.scene else "Reviewing original source and generated geometry.",config=config)
                if not current.scene or mode=="reconstruct":
                    self._update(identity,phase="extraction_provider",message="Interpreting original source.")
                    output=provider.reconstruct(current)
                    self._check(identity,deadline)
                    self._update(identity,phase="interpretation_validation",message="Validating returned interpretation.")
                    candidate=self.store.prepare(current)
                    description=normalize_views(BuildingDescription.model_validate(output))
                    candidate.description=(assign_replacement_identities(candidate,description)if current.scene
                                           else assign_identities(candidate,description))
                    candidate.reasoning=None
                    if not description.floors:
                        candidate.scene=None;candidate.ifc_bytes=None;candidate.reasoning=build_reasoning(candidate)
                        if current.scene:
                            path=self.store.save_candidate(candidate,None,"Replacement removed all existing floor geometry.",config)
                            self._update(identity,status="needs_attention",phase="complete",
                                message="Replacement contains no floor geometry; previous usable model retained. Use targeted refinement to review supported changes.",
                                attempts=[{"candidate":path,"accepted":False}])
                            return
                        self._publish(identity,candidate,current.revision_id,status="source_only",config=config)
                        self._update(identity,status="needs_attention",phase="complete",message="Original evidence is available; no supported floor-plan geometry was reconstructed.",
                                     unresolved_views=[v.model_dump()for v in description.unresolved_views])
                        return
                    if not current.scene:
                        candidate.interpretation_status="complete";candidate.reasoning=build_reasoning(candidate)
                        current=self._publish(identity,candidate,current.revision_id,status="interpreted",config=config)
                        candidate=self.store.prepare(current)
                    self._update(identity,phase="generating",message="Generating and reopening the first model.")
                    self._geometry(candidate)
                    self._check(identity,deadline)
                    if current.scene:
                        failures=regression_findings(current,candidate,{})
                        if failures:
                            path=self.store.save_candidate(candidate,None,failures,config)
                            self._update(identity,status="needs_attention",phase="complete",
                                message="Replacement lost or could not reliably match existing objects; previous model retained. Use targeted refinement for supported changes.",
                                attempts=[{"candidate":path,"accepted":False,"findings":failures}])
                            return
                        self._update(identity,phase="checking_revision",message="Checking replacement against original source and previous geometry before publication.")
                        prior=self._baseline_review(current)
                        context=build_revision_delta(current,candidate,[],{})
                        context["prior_findings"]=[i.model_dump(mode="json")for i in prior.issues] if prior else []
                        review=ReconstructionReview.model_validate(self._review_candidate(identity,provider,candidate,candidate.description,candidate.scene,
                            previous_description=current.description,previous_scene=current.scene,previous_review=prior,
                            previous_user_values=current.user_values,change_context=context))
                        self._check(identity,deadline)
                        if not review.candidate_supported:
                            path=self.store.save_candidate(candidate,review,"Replacement not supported against original source.",config)
                            self._update(identity,status="needs_attention",phase="complete",message="Replacement was not supported by source review; previous usable model retained.",
                                attempts=[{"candidate":path,"accepted":False}],candidate_issues=[i.model_dump()for i in review.issues])
                            return
                    current=self._publish(identity,candidate,current.revision_id,status="preview_reviewing",config=config)
                    self._update(identity,phase="reviewing",message="Preview · review in progress")
            if not current.description:
                self._update(identity,status="needs_attention",phase="complete",message="This older artifact has original pages but no exact description. Its existing model is retained; an explicit new reconstruction is needed to refine it.")
                return
            self._check(identity,deadline)
            if review is None:
                review=ReconstructionReview.model_validate(self._review_candidate(identity,provider,current,current.description,current.scene))
            self._check(identity,deadline)
            feedback=None;authorizations=[];seen_proposals=set();reviewed_requests=set()
            for attempt in range(config["patch_attempts"]):
                self._update(identity,issues=[i.model_dump()for i in review.issues])
                actionable=[i for i in review.issues if i.actionable and i.category=="extraction"]
                if not actionable:
                    self._finish_review(identity,current,review,config,
                        "reviewed_issues" if review.issues or not review.candidate_supported else "reviewed_no_action",
                        "Review stopped: remaining uncertainty is visible." if review.issues or not review.candidate_supported else "Review found no further supported correction. This is not a guarantee of accuracy.")
                    return
                self._check(identity,deadline)
                self._update(identity,phase="correcting",message="Proposing a targeted correction within the reviewed source scope.")
                kwargs={}
                if feedback is not None:kwargs["validation_feedback"]=feedback
                if authorizations:kwargs["authorizations"]=[g.model_dump(mode="json")for g in authorizations]
                patch=provider.patch_reconstruction(current,current.description,current.scene,review,**kwargs)
                self._check(identity,deadline)
                self._update(identity,last_proposed_patch=patch.model_dump() if hasattr(patch,"model_dump") else patch)
                fingerprint=proposal_fingerprint(patch)
                authority=tuple(sorted((g.issue_id,g.target_id,json.dumps(g.evidence,sort_keys=True))for g in authorizations))
                state=(description_hash(current.description),authority,fingerprint)
                if state in seen_proposals:
                    self._recovery_event(identity,kind="stopped",attempt=attempt+1,message="The same material proposal repeated with unchanged authorization.")
                    self._unresolved_correction(identity,review,"Correction repeated without material progress; previous usable revision retained.")
                    return
                seen_proposals.add(state)
                grants_before=len(authorizations);decisions=[]
                try:
                    requests=validate_target_requests(current,review,patch.additional_target_requests)
                    pending=[]
                    for request in requests:
                        key=(current.revision_id,request.issue_id,request.target_id,request.floor_id,request.collection,
                             json.dumps(request.evidence.model_dump(mode="json"),sort_keys=True))
                        if key not in reviewed_requests:pending.append(request)
                    if pending:
                        self._check(identity,deadline)
                        self._update(identity,phase="reviewing_targets",message="Inspecting original evidence before authorizing requested additional targets.")
                        scope_review=provider.review_target_requests(current,current.description,current.scene,review,pending,
                                                                    validation_feedback=feedback)
                        self._check(identity,deadline)
                        new_grants=authorize_targets(current,review,pending,scope_review)
                        decisions=[d.model_dump(mode="json")for d in scope_review.decisions]
                        self._recovery_event(identity,kind="authorization",attempt=attempt+1,base_revision_id=current.revision_id,
                            requests=[r.model_dump(mode="json")for r in pending],decisions=decisions,
                            message="Additional targets were inspected against the original; only explicit approvals grant scope.")
                        for request in pending:
                            reviewed_requests.add((current.revision_id,request.issue_id,request.target_id,request.floor_id,request.collection,
                                                   json.dumps(request.evidence.model_dump(mode="json"),sort_keys=True)))
                        known={(g.issue_id,g.target_id)for g in authorizations}
                        authorizations.extend(g for g in new_grants if (g.issue_id,g.target_id)not in known)
                    self._update(identity,phase="validating_patch",message="Validating all proposed edits atomically against source and authorized targets.")
                    candidate,changes=apply_patch(current,patch,review,authorizations=authorizations)
                except PatchRejection as error:
                    feedback={**error.feedback,"base_revision_id":current.revision_id,"proposal_sha256":fingerprint,
                              "rejected_proposal":patch.model_dump(mode="json"),"authorization_decisions":decisions}
                    self._recovery_event(identity,kind="rejection",attempt=attempt+1,
                        feedback={k:v for k,v in feedback.items()if k!="rejected_proposal"},
                        message=error.message)
                    self._update(identity,last_validation_feedback=feedback)
                    if error.feedback.get("code")=="no_material_change" and len(authorizations)==grants_before:
                        self._unresolved_correction(identity,review,"Correction made no material change; unresolved findings and previous usable revision retained.")
                        return
                    if attempt+1==config["patch_attempts"]:
                        self._unresolved_correction(identity,review,"Correction remains unresolved after the configured attempts: "+error.message+" Previous usable revision retained.")
                        return
                    continue
                candidate=self.store.prepare(candidate)
                self._geometry(candidate)
                failures=regression_findings(current,candidate,changes)
                if failures:
                    candidate_path=self.store.save_candidate(candidate,review,failures,config)
                    self._update(identity,attempts=self.jobs[identity]["attempts"]+
                        [{"candidate":candidate_path,"accepted":False,"findings":failures}])
                    geometry_feedback=self._geometry_loss_feedback(current,candidate,failures)
                    if geometry_feedback:
                        feedback={**geometry_feedback,"base_revision_id":current.revision_id,
                            "proposal_sha256":fingerprint,"rejected_proposal":patch.model_dump(mode="json")}
                        self._recovery_event(identity,kind="rejection",attempt=attempt+1,
                            feedback={key:value for key,value in feedback.items()if key!="rejected_proposal"},
                            message=geometry_feedback["explanation"])
                        self._update(identity,last_validation_feedback=feedback)
                        if attempt+1<config["patch_attempts"]:continue
                    self._update(identity,status="needs_attention",phase="complete",
                        message="Candidate rejected: geometry disappeared or an unchanged frame moved. Previous usable revision retained.")
                    return
                self._check(identity,deadline)
                context=build_revision_delta(current,candidate,[],changes)
                context["prior_findings"]=[i.model_dump(mode="json")for i in review.issues]
                self._update(identity,phase="checking_revision",message="Checking the requested correction and actual IFC changes against original evidence.")
                candidate_review=ReconstructionReview.model_validate(self._review_candidate(identity,provider,candidate,candidate.description,candidate.scene,
                    previous_description=current.description,previous_scene=current.scene,previous_review=review,
                    previous_user_values=current.user_values,change_context=context))
                self._check(identity,deadline)
                if not candidate_review.candidate_supported:
                    path=self.store.save_candidate(candidate,candidate_review,"Source/geometry reviewer did not support the candidate delta.",config)
                    self._update(identity,status="needs_attention",phase="complete",message="Candidate change was not supported by source review; previous usable model retained.",
                        attempts=self.jobs[identity]["attempts"]+[{"candidate":path,"accepted":False,"review":candidate_review.model_dump()}],
                        candidate_issues=[i.model_dump()for i in candidate_review.issues])
                    return
                current=self._publish(identity,candidate,current.revision_id,status="preview_reviewing",review=candidate_review,config=config)
                self._update(identity,attempts=self.jobs[identity]["attempts"]+[{"revision_id":current.revision_id,"accepted":True,"changes":changes}])
                review=candidate_review;feedback=None;authorizations=[];reviewed_requests=set()
            if not review.issues and review.candidate_supported:
                self._finish_review(identity,current,review,config,"reviewed_no_action",
                    "Requested corrections were reviewed; no further supported correction was identified. This is not a guarantee of accuracy.")
            else:
                self._unresolved_correction(identity,review,"Configured correction attempts completed; latest supported revision retained with remaining findings.")
        except JobStopped:
            self._update(identity,status="stopped",phase="stopped",message="Stopped; previous usable revision retained.")
        except JobBudget:
            self._update(identity,status="budget_exhausted",phase="complete",message="Configured processing budget exhausted; this is not an evidence-insufficiency judgment.")
        except Exception as error:
            self._failure(identity,error,provider)
        finally:
            if provider:
                self._update(identity,usage=provider.usage.model_dump() if hasattr(provider,"usage") else {})
                provider.close()

    def _question(self,identity,snapshot,question,pin_display=False):
        provider=None
        try:
            self._check(identity,float("inf"))
            provider=self._bind_provider(identity,self.provider_factory())
            def progress(phase):
                self._check(identity,float("inf"))
                self._update(identity,status="running",phase=phase,message=phase)
            answer=ask(snapshot,question,provider,progress=progress)
            self._check(identity,float("inf"))
            displayed=snapshot if pin_display else self.store.get(snapshot.id)
            answer.building_id=snapshot.id;answer.answered_revision_id=snapshot.revision_id
            answer.display_revision_id=displayed.revision_id
            if displayed.revision_id!=snapshot.revision_id:
                previous=list(answer.highlight_ids)
                answer.highlight_ids=validated_highlights(answer,displayed)
                if previous!=answer.highlight_ids:
                    answer.review_note += " Model updated while answering; unavailable object highlights were omitted. Original source citations remain available."
            from .conversation import assistant_message
            with self.lock:
                with self.store.lock:
                    self._check(identity,float("inf"))
                    message=assistant_message(snapshot,answer,identity,self.jobs[identity].get("user_message_id"))
                    self.store.append_conversation(snapshot.id,message)
                    self._update(identity,status="complete",phase="complete",message="Clarification requested." if answer.status=="clarification" else "Answer checked against supplied evidence.",
                        answer=answer.model_dump(),assistant_message_id=message["id"],conversation_id=snapshot.id,
                        revision_id=displayed.revision_id,revision_number=displayed.revision_number)
        except JobStopped:
            self._update(identity,status="stopped",phase="stopped",message="Question stopped; unpublished draft discarded.")
        except Exception as error:
            safe=error.message if isinstance(error,(ProviderError,DocumentError)) else "Question processing failed operationally; no evidence conclusion was made."
            self._update(identity,status="failed",phase="failed",message=safe)
        finally:
            if provider:provider.close()


    def _failure(self,identity,error,provider=None):
        from .reconstruction_errors import reconstruction_error
        phase=getattr(error,"error_stage",self.jobs[identity].get("phase","processing"))
        mapped={"provider_setup":"provider","extraction_provider":"provider","geometry_enrichment":"provider",
            "checking_revision":"provider","reviewing":"provider","correcting":"provider","user_input_review":"provider",
            "interpretation_validation":"description","ifc_generation":"generation","generating":"generation","ifc_reopening":"artifact"}.get(phase,"provider" if "review" in phase else "description")
        # A locally rejected data operation is distinct from a provider request failure.
        if isinstance(error,DocumentError) and mapped=="provider":mapped="description"
        safe=reconstruction_error(error,mapped)
        diagnostic_id=getattr(safe,"diagnostic_id",None) or uuid.uuid4().hex
        calls=getattr(provider,"provider_calls",[]) if provider else []
        call=calls[-1] if calls else None
        bound=bool(call and getattr(provider,"last_response_call_id",None)==call["call_id"])
        output=getattr(provider,"last_structured_output",None) if bound else None
        response_text=getattr(provider,"last_response_text",None) if bound else None
        folder=self.store.directory(self.jobs[identity]["building_id"])/"diagnostics";folder.mkdir(exist_ok=True)
        payload={"stage":phase,"provider_call":call,"response_call_id":call["call_id"] if bound else None,
            "response_stage":call["stage"] if bound else None,"structured_output":output,
            "response_available":bound,"nonthought_response_text":response_text}
        try:(folder/(diagnostic_id+".json")).write_text(json.dumps(payload,ensure_ascii=False,allow_nan=False))
        except (OSError,TypeError,ValueError):pass
        current=self.store.get(self.jobs[identity]["building_id"])
        usable=bool(current.scene and any(element.geometry for element in current.scene.elements))
        retained="Previous usable model retained." if usable else "Original sources are saved; no usable model has been generated."
        if current.description is not None:retained+=" Saved interpretation retained."
        exhausted=monotonic()>=self.deadlines.get(identity,float("inf"))
        self._update(identity,status="budget_exhausted" if exhausted else "failed",phase="failed",error_stage=phase,
            error_category=getattr(safe,"category","application_rejection" if isinstance(error,DocumentError) else "operational_failure"),
            diagnostic_id=diagnostic_id,message=f"{phase.replace('_',' ').capitalize()} failed operationally. {retained} No evidence-quality conclusion was made. [{mapped}/{getattr(safe,'category','application_rejection' if isinstance(error,DocumentError) else 'operational_failure')}; reference {diagnostic_id}]",
            diagnostic_message=safe.message,has_previous_model=usable)

    def _refine_inputs(self,identity,current,candidate,submitted,needs_model,conflicts,changes):
        provider=None;review=None
        try:
            config=pipeline_config();self._update(identity,config=config);deadline=monotonic()+config["job_seconds"];self.deadlines[identity]=deadline
            self._check(identity,deadline)
            candidate=self.store.prepare(candidate)
            if conflicts:
                path=self.store.save_candidate(candidate,None,conflicts,config)
                self._update(identity,status="needs_attention",phase="complete",message="Supplied inputs were saved but conflict with observed source values. Prior usable revision retained.",attempts=[{"candidate":path,"accepted":False}],conflicts=conflicts);return
            if needs_model:
                provider=self._bind_provider(identity,self.provider_factory());provider.request_deadline=deadline
                self._update(identity,status="running",phase="user_input_review",message="Reviewing supplied correction against original evidence.")
                # Enrichment is a typed data patch; supplied statements remain attributed inputs.
                hook=getattr(provider,"refine_user_inputs",None)
                if not callable(hook):raise ProviderError("The selected provider cannot review interpretation corrections.",503)
                candidate.revision_id=current.revision_id
                patch=hook(candidate,submitted)
                candidate,patch_changes=apply_enrichment(candidate,patch)
                changes={"changed_ids":list(set(changes.get("changed_ids",[])+patch_changes["changed_ids"])),
                    "transform_updates":changes.get("transform_updates",[])+patch_changes["transform_updates"]}
                candidate=self.store.prepare(candidate)
            self._check(identity,deadline)
            if current.scene:
                self._update(identity,status="running",phase="ifc_generation",message="Applying supplied values to deterministic geometry.")
                self._geometry(candidate)
                failures=regression_findings(current,candidate,changes)
                if failures:
                    path=self.store.save_candidate(candidate,None,failures,config)
                    self._update(identity,status="needs_attention",phase="complete",message="Refined candidate lost usable geometry; submitted inputs and previous revision retained.",attempts=[{"candidate":path,"accepted":False,"findings":failures}]);return
                if current.pages:
                    if provider is None:
                        provider=self._bind_provider(identity,self.provider_factory());provider.request_deadline=deadline
                    previous_review=self._baseline_review(current)
                    context=build_revision_delta(current,candidate,submitted,changes)
                    context["prior_findings"]=[i.model_dump(mode="json")for i in previous_review.issues] if previous_review else []
                    self._update(identity,change_context=context)
                    if context["local_failures"]:
                        path=self.store.save_candidate(candidate,previous_review,context["local_failures"],config)
                        self._update(identity,status="needs_attention",phase="complete",
                            message="Refinement changed unrelated geometry or attribution; previous model and submitted inputs retained.",
                            attempts=[{"candidate":path,"accepted":False,"findings":context["local_failures"]}]);return
                    self._update(identity,phase="checking_revision",message="Checking supplied changes against original sources and regenerated geometry.")
                    review=ReconstructionReview.model_validate(self._review_candidate(identity,provider,candidate,candidate.description,candidate.scene,
                        previous_description=current.description,previous_scene=current.scene,previous_review=previous_review,
                        previous_user_values=current.user_values,change_context=context))
                    self._update(identity,issues=[issue.model_dump() for issue in review.issues])
                    if not review.candidate_supported:
                        path=self.store.save_candidate(candidate,review,"Source review did not support supplied correction.",config)
                        self._update(identity,status="needs_attention",phase="complete",message="Correction remains unresolved; submitted values and previous model retained.",attempts=[{"candidate":path,"accepted":False}]);return
            else:
                candidate.reasoning=build_reasoning(candidate)
            self._check(identity,deadline)
            saved=self._publish(identity,candidate,current.revision_id,status="user_refined",review=review,config=config)
            self._update(identity,status="complete",phase="complete",message="Supplied information saved with user provenance; accepted update published.",revision_id=saved.revision_id)
        except JobStopped:self._update(identity,status="stopped",phase="stopped",message="Refinement stopped; submitted inputs and previous revision retained.")
        except JobBudget:self._update(identity,status="budget_exhausted",phase="complete",message="Refinement budget reached; submitted inputs and previous revision retained.")
        except Exception as error:self._failure(identity,error,provider)
        finally:
            if provider:
                self._update(identity,usage=provider.usage.model_dump() if hasattr(provider,"usage") else {})
                provider.close()
