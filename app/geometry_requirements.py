"""Explicit geometry gaps shared by routing and source enrichment instructions."""

def missing_geometry_requests(description):
    if description is None:return [{'collection':'floors','fields':['description'],'reason':'No interpretation is saved.'}]
    requests=[]
    floors=description.floors
    ordered=[f for f in floors if f.order is not None and f.order_basis.strip()]
    reference=min(ordered,key=lambda f:f.order) if len(ordered)==len(floors) and ordered else (floors[0] if floors else None)
    def add(floor,collection,item,fields,reason):
        requests.append({'floor_id':floor.persistent_id,'collection':collection,
            'target_id':item.persistent_id if item else None,'fields':fields,'reason':reason})
    for floor in floors:
        if not any(getattr(floor,key)for key in ['rooms','boundaries','openings','features','unresolved']):
            add(floor,'floors',floor,['rooms','boundaries','openings','features','unresolved'],'Source-only interpretation has no physical feature inventory. Inspect all meaningful source features; unsupported features remain unresolved.')
        elif not floor.boundaries and floor.rooms:
            add(floor,'boundaries',None,['inventory'],'Explicit physical walls/openings are not traced. Inspect visible boundaries, openings and meaningful features, without enclosing room polygons automatically.')
        if len(floors)>1 and floor is not reference and not floor.registration and not floor.alignment:
            add(floor,'floors',floor,['registration'],f'Placement relative to reference floor {reference.persistent_id} is not described. Use supported source anchors, otherwise explicitly unclear.')
        for item in floor.rooms:
            if not item.polygon:add(floor,'rooms',item,['polygon'],'Room footprint is absent.')
        for item in floor.boundaries:
            if not item.segment and not item.footprint:add(floor,'boundaries',item,['segment','footprint'],'Neither wall segment nor footprint exists. Either supported representation is sufficient.')
        for item in floor.openings:
            if not item.segment:add(floor,'openings',item,['segment','host_wall'],'Depicted gap endpoints are absent; unsupported host remains unresolved.')
        for item in floor.features:
            fields=[]
            if not item.polygon:fields.append('polygon')
            if len(floors)>1 and item.kind=='stairs' and not item.connection:fields.append('connection')
            if fields:add(floor,'features',item,fields,'Supported footprint or explicit inter-floor relationship is missing; unknown vertical dimensions remain display assumptions.')
    return requests
