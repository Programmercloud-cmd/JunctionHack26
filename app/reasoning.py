"""Shared source-grounded reasoning and scope-aware deterministic native calculations."""
import hashlib
import json
import math
import re
from .provider import ProviderError


def build_reasoning(document):
    if document.kind=="ifc" and document.scene and not document.scene.derived:
        from .ifc_reasoning import extract_native_reasoning
        if document.source_bytes:
            return extract_native_reasoning(document.source_bytes,document.scene)
        # Compatibility for caller-created Documents: retained scene properties are a partial view.
        return {"version":1,"source_kind":"native_ifc","objects":[{"id":e.id,"ifc_type":e.ifc_type,"kind":e.kind,"name":e.name,"source":e.source.model_dump(),"storey_id":e.storey_id,
          "type_groups":[e.ifc_type]+({"wall":["IfcWall"],"room":["IfcSpace"],"door":["IfcDoor"],"window":["IfcWindow"]}.get(e.kind,[])),
          "values":{p.name:{"value":p.value,"unit":p.unit,"provenance":"supplied","source":e.source.model_dump()}for p in e.properties if p.origin=="source"},"geometry_available":e.geometry is not None,"missing":["Original IFC bytes unavailable; retained property view only."]}for e in document.scene.elements],
          "relationships":[],"coverage":{"catalog_complete":document.scene.catalog_complete,"property_complete":False,"relationship_complete":False,"missing_containment_ids":[e.id for e in document.scene.elements if not e.storey_id],"warnings":["Original bytes unavailable; property/relationship coverage incomplete."]}}
    scene=document.scene
    objects=[{"id":e.id,"kind":e.kind,"name":e.name,"floor_id":e.storey_id,"source":e.source.model_dump(),"provenance":"interpretation","evidence_basis":e.evidence_basis,"representation":e.representation,"environment":e.environment,"note":e.note}for e in scene.elements]if scene else[]
    return {"version":1,"source_kind":"drawing","source_note":"Interpretation JSON is fallible. Original pages are authoritative; inferred geometry, display dimensions and concept proposals are not evidence.",
      "objects":objects,"relationships":[],"interpretation":document.description.model_dump(mode="json")if document.description else None,
      "coverage":{"catalog_complete":False,"property_complete":False,"relationship_complete":False,"inspected_pages":[p.number for p in document.pages],"warnings":document.warnings}}


def ensure_reasoning(document):
    if document.reasoning is None:document.reasoning=build_reasoning(document)
    return document.reasoning


def retrieve_context(document, question=""):
    reasoning=ensure_reasoning(document)
    if reasoning["source_kind"]!="native_ifc":
        return {"source_kind":"drawing","building_id":document.building_id or document.id,"revision_id":document.revision_id,
          "evidence_rule":reasoning["source_note"],"coverage":reasoning["coverage"],"interpretation":reasoning.get("interpretation"),"objects":reasoning["objects"],
          "floors":[{"id":f.id,"label":f.label,"page":f.source.page,"bbox":f.source.bbox}for f in document.scene.floors]if document.scene else[]}
    tokens=set(re.findall(r"[\w]+",question.casefold()))-{"what","which","the","this","are","is","of","in","a","an","and","model","building","please","how","many"}
    types=[]
    for word,kind in (("wall","IfcWall"),("door","IfcDoor"),("window","IfcWindow"),("room","IfcSpace"),("space","IfcSpace"),("storey","IfcBuildingStorey"),("floor","IfcBuildingStorey"),("slab","IfcSlab"),("stair","IfcStair")):
        if word in tokens or word+"s"in tokens:types.append(kind)
    objects=reasoning["objects"]
    selected=[r for r in objects if not types or any(t in r.get("type_groups",[])for t in types)or r["id"]in question or any(t in r["name"].casefold()for t in tokens)]
    records=[]
    for r in selected:
        values={k:v for k,v in r["values"].items()if not tokens or any(t in k.casefold()for t in tokens)or k in {"Name","Description","PredefinedType","OverallHeight","OverallWidth"}}
        records.append({**{k:v for k,v in r.items()if k!="values"},"values":values,"omitted_value_count":len(r["values"])-len(values)})
    selected_ids={r["id"]for r in selected}
    relationships=[r for r in reasoning["relationships"]if any(rid in json.dumps(r)for rid in selected_ids)]
    return {"source_kind":"native_ifc","building_id":document.building_id or document.id,"revision_id":document.revision_id,
      "evidence_rule":reasoning.get("source_note","Facts describe supplied IFC records, not as-built guarantees."),"coverage":reasoning["coverage"],
      "catalog":[{k:r.get(k)for k in ("id","ifc_type","type_groups","name","storey_id","source")}for r in objects],
      "retrieval":{"question":question,"selected_records":len(records),"total_records":len(objects),"all_records_selected":len(records)==len(objects),"property_view_complete":all(r["omitted_value_count"]==0 for r in records),"note":"A selected subset is not the full catalog. Omitted values may exist; calculations use original complete records."},
      "objects":records,"relationships":relationships}


_UNITS={"m":(1,"m"),"mm":(.001,"m"),"cm":(.01,"m"),"ft":(.3048,"m"),"in":(.0254,"m"),
        "m2":(1,"m2"),"m²":(1,"m2"),"mm2":(1e-6,"m2"),"cm2":(1e-4,"m2"),"ft2":(.09290304,"m2"),
        "m3":(1,"m3"),"m³":(1,"m3"),"mm3":(1e-9,"m3"),"cm3":(1e-6,"m3"),"ft3":(.028316846592,"m3")}


def execute_native_calculation(reasoning, calculation):
    """No numeric model operands: resolve values and membership from original records."""
    if reasoning.get("source_kind")!="native_ifc":raise ProviderError("Native calculations require genuinely supplied IFC evidence.")
    records=reasoning["objects"];by_id={r["id"]:r for r in records};c=calculation
    candidates=[r for r in records if not c.entity_type or c.entity_type==r["ifc_type"]or c.entity_type in r.get("type_groups",[])]
    missing=[]
    known_types=set(reasoning["coverage"].get("supported_entity_types",[]))|{"IfcObjectDefinition","IfcElement","IfcFeatureElement","IfcSpace","IfcBuildingStorey","IfcWall","IfcDoor","IfcWindow","IfcSlab","IfcRoof","IfcStair","IfcFurnishingElement"}|{r["ifc_type"]for r in records}|{t for r in records for t in r.get("type_groups",[])}
    if c.entity_type and c.entity_type not in known_types:missing.append("Requested entity type is outside the catalogued type coverage.")
    if c.scope in {"model","storey"}and not reasoning["coverage"].get("catalog_complete"):
        missing.append("Complete source entity catalog is unavailable.")
    if c.scope=="storey":
        if not c.storey_id or c.storey_id not in by_id:missing.append("Requested storey record is unavailable.")
        relevant=[r for r in candidates if r.get("kind")in {"wall","door","window","room"}or"IfcElement"in r.get("type_groups",[])]
        if any(not r.get("storey_id")for r in relevant):missing.append("Some relevant objects have missing containment; storey total could be incomplete.")
        candidates=[r for r in candidates if r.get("storey_id")==c.storey_id]
    elif c.scope=="objects":
        if not c.object_ids or any(i not in by_id for i in c.object_ids):missing.append("Selected object references are missing.")
        candidates=[by_id[i]for i in dict.fromkeys(c.object_ids)if i in by_id]
        if c.entity_type and any(c.entity_type!=r["ifc_type"]and c.entity_type not in r.get("type_groups",[])for r in candidates):missing.append("An object does not belong to the requested entity type.")
    if c.operation=="count":
        if not c.entity_type and c.scope!="objects":missing.append("Count needs an explicit IFC entity type or selected objects; generic object totals are ambiguous.")
        value=len(candidates);unit="records";refs=[{"object_id":r["id"],"property_name":None,"source":r["source"]}for r in candidates]
        method="Count of matching original IFC semantic records, including geometry-less records."
    else:
        refs=[];values=[];units=[]
        operands=[(o.object_id,o.property_name)for o in c.operands]if c.operands else[(r["id"],c.property_name)for r in candidates]
        if not operands:missing.append("No calculation inputs are available.")
        selected_ids={r["id"]for r in candidates}
        if c.operands and c.scope in {"model","storey"}:
            expected={(r["id"],c.property_name)for r in candidates}
            if not c.property_name or set(operands)!=expected or len(operands)!=len(expected):
                missing.append("Explicit inputs do not cover the requested model/storey property aggregate; use selected-object scope for a partial calculation.")
        for rid,name in operands:
            if rid not in selected_ids:
                missing.append(f"Input {rid} is outside the requested calculation scope.");continue
            r=by_id.get(rid);v=(r or{}).get("values",{}).get(name)
            if any(m.startswith(f"Ambiguous duplicate property path {name};")for m in (r or {}).get("missing",[])):
                missing.append(f"Ambiguous original property {rid}:{name}; select a uniquely identified source property.");continue
            if not v or isinstance(v.get("value"),bool)or not isinstance(v.get("value"),(int,float))or not math.isfinite(v["value"]):
                missing.append(f"Numeric original input {rid}:{name} unavailable.");continue
            if v.get("provenance")not in {"supplied","calculated"}:missing.append("Input is not original or deterministically calculated native evidence.");continue
            factor,unit=_UNITS.get(v.get("unit"),(1,v.get("unit")))
            if unit is None:missing.append(f"Unit missing for {rid}:{name}.");continue
            values.append(v["value"]*factor);units.append(unit);refs.append({"object_id":rid,"property_name":name,"source":v.get("source",r["source"]),"provenance":v["provenance"]})
        value=None;unit=units[0]if units else None;method=f"Server {c.operation} of source-bound inputs after supported unit conversion."
        if len(values)!=len(operands):missing.append("Not all requested operands were available; no complete total produced.")
        elif c.operation in {"sum","difference"}and len(set(units))!=1:missing.append("Incompatible units.")
        elif c.operation=="sum":value=sum(values)
        elif c.operation=="product":value=math.prod(values);unit=" * ".join(units)
        elif len(values)!=2:missing.append("Difference/quotient requires two inputs.")
        elif c.operation=="difference":value=values[0]-values[1]
        elif values[1]==0:missing.append("Division by zero.")
        else:value=values[0]/values[1];unit="1"if units[0]==units[1]else" / ".join(units)
    if value is not None and isinstance(value,(int,float))and not math.isfinite(value):missing.append("Calculation result is not finite.")
    result={"status":"incomplete"if missing else"complete","value":None if missing else value,"unit":unit,"method":method,"contributing_records":refs,"missing_inputs":missing,"scope":c.model_dump(mode="json")}
    result["id"]=hashlib.sha256(json.dumps(result,sort_keys=True).encode()).hexdigest()[:16]
    return result
