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
            raise ValueError("Enter a name")
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
                    # A first-upload namespace may survive a failed pointer write.
                    # Keep it reserved for its original owner so a retry can finish.
                    retained = [*projects, *(json.loads(self.path.read_text()).get('deleted_projects', []) if self.path.exists() else [])]
                    if any(self.shared_group_id(p['id']) == identity for p in retained):continue
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
            project['shared_drawing_building_id'] = None
            projects.append(project)
            self._write(projects)
            return deepcopy(project)

    def update(self, identity, *, name=None, add=None, remove=None, active=None):
        with self.store.lock:
            projects = self._read()
            project = next((item for item in projects if item["id"] == identity), None)
            if project is None:
                raise DocumentError("Building not found or read-only.", 404)
            if name is not None:
                project["name"] = ProjectName.model_validate({"name": name}).name
            if add is not None and add not in project["building_ids"]:
                self.store.get(add)
                project["building_ids"].append(add)
                project["active_building_id"] = add
            if remove is not None:
                if remove == project.get('shared_drawing_building_id'):
                    raise DocumentError('This group supplies the Building and its chats. Remove the Building entry instead; its saved drawings and history will be retained.', 409)
                project["building_ids"] = [item for item in project["building_ids"] if item != remove]
                if project.get("active_building_id") == remove:
                    project["active_building_id"] = next(iter(project["building_ids"]), None)
            if active is not None:
                if active not in project["building_ids"]:
                    raise DocumentError("These sources are not part of this Building.", 422)
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
                raise DocumentError("Building not found or read-only.", 404)
            source.remove(project)
            target.append(project)
            known = set(data.get("known_building_ids", []))
            known.update(item for p in [*projects, *deleted] for item in p["building_ids"])
            _atomic_json(self.path, {**data, "projects": projects, "deleted_projects": deleted,
                                    "known_building_ids": sorted(known)})
            return deepcopy(project)

    @staticmethod
    def shared_group_id(project_id):
        import hashlib
        return hashlib.sha256(('building-sources:' + project_id).encode()).hexdigest()

    def get(self, identity):
        project = next((item for item in self._read() if item['id'] == identity), None)
        if project is None:
            raise DocumentError('Building not found.', 404)
        return deepcopy(project)

    def shared_owners(self, building_id):
        data = json.loads(self.path.read_text()) if self.path.exists() else {}
        return {p['id'] for p in [*data.get('projects', []), *data.get('deleted_projects', [])]
                if building_id in p.get('building_ids', []) or p.get('shared_drawing_building_id') == building_id}

    def require_exclusive_upload(self, building_id):
        if len(self.shared_owners(building_id)) > 1:
            raise DocumentError('These drawings are linked to more than one saved Building. Inspection and chats remain available; create a new Building and upload its drawings to make an independent editable group.', 409)

    def establish_shared_group(self, project_id, building_id):
        with self.store.lock:
            projects = self._read()
            project = next((p for p in projects if p['id'] == project_id), None)
            if project is None:raise DocumentError('Building not found.', 404)
            current = project.get('shared_drawing_building_id')
            if current is not None and current != building_id:
                raise DocumentError('This Building already has a different shared drawing group. Refresh before uploading.', 409)
            project['shared_drawing_building_id'] = building_id
            if building_id not in project['building_ids']:project['building_ids'].append(building_id)
            project['active_building_id'] = building_id
            self._write(projects)
            return deepcopy(project)

    def scope_catalog(self, projects, documents, *, source_free_owners=(), include_deleted=False):
        visible = {d.get('building_id') or d['document_id']: d for d in documents}
        result = []
        for project in projects:
            primary = project.get('shared_drawing_building_id')
            legacy = [identity for identity in project['building_ids'] if identity != primary and identity in visible]
            scopes = [(identity, identity) for identity in legacy]
            if ('shared_drawing_building_id' in project or not project['building_ids']
                    or project['id'] in source_free_owners or 'shared' in project.get('scope_overrides', {})):
                scopes.insert(0, ('shared', primary))
            for scope_id, group_id in scopes:
                if group_id is not None and group_id not in visible:continue
                overrides = project.get('scope_overrides', {}).get(scope_id, {})
                if overrides.get('deleted') and not include_deleted:continue
                document = self.store.get(group_id) if group_id else None
                kind = ('native_ifc' if document.kind == 'ifc' and not (document.scene and document.scene.derived)
                        else 'drawing') if document else None
                read_only = bool(project.get('read_only') or group_id and visible[group_id].get('read_only_model'))
                reason = ('This cached example is read-only. Create another Building to upload drawings.' if read_only
                          else 'Native IFC is a separate Building. Create another Building for additional sources.' if kind == 'native_ifc'
                          else 'These drawings are linked to more than one saved Building. Create a new Building to upload an independent group.' if group_id and len(self.shared_owners(group_id)) > 1 else '')
                name = project['name']
                if scope_id == 'shared' and legacy:name += ' · General chats'
                elif scope_id != 'shared' and len(scopes) > 1:name += ' · ' + visible[group_id]['filename']
                result.append({'id': project['id'] + ':' + scope_id, 'owner_project_id': project['id'],
                    'scope_id': scope_id, 'name': overrides.get('name', name), 'source_group_id': group_id,
                    'building_ids': [group_id] if group_id else [], 'active_building_id': group_id,
                    'read_only': read_only, 'kind': kind, 'upload_allowed': not bool(reason), 'upload_reason': reason,
                    'deleted': bool(overrides.get('deleted')), 'created_at': project.get('created_at', 0)})
        return result

    def update_scope(self, project_id, scope_id, *, name=None, deleted=None):
        with self.store.lock:
            projects = self._read()
            project = next((p for p in projects if p['id'] == project_id), None)
            if project is None:raise DocumentError('Building not found.', 404)
            value = project.setdefault('scope_overrides', {}).setdefault(scope_id, {})
            if name is not None:value['name'] = ProjectName(name=name).name
            if deleted is not None:value['deleted'] = deleted
            self._write(projects)
            return deepcopy(project)
