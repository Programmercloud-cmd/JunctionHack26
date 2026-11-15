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
from .documents import DocumentError
from .providers.gemini import ProviderError,configured_number,settings
from .identities import assign_identities,assign_replacement_identities
from .ifc_generate import generate_ifc
from .ifc_artifact import load_artifact
from .reasoning import build_reasoning
from .revisions import apply_patch,apply_enrichment,needs_geometry,regression_findings,description_hash,normalize_views
from .review_schema import ReconstructionReview
from .schemas import ChatQuestionIntent
from .vlm import VLM
from .highlights import validated_highlights
from .conversation import (RECONSTRUCTION_STARTED, RECONSTRUCTION_ALREADY_RUNNING,
                           localize_reconstruction_notice, reconstruction_message)

TERMINAL={"complete","needs_attention","failed","budget_exhausted","stopped","interrupted"}


class JobStopped(Exception):pass
class JobBudget(Exception):pass


class ReconstructionScopeChanged(DocumentError):
    def __init__(self):
        super().__init__("The linked plans have changed. Check the current set of plans and try the 3D reconstruction again.", 409)


def _source_ids(document):
    return sorted(source["source_id"] for source in document.sources)


def pipeline_config():
    config=settings()
    return {"pipeline_version":"progressive-v1","provider":config["name"],"model":config["model"],
        "interpretation_model":config["interpretation_model"],
        "reconstruction_model":config["reconstruction_model"],"decision_model":config["decision_model"],
        "prompt_sha256":hashlib.sha256(BUILDING_PROMPT.encode()).hexdigest(),
        "reconstruction_call_seconds":configured_number("RECONSTRUCTION_CALL_SECONDS",300),
        "reconstruction_max_tokens":configured_number("RECONSTRUCTION_MAX_TOKENS",65536,integer=True),
        "reconstruction_review_seconds":configured_number("RECONSTRUCTION_REVIEW_SECONDS",120),
        "reconstruction_review_tokens":configured_number("RECONSTRUCTION_REVIEW_TOKENS",16384,integer=True),
        "temperature":0,"reconstruction_thinking_level":"high",
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
        with self.lock:
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
            return localize_reconstruction_notice(deepcopy(self.jobs[identity]), "message")

    def for_building(self,building_id):
        with self.lock:
            jobs = [
                localize_reconstruction_notice(deepcopy(job), "message")
                for job in self.jobs.values() if job["building_id"] == building_id
            ]
            return sorted(jobs, key=lambda job: job["created_at"], reverse=True)

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
        with self.lock,self.store.lock:
            document=self.store.get(building_id)
            if document.kind=="ifc" and document.scene and not document.scene.derived:
                raise DocumentError("Genuine IFC uses its supplied records and geometry; it is not reconstructed or rewritten.",422)
            if base_revision_id and base_revision_id!=document.revision_id:
                raise DocumentError("The building revision changed; refresh before starting another review.",409)
            active=self.active.get(building_id)
            if active and self.jobs[active]["status"] not in TERMINAL:
                return self.get(active)
            identity=self._new(document,"reconstruction")
            self.active[building_id]=identity
            self._update(identity,source_ids=_source_ids(document),mode=mode)
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
            self._check_reconstruction_scope(identity, document)
            if source_id in document.source_interpretations:return document
            cached=self.store.cached_interpretation(source_id)
            if cached is None:
                source=self.store.source_document(document,source_id)
                self._update(identity,status="running",phase="extraction_provider",message="Extracting source-linked interpretation; 3D is optional.")
                output=VLM(provider).extract(source)
                self._check(identity,deadline)
                self._update(identity,phase="interpretation_validation",message="Validating and saving source interpretation.")
                cached=normalize_views(BuildingDescription.model_validate(output))
                from .revisions import _validate_all_sources,_provided_fields
                _validate_all_sources(source,cached.model_dump(mode="json"))
                if _provided_fields(cached.model_dump(mode="json")):
                    raise DocumentError("Source extraction cannot invent user-provided provenance.",422)
                self.store.save_interpretation(source_id,cached)
            self._check(identity,deadline)
            with self.store.lock:
                self._check_reconstruction_scope(identity, self.store.get(document.id))
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

    def question(self,request):
        from .conversation import question_context,user_message
        with self.lock,self.store.lock:
            document=self.store.get(request.document_id)
            if request.request_id:
                prior=next((j for j in self.jobs.values() if j["kind"]=="question" and j["building_id"]==document.id and j.get("request_id")==request.request_id),None)
                if prior:return self.get(prior["id"])
            if request.revision_id and request.revision_id!=document.revision_id:
                raise DocumentError("The building updated before this question started; refresh its revision and ask again.",409)
            context=question_context(self.store,document,request)
            identity=self._new(document,"question",request.request_id)
            message=user_message(document,request,identity)
            self.store.append_conversation(document.id,message)
            snapshot=document.snapshot();snapshot.conversation_context=context
            self._update(identity,question=request.question,user_message_id=message["id"],conversation_id=document.id)
            self.futures[identity]=self.executor.submit(self._question,identity,snapshot,request.question,allow_3d=request.allow_3d)
            return self.get(identity)

    def stop(self,identity):
        # Same lock as publication gives stop/publication a defined order.
        with self.lock:
            job=self.get(identity)
            if job["status"] in TERMINAL:return job
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

    def _check_reconstruction_scope(self, identity, document):
        expected = self.jobs[identity].get("source_ids")
        if expected is not None and expected != _source_ids(document):
            raise ReconstructionScopeChanged()

    def _publish(self,identity,candidate,base,*,status,review=None,config=None):
        with self.lock,self.store.lock:
            self._check_reconstruction_scope(identity, self.store.get(candidate.id))
            result=self.store.commit(candidate,base,status=status,review=review,config=config,
                                     job_guard=lambda:self._valid(identity) and monotonic()<self.deadlines.get(identity,float("inf")))
            model_available=bool(result.scene and any(e.geometry for e in result.scene.elements))
            fields={"revision_id":result.revision_id,"revision_number":result.revision_number,"model_available":model_available}
            if status=="preview_reviewing" and model_available:
                fields["preview_geometry_revision_id"]=result.geometry_revision_id
            self._update(identity,**fields)
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
            self._check_reconstruction_scope(identity, self.store.get(current.id))
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
                self._check_reconstruction_scope(identity, self.store.get(current.id))
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
                        review=ReconstructionReview.model_validate(self._review_candidate(identity,provider,candidate,candidate.description,candidate.scene,previous_description=current.description,previous_scene=current.scene))
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
                        review=ReconstructionReview.model_validate(self._review_candidate(identity,provider,candidate,candidate.description,candidate.scene,
                            previous_description=current.description,previous_scene=current.scene))
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
            seen_feedback=set()
            for attempt in range(config["patch_attempts"]+1):
                self._update(identity,issues=[i.model_dump()for i in review.issues])
                actionable=[i for i in review.issues if i.actionable and i.category=="extraction"]
                if not actionable:
                    self._finish_review(identity,current,review,config,
                        "reviewed_issues" if review.issues or not review.candidate_supported else "reviewed_no_action",
                        "Review stopped: remaining uncertainty is visible." if review.issues or not review.candidate_supported else "Review found no further supported correction. This is not a guarantee of accuracy.")
                    return
                if attempt==config["patch_attempts"]:
                    self._update(identity,status="budget_exhausted",phase="complete",message="Configured correction-attempt budget reached; best available revision retained.")
                    return
                fingerprint=json.dumps(sorted((tuple(sorted(i.object_ids)),i.source.page,tuple(i.source.bbox),i.proposed_action)for i in actionable))
                if fingerprint in seen_feedback:
                    self._finish_review(identity,current,review,config,"reviewed_issues","Review repeated without material progress; usable revision retained.")
                    return
                seen_feedback.add(fingerprint)
                self._check(identity,deadline)
                self._update(identity,phase="correcting",message="Applying a targeted source-backed correction.")
                patch=provider.patch_reconstruction(current,current.description,current.scene,review)
                self._check(identity,deadline)
                # Persist structured model output for failed-patch diagnosis, never the provider request.
                self._update(identity,last_proposed_patch=patch.model_dump() if hasattr(patch,"model_dump") else patch)
                candidate,changes=apply_patch(current,patch,review)
                candidate=self.store.prepare(candidate)
                self._geometry(candidate)
                failures=regression_findings(current,candidate,changes)
                if failures:
                    candidate_path=self.store.save_candidate(candidate,review,failures,config)
                    self._update(identity,status="needs_attention",phase="complete",
                        message="Candidate rejected: geometry disappeared or an unchanged frame moved. Previous usable revision retained.",
                        attempts=self.jobs[identity]["attempts"]+[{"candidate":candidate_path,"accepted":False,"findings":failures}])
                    return
                self._check(identity,deadline)
                self._update(identity,phase="checking_revision",message="Checking corrected geometry and possible regressions against the original.")
                candidate_review=ReconstructionReview.model_validate(self._review_candidate(identity,provider,candidate,candidate.description,candidate.scene,
                    previous_description=current.description,previous_scene=current.scene,previous_review=review))
                self._check(identity,deadline)
                if not candidate_review.candidate_supported:
                    path=self.store.save_candidate(candidate,candidate_review,"Source/geometry reviewer did not support the candidate.",config)
                    self._update(identity,status="needs_attention",phase="complete",message="Candidate was not supported by source review; previous usable revision retained.",
                        attempts=self.jobs[identity]["attempts"]+[{"candidate":path,"accepted":False,"review":candidate_review.model_dump()}],
                        candidate_issues=[i.model_dump()for i in candidate_review.issues])
                    return
                current=self._publish(identity,candidate,current.revision_id,status="preview_reviewing",review=candidate_review,config=config)
                self._update(identity,attempts=self.jobs[identity]["attempts"]+[{"revision_id":current.revision_id,"accepted":True,"changes":changes}])
                review=candidate_review
        except JobStopped:
            self._update(identity,status="stopped",phase="stopped",message="Stopped; previous usable revision retained.")
        except JobBudget:
            self._update(identity,status="budget_exhausted",phase="complete",message="Configured processing budget exhausted; this is not an evidence-insufficiency judgment.")
        except ReconstructionScopeChanged as error:
            self._update(identity,status="needs_attention",phase="complete",message=error.message)
        except Exception as error:
            self._failure(identity,error,provider)
        finally:
            if provider:
                self._update(identity,usage=provider.usage.model_dump() if hasattr(provider,"usage") else {})
                provider.close()

    def _check_chat_reconstruction_revision(self, snapshot, target_revision_id, *, allow_ancestor=False):
        if snapshot.revision_id == target_revision_id:
            return
        revisions = {revision["revision_id"]: revision for revision in self.store.history(snapshot.id)}
        target = revisions.get(target_revision_id)
        if target:
            target_is_ancestor = allow_ancestor and target["revision_number"] < snapshot.revision_number
            revision_id, expected_id, expected_number = (
                (snapshot.revision_id, target_revision_id, target["revision_number"]) if target_is_ancestor
                else (target_revision_id, snapshot.revision_id, snapshot.revision_number)
            )
            while revision_id != expected_id:
                revision = revisions.get(revision_id)
                if (not revision or revision["revision_number"] <= expected_number
                        or (not target_is_ancestor and revision["status"] != "interpretation_available")):
                    break
                revision_id = revision["parent_revision_id"]
            if revision_id == expected_id:
                return
        raise DocumentError("The plan group has changed. Check the current plans and try the 3D reconstruction again.", 409)

    def _start_chat_reconstruction(self, identity, snapshot):
        with self.lock,self.store.lock:
            self._check(identity,float("inf"))
            current = self.store.get(snapshot.id)
            source_ids = _source_ids(snapshot)
            if source_ids != _source_ids(current):
                raise ReconstructionScopeChanged()
            active = self.jobs.get(self.active.get(current.id))
            if active and active["status"] not in TERMINAL:
                if (active["kind"] != "reconstruction" or active.get("mode") != "reconstruct"
                        or active.get("source_ids") != source_ids):
                    raise DocumentError("Another 3D job is running for this building. Let it finish or stop it, then ask again.", 409)
                self._check_chat_reconstruction_revision(snapshot, active["base_revision_id"], allow_ancestor=True)
                reconstruction = active
                text = RECONSTRUCTION_ALREADY_RUNNING
            else:
                self._check_chat_reconstruction_revision(snapshot, current.revision_id)
                reconstruction = self.reconstruct(current.id, current.revision_id, mode="reconstruct")
                text = RECONSTRUCTION_STARTED
            reconstruction_id = reconstruction["id"]
            message = reconstruction_message(snapshot, text, reconstruction_id, identity, self.jobs[identity].get("user_message_id"))
            self.store.append_conversation(snapshot.id,message)
            self._update(identity,status="complete",phase="complete",message=text,
                reconstruction_job_id=reconstruction_id,assistant_message_id=message["id"],conversation_id=snapshot.id,
                revision_id=current.revision_id,revision_number=current.revision_number)

    def _question(self,identity,snapshot,question,*,allow_3d=False):
        provider=None
        try:
            self._check(identity,float("inf"))
            provider=self._bind_provider(identity,self.provider_factory())
            def progress(phase):
                self._check(identity,float("inf"))
                self._update(identity,status="running",phase=phase,message=phase)
            answer=VLM(provider).answer(snapshot,question,progress=progress,allow_3d=allow_3d)
            self._check(identity,float("inf"))
            if isinstance(answer, ChatQuestionIntent):
                self._start_chat_reconstruction(identity, snapshot)
                return
            from .voice_format import with_spoken_answers
            answer=with_spoken_answers(answer,question)
            displayed=self.store.get(snapshot.id)
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
                    self._update(identity,phase="checking_revision",message="Checking supplied changes against original sources and regenerated geometry.")
                    review=ReconstructionReview.model_validate(self._review_candidate(identity,provider,candidate,candidate.description,candidate.scene,previous_description=current.description,previous_scene=current.scene))
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
