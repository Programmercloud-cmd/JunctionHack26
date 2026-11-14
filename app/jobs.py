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
from .provider import ProviderError,configured_number,settings
from .identities import assign_identities,assign_replacement_identities
from .ifc_generate import generate_ifc
from .ifc_artifact import load_artifact
from .reasoning import build_reasoning
from .revisions import apply_patch,regression_findings,description_hash,normalize_views
from .review_schema import ReconstructionReview
from .service import ask
from .highlights import validated_highlights

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
        self.lock=threading.RLock();self.jobs={};self.events={};self.futures={};self.active={};self.deadlines={};self.closing=False
        for building in store.list():
            for job in store.saved_jobs(building["building_id"]):self.jobs[job["id"]]=job

    def close(self):
        self.closing=True
        for identity,job in list(self.jobs.items()):
            if job["status"] not in TERMINAL:
                self.events.get(identity,threading.Event()).set()
                self._update(identity,status="interrupted",phase="interrupted",message="Application stopped; usable revision retained.")
        self.executor.shutdown(wait=False,cancel_futures=True)

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

    def question(self,request):
        document=self.store.get(request.document_id)
        if request.revision_id and request.revision_id!=document.revision_id:
            raise DocumentError("The building updated before this question started; refresh its revision and ask again.",409)
        with self.lock:
            identity=self._new(document,"question",request.request_id)
            self.jobs[identity]["question"]=request.question
            self.futures[identity]=self.executor.submit(self._question,identity,document.snapshot(),request.question)
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
            job["kind"]!="reconstruction" or self.active.get(job["building_id"])==identity)

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
        candidate.ifc_bytes=generate_ifc(candidate.description,candidate)
        candidate.scene=load_artifact(candidate.ifc_bytes,candidate.id)[0]
        candidate.reasoning=build_reasoning(candidate)

    def _finish_review(self,identity,current,review,config,status,message):
        updated=self.store.prepare(current)
        current=self._publish(identity,updated,current.revision_id,status=status,review=review,config=config)
        self._update(identity,status="complete" if status=="reviewed_no_action" else "needs_attention",
            phase="complete",message=message,issues=[i.model_dump()for i in review.issues])

    def _reconstruct(self,identity,current,mode):
        provider=None
        try:
            config=pipeline_config();deadline=monotonic()+config["job_seconds"]
            self.deadlines[identity]=deadline
            self._check(identity,deadline)
            provider=self.provider_factory();provider.request_deadline=deadline
            review=None
            self._update(identity,status="running",phase="describing" if not current.scene or mode=="reconstruct" else "reviewing",
                         message="Describing original source." if not current.scene else "Reviewing original source and generated geometry.",config=config)
            if not current.scene or mode=="reconstruct":
                output=provider.reconstruct(current)
                self._check(identity,deadline)
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
                    review=ReconstructionReview.model_validate(provider.review_reconstruction(candidate,candidate.description,candidate.scene,
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
                review=ReconstructionReview.model_validate(provider.review_reconstruction(current,current.description,current.scene))
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
                candidate_review=ReconstructionReview.model_validate(provider.review_reconstruction(candidate,candidate.description,candidate.scene,
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
        except Exception as error:
            safe=error.message if isinstance(error,(DocumentError,ProviderError)) else "Source processing failed operationally. Previous usable revision retained; no evidence-quality conclusion was made."
            exhausted=monotonic()>=self.deadlines.get(identity,float("inf"))
            self._update(identity,status="budget_exhausted" if exhausted else "failed",phase="complete" if exhausted else "failed",
                         message="Configured processing budget exhausted; usable revision retained." if exhausted else safe)
        finally:
            if provider:
                self._update(identity,usage=provider.usage.model_dump() if hasattr(provider,"usage") else {})
                provider.close()

    def _question(self,identity,snapshot,question):
        provider=None
        try:
            self._check(identity,float("inf"))
            provider=self.provider_factory()
            def progress(phase):
                self._check(identity,float("inf"))
                self._update(identity,status="running",phase=phase,message=phase)
            answer=ask(snapshot,question,provider,progress=progress)
            self._check(identity,float("inf"))
            displayed=self.store.get(snapshot.id)
            answer.building_id=snapshot.id;answer.answered_revision_id=snapshot.revision_id
            answer.display_revision_id=displayed.revision_id
            if displayed.revision_id!=snapshot.revision_id:
                previous=list(answer.highlight_ids)
                answer.highlight_ids=validated_highlights(answer,displayed)
                if previous!=answer.highlight_ids:
                    answer.review_note += " Model updated while answering; unavailable object highlights were omitted. Original source citations remain available."
            self._update(identity,status="complete",phase="complete",message="Answer checked against supplied evidence.",answer=answer.model_dump(),
                         revision_id=displayed.revision_id,revision_number=displayed.revision_number)
        except JobStopped:
            self._update(identity,status="stopped",phase="stopped",message="Question stopped; unpublished draft discarded.")
        except Exception as error:
            safe=error.message if isinstance(error,(ProviderError,DocumentError)) else "Question processing failed operationally; no evidence conclusion was made."
            self._update(identity,status="failed",phase="failed",message=safe)
        finally:
            if provider:provider.close()
