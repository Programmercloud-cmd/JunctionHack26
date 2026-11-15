"""Local project organization; saved source/model bundles keep their identities."""
from copy import deepcopy
import json
import time
import uuid

from pydantic import model_validator

from .bundles import _atomic_json
from .documents import DocumentError
from .schemas import StrictModel


class ProjectName(StrictModel):
    name: str

    @model_validator(mode="after")
    def meaningful(self):
        self.name = self.name.strip()
        if not self.name:
            raise ValueError("Enter a project name")
        return self


class ProjectStore:
    def __init__(self, store):
        self.store = store
        self.path = store.root.parent / "projects.json"

    def _read(self):
        if not self.path.exists():
            return []
        return json.loads(self.path.read_text())["projects"]

    def _write(self, projects):
        previous = json.loads(self.path.read_text()) if self.path.exists() else {}
        known = set(previous.get("known_building_ids", []))
        known.update(identity for project in projects for identity in project["building_ids"])
        _atomic_json(self.path, {**previous, "projects": projects, "known_building_ids": sorted(known)})

    @staticmethod
    def _new(name, building_id=None):
        return {"id": uuid.uuid4().hex, "name": name,
                "building_ids": [building_id] if building_id else [],
                "active_building_id": building_id, "created_at": time.time()}

    def catalog(self, documents, *, writable):
        with self.store.lock:
            projects = self._read()
            known = set(json.loads(self.path.read_text()).get("known_building_ids", [])) if self.path.exists() else set()
            visible = {doc["building_id"]: doc for doc in documents}
            assigned = {identity for project in projects for identity in project["building_ids"]}
            changed = False
            public = []
            for identity, doc in visible.items():
                if doc.get("public_example") or doc.get("read_only_model"):
                    public.append({**self._new(doc.get("example_title") or doc["filename"], identity),
                                   "id": "example-" + identity, "created_at": 0, "read_only": True})
                elif writable and identity not in assigned and identity not in known:
                    projects.append(self._new(doc["filename"], identity))
                    changed = True
            if changed:
                self._write(projects)
            result = []
            for project in ([*projects, *public] if writable else public):
                ids = [identity for identity in project["building_ids"] if identity in visible]
                # Empty private projects are intentional; hidden file entries stay hidden.
                if project["building_ids"] and not ids:
                    continue
                selected = project.get("active_building_id")
                selected = selected if selected in ids else next(iter(ids), None)
                result.append({**deepcopy(project), "building_ids": ids, "active_building_id": selected})
            return result

    def create(self, name):
        name = ProjectName.model_validate({"name": name}).name
        with self.store.lock:
            projects = self._read()
            project = self._new(name)
            projects.append(project)
            self._write(projects)
            return deepcopy(project)

    def update(self, identity, *, name=None, add=None, remove=None, active=None):
        with self.store.lock:
            projects = self._read()
            project = next((item for item in projects if item["id"] == identity), None)
            if project is None:
                raise DocumentError("Project not found or read-only.", 404)
            if name is not None:
                project["name"] = ProjectName.model_validate({"name": name}).name
            if add is not None and add not in project["building_ids"]:
                self.store.get(add)
                project["building_ids"].append(add)
                project["active_building_id"] = add
            if remove is not None:
                project["building_ids"] = [item for item in project["building_ids"] if item != remove]
                if project.get("active_building_id") == remove:
                    project["active_building_id"] = next(iter(project["building_ids"]), None)
            if active is not None:
                if active not in project["building_ids"]:
                    raise DocumentError("The file is not part of this project.", 422)
                project["active_building_id"] = active
            self._write(projects)
            return deepcopy(project)

    def delete(self, identity, *, restore=False):
        """Hide organization metadata; shared sources, jobs and chats stay saved."""
        with self.store.lock:
            data = json.loads(self.path.read_text()) if self.path.exists() else {}
            projects, deleted = data.get("projects", []), data.get("deleted_projects", [])
            source, target = (deleted, projects) if restore else (projects, deleted)
            project = next((item for item in source if item["id"] == identity), None)
            if project is None:
                raise DocumentError("Project not found or read-only.", 404)
            source.remove(project)
            target.append(project)
            known = set(data.get("known_building_ids", []))
            known.update(item for p in [*projects, *deleted] for item in p["building_ids"])
            _atomic_json(self.path, {**data, "projects": projects, "deleted_projects": deleted,
                                    "known_building_ids": sorted(known)})
            return deepcopy(project)
