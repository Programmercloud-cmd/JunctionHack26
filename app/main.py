from contextlib import asynccontextmanager
from pathlib import Path
import threading

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

ROOT = Path(__file__).resolve().parent.parent


class SceneRequest(StrictModel):
    page: int = Field(default=1, ge=1, le=5)


def create_app(*, provider_factory=create_provider, storage_root=None):
    @asynccontextmanager
    async def lifespan(application):
        application.state.documents = DocumentStore(Path(storage_root or ROOT / ".runtime"))
        yield
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
            document = await run_in_threadpool(application.state.documents.add, data, file.filename or "Untitled plan")
            return document.public()
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

    @application.post("/api/ask", response_model=Answer)
    def question(request: AskRequest):
        provider = None
        if not application.state.inference_slots.acquire(blocking=False):
            raise HTTPException(429, "Two questions are already processing. Please wait and retry.")
        try:
            document = application.state.documents.get(request.document_id)
            provider = application.state.provider_factory()
            return ask(document, request.question, provider)
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
                if not 1 <= request.page <= len(document.pages):
                    raise DocumentError("Page not found.", 404)
                acquired = application.state.inference_slots.acquire(blocking=False)
                if not acquired:
                    raise DocumentError("Two model requests are already processing. Please retry shortly.", 429)
                from .reconstruction import reconstruct_scene
                provider = application.state.provider_factory()
                scene = reconstruct_scene(document, request.page, provider)
                document.scene = scene
                return scene
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
