"""Local versioned building bundles. A failed candidate never changes CURRENT."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
import time
import uuid

from .building import BuildingDescription
from .documents import Document, DocumentError, DocumentStore, Page
from .scene import Scene


def _json(path, value):
    path.write_text(json.dumps(value,ensure_ascii=False,allow_nan=False,indent=2))


def _atomic_json(path, value):
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        _json(temporary,value)
        with temporary.open("rb") as stream:
            os.fsync(stream.fileno())
        os.replace(temporary,path)
    finally:
        temporary.unlink(missing_ok=True)


class BuildingStore:
    """One-process filesystem store; immutable source and revision directories."""
    def __init__(self, root: Path):
        self.root = Path(root) / "buildings"
        self.root.mkdir(parents=True,exist_ok=True)
        self.documents = {}
        self.lock = threading.RLock()
        # A restarted process cannot prove an old provider call is still running.
        for path in self.root.glob("*/jobs/*.json"):
            try:
                job = json.loads(path.read_text())
                if job.get("status") in {"queued","running","stopping"}:
                    job.update(status="interrupted",phase="interrupted",message="Application restarted; previous usable revision retained.")
                    _atomic_json(path,job)
            except (ValueError,OSError):
                continue

    def close(self):
        # Durable sources and revisions intentionally survive application shutdown.
        self.documents.clear()

    def directory(self, building_id):
        if len(building_id)!=64 or any(c not in "0123456789abcdef" for c in building_id):
            raise DocumentError("Building not found.",404)
        return self.root / building_id

    def list(self):
        result=[]
        for path in self.root.glob("*/building.json"):
            try:
                metadata=json.loads(path.read_text())
                current=json.loads((path.parent/"CURRENT.json").read_text())
                result.append({**metadata,**current})
            except (OSError,ValueError):
                continue
        return sorted(result,key=lambda b:b.get("updated_at",0),reverse=True)

    def add(self,data,filename):
        building_id=hashlib.sha256(data).hexdigest()
        with self.lock:
            directory=self.directory(building_id)
            if (directory/"CURRENT.json").exists():
                return self.get(building_id)
            # Reuse the existing upload normalization/importer; do not create a parallel parser.
            with tempfile.TemporaryDirectory(prefix="normalize-",dir=self.root.parent) as tmp:
                normalizer=DocumentStore(Path(tmp))
                try:
                    document=normalizer.add(data,filename)
                    staged=self.root/(".pending-"+uuid.uuid4().hex)
                    staged.mkdir();(staged/"pages").mkdir();(staged/"revisions").mkdir();(staged/"jobs").mkdir()
                    (staged/"source.original").write_bytes(data)
                    pages=[]
                    for page in document.pages:
                        name=f"{page.number}.png"
                        shutil.copyfile(page.path,staged/"pages"/name)
                        pages.append(Page(page.number,page.width,page.height,directory/"pages"/name))
                    now=time.time()
                    _json(staged/"building.json",{"schema_version":1,"building_id":building_id,
                        "document_id":building_id,"filename":document.filename,"kind":document.kind,
                        "content_sha256":building_id,"created_at":now,
                        "pages":[{"number":p.number,"width":p.width,"height":p.height,
                                  "sha256":hashlib.sha256((staged/"pages"/f"{p.number}.png").read_bytes()).hexdigest()}for p in pages]})
                    document=replace(document,id=building_id,building_id=building_id,pages=pages,source_bytes=data)
                    if document.scene:
                        document.scene.document_id=building_id
                        document.scene.building_id=building_id
                        document.scene.ifc_url=f"/api/documents/{building_id}/model.ifc"
                    if document.description:
                        from .identities import assign_identities
                        document.description=assign_identities(document,document.description,imported=True)
                    from .reasoning import build_reasoning
                    document.reasoning=build_reasoning(document)
                    if directory.exists():
                        # Only an incomplete, never-published staging result can be present here.
                        shutil.rmtree(directory)
                    os.replace(staged,directory)
                    self.documents[building_id]=document
                    return self.commit(document,None,status="available" if document.scene else "source_available",
                                       config={"pipeline_version":"progressive-v1","operation":"source_import"})
                finally:
                    normalizer.close()

    def get(self,building_id):
        with self.lock:
            if building_id in self.documents:
                return self.documents[building_id]
            directory=self.directory(building_id)
            try:
                metadata=json.loads((directory/"building.json").read_text())
                current=json.loads((directory/"CURRENT.json").read_text())
                document=self._load_revision(directory,metadata,current["revision_id"])
            except (OSError,ValueError,KeyError) as error:
                raise DocumentError("Saved building is unavailable or incomplete. Its original files have not been replaced.",404) from None
            self.documents[building_id]=document
            return document

    def revision(self,building_id,revision_id):
        with self.lock:
            directory=self.directory(building_id)
            if not isinstance(revision_id,str) or len(revision_id)!=32 or any(c not in "0123456789abcdef"for c in revision_id):
                raise DocumentError("Revision not found.",404)
            try:
                metadata=json.loads((directory/"building.json").read_text())
                return self._load_revision(directory,metadata,revision_id)
            except (OSError,ValueError,KeyError):
                raise DocumentError("Revision not found or incomplete.",404) from None

    def _load_revision(self,directory,metadata,revision_id):
        folder=directory/"revisions"/revision_id
        info=json.loads((folder/"revision.json").read_text())
        for name,expected in info["hashes"].items():
            if hashlib.sha256((folder/name).read_bytes()).hexdigest()!=expected:
                raise ValueError("Corrupted revision file")
        source=(directory/"source.original").read_bytes()
        if hashlib.sha256(source).hexdigest()!=metadata["content_sha256"]:
            raise ValueError("Original source changed")
        pages=[]
        for p in metadata["pages"]:
            path=directory/"pages"/f'{p["number"]}.png'
            if hashlib.sha256(path.read_bytes()).hexdigest()!=p["sha256"]:
                raise ValueError("Original page changed")
            pages.append(Page(p["number"],p["width"],p["height"],path))
        def read(name):
            return json.loads((folder/name).read_text()) if (folder/name).exists() else None
        scene_data=read("scene.json");description=read("description.json")
        return Document(id=metadata["building_id"],filename=metadata["filename"],pages=pages,
            warnings=info.get("warnings",[]),kind=metadata["kind"],
            scene=Scene.model_validate(scene_data) if scene_data else None,
            ifc_bytes=(folder/"model.ifc").read_bytes() if (folder/"model.ifc").exists() else None,
            source_bytes=source,description=BuildingDescription.model_validate(description) if description else None,
            reasoning=read("reasoning.json"),building_id=metadata["building_id"],revision_id=revision_id,
            parent_revision_id=info.get("parent_revision_id"),revision_number=info["revision_number"],
            identity_registry=read("identities.json") or {},frame_registry=read("frames.json") or {},
            review_status=info["status"])

    def prepare(self,document):
        candidate=document.snapshot()
        candidate.parent_revision_id=document.revision_id
        candidate.revision_id=uuid.uuid4().hex
        candidate.revision_number=document.revision_number+1
        candidate.question_context=None
        return candidate

    def commit(self,candidate,expected_revision_id,*,status,review=None,config=None,job_guard=None):
        with self.lock:
            directory=self.directory(candidate.id)
            pointer=directory/"CURRENT.json"
            current=json.loads(pointer.read_text()) if pointer.exists() else {"revision_id":None,"revision_number":0}
            if current["revision_id"]!=expected_revision_id or (job_guard and not job_guard()):
                raise DocumentError("Stale or stopped reconstruction cannot replace the current building revision.",409)
            if not candidate.revision_id or candidate.revision_id==expected_revision_id:
                candidate=self.prepare(candidate)
            candidate.revision_number=current["revision_number"]+1
            candidate.parent_revision_id=expected_revision_id
            candidate.review_status=status
            if candidate.scene:
                candidate.scene.building_id=candidate.id
                candidate.scene.document_id=candidate.id
                candidate.scene.revision_id=candidate.revision_id
                candidate.scene.parent_revision_id=expected_revision_id
                candidate.scene.revision_number=candidate.revision_number
                candidate.scene.review_status=status
                candidate.scene.ifc_url=f"/api/documents/{candidate.id}/model.ifc"
            folder=directory/"revisions"/candidate.revision_id
            if folder.exists():
                raise DocumentError("A revision identity cannot be overwritten.",409)
            temporary=directory/"revisions"/(".pending-"+uuid.uuid4().hex)
            temporary.mkdir()
            try:
                for name,value in (("scene.json",candidate.scene.model_dump() if candidate.scene else None),
                    ("description.json",candidate.description.model_dump() if candidate.description else None),
                    ("reasoning.json",candidate.reasoning),("identities.json",candidate.identity_registry),
                    ("frames.json",candidate.frame_registry),("review.json",review),("pipeline.json",config or {})):
                    if value is not None:
                        _json(temporary/name,value.model_dump() if hasattr(value,"model_dump") else value)
                if candidate.ifc_bytes:
                    (temporary/"model.ifc").write_bytes(candidate.ifc_bytes)
                hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest()for p in temporary.iterdir()if p.is_file()}
                info={"schema_version":1,"building_id":candidate.id,"revision_id":candidate.revision_id,
                    "parent_revision_id":expected_revision_id,"revision_number":candidate.revision_number,
                    "status":status,"updated_at":time.time(),"warnings":candidate.warnings,"hashes":hashes}
                _json(temporary/"revision.json",info)
                os.replace(temporary,folder)
                # Publish only after every artifact exists. Older revision directories are never changed.
                if job_guard and not job_guard():
                    rejected=directory/"candidates"
                    rejected.mkdir(exist_ok=True)
                    os.replace(folder,rejected/candidate.revision_id)
                    raise DocumentError("Stopped processing cannot publish a late revision.",409)
                _atomic_json(pointer,{k:info[k]for k in ("revision_id","revision_number","status","updated_at")})
                self.documents[candidate.id]=candidate
                return candidate
            finally:
                if temporary.exists():
                    shutil.rmtree(temporary)

    def history(self,building_id):
        self.get(building_id)
        result=[]
        for path in (self.directory(building_id)/"revisions").glob("*/revision.json"):
            info=json.loads(path.read_text())
            result.append({k:v for k,v in info.items()if k!="hashes"})
        return sorted(result,key=lambda r:r["revision_number"])

    def save_job(self,building_id,job):
        with self.lock:
            folder=self.directory(building_id)/"jobs"
            folder.mkdir(exist_ok=True)
            _atomic_json(folder/(job["id"]+".json"),job)

    def saved_jobs(self,building_id):
        return [json.loads(p.read_text())for p in (self.directory(building_id)/"jobs").glob("*.json")]

    def save_candidate(self,candidate,review,reason,config):
        """Keep rejected evidence inspectable without changing the usable revision pointer."""
        with self.lock:
            folder=self.directory(candidate.id)/"candidates"/(candidate.revision_id or uuid.uuid4().hex)
            folder.mkdir(parents=True,exist_ok=False)
            for name,value in (("description.json",candidate.description.model_dump() if candidate.description else None),
                               ("scene.json",candidate.scene.model_dump() if candidate.scene else None),
                               ("reasoning.json",candidate.reasoning),("pipeline.json",config),
                               ("review.json",review.model_dump() if hasattr(review,"model_dump") else review),
                               ("rejection.json",{"status":"rejected","reason":reason,"base_revision_id":candidate.parent_revision_id})):
                if value is not None:_json(folder/name,value)
            if candidate.ifc_bytes:(folder/"model.ifc").write_bytes(candidate.ifc_bytes)
            return str(folder.relative_to(self.directory(candidate.id)))
