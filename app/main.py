from contextlib import asynccontextmanager
from pathlib import Path
import threading
import hashlib
import os
from typing import Literal

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from .documents import DocumentError, DocumentStore, MAX_UPLOAD, MAX_IFC_UPLOAD
from .scene import Scene
from .schemas import StrictModel
from pydantic import Field
from .providers.gemini import create_provider, ProviderError, settings
from .schemas import Answer, AskRequest
from .vlm import VLM
from .bundles import BuildingStore
from .jobs import JobRunner
from .user_inputs import RefinementRequest, assumptions
from .conversation import question_context, user_message, assistant_message, localize_reconstruction_notice

ROOT = Path(__file__).resolve().parent.parent


class SceneRequest(StrictModel):
    page: int = Field(default=1, ge=1)


class ReconstructionRequest(StrictModel):
    base_revision_id: str | None = None
    mode: Literal["refine", "reconstruct"] = "refine"


class ExtractionRequest(StrictModel):
    source_ids: list[str] | None = None
    retry: bool = True


def create_app(*, provider_factory=create_provider, storage_root=None,
               transcription_factory=None, speech_factory=None):
    @asynccontextmanager
    async def lifespan(application):
        application.state.documents = BuildingStore(Path(storage_root or os.getenv("BLUEPRINT_STORAGE_ROOT") or ROOT / ".runtime"))
        application.state.jobs = JobRunner(application.state.documents, application.state.provider_factory)
        yield
        application.state.jobs.close()
        application.state.documents.close()

    application = FastAPI(title="Blueprint QA", lifespan=lifespan)
    application.state.provider_factory = provider_factory
    application.state.inference_slots = threading.BoundedSemaphore(2)
    application.mount("/static", StaticFiles(directory=ROOT / "app" / "static", check_dir=False), name="static")

    @application.get("/")
    def index():
        return FileResponse(ROOT / "app" / "static" / "index.html")

    @application.get("/api/health")
    def health():
        config = settings()
        return {"status": "ok", "provider_ready": bool(config["api_key"]), "model": config["model"],
                "interpretation_model": config["interpretation_model"], "clarification_model": config["clarification_model"],
                "reconstruction_model": config["reconstruction_model"],
                "provider": config["name"], "provider_label": config["label"],
                "credential_env": config["credential_env"], "gate_kind": config["gate_kind"],
                "decision_model": config["decision_model"], "limits": {"max_upload_mb": 10, "max_ifc_mb": 25, "max_pages": 5}}

    async def save_uploads(uploads,building_id=None):
        if not uploads:raise HTTPException(422,"Choose at least one source file.")
        try:
            payloads=[(await upload.read(MAX_IFC_UPLOAD+1),upload.filename or "Untitled source") for upload in uploads]
            def save():
                store=application.state.documents
                initial_id=building_id or hashlib.sha256(payloads[0][0]).hexdigest()
                with store.lock:
                    existed=(store.directory(initial_id)/"CURRENT.json").exists()
                    previous=store.get(initial_id) if existed else None
                    previous_sources={source["source_id"] for source in previous.sources} if previous else set()
                    document=store.add_many(payloads,building_id=building_id)
                    new_ids=[source["source_id"] for source in document.sources if source["source_id"] not in previous_sources]
                extraction_jobs=application.state.jobs.extract(document.id,new_ids,retry=False) if new_ids and document.interpretation_status!="complete" else []
                return {**document.public(),"is_new_upload":not existed,"added_source_ids":new_ids,"extraction_jobs":extraction_jobs}
            return await run_in_threadpool(save)
        except DocumentError as error:raise HTTPException(error.status,error.message) from None
        finally:
            for upload in uploads:await upload.close()

    @application.post("/api/documents")
    async def upload(file: UploadFile | None = File(None), files: list[UploadFile] | None = File(None)):
        return await save_uploads(([file] if file else [])+(files or []))

    @application.post("/api/buildings/{building_id}/sources")
    async def add_sources(building_id: str,file: UploadFile | None = File(None),files: list[UploadFile] | None = File(None)):
        return await save_uploads(([file] if file else [])+(files or []),building_id)

    @application.get("/api/documents/{document_id}/pages/{page}")
    def preview(document_id: str, page: int):
        try:
            document = application.state.documents.get(document_id)
            selected=next((p for p in document.pages if p.number==page),None)
            if selected is None:
                raise DocumentError("Page not found.", 404)
            return FileResponse(selected.path, media_type="image/png", headers={"Cache-Control": "no-store"})
        except DocumentError as error:
            raise HTTPException(error.status, error.message) from None

    @application.get("/api/buildings/{building_id}/revisions/{revision_id}/pages/{page}")
    def revision_page(building_id: str,revision_id: str,page: int):
        try:
            document=application.state.documents.revision(building_id,revision_id)
            selected=next((p for p in document.pages if p.number==page),None)
            if selected is None:raise DocumentError("Page not present in this answered revision.",404)
            return FileResponse(selected.path,media_type="image/png",headers={"Cache-Control":"no-store"})
        except DocumentError as error:raise HTTPException(error.status,error.message) from None

    @application.get("/api/buildings/{building_id}/sources/{source_id}/original")
    def original_source(building_id: str,source_id: str):
        try:
            document=application.state.documents.get(building_id)
            if source_id not in document.source_files:raise DocumentError("Original source not found.",404)
            return Response(document.source_files[source_id],media_type="application/octet-stream",
                headers={"Content-Disposition":"attachment; filename=original-source","Cache-Control":"no-store"})
        except DocumentError as error:raise HTTPException(error.status,error.message) from None

    @application.post("/api/buildings/{building_id}/extraction",status_code=202)
    def extraction_job(building_id: str,request: ExtractionRequest):
        try:return {"jobs":application.state.jobs.extract(building_id,request.source_ids,retry=request.retry)}
        except (DocumentError,ProviderError) as error:raise HTTPException(error.status,error.message) from None

    @application.get("/api/buildings/{building_id}/conversation")
    def conversation(building_id: str):
        try:
            application.state.documents.get(building_id)
            messages = application.state.documents.conversation(building_id)
            return {"conversation_id": building_id, "messages": [
                localize_reconstruction_notice(message, "text") for message in messages
            ]}
        except DocumentError as error:raise HTTPException(error.status,error.message) from None

    @application.get("/api/buildings/{building_id}/assumptions")
    def assumption_rows(building_id: str):
        try:return assumptions(application.state.documents.get(building_id))
        except DocumentError as error:raise HTTPException(error.status,error.message) from None

    @application.post("/api/buildings/{building_id}/refinements",status_code=202)
    def refinement_job(building_id: str,request: RefinementRequest):
        try:return application.state.jobs.refine_inputs(building_id,request)
        except (DocumentError,ProviderError) as error:raise HTTPException(error.status,error.message) from None

    @application.get("/api/buildings")
    def buildings():
        store = application.state.documents
        return {"buildings": [store.get(item["building_id"]).public() for item in store.list()]}

    @application.get("/api/buildings/{building_id}")
    def building(building_id: str):
        try:
            document = application.state.documents.get(building_id)
            return {**document.public(), "jobs": application.state.jobs.for_building(building_id)}
        except DocumentError as error:
            raise HTTPException(error.status, error.message) from None

    @application.post("/api/buildings/{building_id}/reconstruction", status_code=202)
    def reconstruction_job(building_id: str, request: ReconstructionRequest):
        try:
            return application.state.jobs.reconstruct(building_id, request.base_revision_id, request.mode)
        except (DocumentError, ProviderError) as error:
            raise HTTPException(error.status, error.message) from None

    @application.get("/api/buildings/{building_id}/revisions/{revision_id}/evidence/{object_id}")
    def native_evidence(building_id: str, revision_id: str, object_id: str):
        try:
            document = application.state.documents.revision(building_id, revision_id)
            if document.kind != "ifc" or not document.scene or document.scene.derived:
                raise DocumentError("This building uses original drawing evidence, not native IFC factual records.", 422)
            from .reasoning import ensure_reasoning
            context = ensure_reasoning(document)
            record = next((r for r in context["objects"] if r["id"] == object_id), None)
            if record is None:
                raise DocumentError("Original IFC record not found in the answered revision.", 404)
            return {"building_id": building_id, "revision_id": revision_id, "source_kind": "ifc",
                    "record": record, "coverage": context["coverage"]}
        except DocumentError as error:
            raise HTTPException(error.status, error.message) from None

    @application.get("/api/jobs/{job_id}")
    def job(job_id: str):
        try:
            return application.state.jobs.get(job_id)
        except DocumentError as error:
            raise HTTPException(error.status, error.message) from None

    @application.post("/api/jobs/{job_id}/stop")
    def stop_job(job_id: str):
        try:
            return application.state.jobs.stop(job_id)
        except DocumentError as error:
            raise HTTPException(error.status, error.message) from None

    @application.post("/api/questions", status_code=202)
    def question_job(request: AskRequest):
        try:
            return application.state.jobs.question(request)
        except (DocumentError, ProviderError) as error:
            raise HTTPException(error.status, error.message) from None

    @application.post("/api/ask", response_model=Answer)
    def question(request: AskRequest):
        provider = None
        if not application.state.inference_slots.acquire(blocking=False):
            raise HTTPException(429, "Two questions are already processing. Please wait and retry.")
        try:
            document = application.state.documents.get(request.document_id).snapshot()
            if request.revision_id and request.revision_id != document.revision_id:
                raise DocumentError("The building revision changed; refresh before asking.", 409)
            document.conversation_context=question_context(application.state.documents,document,request)
            message=user_message(document,request)
            application.state.documents.append_conversation(document.id,message)
            provider = application.state.provider_factory()
            answer = VLM(provider).answer(document, request.question)
            latest = application.state.documents.get(document.id)
            answer.building_id = document.id
            answer.answered_revision_id = document.revision_id
            answer.display_revision_id = latest.revision_id
            if latest.revision_id != document.revision_id:
                from .highlights import validated_highlights
                answer.highlight_ids = validated_highlights(answer, latest)
                answer.review_note += " Building updated while answering; highlights were rechecked and original citations retained."
            application.state.documents.append_conversation(document.id,assistant_message(document,answer,reply_to=message["id"]))
            from .voice_format import with_spoken_answers
            return with_spoken_answers(answer, request.question)
        except (DocumentError, ProviderError) as error:
            raise HTTPException(error.status, error.message) from None
        finally:
            application.state.inference_slots.release()
            if provider is not None:
                provider.close()

    @application.get("/api/documents/{document_id}/scene", response_model=Scene)
    def get_scene(document_id: str):
        try:
            document = application.state.documents.get(document_id)
            if not document.scene:
                raise DocumentError("No model yet. Generate a building model from the original drawing pages.", 404)
            return document.scene
        except DocumentError as error:
            raise HTTPException(error.status, error.message) from None

    @application.post("/api/documents/{document_id}/scene", response_model=Scene)
    def generate_scene(document_id: str, request: SceneRequest):
        try:
            document=application.state.documents.get(document_id)
            if document.scene:return document.scene
            if request.page not in {p.number for p in document.pages}:raise DocumentError("Page not found.",404)
            job=application.state.jobs.reconstruct(document_id,document.revision_id,"reconstruct")
            application.state.jobs.futures[job["id"]].result()
            saved=application.state.documents.get(document_id)
            if saved.scene:return saved.scene
            result=application.state.jobs.get(job["id"])
            raise DocumentError(result["message"],502 if result["status"]=="failed" else 422)
        except (DocumentError,ProviderError) as error:raise HTTPException(error.status,error.message) from None

    @application.get("/api/documents/{document_id}/model.ifc")
    def download_model(document_id: str):
        try:
            document = application.state.documents.get(document_id)
            if not document.ifc_bytes:
                raise DocumentError("Generate the drawing-derived IFC first.", 404)
            return Response(document.ifc_bytes, media_type="application/x-step",
                            headers={"Content-Disposition": 'attachment; filename="blueprint-derived.ifc"',
                                     "Cache-Control": "no-store"})
        except DocumentError as error:
            raise HTTPException(error.status, error.message) from None

    from .voice import attach_voice_routes
    attach_voice_routes(application, transcription_factory=transcription_factory, speech_factory=speech_factory)
    return application


app = create_app()
