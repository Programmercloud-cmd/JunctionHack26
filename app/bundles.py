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
        self.resources = self.root.parent / "resources"
        self.resources.mkdir(exist_ok=True)
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
            if (path.parent / "removed-from-library").exists():
                continue
            try:
                metadata=json.loads(path.read_text())
                current=json.loads((path.parent/"CURRENT.json").read_text())
                result.append({**metadata,**current})
            except (OSError,ValueError):
                continue
        return sorted(result,key=lambda b:b.get("updated_at",0),reverse=True)

    def linked_source_path(self, document):
        link = self.directory(document.id) / "original-path.json"
        try:
            path = Path(json.loads(link.read_text()))
            if path.is_absolute() and path.is_file():
                return str(path)
        except (OSError, ValueError, TypeError):
            pass
        return None

    def link_original_path(self, building_id, filename):
        document = self.get(building_id)
        try:
            path = Path(filename).expanduser()
            if not path.is_absolute():
                raise DocumentError("Enter the absolute path to the original file.", 422)
            path = path.resolve(strict=True)
            stored = self.directory(building_id) / "source.original"
            if self.root.parent.resolve() in path.parents:
                raise DocumentError("Choose the original file outside Concrete storage.", 422)
            if not path.is_file() or path.stat().st_size != stored.stat().st_size:
                raise DocumentError("That file does not match the saved upload.", 422)
            with path.open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != hashlib.sha256(document.source_bytes).hexdigest():
                    raise DocumentError("That file does not match the saved upload.", 422)
        except (OSError, ValueError, RuntimeError):
            raise DocumentError("Concrete could not read that file path.", 422) from None
        with self.lock:
            _atomic_json(self.directory(building_id) / "original-path.json", str(path))
        return str(path)

    def set_library_visibility(self, building_id, visible):
        with self.lock:
            self.get(building_id)
            marker = self.directory(building_id) / "removed-from-library"
            if visible:
                marker.unlink(missing_ok=True)
            else:
                marker.touch()

    def add(self,data,filename,*,group_id=None):
        source_hash=hashlib.sha256(data).hexdigest()
        building_id=group_id or source_hash
        with self.lock:
            directory=self.directory(building_id)
            if (directory/"CURRENT.json").exists():
                document=self.get(building_id)
                self._alias(document,data,filename)
                self.set_library_visibility(building_id, True)
                return document
            # Reuse the existing upload normalization/importer; do not create a parallel parser.
            with tempfile.TemporaryDirectory(prefix="normalize-",dir=self.root.parent) as tmp:
                normalizer=DocumentStore(Path(tmp))
                try:
                    resource_ready=(self._resource_path(source_hash)/"source.json").exists()
                    document=self._resource(data,filename) if resource_ready and not data.lstrip().startswith(b"ISO-10303-21;") else normalizer.add(data,filename)
                    staged=self.root/(".pending-"+uuid.uuid4().hex)
                    staged.mkdir();(staged/"pages").mkdir();(staged/"revisions").mkdir();(staged/"jobs").mkdir()
                    (staged/"source.original").write_bytes(data)
                    pages=[]
                    for page in document.pages:
                        name=f"{page.number}.png"
                        shutil.copyfile(page.path,staged/"pages"/name)
                        pages.append(replace(page,path=directory/"pages"/name))
                    now=time.time()
                    _json(staged/"building.json",{"schema_version":1,"building_id":building_id,
                        "document_id":building_id,"filename":document.filename,"kind":document.kind,
                        "content_sha256":source_hash,"created_at":now,
                        "pages":[{"number":p.number,"width":p.width,"height":p.height,
                                  "sha256":hashlib.sha256((staged/"pages"/f"{p.number}.png").read_bytes()).hexdigest()}for p in pages]})
                    document=replace(document,id=building_id,building_id=building_id,pages=pages,source_bytes=data)
                    if not document.sources and not (document.scene and document.scene.derived):
                        document.sources=[{"source_id":source_hash,"filename":document.filename,"filenames":[document.filename],
                            "kind":document.kind,"media_type":"application/x-step" if document.kind=="ifc" else "application/octet-stream",
                            "pages":[],"metadata":{}}]
                        document.source_files={source_hash:data}
                    for source in document.sources:
                        sid=source["source_id"]
                        source_pages=[replace(p,path=staged/"pages"/f"{p.number}.png") for p in pages if p.source_id==sid]
                        self._save_resource(source,document.source_files[sid],source_pages)
                    if document.scene:
                        document.geometry_status="available"
                    if document.description or document.kind=="ifc":document.interpretation_status="complete"
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
        source_interpretations=read("source_interpretations.json") or {}
        sources=read("sources.json")
        legacy_pages=read("legacy_pages.json")
        source_files={}
        if sources is not None:
            pages=[]
            for entry in sources:
                sid=entry["source_id"]
                resource=self._resource_path(sid)
                original=(resource/"source.original").read_bytes()
                if hashlib.sha256(original).hexdigest()!=sid:raise ValueError("Original resource changed")
                source_files[sid]=original
                for item in entry.get("pages",[]):
                    path=resource/"pages"/f'{item["source_page"]}.png'
                    if hashlib.sha256(path.read_bytes()).hexdigest()!=item["sha256"]:
                        # A pre-fix double-normalized source may still have its
                        # exact extraction pixels in the immutable original upload.
                        pinned=directory/"pages"/f'{item["page"]}.png'
                        if not pinned.exists() or hashlib.sha256(pinned.read_bytes()).hexdigest()!=item["sha256"]:
                            raise ValueError("Source page changed")
                        path=pinned
                    pages.append(Page(item["page"],item["width"],item["height"],path,sid,item["source_page"],entry["filename"]))
            for item in legacy_pages or []:
                path=folder/f'legacy-page-{item["number"]}.png'
                if hashlib.sha256(path.read_bytes()).hexdigest()!=item["sha256"]:raise ValueError("Legacy original page changed")
                pages.append(Page(item["number"],item["width"],item["height"],path))
            pages.sort(key=lambda p:p.number)
        else:
            # Old derived artifacts contain normalized pages, not recoverable original files.
            derived=scene_data and scene_data.get("derived")
            sources=[] if derived else [{"source_id":metadata["content_sha256"],"filename":metadata["filename"],
                "filenames":[metadata["filename"]],"kind":metadata["kind"],"media_type":"application/octet-stream",
                "pages":[{"page":p.number,"source_page":p.number,"width":p.width,"height":p.height,
                    "sha256":hashlib.sha256(p.path.read_bytes()).hexdigest()}for p in pages],"metadata":{}}]
            if not derived:
                sid=metadata["content_sha256"];source_files={sid:source}
                pages=[replace(p,source_id=sid,source_page=p.number,source_filename=metadata["filename"])for p in pages]
                self._save_resource(sources[0],source,pages)
        if description and len(sources)==1 and not source_interpretations:
            # Reuse the exact saved single-source interpretation; this is not a new extraction
            # and is not promoted into the independent global resource cache.
            source_interpretations={sources[0]["source_id"]:deepcopy(description)}
        return Document(id=metadata["building_id"],filename=metadata["filename"],pages=pages,
            warnings=info.get("warnings",[]),kind=metadata["kind"],
            scene=Scene.model_validate(scene_data) if scene_data else None,
            ifc_bytes=(folder/"model.ifc").read_bytes() if (folder/"model.ifc").exists() else None,
            source_bytes=source,description=BuildingDescription.model_validate(description) if description else None,
            reasoning=read("reasoning.json"),building_id=metadata["building_id"],revision_id=revision_id,
            parent_revision_id=info.get("parent_revision_id"),revision_number=info["revision_number"],
            identity_registry=read("identities.json") or {},frame_registry=read("frames.json") or {},
            review_status=info["status"],sources=sources,source_files=source_files,
            source_interpretations=source_interpretations,user_values=read("user_values.json") or [],
            interpretation_status=info.get("interpretation_status","complete" if description else "pending"),
            geometry_status=info.get("geometry_status","available" if scene_data else "not_requested"),
            geometry_revision_id=info.get("geometry_revision_id",revision_id if scene_data else None))

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
                if candidate.geometry_status != "stale":
                    candidate.geometry_revision_id=candidate.revision_id
                    candidate.scene.revision_id=candidate.revision_id
                candidate.scene.parent_revision_id=expected_revision_id
                if candidate.geometry_status != "stale":candidate.scene.revision_number=candidate.revision_number
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
                    ("frames.json",candidate.frame_registry),
                    ("sources.json",candidate.sources if candidate.sources else None),
                    ("source_interpretations.json",candidate.source_interpretations),("user_values.json",candidate.user_values),
                    ("review.json",review),("pipeline.json",config or {})):
                    if value is not None:
                        _json(temporary/name,value.model_dump() if hasattr(value,"model_dump") else value)
                legacy=[]
                for page in candidate.pages:
                    if page.source_id is None:
                        target=temporary/f"legacy-page-{page.number}.png"
                        shutil.copyfile(page.path,target)
                        legacy.append({"number":page.number,"width":page.width,"height":page.height,
                            "sha256":hashlib.sha256(target.read_bytes()).hexdigest()})
                if legacy:_json(temporary/"legacy_pages.json",legacy)
                if candidate.ifc_bytes:
                    (temporary/"model.ifc").write_bytes(candidate.ifc_bytes)
                hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest()for p in temporary.iterdir()if p.is_file()}
                info={"schema_version":1,"building_id":candidate.id,"revision_id":candidate.revision_id,
                    "parent_revision_id":expected_revision_id,"revision_number":candidate.revision_number,
                    "status":status,"updated_at":time.time(),"warnings":candidate.warnings,"hashes":hashes,
                    "interpretation_status":candidate.interpretation_status,"geometry_status":candidate.geometry_status,
                    "geometry_revision_id":candidate.geometry_revision_id}
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

    def _resource_path(self, source_id):
        if not isinstance(source_id,str) or len(source_id)!=64 or any(c not in "0123456789abcdef"for c in source_id):
            raise DocumentError("Source not found.",404)
        return self.resources/source_id

    def _save_resource(self, metadata, data, pages):
        sid=metadata["source_id"]
        if hashlib.sha256(data).hexdigest()!=sid:raise DocumentError("Original source hash mismatch.",422)
        directory=self._resource_path(sid)
        if (directory/"source.json").exists():return
        directory.mkdir(exist_ok=True);(directory/"pages").mkdir(exist_ok=True)
        (directory/"source.original").write_bytes(data)
        local=deepcopy(metadata)
        local["pages"]=[]
        for page in pages:
            number=page.source_page or page.number
            destination=directory/"pages"/f"{number}.png"
            shutil.copyfile(page.path,destination)
            local["pages"].append({"page":number,"source_page":number,"width":page.width,"height":page.height,
                "sha256":hashlib.sha256(destination.read_bytes()).hexdigest()})
        _atomic_json(directory/"source.json",local)

    def _alias(self, document, data, filename):
        sid=hashlib.sha256(data).hexdigest()
        safe=Path(filename.replace("\\","/")).name[:200]
        directory=self._resource_path(sid)
        if (directory/"source.json").exists():
            metadata=json.loads((directory/"source.json").read_text())
            if safe not in metadata.setdefault("filenames",[]):
                metadata["filenames"].append(safe);_atomic_json(directory/"source.json",metadata)

    def _resource(self,data,filename):
        sid=hashlib.sha256(data).hexdigest();directory=self._resource_path(sid)
        if not (directory/"source.json").exists():
            with tempfile.TemporaryDirectory(prefix="source-",dir=self.root.parent)as tmp:
                parser=DocumentStore(Path(tmp))
                try:
                    doc=parser.add(data,filename)
                    if doc.scene and doc.scene.derived:
                        for source in doc.sources:self._save_resource(source,doc.source_files[source["source_id"]],
                            [p for p in doc.pages if p.source_id==source["source_id"]])
                        return doc
                    metadata=doc.sources[0] if doc.sources else {"source_id":sid,"filename":doc.filename,
                        "filenames":[doc.filename],"kind":doc.kind,"media_type":"application/x-step","pages":[],"metadata":{}}
                    self._save_resource(metadata,data,doc.pages)
                finally:parser.close()
        metadata=json.loads((directory/"source.json").read_text())
        pages=[Page(p["page"],p["width"],p["height"],directory/"pages"/f'{p["source_page"]}.png',sid,p["source_page"],metadata["filename"])for p in metadata["pages"]]
        return Document(sid,metadata["filename"],pages,warnings=metadata.get("warnings",[]),source_bytes=data,sources=[metadata],source_files={sid:data},kind="ifc" if metadata["kind"]=="ifc"else"drawing")

    def add_many(self, files, building_id=None, *, new_group_id=None):
        if not files:raise DocumentError("Choose at least one source file.")
        with self.lock:
            # Preflight before publishing any source membership, including a new batch.
            resources=[self._resource(data,name)for data,name in files]
            target=building_id or new_group_id
            existing=self.get(target) if target and (self.directory(target)/"CURRENT.json").exists() else None
            if building_id and existing is None:raise DocumentError('Building not found.',404)
            identities={s['source_id']for r in resources for s in r.sources}
            if existing:identities.update(s['source_id']for s in existing.sources)
            native_incoming=any(r.kind=='ifc'for r in resources)
            legacy_drawings=bool(existing and existing.kind=='drawing' and existing.pages)
            if (native_incoming and legacy_drawings) or (len(identities)>1 and (native_incoming or existing and existing.kind=='ifc')):
                raise DocumentError('Native IFC must be opened as a separate building. Grouped drawing sources are supported; mixed native IFC evidence is not yet supported.',422)
            for r in resources:
                if r.scene and r.scene.derived and not r.sources and (existing or len(files)>1):
                    raise DocumentError('This older derived IFC contains normalized pages but lacks original-file membership. Open it separately; its pages remain available for QA and additional drawing sources.',422)
            current=existing if existing else self.add(*files[0],group_id=new_group_id)
            # A reserved namespace can predate its project pointer after an IO
            # failure. A retry must append its first incoming file as well.
            additions=files if existing is not None else files[1:]
            for data,filename in additions:
                sid=hashlib.sha256(data).hexdigest()
                if any(s["source_id"]==sid for s in current.sources):
                    self._alias(current,data,filename);continue
                resource=self._resource(data,filename)
                candidate=self.prepare(current)
                number=max((p.number for p in candidate.pages),default=0)
                for source in resource.sources:
                    if any(s["source_id"]==source["source_id"]for s in candidate.sources):continue
                    entry=deepcopy(source);entry["pages"]=[]
                    for page in resource.pages:
                        if page.source_id!=source["source_id"]:continue
                        number+=1
                        local=page.source_page or page.number
                        path=self._resource_path(source["source_id"])/"pages"/f"{local}.png"
                        candidate.pages.append(replace(page,number=number,path=path))
                        entry["pages"].append({"page":number,"source_page":local,"width":page.width,"height":page.height,
                            "sha256":hashlib.sha256(path.read_bytes()).hexdigest()})
                    candidate.sources.append(entry)
                    candidate.source_files[source["source_id"]]=resource.source_files[source["source_id"]]
                candidate.interpretation_status="pending"
                if candidate.scene:candidate.geometry_status="stale"
                candidate.reasoning=None
                from .reasoning import build_reasoning
                candidate.reasoning=build_reasoning(candidate)
                current=self.commit(candidate,current.revision_id,status="source_added")
            return current

    def source_document(self, document, source_id):
        source=next((s for s in document.sources if s["source_id"]==source_id),None)
        if source is None:raise DocumentError("Source is not part of this revision.",404)
        pages=[replace(p,number=p.source_page or p.number)for p in document.pages if p.source_id==source_id]
        metadata=deepcopy(source)
        for page in metadata["pages"]:page["page"]=page["source_page"]
        return Document(source_id,source["filename"],pages,source_bytes=document.source_files.get(source_id),
            sources=[metadata],source_files={source_id:document.source_files[source_id]},
            kind="ifc" if source["kind"]=="ifc"else"drawing")

    def cached_interpretation(self, source_id):
        path=self._resource_path(source_id)/"interpretation.json"
        if not path.exists():return None
        return BuildingDescription.model_validate(json.loads(path.read_text()))

    def save_interpretation(self,source_id,description):
        with self.lock:
            _atomic_json(self._resource_path(source_id)/"interpretation.json",description.model_dump()if hasattr(description,"model_dump")else description)

    def merge_interpretation(self,building_id,source_id,description,job_guard=None):
        from .source_merge import merge_source_interpretation
        from .reasoning import build_reasoning
        with self.lock:
            current=self.get(building_id)
            candidate=self.prepare(current)
            merge_source_interpretation(candidate,source_id,description)
            candidate.interpretation_status="complete"if all(s["source_id"]in candidate.source_interpretations or s["kind"]=="ifc"for s in candidate.sources)else"partial"
            if candidate.scene:candidate.geometry_status="stale"
            candidate.reasoning=build_reasoning(candidate)
            return self.commit(candidate,current.revision_id,status="interpretation_available",job_guard=job_guard)

    def conversation(self,building_id):
        with self.lock:
            self.get(building_id)
            path=self.directory(building_id)/"conversation.json"
            return json.loads(path.read_text())if path.exists()else[]

    def append_conversation(self,building_id,message):
        with self.lock:
            messages=self.conversation(building_id)
            messages.append(deepcopy(message))
            _atomic_json(self.directory(building_id)/"conversation.json",messages)
            return messages
