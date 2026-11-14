"""Shared source-grounded reasoning and scope-aware deterministic native calculations."""
import hashlib
import json
import math
import re
from copy import deepcopy
from .providers.gemini import ProviderError


def build_reasoning(document):
    if document.kind=="ifc" and document.scene and not document.scene.derived:
        from .ifc_reasoning import extract_native_reasoning
        if document.source_bytes:
            result=extract_native_reasoning(document.source_bytes,document.scene)
            source_id=hashlib.sha256(document.source_bytes).hexdigest()
            result["source_id"]=source_id
            for record in result["objects"]:
                record["source_id"]=source_id
                record.setdefault("source",{})["source_id"]=source_id
                for value in record.get("values",{}).values():
                    if isinstance(value.get("source"),dict):value["source"]["source_id"]=source_id
            return result
        # Compatibility for caller-created Documents: retained scene properties are a partial view.
        return {"version":1,"source_kind":"native_ifc","objects":[{"id":e.id,"ifc_type":e.ifc_type,"kind":e.kind,"name":e.name,"source":e.source.model_dump(),"storey_id":e.storey_id,
          "type_groups":[e.ifc_type]+({"wall":["IfcWall"],"room":["IfcSpace"],"door":["IfcDoor"],"window":["IfcWindow"]}.get(e.kind,[])),
          "values":{p.name:{"value":p.value,"unit":p.unit,"provenance":"supplied","source":e.source.model_dump()}for p in e.properties if p.origin=="source"},"geometry_available":e.geometry is not None,"missing":["Original IFC bytes unavailable; retained property view only."]}for e in document.scene.elements],
          "relationships":[],"coverage":{"catalog_complete":document.scene.catalog_complete,"property_complete":False,"relationship_complete":False,"missing_containment_ids":[e.id for e in document.scene.elements if not e.storey_id],"warnings":["Original bytes unavailable; property/relationship coverage incomplete."]}}
    scene=document.scene
    description=document.description
    objects=[];floors=[]
    scene_elements={e.id:e for e in scene.elements} if scene else {}
    if description:
        for floor in description.floors:
            source=floor.source.model_dump(mode="json")
            floors.append({"id":floor.persistent_id,"label":floor.label,**source,"order":floor.order})
            for collection,kind in (("rooms","room"),("boundaries","wall"),("openings","opening"),("features","feature"),("unresolved","unresolved")):
                for item in getattr(floor,collection):
                    region=getattr(item,"source",None)
                    item_source={"kind":"image",**(region.model_dump(mode="json") if region else deepcopy(source))}
                    if not region and getattr(item,"polygon",None):
                        points=item.polygon
                        if all(len(point)==2 for point in points):
                            xs,ys=zip(*points)
                            if min(xs)<max(xs) and min(ys)<max(ys):item_source["bbox"]=[min(xs),min(ys),max(xs),max(ys)]
                    associated=scene_elements.get(item.persistent_id)
                    objects.append({"id":item.persistent_id,"kind":getattr(item,"kind",kind),"name":item.label,
                        "floor_id":floor.persistent_id,"source":item_source,"provenance":"interpretation",
                        "evidence_basis":getattr(item,"basis","unknown"),"environment":getattr(item,"environment",None),
                        "note":getattr(item,"note",getattr(item,"reason","")),
                        "geometry_available":bool(associated and associated.geometry),
                        "representation":associated.representation if associated else "not_generated"})
    elif scene:
        # Older portable artifacts may not contain an exact description. Keep their
        # fallible association inventory, never reinterpret it as a native catalog.
        objects=[{"id":e.id,"kind":e.kind,"name":e.name,"floor_id":e.storey_id,"source":e.source.model_dump(),"provenance":"interpretation","evidence_basis":e.evidence_basis,"representation":e.representation,"environment":e.environment,"note":e.note}for e in scene.elements]
        floors=[{"id":f.id,"label":f.label,**f.source.model_dump()}for f in scene.floors]
    observations=[value.model_dump(mode="json") if hasattr(value,"model_dump") else deepcopy(value)
                  for value in getattr(description,"observations",[])] if description else []
    return {"version":2,"source_kind":"drawing","source_note":"Interpretation JSON is fallible. Original pages are authoritative; missing extracted records do not establish missing source evidence. Inferred geometry, display dimensions and concept proposals are not evidence.",
      "objects":objects,"floors":floors,"relationships":[r.model_dump(mode="json") if hasattr(r,"model_dump") else deepcopy(r) for r in getattr(description,"relationships",[])],
      "observations":observations,"interpretation":description.model_dump(mode="json")if description else None,
      "coverage":{"catalog_complete":False,"property_complete":False,"relationship_complete":False,
        "available_pages":[p.number for p in document.pages],"inspected_pages":[p.number for p in document.pages] if description else [],
        "interpretation_status":getattr(document,"interpretation_status","complete" if description else "pending"),
        "sources":source_catalog(document),"warnings":document.warnings}}


def source_catalog(document):
    """Only public provenance metadata, never original bytes or filesystem paths."""
    sources=getattr(document,"sources",[]) or []
    entries=[{key:deepcopy(value) for key,value in source.items() if key in
             {"source_id","filename","filenames","kind","media_type","interpretation_status","warnings"}}for source in sources]
    return {"files":entries,"pages":[{"page":page.number,"source_id":getattr(page,"source_id",None),
        "source_page":getattr(page,"source_page",None),"width":page.width,"height":page.height} for page in document.pages]}


def without_user_provided(value):
    """Remove attributed geometry inputs from drawing-only factual context, without mutating saved data."""
    if isinstance(value,dict):
        if value.get("provenance")=="user_provided":return None
        return {key:without_user_provided(child) for key,child in value.items()}
    if isinstance(value,list):
        return [cleaned for child in value if (cleaned:=without_user_provided(child)) is not None]
    return value


def source_only_question(question):
    """Conservative extra guard: explicit original-source requests never use supplied values."""
    authority=r"(?:drawing|drawings|blueprint|blueprints|plan|plans|source|original IFC)"
    return bool(re.search(r"\b(?:according to|shown (?:on|in)|printed (?:on|in)|established by|from|in) (?:the |these |this )?(?:original )?"+authority+r"\b|\b"+authority+r".*\b(?:establish|show|specif|state|indicat|provid|say)|\b"+authority+r"[ -]only\b",question,re.I))


def relevant_user_values(document,question,*,allow=False):
    if not allow or source_only_question(question):return []
    tokens=set(re.findall(r"[\w]+",question.casefold()))
    values=[]
    for value in getattr(document,"user_values",[]) or []:
        if not isinstance(value,dict):continue
        property_words=set(re.findall(r"[\w]+",str(value.get("property","")).casefold().replace("_"," ")))
        if property_words & tokens or tokens & {"provided","supplied","values","inputs"}:
            values.append({**deepcopy(value),"provenance":"user_provided","evidence_rule":"Provided by user; not observed in original sources."})
    return values


def ensure_reasoning(document):
    if document.reasoning is None:document.reasoning=build_reasoning(document)
    return document.reasoning


def retrieve_context(document, question=""):
    reasoning=ensure_reasoning(document)
    conversational=getattr(document,"conversation_context",None)
    evidence_scope="sources_only" if source_only_question(question) else (conversational or {}).get("evidence_scope","sources_only")
    common={"building_id":document.building_id or document.id,"revision_id":document.revision_id,
        "sources":source_catalog(document),"conversation_context":deepcopy(conversational),
        "conversation_rule":"Earlier assistant answers resolve references only; they are not factual evidence.",
        "user_values":relevant_user_values(document,question,allow=evidence_scope=="sources_and_user"),
        "evidence_scope":evidence_scope}
    if reasoning["source_kind"]!="native_ifc":
        interpretation=deepcopy(reasoning.get("interpretation"))
        if evidence_scope=="sources_only":interpretation=without_user_provided(interpretation)
        return {**common,"source_kind":"drawing",
          "evidence_rule":reasoning["source_note"],"coverage":reasoning["coverage"],"interpretation":interpretation,"objects":reasoning["objects"],
          "observations":reasoning.get("observations",[]),"relationships":reasoning.get("relationships",[]),
          "floors":reasoning.get("floors",[{"id":f.id,"label":f.label,"page":f.source.page,"bbox":f.source.bbox}for f in document.scene.floors]if document.scene else[])}
    tokens=set(re.findall(r"[\w]+",question.casefold()))-{"what","which","the","this","that","these","those","are","is","was","were","be","been","being","of","in","on","at","to","for","from","by","with","as","a","an","and","or","it","its","their","there","does","do","did","have","has","had","model","building","please","how","many"}
    types=[]
    for word,kind in (("wall","IfcWall"),("door","IfcDoor"),("window","IfcWindow"),("room","IfcSpace"),("space","IfcSpace"),("storey","IfcBuildingStorey"),("floor","IfcBuildingStorey"),("slab","IfcSlab"),("stair","IfcStair")):
        if word in tokens or word+"s"in tokens:types.append(kind)
    objects=reasoning["objects"]
    selected=[r for r in objects if not types or any(t in r.get("type_groups",[])for t in types)or r["id"]in question]
    records=[]
    for r in selected:
        values={k:v for k,v in r["values"].items()if not tokens or any(t in k.casefold()for t in tokens)or k in {"Name","Description","PredefinedType","OverallHeight","OverallWidth"}}
        records.append({**{k:v for k,v in r.items()if k!="values"},"values":values,"omitted_value_count":len(r["values"])-len(values)})
    selected_ids={r["id"]for r in selected}
    relationships=[r for r in reasoning["relationships"]if any(rid in json.dumps(r)for rid in selected_ids)]
    return {**common,"source_kind":"native_ifc",
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
