"""Server-owned durable object identities and source/display frame provenance."""
from copy import deepcopy
import hashlib
import json
import uuid

import ifcopenshell.guid

from .documents import DocumentError
from .ifc_import import GLOBAL_ID

COLLECTIONS = {"rooms":"room", "boundaries":"boundary", "openings":"opening",
               "features":"feature", "unresolved":"unresolved"}


def artifact_namespace(document):
    return (document.scene.artifact_id if document.scene and document.scene.derived else None) or str(
        uuid.uuid5(uuid.NAMESPACE_URL, "blueprintqa:" + document.id))


def legacy_guid(namespace, key):
    return ifcopenshell.guid.compress(uuid.uuid5(uuid.UUID(namespace), key).hex)


def records(description):
    for floor in description.floors:
        yield floor, None, "floors"
        for collection in COLLECTIONS:
            for item in getattr(floor, collection):
                yield item, floor, collection


def assign_identities(document, description, *, imported=False):
    """Bind legacy IDs once; fresh model output cannot choose IDs or reuse tombstones."""
    result = description.model_copy(deep=True)
    registry = deepcopy(document.identity_registry) or {"version":1,"objects":{},"tombstones":[]}
    namespace = artifact_namespace(document)
    existing = ({e.id for e in document.scene.elements} | {f.id for f in document.scene.floors}
                if imported and document.scene else set())
    seen = set()
    for i, floor in enumerate(result.floors, 1):
        prefix = f"floor:{i}"
        entries = [(floor,None,"floors",prefix)]
        entries += [(item,floor,collection,f"{prefix}:{role}:{j}")
                    for collection,role in COLLECTIONS.items()
                    for j,item in enumerate(getattr(floor,collection),1)]
        for item,parent,collection,old_key in entries:
            # Stored v4 IDs are authoritative only when they match the actual imported inventory.
            candidate = item.persistent_id if imported and item.persistent_id in existing else (
                new_identity(registry) if not imported and document.scene else legacy_guid(namespace,old_key))
            if imported and existing and candidate not in existing:
                raise DocumentError("The saved description cannot be associated with its original object identities.",422)
            if candidate in seen or candidate in registry.get("tombstones",[]):
                raise DocumentError("An object identity was duplicated or reused after deletion.",422)
            item.persistent_id = candidate
            seen.add(candidate)
            registry.setdefault("objects",{})[candidate] = {"collection":collection,
                "floor_id":parent.persistent_id if parent else None}
    document.identity_registry = registry
    for identity in set(registry.get("objects",{}))-seen:
        registry["objects"].pop(identity,None)
        if identity not in registry["tombstones"]:registry["tombstones"].append(identity)
    if imported and document.scene:
        by_id = {f.persistent_id:f for f in result.floors}
        for floor in document.scene.floors:
            if floor.id in by_id:
                document.frame_registry.setdefault(floor.id, {"transform":deepcopy(floor.transform),
                    "signature":frame_signature(by_id[floor.id]),"known":floor.scale_status=="known",
                    "rotation":floor.rotation_degrees,"aligned":floor.alignment_status=="supported"})
    return result


def new_identity(registry):
    reserved = set(registry.get("objects",{})) | set(registry.get("tombstones",[]))
    while True:
        value = ifcopenshell.guid.new()
        if value not in reserved:
            return value


def validate_identities(description, registry=None):
    seen = set()
    for item,_,_ in records(description):
        if not item.persistent_id or not GLOBAL_ID.fullmatch(item.persistent_id) or item.persistent_id in seen:
            raise DocumentError("Description records require unique persistent IFC identities.",422)
        if registry and item.persistent_id in registry.get("tombstones",[]):
            raise DocumentError("A deleted identity cannot be reassigned.",422)
        seen.add(item.persistent_id)


def expected_registry(description,namespace):
    result={}
    for i,floor in enumerate(description.floors,1):
        prefix=floor.persistent_id or f"floor:{i}"
        fid=floor.persistent_id or legacy_guid(namespace,prefix)
        if not GLOBAL_ID.fullmatch(fid) or fid in result:raise ValueError("Invalid floor identity")
        result[fid]={"collection":"floors","floor_id":None}
        for collection,role in COLLECTIONS.items():
            for j,item in enumerate(getattr(floor,collection),1):
                identity=item.persistent_id or legacy_guid(namespace,f"{prefix}:{role}:{j}")
                if not GLOBAL_ID.fullmatch(identity) or identity in result:raise ValueError("Invalid object identity")
                result[identity]={"collection":collection,"floor_id":fid}
    return result


def frame_signature(floor):
    # Deliberately excludes bbox and label: ordinary refinement cannot move existing geometry.
    values = {"page":floor.source.page,"rotation":floor.rotation_degrees,
              "orientation_basis":floor.orientation_basis,
              "calibration":floor.calibration.model_dump() if floor.calibration else None,
              "alignment":floor.alignment.model_dump() if floor.alignment else None}
    return hashlib.sha256(json.dumps(values,sort_keys=True).encode()).hexdigest()
