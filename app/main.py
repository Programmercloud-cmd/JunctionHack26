from contextlib import asynccontextmanager
from pathlib import Path
from copy import deepcopy
import threading
import hashlib
import os
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, Request
from fastapi.responses import FileResponse, Response, JSONResponse
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
from .projects import ProjectStore, ProjectName
from .project_chats import ProjectChats
from . import native_picker
from .jobs import JobRunner
from .public_access import PublicAccess
from .user_inputs import RefinementRequest, assumptions
from .conversation import question_context, user_message, assistant_message
from .chat_actions import ChatActionRequest, chat_actions
from .agent_chat import AgentChatRequest, agent_chat
from .annotations import AnnotationRequest, AnnotationStateRequest, list_annotations, save_annotation, selected_annotations, change_annotations

ROOT = Path(__file__).resolve().parent.parent


class AccessRequest(StrictModel):
    code: str


class NewProjectChat(ProjectName):
    name: str = "New chat"
    building_id: str | None = None


class NewScopedChat(ProjectName):
    name: str = "New chat"


class SceneRequest(StrictModel):
    page: int = Field(default=1, ge=1)


class ReconstructionRequest(StrictModel):
    base_revision_id: str | None = None
    mode: Literal["refine", "reconstruct"] = "refine"


class ExtractionRequest(StrictModel):
    source_ids: list[str] | None = None
    retry: bool = True


class RenderRequest(StrictModel):
    base_revision_id: str
    message: str = Field(default="Generate the interactive building model.", min_length=1, max_length=2000)
    annotation_ids: list[str] = Field(default_factory=list)


class TaskOriginRequest(StrictModel):
    project_id: str
    session_id: str | None = None
    request_id: str | None = None
    message_id: str | None = None


def create_app(*, provider_factory=create_provider, storage_root=None,
               transcription_factory=None, speech_factory=None):
    access=PublicAccess.from_environment()
    @asynccontextmanager
    async def lifespan(application):
        application.state.documents = BuildingStore(Path(storage_root or os.getenv("BLUEPRINT_STORAGE_ROOT") or ROOT / ".runtime"))
        application.state.projects = ProjectStore(application.state.documents)
        application.state.project_chats = ProjectChats(application.state.documents, application.state.projects)
        access.validate_store(application.state.documents)
        application.state.jobs = JobRunner(application.state.documents, application.state.provider_factory,
                                           debug_answers=not access.enabled)
        yield
        application.state.jobs.close()
        application.state.documents.close()

    application = FastAPI(title="Concrete", lifespan=lifespan)
    application.state.access=access
    application.state.provider_factory = provider_factory
    application.state.inference_slots = threading.BoundedSemaphore(2)
    application.mount("/static", StaticFiles(directory=ROOT / "app" / "static", check_dir=False), name="static")

    @application.middleware("http")
    async def public_demo_access(http_request,call_next):
        try:access.authorize_http(http_request)
        except HTTPException as error:
            return JSONResponse({"detail":error.detail},status_code=error.status_code,headers={"Cache-Control":"no-store"})
        response=await call_next(http_request)
        if access.enabled and http_request.url.path.startswith("/api/"):
            response.headers["Cache-Control"]="no-store"
        return response

    @application.get("/api/access")
    def access_status(http_request:Request):return access.status(http_request)

    @application.post("/api/access/unlock")
    def unlock_access(http_request:Request,request:AccessRequest):return access.unlock(http_request,request.code)

    @application.post("/api/access/lock")
    def lock_access(http_request:Request):return access.lock(http_request)

    def selected_document(http_request,identity,revision=None):
        return access.document(application.state.documents,http_request,identity,revision)

    def require_single_file_chat(document):
        if len(document.sources) > 1:
            raise DocumentError("This saved bundle contains multiple files. Chat is available for single-file entries.", 409)

    def pinned_question(http_request,request):
        if access.enabled and request.document_id in access.examples:
            document=access.question_document(application.state.documents,http_request,request.document_id,request.revision_id)
            require_single_file_chat(document)
            return request.model_copy(update={"revision_id":document.revision_id}),document
        document = application.state.documents.get(request.document_id)
        require_single_file_chat(document)
        return request, None

    @application.get("/")
    def index():
        return FileResponse(ROOT / "app" / "static" / "index.html")

    @application.get("/api/health")
    def health(http_request: Request):
        try:
            config = settings()
        except ProviderError as error:
            raise HTTPException(error.status, error.message) from None
        return {"status": "ok", "project_deletion_ready": True, "building_scopes_ready": True, "native_file_picker": native_picker_allowed(http_request) and native_picker.available(), "provider_ready": bool(config["api_key"]), "model": config["model"],
                "interpretation_model": config["interpretation_model"], "clarification_model": config["clarification_model"],
                "basic_model": config["basic_model"], "advanced_model": config["advanced_model"],
                "router_model": config["router_model"], "ui_model": config["ui_model"],
                "render_model": config["render_model"], "chat_gate_kind": "answer_time",
                "reconstruction_model": config["reconstruction_model"],
                "provider": config["name"], "provider_label": config["label"],
                "credential_env": config["credential_env"], "gate_kind": config["gate_kind"],
                "decision_model": config["decision_model"], "limits": {"max_upload_mb": 10, "max_ifc_mb": 25, "max_pages": 5}}

    @application.post("/api/chat/actions")
    def resolve_chat_actions(request: ChatActionRequest,http_request:Request):
        try:
            if not request.document_id:
                raise DocumentError("Open a file from Home to use chat.", 422)
            require_single_file_chat(selected_document(http_request, request.document_id, request.revision_id))
            if request.workspace.geometry_revision_id:
                require_single_file_chat(selected_document(http_request, request.document_id, request.workspace.geometry_revision_id))
            result=chat_actions(application.state.documents, application.state.jobs,
                application.state.provider_factory, request, file_only=True)
            if request.document_id and any(action["type"] in {"refine","reconstruct","retry_extraction","attach_sources"}
                                           for action in result.get("actions",[])):
                access.require_editable(http_request,request.document_id)
            return result
        except (DocumentError, ProviderError) as error:
            raise HTTPException(error.status, error.message) from None

    @application.post("/api/chat")
    def chat(request: AgentChatRequest, http_request: Request):
        try:
            access.require_editor(http_request)
            if not request.project_id or not request.session_id:
                raise DocumentError("Open a Building chat before sending. Refresh an older page to load Building chats.", 422)
            project = selected_project(http_request, request.project_id)
            session = application.state.project_chats.validate_context(project, request.session_id, request.document_id)
            document = selected_document(http_request, request.document_id, request.revision_id) if request.document_id else None
            if request.workspace.geometry_revision_id:
                if document is None:
                    raise DocumentError("A model view requires an open building.", 422)
                selected_document(http_request, document.id, request.workspace.geometry_revision_id)
            annotations = selected_annotations(application.state.documents, document, request.annotation_ids,
                                               geometry_revision_id=request.workspace.geometry_revision_id)
            def authorize_tool(tool):
                if tool in {"render","refine"}:
                    if document is None:
                        raise DocumentError("Open a blueprint before generating its model.", 422)
                    try:
                        access.require_editable(http_request, document.id)
                    except HTTPException as error:
                        # Keep access denials in the coordinator's known-error path;
                        # they are not upstream provider failures to retry.
                        raise DocumentError(error.detail, error.status_code) from None
            def remember_chat(document,submission,result):
                user_id=application.state.project_chats.append(
                    selected_project(http_request,project['id']),session['id'],document,submission,result)
                if result.get('job'):
                    result['job']=application.state.jobs.set_origin(result['job']['id'],{
                        'project_id':project['id'],'session_id':session['id'],
                        'request_id':submission.request_id,'message_id':user_id},message=submission.message)
            return agent_chat(application.state.documents, application.state.jobs,
                application.state.provider_factory, request, document=document, annotations=annotations,
                authorize_tool=authorize_tool,
                session=session,
                remember=remember_chat,
                pin_display=access.enabled and request.document_id in access.examples)
        except (DocumentError, ProviderError) as error:
            raise HTTPException(error.status, error.message) from None

    @application.get("/api/buildings/{building_id}/annotations")
    def annotations(building_id: str, http_request: Request):
        try:
            access.require_editor(http_request)
            selected_document(http_request, building_id)
            return {"annotations": list_annotations(application.state.documents, building_id)}
        except DocumentError as error:
            raise HTTPException(error.status, error.message) from None

    @application.post("/api/buildings/{building_id}/annotations")
    def annotate(building_id: str, request: AnnotationRequest, http_request: Request):
        try:
            access.require_editable(http_request, building_id)
            return save_annotation(application.state.documents, building_id, request)
        except DocumentError as error:
            raise HTTPException(error.status, error.message) from None

    @application.patch("/api/buildings/{building_id}/annotations")
    def edit_annotations(building_id: str, request: AnnotationStateRequest, http_request: Request):
        try:
            access.require_editable(http_request, building_id)
            return change_annotations(application.state.documents, building_id, request)
        except DocumentError as error:
            raise HTTPException(error.status, error.message) from None

    @application.post("/api/buildings/{building_id}/render", status_code=202)
    def render_model(building_id: str, request: RenderRequest, http_request: Request):
        try:
            access.require_editable(http_request, building_id)
            selected_document(http_request, building_id, request.base_revision_id)
            return application.state.jobs.render(building_id, request.base_revision_id, request.message,
                                                  annotation_ids=request.annotation_ids)
        except (DocumentError, ProviderError) as error:
            raise HTTPException(error.status, error.message) from None

    def local_paths_enabled(request):
        return not access.enabled and request.url.hostname in {"127.0.0.1", "localhost", "::1", "testserver"}

    picker_lock = threading.Lock()

    def native_picker_allowed(request):
        return local_paths_enabled(request) and request.client is not None and request.client.host in {
            "127.0.0.1", "::1", "testclient",
        }

    def save_file(http_request, payload, filename, original_path=None, *, require_path=False):
        access.require_uploadable(http_request, [(payload, filename)])
        store = application.state.documents
        identity = hashlib.sha256(payload).hexdigest()
        path_error = False
        with store.lock:
            existed = (store.directory(identity) / "CURRENT.json").exists()
            previous = store.get(identity) if existed else None
            previous_sources = {source["source_id"] for source in previous.sources} if previous else set()
            document = store.add(payload, filename)
            if original_path and local_paths_enabled(http_request):
                try:
                    store.link_original_path(document.id, original_path)
                except (DocumentError, OSError):
                    path_error = True
            new_ids = [source["source_id"] for source in document.sources if source["source_id"] not in previous_sources]
        jobs = application.state.jobs.extract(document.id, new_ids, retry=False) if new_ids and document.interpretation_status != "complete" else []
        if require_path and path_error:
            raise DocumentError("The file was saved, but its original path could not be verified.", 422)
        return {**document.public(), "is_new_upload": not existed, "added_source_ids": new_ids, "extraction_jobs": jobs}

    @application.post("/api/documents/native-picker")
    def upload_from_native_picker(http_request: Request):
        if not native_picker_allowed(http_request) or not native_picker.available():
            raise HTTPException(404, "Desktop file picker unavailable.")
        if http_request.headers.get("origin") != str(http_request.base_url).rstrip("/"):
            raise HTTPException(403, "Open the file picker from Concrete.")
        if not picker_lock.acquire(blocking=False):
            raise HTTPException(409, "The desktop file picker is already open.")
        try:
            path = native_picker.pick_file()
            if path is None:
                return {"cancelled": True}
            path = path.resolve(strict=True)
            with path.open("rb") as stream:
                payload = stream.read(MAX_IFC_UPLOAD + 1)
            return save_file(http_request, payload, path.name, str(path), require_path=True)
        except DocumentError as error:
            raise HTTPException(error.status, error.message) from None
        except OSError:
            raise HTTPException(422, "The selected file could not be read.") from None
        finally:
            picker_lock.release()

    @application.post("/api/documents")
    async def upload(
        http_request: Request, file: UploadFile | None = File(None),
        files: list[UploadFile] | None = File(None),
        original_path: str | None = Form(None, max_length=4096),
    ):
        uploads = ([file] if file else []) + (files or [])
        try:
            if not uploads:raise HTTPException(422,"Choose at least one source file.")
            if len(uploads)>1:
                return await save_group(http_request, uploads)
            item = uploads[0]
            payload = await item.read(MAX_IFC_UPLOAD + 1)
            return await run_in_threadpool(save_file, http_request, payload, item.filename or "Untitled source", original_path)
        except DocumentError as error:
            raise HTTPException(error.status, error.message) from None
        finally:
            for item in uploads:
                await item.close()

    async def save_group(http_request, uploads, building_id=None):
        payloads=[(await upload.read(MAX_IFC_UPLOAD+1),upload.filename or "Untitled source") for upload in uploads]
        access.require_uploadable(http_request,payloads)
        if building_id:access.require_editable(http_request,building_id)
        def save():
            store=application.state.documents
            with store.lock:
                identity=building_id or hashlib.sha256(payloads[0][0]).hexdigest()
                existed=(store.directory(identity)/"CURRENT.json").exists()
                before=store.get(identity) if existed else None
                application.state.projects.require_exclusive_upload(identity)
                previous={source["source_id"] for source in before.sources} if before else set()
                document=store.add_many(payloads,building_id=building_id)
                new_ids=[source["source_id"] for source in document.sources if source["source_id"] not in previous]
            jobs=application.state.jobs.extract(document.id,new_ids,retry=False) if new_ids and document.interpretation_status!="complete" else []
            return {**document.public(),"is_new_upload":not existed,"added_source_ids":new_ids,"extraction_jobs":jobs}
        return await run_in_threadpool(save)

    @application.post("/api/buildings/{building_id}/sources")
    async def add_sources(building_id: str,http_request:Request,file: UploadFile | None = File(None),files: list[UploadFile] | None = File(None)):
        uploads=([file] if file else [])+(files or [])
        try:
            access.require_editable(http_request, building_id)
            if not uploads:raise HTTPException(422,"Choose at least one source file.")
            return await save_group(http_request,uploads,building_id)
        except DocumentError as error:raise HTTPException(error.status,error.message) from None
        finally:
            for upload in uploads:
                await upload.close()

    @application.get("/api/documents/{document_id}/pages/{page}")
    def preview(document_id: str, page: int,http_request:Request):
        try:
            document = selected_document(http_request,document_id)
            selected=next((p for p in document.pages if p.number==page),None)
            if selected is None:
                raise DocumentError("Page not found.", 404)
            return FileResponse(selected.path, media_type="image/png", headers={"Cache-Control": "no-store"})
        except DocumentError as error:
            raise HTTPException(error.status, error.message) from None

    @application.get("/api/buildings/{building_id}/revisions/{revision_id}/pages/{page}")
    def revision_page(building_id: str,revision_id: str,page: int,http_request:Request):
        try:
            document=selected_document(http_request,building_id,revision_id)
            selected=next((p for p in document.pages if p.number==page),None)
            if selected is None:raise DocumentError("Page not present in this answered revision.",404)
            return FileResponse(selected.path,media_type="image/png",headers={"Cache-Control":"no-store"})
        except DocumentError as error:raise HTTPException(error.status,error.message) from None

    @application.get("/api/buildings/{building_id}/sources/{source_id}/original")
    def original_source(building_id: str,source_id: str,http_request:Request):
        try:
            document=selected_document(http_request,building_id)
            if source_id not in document.source_files:raise DocumentError("Original source not found.",404)
            return Response(document.source_files[source_id],media_type="application/octet-stream",
                headers={"Content-Disposition":"attachment; filename=original-source","Cache-Control":"no-store"})
        except DocumentError as error:raise HTTPException(error.status,error.message) from None

    @application.post("/api/buildings/{building_id}/extraction",status_code=202)
    def extraction_job(building_id: str,request: ExtractionRequest,http_request:Request):
        access.require_editable(http_request,building_id)
        try:return {"jobs":application.state.jobs.extract(building_id,request.source_ids,retry=request.retry)}
        except (DocumentError,ProviderError) as error:raise HTTPException(error.status,error.message) from None

    @application.get("/api/buildings/{building_id}/conversation")
    def conversation(building_id: str):
        try:
            application.state.documents.get(building_id)
            return {"conversation_id":building_id,"messages":application.state.documents.conversation(building_id)}
        except DocumentError as error:raise HTTPException(error.status,error.message) from None

    @application.get("/api/buildings/{building_id}/assumptions")
    def assumption_rows(building_id: str,http_request:Request):
        try:return assumptions(selected_document(http_request,building_id))
        except DocumentError as error:raise HTTPException(error.status,error.message) from None

    @application.post("/api/buildings/{building_id}/refinements",status_code=202)
    def refinement_job(building_id: str,request: RefinementRequest,http_request:Request):
        access.require_editable(http_request,building_id)
        try:return application.state.jobs.refine_inputs(building_id,request)
        except (DocumentError,ProviderError) as error:raise HTTPException(error.status,error.message) from None

    @application.get("/api/buildings")
    def buildings(http_request:Request):
        store = application.state.documents
        writable=access.is_editor(http_request)
        # Capture bundles and their owner memberships in one store snapshot.
        # Fetch runner-owned jobs after releasing this lock.
        with store.lock:
            if access.enabled:
                examples=access.public_buildings(store)
                private=[access.descriptor(store.get(item['building_id'])) for item in store.list()
                         if item['building_id'] not in access.examples] if writable else []
                documents=examples+private
            else:
                include_local_paths=local_paths_enabled(http_request)
                documents=[{**document.public(), 'local_file_path':store.linked_source_path(document) if include_local_paths else None}
                           for document in [store.get(item['building_id']) for item in store.list()]]
            projects=application.state.projects.catalog(documents,writable=writable)
            scopes=application.state.projects.scope_catalog(projects,documents,
                source_free_owners=application.state.project_chats.source_free_owners() if writable else ())
        return {'buildings':documents,'projects':projects,'building_scopes':scopes,'workspace_jobs':workspace_jobs(http_request)}

    @application.post("/api/projects", status_code=201)
    def create_project(request: ProjectName, http_request: Request):
        access.require_editor(http_request)
        return application.state.projects.create(request.name)

    def selected_project(http_request, identity):
        if access.enabled and identity.startswith('example-'):
            project=next((item for item in application.state.projects.catalog(access.public_buildings(application.state.documents),writable=False)
                          if item['id']==identity),None)
            if project is not None:return project
        if not access.is_editor(http_request):raise DocumentError('Building not found.',404)
        with application.state.documents.lock:
            return application.state.projects.get(identity)

    def scope_for_owner(project, scope_id, *, include_deleted=False):
        store=application.state.documents
        documents=[access.descriptor(store.get(identity)) for identity in project['building_ids']]
        scopes=application.state.projects.scope_catalog([project],documents,
            source_free_owners=application.state.project_chats.source_free_owners(),include_deleted=include_deleted)
        scope=next((item for item in scopes if item['scope_id']==scope_id),None)
        if scope is None:raise DocumentError('Building not found.',404)
        return scope

    def selected_scope(http_request, owner, scope_id, *, include_deleted=False):
        project=selected_project(http_request,owner)
        return project,scope_for_owner(project,scope_id,include_deleted=include_deleted)

    def editable_scope(scope):
        if scope['read_only']:raise DocumentError('This cached Building is read-only.',409)

    @application.get('/api/projects/{owner}/scopes/{scope_id}/chats')
    def scoped_chats(owner:str,scope_id:str,http_request:Request):
        access.require_editor(http_request)
        try:
            project,scope=selected_scope(http_request,owner,scope_id)
            return {'chats':application.state.project_chats.scoped_catalog(project,scope)}
        except DocumentError as error:raise HTTPException(error.status,error.message) from None

    @application.post('/api/projects/{owner}/scopes/{scope_id}/chats',status_code=201)
    def create_scoped_chat(owner:str,scope_id:str,request:NewScopedChat,http_request:Request):
        access.require_editor(http_request)
        try:
            project,scope=selected_scope(http_request,owner,scope_id)
            record=application.state.project_chats.create(project,request.name,scope['source_group_id'])
            return {**record,'effective_building_id':application.state.project_chats.effective_building_id(project,record)}
        except DocumentError as error:raise HTTPException(error.status,error.message) from None

    async def scoped_source_upload(http_request,owner,scope_id,uploads):
        access.require_editor(http_request)
        project,scope=selected_scope(http_request,owner,scope_id)
        editable_scope(scope)
        if not scope['upload_allowed']:raise DocumentError(scope['upload_reason'],409)
        payloads=[(await upload.read(MAX_IFC_UPLOAD+1),upload.filename or 'Untitled source') for upload in uploads]
        access.require_uploadable(http_request,payloads)
        def save():
            store=application.state.documents
            with store.lock:
                # Re-resolve under the lock: two first uploads join one group.
                # Do not call buildings()/workspace_jobs here (runner lock order).
                project=application.state.projects.get(owner)
                scope=scope_for_owner(project,scope_id)
                editable_scope(scope)
                if not scope['upload_allowed']:raise DocumentError(scope['upload_reason'],409)
                target=scope['source_group_id']
                identity=target or application.state.projects.shared_group_id(owner)
                existed=(store.directory(identity)/'CURRENT.json').exists()
                previous=store.get(identity) if existed else None
                prior_sources={source['source_id'] for source in previous.sources} if previous else set()
                application.state.projects.require_exclusive_upload(identity)
                document=store.add_many(payloads,building_id=target,new_group_id=None if target else identity)
                if scope_id=='shared':project=application.state.projects.establish_shared_group(owner,document.id)
                new_ids=[source['source_id'] for source in document.sources if source['source_id'] not in prior_sources]
                updated_scope=scope_for_owner(project,scope_id)
            jobs=application.state.jobs.extract(document.id,new_ids,retry=False) if new_ids and document.interpretation_status!='complete' else []
            return {**document.public(),'is_new_upload':not existed,'added_source_ids':new_ids,
                    'extraction_jobs':jobs,'building_scope':updated_scope}
        return await run_in_threadpool(save)

    @application.post('/api/projects/{owner}/scopes/{scope_id}/sources')
    async def upload_scoped_sources(owner:str,scope_id:str,http_request:Request,
        file:UploadFile|None=File(None),files:list[UploadFile]|None=File(None)):
        uploads=([file] if file else [])+(files or [])
        try:
            if not uploads:raise DocumentError('Choose at least one source file.',422)
            return await scoped_source_upload(http_request,owner,scope_id,uploads)
        except DocumentError as error:raise HTTPException(error.status,error.message) from None
        finally:
            for upload in uploads:await upload.close()

    @application.patch('/api/projects/{owner}/scopes/{scope_id}')
    def rename_scope(owner:str,scope_id:str,request:ProjectName,http_request:Request):
        access.require_editor(http_request)
        try:
            project,scope=selected_scope(http_request,owner,scope_id);editable_scope(scope)
            updated=application.state.projects.update_scope(owner,scope_id,name=request.name)
            return scope_for_owner(updated,scope_id)
        except DocumentError as error:raise HTTPException(error.status,error.message) from None

    @application.delete('/api/projects/{owner}/scopes/{scope_id}')
    def delete_scope(owner:str,scope_id:str,http_request:Request):
        access.require_editor(http_request)
        try:
            project,scope=selected_scope(http_request,owner,scope_id);editable_scope(scope)
            application.state.projects.update_scope(owner,scope_id,deleted=True)
            return {**scope,'deleted':True}
        except DocumentError as error:raise HTTPException(error.status,error.message) from None

    @application.post('/api/projects/{owner}/scopes/{scope_id}/restore')
    def restore_scope(owner:str,scope_id:str,http_request:Request):
        access.require_editor(http_request)
        try:
            project,scope=selected_scope(http_request,owner,scope_id,include_deleted=True);editable_scope(scope)
            updated=application.state.projects.update_scope(owner,scope_id,deleted=False)
            return scope_for_owner(updated,scope_id)
        except DocumentError as error:raise HTTPException(error.status,error.message) from None

    @application.get("/api/projects/{project_id}/chats")
    def project_chats(project_id: str, http_request: Request):
        access.require_editor(http_request)
        try:
            project=selected_project(http_request,project_id)
            return {"chats":[application.state.project_chats.descriptor(project,r) for r in application.state.project_chats.catalog(project)]}
        except DocumentError as error:raise HTTPException(error.status,error.message) from None

    @application.post("/api/projects/{project_id}/chats", status_code=201)
    def create_project_chat(project_id: str, request: NewProjectChat, http_request: Request):
        access.require_editor(http_request)
        try:
            project=selected_project(http_request,project_id)
            record=application.state.project_chats.create(project,request.name,request.building_id)
            return {**record,'effective_building_id':application.state.project_chats.effective_building_id(project,record)}
        except DocumentError as error:raise HTTPException(error.status,error.message) from None

    @application.get("/api/projects/{project_id}/chats/{session_id}")
    def project_chat(project_id: str, session_id: str, http_request: Request):
        access.require_editor(http_request)
        try:
            project=selected_project(http_request,project_id)
            record=application.state.project_chats.get(project_id,session_id)
            return {**record,'effective_building_id':application.state.project_chats.effective_building_id(project,record)}
        except DocumentError as error:raise HTTPException(error.status,error.message) from None

    @application.patch("/api/projects/{project_id}/chats/{session_id}")
    def rename_project_chat(project_id: str, session_id: str, request: ProjectName, http_request: Request):
        access.require_editor(http_request)
        try:
            selected_project(http_request,project_id)
            return application.state.project_chats.update(project_id,session_id,name=request.name)
        except DocumentError as error:raise HTTPException(error.status,error.message) from None

    @application.delete("/api/projects/{project_id}/chats/{session_id}")
    def delete_project_chat(project_id: str, session_id: str, http_request: Request):
        access.require_editor(http_request)
        try:
            selected_project(http_request,project_id)
            return application.state.project_chats.update(project_id,session_id,delete=True)
        except DocumentError as error:raise HTTPException(error.status,error.message) from None

    @application.patch("/api/projects/{project_id}")
    def rename_project(project_id: str, request: ProjectName, http_request: Request):
        access.require_editor(http_request)
        try:return application.state.projects.update(project_id,name=request.name)
        except DocumentError as error:raise HTTPException(error.status,error.message) from None

    @application.put("/api/projects/{project_id}/files/{building_id}")
    def add_project_file(project_id: str, building_id: str, http_request: Request):
        access.require_editable(http_request,building_id)
        try:return application.state.projects.update(project_id,add=building_id)
        except DocumentError as error:raise HTTPException(error.status,error.message) from None

    @application.delete("/api/projects/{project_id}")
    def delete_project(project_id: str, http_request: Request):
        access.require_editor(http_request)
        try:return application.state.projects.delete(project_id)
        except DocumentError as error:raise HTTPException(error.status,error.message) from None

    @application.post("/api/projects/{project_id}/restore")
    def restore_project(project_id: str, http_request: Request):
        access.require_editor(http_request)
        try:return application.state.projects.delete(project_id,restore=True)
        except DocumentError as error:raise HTTPException(error.status,error.message) from None

    @application.delete("/api/projects/{project_id}/files/{building_id}")
    def remove_project_file(project_id: str, building_id: str, http_request: Request):
        access.require_editor(http_request)
        try:return application.state.projects.update(project_id,remove=building_id)
        except DocumentError as error:raise HTTPException(error.status,error.message) from None

    @application.put("/api/projects/{project_id}/active-file/{building_id}")
    def activate_project_file(project_id: str, building_id: str, http_request: Request):
        access.require_editor(http_request)
        try:return application.state.projects.update(project_id,active=building_id)
        except DocumentError as error:raise HTTPException(error.status,error.message) from None

    def workspace_jobs(http_request):
        if not access.is_editor(http_request):return []
        runner=application.state.jobs
        with runner.lock:return [deepcopy(job) for job in runner.jobs.values()]

    @application.put("/api/buildings/{building_id}/library")
    def set_library_visibility(building_id: str, visible: bool, http_request: Request):
        access.require_editable(http_request, building_id)
        try:
            application.state.documents.set_library_visibility(building_id, visible)
            return {"visible": visible}
        except DocumentError as error:
            raise HTTPException(error.status, error.message) from None

    @application.get("/api/buildings/{building_id}")
    def building(building_id: str,http_request:Request):
        try:
            document = selected_document(http_request,building_id)
            jobs = application.state.jobs.for_building(building_id, include_debug_answers=True) if access.is_editor(http_request) else []
            if len(document.sources) > 1:
                jobs = [job for job in jobs if job["kind"] != "question"]
            return {**access.descriptor(document), "jobs": jobs,"workspace_jobs":workspace_jobs(http_request)}
        except DocumentError as error:
            raise HTTPException(error.status, error.message) from None

    @application.post("/api/buildings/{building_id}/reconstruction", status_code=202)
    def reconstruction_job(building_id: str, request: ReconstructionRequest,http_request:Request):
        access.require_editable(http_request,building_id)
        try:
            return application.state.jobs.reconstruct(building_id, request.base_revision_id, request.mode)
        except (DocumentError, ProviderError) as error:
            raise HTTPException(error.status, error.message) from None

    @application.get("/api/buildings/{building_id}/revisions/{revision_id}/evidence/{object_id}")
    def native_evidence(building_id: str, revision_id: str, object_id: str,http_request:Request):
        try:
            document = selected_document(http_request,building_id,revision_id)
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

    @application.post("/api/jobs/{job_id}/origin")
    def task_origin(job_id: str, request: TaskOriginRequest, http_request: Request):
        access.require_editor(http_request)
        try:
            job=application.state.jobs.get(job_id)
            project=selected_project(http_request,request.project_id)
            if job['building_id'] not in project['building_ids']:
                raise DocumentError("The task's sources are not in this Building.",422)
            if request.session_id:
                session=application.state.project_chats.validate_context(project,request.session_id,job['building_id'])
                if request.message_id and not any(message['id']==request.message_id and message['role']=='user'
                    and message.get('request_id')==request.request_id for message in session['messages']):
                    raise DocumentError("The initiating message is not in this chat.",422)
            elif request.message_id or request.request_id:
                raise DocumentError("A message reference requires its Building chat.",422)
            return application.state.jobs.set_origin(job_id,request.model_dump(exclude_none=True))
        except DocumentError as error:raise HTTPException(error.status,error.message) from None

    @application.post("/api/jobs/{job_id}/dismiss")
    def dismiss_task_activity(job_id: str, http_request: Request):
        access.require_editor(http_request)
        try:return application.state.jobs.dismiss_activity(job_id)
        except DocumentError as error:raise HTTPException(error.status,error.message) from None

    @application.post("/api/jobs/{job_id}/stop")
    def stop_job(job_id: str):
        try:
            return application.state.jobs.stop(job_id)
        except DocumentError as error:
            raise HTTPException(error.status, error.message) from None

    @application.post("/api/questions", status_code=202)
    def question_job(request: AskRequest,http_request:Request):
        try:
            request,pinned=pinned_question(http_request,request)
            return application.state.jobs.question(request,pinned_document=pinned)
        except (DocumentError, ProviderError) as error:
            raise HTTPException(error.status, error.message) from None

    @application.post("/api/ask", response_model=Answer)
    def question(request: AskRequest,http_request:Request):
        provider = None
        if not application.state.inference_slots.acquire(blocking=False):
            raise HTTPException(429, "Two questions are already processing. Please wait and retry.")
        try:
            request,pinned=pinned_question(http_request,request)
            document=(pinned or application.state.documents.get(request.document_id)).snapshot()
            if request.revision_id and request.revision_id != document.revision_id:
                raise DocumentError("The building revision changed; refresh before asking.", 409)
            document.conversation_context=question_context(application.state.documents,document,request)
            message=user_message(document,request)
            application.state.documents.append_conversation(document.id,message)
            provider = application.state.provider_factory()
            answer = VLM(provider).answer(document, request.question)
            latest = document if pinned is not None else application.state.documents.get(document.id)
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
    def get_scene(document_id: str,http_request:Request):
        try:
            document = selected_document(http_request,document_id)
            if not document.scene:
                raise DocumentError("No model yet. Generate a building model from the original drawing pages.", 404)
            return document.scene
        except DocumentError as error:
            raise HTTPException(error.status, error.message) from None

    @application.post("/api/documents/{document_id}/scene", response_model=Scene)
    def generate_scene(document_id: str, request: SceneRequest,http_request:Request):
        access.require_editable(http_request,document_id)
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
    def download_model(document_id: str,http_request:Request):
        try:
            document = selected_document(http_request,document_id)
            if not document.ifc_bytes:
                raise DocumentError("Generate the drawing-derived IFC first.", 404)
            return Response(document.ifc_bytes, media_type="application/x-step",
                            headers={"Content-Disposition": 'attachment; filename="blueprint-derived.ifc"',
                                     "Cache-Control": "no-store"})
        except DocumentError as error:
            raise HTTPException(error.status, error.message) from None

    from .voice import attach_voice_routes
    attach_voice_routes(application, transcription_factory=transcription_factory, speech_factory=speech_factory,
                        project_selector=selected_project)
    return application


app = create_app()
