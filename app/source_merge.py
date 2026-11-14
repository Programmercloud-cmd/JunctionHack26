"""Map independent source interpretations into revision-pinned building coordinates."""
from copy import deepcopy
import json
import uuid
import ifcopenshell.guid
from .building import BuildingDescription, UnmodeledView, SourceObservation
from .documents import DocumentError
from .identities import COLLECTIONS, artifact_namespace


def merge_source_interpretation(document, source_id, description):
    source=next((s for s in document.sources if s['source_id']==source_id),None)
    if source is None:raise DocumentError('Extracted source is no longer in this building.',409)
    original=BuildingDescription.model_validate(description)
    mapping={p['source_page']:p['page']for p in source['pages']}
    def remap(value):
        if isinstance(value,list):return [remap(v)for v in value]
        if not isinstance(value,dict):return value
        if value.get('provenance')=='user_provided':
            raise DocumentError('Source extraction cannot invent user-provided provenance.',422)
        result={k:remap(v)for k,v in value.items()}
        if 'page'in value and 'bbox'in value:
            local=value['page']
            if local not in mapping or value.get('source_id')not in (None,source_id) or value.get('source_page')not in (None,local):
                raise DocumentError('Extraction cited an unknown original source page.',422)
            result.update(page=mapping[local],source_id=source_id,source_page=local)
        return result
    incoming=BuildingDescription.model_validate(remap(original.model_dump()))
    current=document.description or BuildingDescription(floors=[],limitations=[])
    namespace=uuid.UUID(artifact_namespace(document))
    registry=deepcopy(document.identity_registry)or {'version':1,'objects':{},'tombstones':[]}
    def bind(record,key,collection,parent=None):
        identity=ifcopenshell.guid.compress(uuid.uuid5(namespace,source_id+':'+key).hex)
        if identity in registry.get('tombstones',[]):
            identity=ifcopenshell.guid.new()
        record.persistent_id=identity
        registry.setdefault('objects',{})[identity]={'collection':collection,'floor_id':parent}
    def label_key(label):
        return ' '.join(label.casefold().split())
    prior_labels={label_key(f.label)for f in current.floors}
    accepted=[]
    for floor in incoming.floors:
        if label_key(floor.label) in prior_labels:
            incoming.unresolved_views.append(UnmodeledView(label=floor.label,view_type='unknown',source=floor.source,
                reason='Possible alternate view of an already depicted floor. Its relationship is unresolved; no extra storey is generated. Original source interpretation is retained.'))
            incoming.observations.append(SourceObservation(label=floor.label,category='possible_alternate_floor_view',
                source=floor.source,note='Retained source diagram; repeated floor label does not establish another storey.'))
            for collection in COLLECTIONS:
                for item in getattr(floor,collection):
                    incoming.observations.append(SourceObservation(label=item.label,category=collection,
                        source=getattr(item,'source',None)or floor.source,
                        note='Source-supported interpretation from a possible alternate floor view; no extra storey inferred.'))
        else:accepted.append(floor)
    incoming.floors=accepted
    for index,floor in enumerate(incoming.floors):
        bind(floor,f'floor:{index}','floors')
        for collection in COLLECTIONS:
            for i,item in enumerate(getattr(floor,collection)):
                bind(item,f'floor:{index}:{collection}:{i}',collection,floor.persistent_id)
    for index,observation in enumerate(incoming.observations):
        observation.persistent_id=ifcopenshell.guid.compress(uuid.uuid5(namespace,source_id+':observation:'+str(index)).hex)
    # Existing source-specific interpreted geometry cannot be overwritten by a late extraction.
    if source_id in document.source_interpretations:
        old=document.source_interpretations[source_id]
        if old != original.model_dump():
            raise DocumentError('This source already has an interpretation; review a replacement explicitly instead of overwriting refinements.',409)
        return
    document.description=BuildingDescription(
        floors=[*current.floors,*incoming.floors],
        observations=[*current.observations,*incoming.observations],
        unresolved_views=[*current.unresolved_views,*incoming.unresolved_views],
        limitations=list(dict.fromkeys(current.limitations+incoming.limitations+(
            ['Multiple source diagrams are retained separately; matching floors or repeated views are not proven equivalent.']if current.floors and incoming.floors else []))))
    document.source_interpretations[source_id]=original.model_dump()
    document.identity_registry=registry
