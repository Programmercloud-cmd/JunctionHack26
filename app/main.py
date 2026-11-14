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
from .provider import create_provider, ProviderError, settings
from .schemas import Answer, AskRequest
from .service import ask
from .bundles import BuildingStore
from .jobs import JobRunner

ROOT = Path(__file__).resolve().parent.parent


class SceneRequest(StrictModel):
    page: int = Field(default=1, ge=1, le=5)


class ReconstructionRequest(StrictModel):
    base_revision_id: str | None = None
    mode: Literal["refine", "reconstruct"] = "refine"


def create_app(*, provider_factory=create_provider, storage_root=None):
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
        try:
            config = settings()
        except ProviderError as error:
            raise HTTPException(error.status, error.message) from None
        return {"status": "ok", "provider_ready": bool(config["api_key"]), "model": config["model"],
                "reconstruction_model": config["reconstruction_model"],
                "provider": config["name"], "provider_label": config["label"],
                "credential_env": config["credential_env"], "gate_kind": config["gate_kind"],
                "decision_model": config["decision_model"], "limits": {"max_upload_mb": 10, "max_ifc_mb": 25, "max_pages": 5}}

    @application.post("/api/documents")
    async def upload(file: UploadFile = File(...)):
        try:
            data = await file.read(MAX_IFC_UPLOAD + 1)
            def save():
                store = application.state.documents
                with store.lock:
                    identity = hashlib.sha256(data).hexdigest()
                    reused = (store.directory(identity) / "CURRENT.json").exists()
                    document = store.add(data, file.filename or "Untitled plan")
                    return {**document.public(), "is_new_upload": not reused}
            return await run_in_threadpool(save)
        except DocumentError as error:
            raise HTTPException(error.status, error.message) from None
        finally:
            await file.close()

    @application.get("/api/documents/{document_id}/pages/{page}")
    def preview(document_id: str, page: int):
        try:
            document = application.state.documents.get(document_id)
            if not 1 <= page <= len(document.pages):
                raise DocumentError("Page not found.", 404)
            return FileResponse(document.pages[page - 1].path, media_type="image/png", headers={"Cache-Control": "no-store"})
        except DocumentError as error:
            raise HTTPException(error.status, error.message) from None

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
            provider = application.state.provider_factory()
            answer = ask(document, request.question, provider)
            latest = application.state.documents.get(document.id)
            answer.building_id = document.id
            answer.answered_revision_id = document.revision_id
            answer.display_revision_id = latest.revision_id
            if latest.revision_id != document.revision_id:
                from .highlights import validated_highlights
                answer.highlight_ids = validated_highlights(answer, latest)
                answer.review_note += " Building updated while answering; highlights were rechecked and original citations retained."
            return answer
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
        provider = None
        acquired = False
        try:
            document = application.state.documents.get(document_id)
            with document.scene_lock:
                if document.scene:
                    return document.scene
                if any(job["kind"] == "reconstruction" and job["status"] in {"queued", "running"}
                       for job in application.state.jobs.for_building(document_id)):
                    raise DocumentError("Background reconstruction is already running; inspect its job progress.", 409)
                if not 1 <= request.page <= len(document.pages):
                    raise DocumentError("Page not found.", 404)
                acquired = application.state.inference_slots.acquire(blocking=False)
                if not acquired:
                    raise DocumentError("Two model requests are already processing. Please retry shortly.", 429)
                from .reconstruction import reconstruct_scene
                provider = application.state.provider_factory()
                candidate = application.state.documents.prepare(document)
                scene = reconstruct_scene(candidate, request.page, provider)
                candidate.scene = scene
                from .reasoning import build_reasoning
                candidate.reasoning = build_reasoning(candidate)
                return application.state.documents.commit(candidate, document.revision_id,
                    status="preview_unreviewed", config={"operation": "legacy_synchronous_reconstruction"}).scene
        except (DocumentError, ProviderError) as error:
            raise HTTPException(error.status, error.message) from None
        finally:
            if acquired:
                application.state.inference_slots.release()
            if provider:
                provider.close()

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

    return application


app = create_app()
