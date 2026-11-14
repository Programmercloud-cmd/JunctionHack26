"""Faithful native IFC reasoning records, independent of render/property-view limits."""
import math
from collections import Counter
import ifcopenshell
import ifcopenshell.util.element
import ifcopenshell.util.unit
from .ifc_import import _unit_symbol, _kind


def _ref(entity):
    return {"kind":"ifc", "global_id":getattr(entity,"GlobalId",None), "step_id":entity.id(), "ifc_type":entity.is_a()}


def _value(value):
    if hasattr(value,"wrappedValue"):
        return _value(value.wrappedValue)
    if hasattr(value,"is_a"):
        return _ref(value)
    if isinstance(value,(tuple,list)):
        return [_value(v) for v in value]
    if isinstance(value,float) and not math.isfinite(value):
        return None
    return value


def _geometry(geometry):
    if geometry is None or geometry.type!="mesh":
        return {},["Renderable geometry unavailable; geometry calculations unavailable."]
    points=[geometry.positions[i:i+3]for i in range(0,len(geometry.positions),3)]
    values={}
    for axis,label in enumerate("xyz"):
        values[f"geometry.extent_{label}"]={"value":max(p[axis]for p in points)-min(p[axis]for p in points),"unit":"m","provenance":"calculated","method":"Axis-aligned extent of world-coordinate IFC tessellation; not an oriented element dimension."}
    edges=Counter();area=volume=0;adjacency={}
    for i in range(0,len(geometry.indices),3):
        ia,ib,ic=geometry.indices[i:i+3];a,b,c=points[ia],points[ib],points[ic]
        u=[b[j]-a[j]for j in range(3)];v=[c[j]-a[j]for j in range(3)]
        cross=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]]
        area+=math.sqrt(sum(x*x for x in cross))/2
        volume+=(a[0]*(b[1]*c[2]-b[2]*c[1])-a[1]*(b[0]*c[2]-b[2]*c[0])+a[2]*(b[0]*c[1]-b[1]*c[0]))/6
        for left,right in ((ia,ib),(ib,ic),(ic,ia)):
            # IFC meshes may duplicate vertices at face seams: match exact coordinates.
            p,q=tuple(points[left]),tuple(points[right]);edges[(p,q)]+=1
            adjacency.setdefault(p,set()).add(q);adjacency.setdefault(q,set()).add(p)
    values["geometry.surface_area"]={"value":area,"unit":"m2","provenance":"calculated","method":"Sum of triangle areas in extracted world-coordinate IFC tessellation; includes all modeled faces."}
    closed=bool(edges) and all(count==1 and edges.get((b,a))==1 for (a,b),count in edges.items())
    remaining=set(adjacency);shells=0
    while remaining:
        shells+=1;pending=[remaining.pop()]
        while pending:
            for adjacent in adjacency[pending.pop()]:
                if adjacent in remaining:remaining.remove(adjacent);pending.append(adjacent)
    missing=[]
    if closed and shells==1:
        values["geometry.volume"]={"value":abs(volume),"unit":"m3","provenance":"calculated","method":"Absolute signed tetrahedral sum of a single closed, consistently oriented IFC tessellation shell."}
    else:missing.append("Volume unavailable: tessellation must be a single closed consistently oriented two-manifold shell; disconnected or nested shell interpretation is not established.")
    return values,missing


def extract_native_reasoning(data, scene):
    """Retain original semantic values; scene limits remain presentation-only."""
    if scene.derived:
        raise ValueError("Drawing-derived IFC cannot become native factual reasoning")
    try:text=data.decode("utf-8-sig")
    except UnicodeDecodeError:text=data.decode("latin-1")
    model=ifcopenshell.file.from_string(text)
    from .ifc_artifact import has_artifact_marker
    if has_artifact_marker(model):raise ValueError("Derived IFC marker prohibits native extraction")
    rendered={e.id:e for e in scene.elements};records=[];relationships=[];missing=[]
    schema=ifcopenshell.schema_by_name(model.schema)
    def ancestors(declaration):
        names=[]
        while declaration is not None:
            names.append(declaration.name());declaration=declaration.supertype()
        return names
    supported_types=[d.name()for d in schema.declarations()if hasattr(d,"supertype")and "IfcObjectDefinition"in ancestors(d)]
    object_entities=model.by_type("IfcObjectDefinition")
    length_unit=_unit_symbol(ifcopenshell.util.unit.get_project_unit(model,"LENGTHUNIT"))
    for entity in object_entities:
        gid=getattr(entity,"GlobalId",None);rid=gid or f"step:{entity.id()}"
        record={"id":rid,"ifc_type":entity.is_a(),"name":str(getattr(entity,"Name",None)or entity.is_a()),"kind":_kind(entity),
          "source":_ref(entity),"values":{},"storey_id":None,"missing":[],"geometry_available":bool(gid in rendered and rendered[gid].geometry),
          "type_groups":ancestors(schema.declaration_by_name(entity.is_a()))}
        if not gid:record["missing"].append("Original GlobalId unavailable; STEP reference retained.")
        for index in range(len(entity)):
            name=entity.attribute_name(index);value=entity[index]
            if value is None:continue
            unit=length_unit if name in {"OverallHeight","OverallWidth","Elevation"}else None
            record["values"][name]={"value":_value(value),"unit":unit,"provenance":"supplied","source":_ref(entity),"property_path":name}
        try:
            storey=ifcopenshell.util.element.get_container(entity,ifc_class="IfcBuildingStorey")
            record["storey_id"]=storey.GlobalId if storey else None
        except Exception:record["missing"].append("Containment extraction failed.")
        definitions=[]
        for rel in getattr(entity,"IsDefinedBy",())or():
            if rel.is_a("IfcRelDefinesByProperties"):
                d=rel.RelatingPropertyDefinition
                definitions.extend(("",p)for p in ([d]if hasattr(d,"is_a")else d))
        typ=ifcopenshell.util.element.get_type(entity)
        if typ:definitions.extend(("Type::",p)for p in getattr(typ,"HasPropertySets",())or())
        for prefix,definition in definitions:
            members=getattr(definition,"HasProperties",None)or getattr(definition,"Quantities",None)
            if members is None:
                record["missing"].append(f"Unsupported property definition #{definition.id()}.");continue
            for prop in members:
                name=f"{prefix}{definition.Name or definition.is_a()}.{prop.Name}"
                try:
                    unit=_unit_symbol(ifcopenshell.util.unit.get_property_unit(prop,model))
                    if prop.is_a("IfcPropertySingleValue"):value=_value(prop.NominalValue)
                    elif prop.is_a("IfcPhysicalSimpleQuantity"):value=_value(prop[3])
                    else:value={prop.attribute_name(i):_value(prop[i])for i in range(len(prop))}
                    if name in record["values"]:
                        record["missing"].append(f"Ambiguous duplicate property path {name}; preserved under STEP suffix.")
                        name+=f" [#{prop.id()}]"
                    record["values"][name]={"value":value,"unit":unit,"provenance":"supplied","source":_ref(prop),"owner":_ref(entity),"property_path":name}
                except Exception:record["missing"].append(f"Could not extract property #{prop.id()}.")
        geom,geom_missing=_geometry(rendered[gid].geometry if gid in rendered else None)
        for value in geom.values():value["source"]=_ref(entity);value["contributing_records"]=[rid]
        record["values"].update(geom);record["missing"].extend(geom_missing)
        records.append(record)
    for kind in ("IfcRelContainedInSpatialStructure","IfcRelAggregates","IfcRelVoidsElement","IfcRelFillsElement","IfcRelSpaceBoundary"):
        for rel in model.by_type(kind):
            fields={rel.attribute_name(i):_value(rel[i])for i in range(len(rel))if rel[i]is not None}
            relation={"id":getattr(rel,"GlobalId",None)or f"step:{rel.id()}","ifc_type":rel.is_a(),"source":_ref(rel),"fields":fields,"provenance":"supplied"}
            relationships.append(relation)
    record_ids={r["id"]for r in records}
    unresolved_relationships=[]
    for relationship in relationships:
        for key,value in relationship["fields"].items():
            if not key.startswith(("Relating","Related")):continue
            for ref in value if isinstance(value,list)else[value]:
                if isinstance(ref,dict)and ref.get("global_id")and ref["global_id"]not in record_ids:
                    unresolved_relationships.append({"relationship_id":relationship["id"],"role":key,"reference":ref})
    physical=[r for r in records if("IfcElement"in r["type_groups"]and"IfcFeatureElement"not in r["type_groups"])or"IfcSpace"in r["type_groups"]]
    return {"version":1,"source_kind":"native_ifc","source_note":"Facts describe the supplied IFC model, not guaranteed as-built reality.",
      "objects":records,"relationships":relationships,"unresolved_relationships":unresolved_relationships,"coverage":{"catalog_complete":True,"catalog_scope":"All IfcObjectDefinition records; physical counts exclude subtraction features unless explicitly requested.",
      "supported_entity_types":supported_types,"property_complete":not any(any("property"in m.lower()for m in r["missing"])for r in records),
      "relationship_complete":not unresolved_relationships,"relationship_scope":["IfcRelContainedInSpatialStructure","IfcRelAggregates","IfcRelVoidsElement","IfcRelFillsElement","IfcRelSpaceBoundary"],"missing_containment_ids":[r["id"]for r in physical if not r["storey_id"]],
      "geometry_missing_ids":[r["id"]for r in physical if not r["geometry_available"]],"warnings":scene.warnings+missing},
      "units":{"project_length":length_unit,"geometry_length":"m"}}
