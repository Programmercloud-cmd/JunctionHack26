"""Targeted description mutations with stable IDs, source checks and loss auditing."""
from copy import deepcopy
import hashlib
import json

from .building import (BuildingDescription, FloorDescription, RoomDescription, BoundaryDescription,
                       OpeningDescription, FeatureDescription, UnresolvedDescription, UnmodeledView)
from .documents import DocumentError
from .identities import COLLECTIONS, records, new_identity, validate_identities, frame_signature
from .review_schema import DescriptionPatch

TYPES={"floors":FloorDescription,"rooms":RoomDescription,"boundaries":BoundaryDescription,
       "openings":OpeningDescription,"features":FeatureDescription,"unresolved":UnresolvedDescription}


def description_hash(description):
    return hashlib.sha256(json.dumps(description.model_dump(),sort_keys=True).encode()).hexdigest()


def normalize_views(description):
    """Retain unsupported source views without manufacturing a placeholder storey."""
    result=description.model_copy(deep=True)
    floor_plans=[]
    for floor in result.floors:
        if floor.view_type=="floor_plan":
            floor_plans.append(floor)
        else:
            result.unresolved_views.append(UnmodeledView(label=floor.label,view_type=floor.view_type,
                source=floor.source,reason="This source view is not an established floor plan; no floor geometry was inferred."))
    result.floors=floor_plans
    return result


def _evidence(document,region):
    from .documents import resolve_reference
    resolve_reference(document,region.page,getattr(region,"source_id",None),getattr(region,"source_page",None))


def _overlap(a,b):
    return a.page==b.page and min(a.bbox[2],b.bbox[2])>max(a.bbox[0],b.bbox[0]) and min(a.bbox[3],b.bbox[3])>max(a.bbox[1],b.bbox[1])


def _record_region(record,floor=None):
    if getattr(record,"source",None) is not None:return record.source
    if getattr(record,"polygon",None):
        from .building import PageRegion
        xs=[p[0]for p in record.polygon];ys=[p[1]for p in record.polygon]
        try:return PageRegion(page=floor.source.page,bbox=[min(xs),min(ys),max(xs),max(ys)])
        except Exception:return None
    return None


def apply_patch(document,patch,review=None,*,enrichment=False):
    patch=DescriptionPatch.model_validate(patch)
    if patch.base_revision_id!=document.revision_id:
        raise DocumentError("Stale description patch; current revision was retained.",409)
    if not document.description or document.kind=="ifc" or (document.scene and not document.scene.derived):
        raise DocumentError("Only a drawing interpretation can receive reconstruction patches.",422)
    if not enrichment and (not document.scene or review is None):
        raise DocumentError("Reviewed corrections require a generated scene and source review.",422)
    candidate=document.snapshot()
    description=candidate.description
    registry=candidate.identity_registry
    issues={issue.id:issue for issue in review.issues} if review else {}
    changed=set();removed=set();added=set()
    base_floors={floor.persistent_id:floor for floor in document.description.floors}
    declared_replacements=_declared_nested_replacements(patch)
    for operation in patch.operations:
        _evidence(document,operation.evidence)
        supported=[issues[i]for i in operation.issue_ids if i in issues and issues[i].actionable
                   and issues[i].category=="extraction"]
        if (not supported and not enrichment) or not operation.reason.strip():
            raise DocumentError("A description correction needs an actionable extraction finding and original-source evidence.",422)
        supported=[issue for issue in supported if _overlap(issue.source,operation.evidence)]
        if not supported and not enrichment:
            raise DocumentError("Correction evidence does not overlap the reviewed original source region.",422)
        floors={f.persistent_id:f for f in description.floors}
        floor=floors.get(operation.floor_id)
        if operation.collection=="floors":
            target_list=description.floors
        elif floor is None:
            raise DocumentError("Correction references an unknown floor identity.",422)
        else:
            target_list=getattr(floor,operation.collection)
        old=next((r for r in target_list if r.persistent_id==operation.target_id),None)
        if operation.action!="add" and old is None:
            raise DocumentError("Correction references a missing or deleted object identity.",409)
        if not enrichment and operation.action!="add" and not any(not issue.object_ids or old.persistent_id in issue.object_ids for issue in supported):
            raise DocumentError("Correction targets an object not identified by the reviewed issue.",422)
        if old:
            target_source=next((e.source for e in document.scene.elements if e.id==old.persistent_id),None) if document.scene else None
            target_source=target_source or _record_region(old,floor)
            if enrichment and target_source and not _regions_touch(target_source,operation.evidence):
                raise DocumentError("Geometry enrichment cannot change an unrelated source region.",422)
            if not enrichment and not any(old.persistent_id in issue.object_ids or (not issue.object_ids and target_source
                       and _overlap(target_source,issue.source) and _overlap(target_source,operation.evidence))for issue in supported):
                raise DocumentError("A source-region finding cannot change an unrelated object.",422)
        if old and old.persistent_id in changed:
            raise DocumentError("Conflicting repeated operations on the same object are not applied.",422)
        if operation.action=="remove":
            if enrichment:
                raise DocumentError("Geometry enrichment cannot discard existing interpretation records.",422)
            if operation.record is not None:
                raise DocumentError("Removal must not supply replacement geometry.",422)
            target_list.remove(old)
            identities=[old.persistent_id]
            if operation.collection=="floors":
                identities += [item.persistent_id for name in COLLECTIONS for item in getattr(old,name)]
            for identity in identities:
                registry.setdefault("objects",{}).pop(identity,None)
                if identity not in registry.setdefault("tombstones",[]):registry["tombstones"].append(identity)
                removed.add(identity)
            changed.add(old.persistent_id)
            continue
        if operation.record is None:
            raise DocumentError("Correction is missing its typed description record.",422)
        try:
            record=TYPES[operation.collection].model_validate(operation.record.model_dump())
        except Exception:
            raise DocumentError("Correction record does not match its declared collection.",422) from None
        if operation.collection=="floors":
            if record.view_type!="floor_plan":
                raise DocumentError("Unsupported views cannot be inserted as building floors.",422)
            if old:
                _retain_staged_floor_records(record,old,base_floors.get(old.persistent_id),declared_replacements)
            if not old and not any(getattr(record,name)for name in COLLECTIONS):
                raise DocumentError("An empty proposed floor provides no supported reconstruction; retain it as unresolved source evidence.",422)
        if getattr(record,"source",None) is not None and record.source.page!=operation.evidence.page:
            raise DocumentError("Correction record and evidence reference different source pages.",422)
        if not old:
            proposed_source=_record_region(record,floor)
            if not proposed_source or not _regions_touch(proposed_source,operation.evidence) or (not enrichment and not any(_overlap(proposed_source,i.source)for i in supported)):
                raise DocumentError("An inserted object must be associated with its reviewed source region.",422)
        if old:
            if record.persistent_id not in (None,old.persistent_id):
                raise DocumentError("A replacement cannot change the object's persistent identity.",422)
            record.persistent_id=old.persistent_id
            if operation.collection=="boundaries" and record.key!=old.key:
                raise DocumentError("A wall key is stable; revise its dependent openings explicitly rather than renaming a host.",422)
            target_list[target_list.index(old)]=record
        else:
            # Never accept identity assignments from a runtime model.
            record.persistent_id=new_identity(registry)
            registry.setdefault("objects",{})[record.persistent_id]={"collection":operation.collection,
                "floor_id":floor.persistent_id if floor else None}
            if operation.collection=="floors":
                for name in COLLECTIONS:
                    for item in getattr(record,name):
                        item.persistent_id=new_identity(registry)
                        registry["objects"][item.persistent_id]={"collection":name,"floor_id":record.persistent_id}
                        added.add(item.persistent_id)
            target_list.append(record)
            added.add(record.persistent_id)
        changed.add(record.persistent_id)
    updates={update.floor_id:update for update in patch.transform_updates}
    if len(updates)!=len(patch.transform_updates):
        raise DocumentError("Duplicate transform updates are not applied.",422)
    for floor in description.floors:
        saved=candidate.frame_registry.get(floor.persistent_id)
        if saved and saved["signature"]!=frame_signature(floor):
            update=updates.get(floor.persistent_id)
            if not update or not update.reason.strip():
                raise DocumentError("A supported calibration/orientation change requires an explicit transform update.",422)
            _evidence(document,update.evidence)
            if update.evidence.page!=floor.source.page:
                raise DocumentError("Transform evidence references another page.",422)
            candidate.frame_registry.pop(floor.persistent_id,None)
    if _provided_fields(description.model_dump(mode="json")) != _provided_fields(document.description.model_dump(mode="json")):
        raise DocumentError("Model patches cannot invent, remove or alter user-provided provenance. Apply supplied values through the explicit input workflow.",422)
    validate_identities(description,registry)
    _validate_all_sources(document,description.model_dump(mode="json"))
    if not enrichment and description_hash(description)==description_hash(document.description):
        raise DocumentError("The proposed correction makes no material description change.",422)
    return candidate,{"changed_ids":sorted(changed),"added_ids":sorted(added),"removed_ids":sorted(removed),
                      "transform_updates":[u.model_dump()for u in patch.transform_updates]}


def _declared_nested_replacements(patch):
    """Index redundant copies only; this does not approve or execute an operation."""
    replacements={}
    for operation in patch.operations:
        if operation.action!="replace" or operation.collection not in COLLECTIONS or operation.record is None:
            continue
        try:record=TYPES[operation.collection].model_validate(operation.record.model_dump())
        except Exception:continue  # The operation itself still fails normal typed validation.
        if record.persistent_id not in (None,operation.target_id):continue
        record.persistent_id=operation.target_id
        key=(operation.floor_id,operation.collection,operation.target_id)
        replacements.setdefault(key,[]).append(record)
    return replacements


def _retain_staged_floor_records(proposed,staged,base,replacements):
    """A floor operation changes metadata, never nested records copied into its payload."""
    if base is None:
        raise DocumentError("A floor metadata patch requires its original floor identity.",422)
    for collection in COLLECTIONS:
        supplied=getattr(proposed,collection)
        original=getattr(base,collection)
        current=getattr(staged,collection)
        identities=[record.persistent_id for record in supplied]
        if identities not in ([record.persistent_id for record in original],
                               [record.persistent_id for record in current]):
            raise DocumentError("A floor metadata patch cannot change nested identity order or length.",422)
        originals={record.persistent_id:record for record in original}
        staged_records={record.persistent_id:record for record in current}
        for record in supplied:
            key=(staged.persistent_id,collection,record.persistent_id)
            permitted=[originals.get(record.persistent_id),staged_records.get(record.persistent_id),
                       *replacements.get(key,[])]
            if not any(record==allowed for allowed in permitted if allowed is not None):
                raise DocumentError("A floor metadata patch cannot rewrite unrelated nested objects.",422)
        # Even an exact future replacement copy remains inert until its separately
        # declared operation passes source, review, identity and conflict checks.
        setattr(proposed,collection,current)


def regression_findings(before,after,changes):
    """Local loss checks complement visual review; rendering success alone is insufficient."""
    findings=[]
    if not after.scene:
        return ["Candidate has no reopened geometry scene."]
    if not any(e.geometry for e in after.scene.elements):
        findings.append("Candidate lost all usable geometry.")
    old={e.id:e for e in before.scene.elements} if before.scene else {};new={e.id:e for e in after.scene.elements}
    removed=set(changes.get("removed_ids",[]))
    for identity,element in old.items():
        if identity in removed:continue
        if identity not in new:
            findings.append(f"Unrequested object disappeared: {identity}")
        elif element.geometry and not new[identity].geometry:
            findings.append(f"Previously renderable object became unresolved/unrenderable: {identity}")
    before_floors={f.id:f for f in before.scene.floors} if before.scene else {}
    explicit={u["floor_id"]for u in changes.get("transform_updates",[])}
    for floor in after.scene.floors:
        if floor.id in before_floors and floor.id not in explicit and floor.transform!=before_floors[floor.id].transform:
            findings.append(f"An unchanged source/display frame moved: {floor.id}")
    return findings


def _regions_touch(a,b):
    """A line-shaped opening citation may intersect a positive-area inspection region."""
    return a.page==b.page and min(a.bbox[2],b.bbox[2])>=max(a.bbox[0],b.bbox[0]) and min(a.bbox[3],b.bbox[3])>=max(a.bbox[1],b.bbox[1])


def _validate_all_sources(document,value):
    if isinstance(value,dict):
        if "page" in value and "bbox" in value:
            from .documents import resolve_reference
            resolve_reference(document,value["page"],value.get("source_id"),value.get("source_page"))
        for child in value.values():_validate_all_sources(document,child)
    elif isinstance(value,list):
        for child in value:_validate_all_sources(document,child)


def apply_enrichment(document,patch):
    """Source-validated additions to saved interpretation, without pretending prior review."""
    return apply_patch(document,patch,enrichment=True)


def needs_geometry(description):
    from .geometry_requirements import missing_geometry_requests
    return bool(missing_geometry_requests(description))


def _provided_fields(value,path=()):
    result={}
    if isinstance(value,dict):
        if value.get("persistent_id"):path=(value["persistent_id"],)
        if value.get("provenance")=="user_provided":result[path]=json.dumps(value,sort_keys=True)
        for key,child in value.items():result.update(_provided_fields(child,path+(key,)))
    elif isinstance(value,list):
        for index,child in enumerate(value):result.update(_provided_fields(child,path+(index,)))
    return result
