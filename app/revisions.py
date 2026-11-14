"""Targeted description mutations with stable IDs, source checks and loss auditing."""
from copy import deepcopy
import hashlib
import json

from .building import (BuildingDescription, FloorDescription, RoomDescription, BoundaryDescription,
                       OpeningDescription, FeatureDescription, UnresolvedDescription, UnmodeledView)
from .documents import DocumentError
from .identities import COLLECTIONS, records, new_identity, validate_identities, frame_signature
from .review_schema import DescriptionPatch, AdditionalTargetRequest, AuthorizationReview
from pydantic import BaseModel, ConfigDict, PrivateAttr

TYPES={"floors":FloorDescription,"rooms":RoomDescription,"boundaries":BoundaryDescription,
       "openings":OpeningDescription,"features":FeatureDescription,"unresolved":UnresolvedDescription}


class PatchRejection(DocumentError):
    def __init__(self, code, explanation, *, expected_contract="Correct the cited contract without changing unrelated records.", **context):
        super().__init__(explanation,422)
        self.feedback={"code":code,"explanation":explanation,"expected_contract":expected_contract,**context}


_GRANT_SEAL=object()
class SupplementalAuthorization(BaseModel):
    model_config=ConfigDict(frozen=True)
    base_revision_id: str
    request_id: str
    issue_id: str
    target_id: str
    floor_id: str | None
    collection: str
    evidence: dict
    reason: str
    _seal: object = PrivateAttr(default=None)
    _bound: str = PrivateAttr(default="")


def proposal_fingerprint(patch):
    value=DescriptionPatch.model_validate(patch).model_dump(mode="json")
    for group in ("operations","floor_metadata_updates","additional_target_requests","transform_updates"):
        for item in value[group]:
            item.pop("reason",None);item.pop("request_id",None)
            if "issue_ids" in item:item["issue_ids"]=sorted(item["issue_ids"])
            if group=="floor_metadata_updates":item["changes"]=sorted(item["changes"],key=lambda change:change["field"])
        value[group]=sorted(value[group],key=lambda item:json.dumps(item,sort_keys=True))
    return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()


def _request_failure(code, message, document, request=None):
    context={"base_revision_id":document.revision_id}
    if request:context.update(request_id=request.request_id,target_id=request.target_id,issue_ids=[request.issue_id],floor_id=request.floor_id)
    raise PatchRejection(code,message,**context)


def validate_target_requests(document,review,requests):
    requests=[AdditionalTargetRequest.model_validate(r) for r in requests]
    issues={i.id:i for i in review.issues};seen=set();targets=set()
    owners={}
    for current_floor in document.description.floors:
        owners[current_floor.persistent_id]=current_floor.persistent_id
        for collection in COLLECTIONS:
            owners.update({item.persistent_id:current_floor.persistent_id for item in getattr(current_floor,collection)})
    for request in requests:
        if request.request_id in seen or (request.issue_id,request.target_id) in targets:
            _request_failure("duplicate_target_request","Target requests must identify each issue/target exactly once.",document,request)
        seen.add(request.request_id);targets.add((request.issue_id,request.target_id))
        if request.base_revision_id!=document.revision_id:
            raise DocumentError("Stale target request; current revision was retained.",409)
        issue=issues.get(request.issue_id)
        if not issue or not issue.actionable or issue.category!="extraction" or not request.reason.strip():
            _request_failure("invalid_target_issue","Additional targets require an actionable extraction issue and specific rationale.",document,request)
        floor=next((f for f in document.description.floors if f.persistent_id==request.floor_id),None)
        if request.collection=="floors":
            target=next((f for f in document.description.floors if f.persistent_id==request.target_id),None)
            if request.floor_id not in (None,request.target_id):target=None
        else:
            target=next((r for r in getattr(floor,request.collection,[]) if r.persistent_id==request.target_id),None)
        if target is None:
            _request_failure("unknown_target","Requested target must exist in the specified floor and collection.",document,request)
        if issue.object_ids:
            if any(identity not in owners for identity in issue.object_ids):
                _request_failure("unknown_issue_target","Reviewed issue contains an unavailable object; refresh its source review before extending authority.",document,request)
            issue_floors={owners[identity] for identity in issue.object_ids}
            if owners[request.target_id] not in issue_floors:
                _request_failure("cross_floor_target","Additional target must belong to a floor explicitly identified by the reviewed issue.",document,request)
        try:_evidence(document,request.evidence)
        except DocumentError:_request_failure("invalid_target_source","Requested target evidence must identify an available original source.",document,request)
        region=_record_region(target,floor)
        if (not region or not _overlap(issue.source,request.evidence) or not _regions_touch(region,request.evidence)
                or (not issue.object_ids and not _regions_touch(region,issue.source))):
            _request_failure("unrelated_target_source","Requested target and reviewed issue must share inspected original-source context.",document,request)
    return requests


def authorize_targets(document,review,requests,decision):
    requests=validate_target_requests(document,review,requests)
    decision=AuthorizationReview.model_validate(decision)
    if decision.base_revision_id!=document.revision_id:raise DocumentError("Stale target decision; current revision was retained.",409)
    expected={r.request_id:r for r in requests};seen=set();grants=[]
    for item in decision.decisions:
        request=expected.get(item.request_id)
        if not request or item.request_id in seen or item.issue_id!=request.issue_id or item.target_id!=request.target_id:
            _request_failure("invalid_target_decision","Reviewer must return exactly one matching decision for each requested target.",document)
        seen.add(item.request_id)
        try:_evidence(document,item.evidence)
        except DocumentError:_request_failure("invalid_target_decision_source","Reviewer evidence must identify an available original source.",document,request)
        if not item.reason.strip() or not _overlap(item.evidence,request.evidence):
            _request_failure("invalid_target_decision_source","Reviewer must cite the requested original context and explain its decision.",document,request)
        if item.decision=="approved":
            inspected=request.model_copy(update={"evidence":item.evidence,"reason":item.reason})
            validate_target_requests(document,review,[inspected])
            grant=SupplementalAuthorization(base_revision_id=document.revision_id,request_id=request.request_id,issue_id=request.issue_id,
                target_id=request.target_id,floor_id=request.floor_id,collection=request.collection,evidence=item.evidence.model_dump(),reason=item.reason)
            grant._seal=_GRANT_SEAL
            grant._bound=hashlib.sha256(grant.model_dump_json().encode()).hexdigest()
            grants.append(grant)
    if seen!=set(expected):_request_failure("missing_target_decision","Reviewer omitted a requested target decision.",document)
    return grants


def _with_authorizations(document,review,authorizations):
    result=review.model_copy(deep=True) if review else None
    for grant in authorizations:
        if not isinstance(grant,SupplementalAuthorization) or grant._seal is not _GRANT_SEAL or grant._bound!=hashlib.sha256(grant.model_dump_json().encode()).hexdigest() or grant.base_revision_id!=document.revision_id:
            raise PatchRejection("invalid_authorization","Only server-validated grants for this exact revision may authorize targets.")
        issue=next((i for i in result.issues if i.id==grant.issue_id),None) if result else None
        if not issue or not issue.actionable or issue.category!="extraction":raise PatchRejection("invalid_authorization","Grant issue is no longer actionable.")
        # Revalidate registry/source membership even for a previously approved grant.
        validate_target_requests(document,review,[AdditionalTargetRequest(request_id=grant.request_id,base_revision_id=grant.base_revision_id,
            issue_id=grant.issue_id,target_id=grant.target_id,floor_id=grant.floor_id,collection=grant.collection,evidence=grant.evidence,reason=grant.reason)])
        if issue.object_ids and grant.target_id not in issue.object_ids:issue.object_ids.append(grant.target_id)
    return result


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


def apply_patch(document,patch,review=None,*,enrichment=False,authorizations=()):
    patch=DescriptionPatch.model_validate(patch)
    context={"base_revision_id":patch.base_revision_id,"proposal_sha256":proposal_fingerprint(patch)}
    if patch.base_revision_id!=document.revision_id:raise DocumentError("Stale description patch; current revision was retained.",409)
    review=_with_authorizations(document,review,authorizations)
    expanded=patch.model_copy(deep=True)
    metadata_indices={};seen=set()
    for index,update in enumerate(patch.floor_metadata_updates):
        fields=[change.field for change in update.changes]
        if not fields or len(fields)!=len(set(fields)) or update.floor_id in seen:
            raise PatchRejection("conflicting_metadata","Metadata edits must be nonempty with unique fields and floor targets.",metadata_update_index=index,**context)
        seen.add(update.floor_id)
        if any(o.collection=="floors" and o.target_id==update.floor_id for o in patch.operations):
            raise PatchRejection("conflicting_metadata","Do not combine a legacy floor replacement and metadata changes for the same floor.",metadata_update_index=index,**context)
        floor=next((f for f in document.description.floors if f.persistent_id==update.floor_id),None)
        if floor is None:raise PatchRejection("unknown_metadata_floor","Metadata edits require an existing floor.",metadata_update_index=index,**context)
        changed=floor.model_copy(deep=True)
        for change in update.changes:setattr(changed,change.field,change.value)
        from .review_schema import RecordPatch
        metadata_indices[len(expanded.operations)]=index
        expanded.operations.append(RecordPatch(action="replace",collection="floors",target_id=update.floor_id,record=changed,
            evidence=update.evidence,reason=update.reason,issue_ids=update.issue_ids))
    try:return _apply_patch(document,expanded,review,enrichment=enrichment,_context=context)
    except PatchRejection:raise
    except DocumentError as error:
        if error.status!=422:raise
        mapping={
          "A floor metadata patch cannot change nested identity order or length.":("nested_floor_edit","Use floor_metadata_updates for metadata; use separate explicit operations for nested objects."),
          "A floor metadata patch cannot rewrite unrelated nested objects.":("nested_floor_edit","Use floor_metadata_updates; preserve unrelated records."),
          "Correction targets an object not identified by the reviewed issue.":("unauthorized_target","Request this exact additional target with original evidence and rationale; only reviewer-approved targets may change."),
          "Correction is missing its typed description record.":("missing_record","Provide the collection's typed record for add/replace; use explicit null only for remove."),
          "Correction record does not match its declared collection.":("wrong_record_type","Provide the typed record corresponding to collection."),
          "Conflicting repeated operations on the same object are not applied.":("conflicting_operations","Provide one explicit operation per object."),
          "The proposed correction makes no material description change.":("no_material_change","Provide a supported material correction or leave the finding unresolved."),
        }
        if error.message not in mapping:raise
        code,expected=mapping[error.message]
        if context.get("operation_index") in metadata_indices:context["metadata_update_index"]=metadata_indices[context["operation_index"]]
        raise PatchRejection(code,error.message,expected_contract=expected,**context) from None


def _apply_patch(document,patch,review=None,*,enrichment=False,_context=None):
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
    for operation_index,operation in enumerate(patch.operations):
        if _context is not None:_context.update(operation_index=operation_index,target_id=operation.target_id,floor_id=operation.floor_id,issue_ids=operation.issue_ids)
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
