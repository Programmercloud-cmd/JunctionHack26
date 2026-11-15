"""Project-owned chat sessions, separate from original source/model bundles."""
from copy import deepcopy
import json
import re
import time
import uuid

from .bundles import _atomic_json
from .documents import DocumentError
from .projects import ProjectName


class ProjectChats:
    def __init__(self, store, projects):
        self.store, self.projects = store, projects
        self.root = store.root.parent / "project-chats"
        self.root.mkdir(exist_ok=True)

    def _path(self, identity):
        if not isinstance(identity, str) or not re.fullmatch(r"[a-f0-9]{32}", identity):
            raise DocumentError("Chat not found in this Building.", 404)
        return self.root / (identity + ".json")

    def get(self, project_id, identity):
        with self.store.lock:
            try:
                record = json.loads(self._path(identity).read_text())
            except (OSError, ValueError):
                raise DocumentError("Chat not found in this Building.", 404) from None
            if record["project_id"] != project_id or record.get("deleted"):
                raise DocumentError("Chat not found in this Building.", 404)
            return record

    @staticmethod
    def summary(record):
        return {key: deepcopy(value) for key, value in record.items() if key not in {"messages", "deleted"}}

    def create(self, project, name="New chat", building_id=None, *, messages=None):
        if building_id is not None and building_id not in project["building_ids"]:
            raise DocumentError("Choose sources from this Building.", 422)
        now = time.time()
        record = {"id": uuid.uuid4().hex, "project_id": project["id"],
                  "name": ProjectName(name=name).name, "building_id": building_id,
                  "created_at": now, "last_active": max((m.get("timestamp", now) for m in messages or []), default=now),
                  "messages": deepcopy(messages or [])}
        with self.store.lock:
            _atomic_json(self._path(record["id"]), record)
        return record

    def catalog(self, project, *, migrate=True):
        with self.store.lock:
            if migrate:
                path = self.root / "legacy-imports.json"
                imports = json.loads(path.read_text()) if path.exists() else {}
                # Historical turns were file-scoped. Import once into its oldest
                # existing project, never into every project referencing that file.
                projects = sorted(self.projects._read(), key=lambda item: item["created_at"])
                for identity in project["building_ids"]:
                    owner = next((p["id"] for p in projects if identity in p["building_ids"]), project["id"])
                    if identity in imports or owner != project["id"]:
                        continue
                    messages = self.store.conversation(identity)
                    if messages:
                        record = self.create(project, "Previous conversation", identity, messages=messages)
                        imports[identity] = record["id"]
                        _atomic_json(path, imports)
            records = [json.loads(path.read_text()) for path in self.root.glob("*.json") if path.name != "legacy-imports.json"]
            return sorted([self.summary(r) for r in records if r["project_id"] == project["id"] and not r.get("deleted")],
                          key=lambda record: record["last_active"], reverse=True)

    @staticmethod
    def effective_building_id(project, record):
        return record.get('building_id') or project.get('shared_drawing_building_id')

    def descriptor(self, project, record):
        return {**self.summary(record), 'effective_building_id': self.effective_building_id(project, record)}

    def source_free_owners(self):
        owners = set()
        for path in self.root.glob('*.json'):
            if path.name == 'legacy-imports.json':continue
            record = json.loads(path.read_text())
            if not record.get('deleted') and record.get('project_id') and record.get('building_id') is None:
                owners.add(record['project_id'])
        return owners

    def scoped_catalog(self, project, scope):
        primary = project.get('shared_drawing_building_id')
        def belongs(record):
            if scope['scope_id'] == 'shared':return record.get('building_id') in {None, primary}
            return record.get('building_id') == scope['source_group_id']
        return [self.descriptor(project, record) for record in self.catalog(project) if belongs(record)]

    def validate_context(self, project, identity, building_id):
        record = self.get(project["id"], identity)
        effective = self.effective_building_id(project, record)
        scope_id = 'shared' if record.get('building_id') is None or effective == project.get('shared_drawing_building_id') else effective
        if project.get('scope_overrides', {}).get(scope_id, {}).get('deleted'):
            raise DocumentError('This Building was removed. Restore it before continuing the chat.', 409)
        if effective != building_id:
            raise DocumentError("The chat's drawing group changed. Reopen this chat before sending.", 409)
        if building_id is not None and building_id not in project["building_ids"]:
            raise DocumentError("The chat's sources are no longer in this Building. Open a current Building chat.", 409)
        return record

    def update(self, project_id, identity, *, name=None, delete=False):
        with self.store.lock:
            record = self.get(project_id, identity)
            if name is not None:
                record["name"] = ProjectName(name=name).name
            if delete:
                record["deleted"] = True
            _atomic_json(self._path(identity), record)
            return self.summary(record)

    def append(self, project, identity, document, request, result):
        with self.store.lock:
            record = self.validate_context(project, identity, document.id if document else None)
            now, user_id = time.time(), uuid.uuid4().hex
            outcome = result.get("answer") or {"status": "clarification" if result["status"] == "clarification" else "conversation",
                "answer": result.get("message", ""), "tool": result["tool"], "clarification": result.get("clarification")}
            record["messages"].extend([
                {"id": user_id, "role": "user", "question": request.message, "request_id": request.request_id,
                 "document_id": document.id if document else None, "revision_id": request.revision_id,
                 "annotation_ids": list(request.annotation_ids), "timestamp": now},
                {"id": uuid.uuid4().hex, "role": "assistant", "answer": deepcopy(outcome), "reply_to": user_id,
                 "request_id": request.request_id, "document_id": document.id if document else None,
                 "revision_id": outcome.get("answered_revision_id") or request.revision_id, "timestamp": now}])
            record["last_active"] = now
            _atomic_json(self._path(identity), record)
            return user_id
