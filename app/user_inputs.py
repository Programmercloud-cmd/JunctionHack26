"""Typed, attributed user inputs and grouped missing-information rows."""
from copy import deepcopy
import math
import re
import time
import uuid
from typing import Literal
from pydantic import Field, field_validator
from .schemas import StrictModel
from .building import PageRegion, Calibration, StairConnection
from .documents import DocumentError, resolve_reference


PROPERTIES=("floor_height","display_height","calibration","stair_connection","interpretation_correction")
METRES={"m":1.,"mm":.001,"cm":.01,"ft":.3048,"in":.0254}


class InputScope(StrictModel):
    floor_id: str | None = None
    object_id: str | None = None


class UserEdit(StrictModel):
    property: Literal["floor_height","display_height","calibration","stair_connection","interpretation_correction"]
    scope: InputScope
    value: float | str | dict
    unit: str | None = None
    source: PageRegion | None = None
    reason: str = ""

    @field_validator("value",mode="before")
    @classmethod
    def no_boolean_value(cls,value):
        if isinstance(value,bool):raise ValueError("Boolean values are not dimensions or interpretation corrections")
        return value


class RefinementRequest(StrictModel):
    base_revision_id: str
    edits: list[UserEdit] = Field(min_length=1)
    supporting_source_ids: list[str] = Field(default_factory=list)


def _numeric(value):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<=0:
        raise DocumentError("Provide a finite positive dimension.",422)
    return float(value)


def assumptions(document):
    rows=[]
    def row(identity,scope,prop,label,value,unit,provenance,reason,source=None,editable=False):
        rows.append({"id":identity,"scope":scope,"property":prop,"label":label,"value":value,"unit":unit,
            "provenance":provenance,"reason":reason,"source":source,"editable":editable})
    if document.description:
        scenes={floor.id:floor for floor in document.scene.floors} if document.scene else {}
        for floor in document.description.floors:
            scope={"floor_id":floor.persistent_id};source=floor.source.model_dump(mode="json")
            height=floor.height
            row(f"{floor.persistent_id}:floor_height",scope,"floor_height",f"{floor.label}: storey height",
                height.value if height else None,height.unit if height else "m","observed" if height and height.status=="observed" else "unknown",
                height.note if height else "No storey height is established by the original interpretation.",
                height.source.model_dump(mode="json") if height and height.source else source,True)
            calibration=floor.calibration
            row(f"{floor.persistent_id}:calibration",scope,"calibration",f"{floor.label}: known plan distance",
                {"length":calibration.length_m,"segment":calibration.segment} if calibration else None,"m",
                getattr(calibration,"provenance","observed") if calibration else "unknown",
                calibration.note if calibration else "A known plan distance and its endpoints can establish horizontal scale.",source,True)
            seen=set()
            scene=scenes.get(floor.persistent_id)
            for assumption in scene.assumptions if scene else []:
                if assumption.property in seen:continue
                seen.add(assumption.property)
                row(f"{floor.persistent_id}:display:{assumption.property}",scope,assumption.property,
                    f"{floor.label}: {assumption.property.replace('_',' ')}",assumption.value,assumption.unit,
                    "display_assumption",assumption.reason,source,assumption.property in {"display_height","floor_height"})
            for feature in floor.features:
                if feature.kind=="stairs":
                    row(f"{feature.persistent_id}:stair_connection",{"floor_id":floor.persistent_id,"object_id":feature.persistent_id},
                        "stair_connection",f"{feature.label}: connects to",feature.connection.model_dump(mode="json") if feature.connection else None,None,
                        feature.connection.provenance if feature.connection else "unknown",feature.connection.basis if feature.connection else "Destination storey is not established.",feature.source.model_dump(mode="json"),True)
            for item in floor.unresolved:
                row(f"{item.persistent_id}:interpretation_correction",{"floor_id":floor.persistent_id,"object_id":item.persistent_id},
                    "interpretation_correction",item.label,None,None,"unknown",item.reason,item.source.model_dump(mode="json"),True)
            for item in floor.rooms+floor.boundaries+floor.openings+floor.features:
                if getattr(item,"basis",None)=="inferred":
                    ref=getattr(item,"source",None) or floor.source
                    row(f"{item.persistent_id}:interpretation_correction",{"floor_id":floor.persistent_id,"object_id":item.persistent_id},
                        "interpretation_correction",item.label,getattr(item,"note",""),None,"inferred",
                        "Fallible interpretation; provide a correction with supporting source if available.",ref.model_dump(mode="json"),True)
        for observation in document.description.observations:
            row(observation.persistent_id or f"observation:{len(rows)}",{},observation.category,observation.label,observation.value,
                observation.unit,observation.basis,observation.note,observation.source.model_dump(mode="json"),False)
    for value in document.user_values:
        row(value["id"],value.get("scope",{}),value["property"],value["property"].replace('_',' '),value["value"],value.get("unit"),
            "user_provided",value.get("reason") or "Provided by user, not observed in the original drawing.",value.get("source"),True)
    return {"building_id":document.id,"revision_id":document.revision_id,"rows":rows,"editable_properties":list(PROPERTIES)}


def prepare_inputs(document,request):
    """Validate all edits before applying any; retain observed fields independently."""
    request=RefinementRequest.model_validate(request)
    if request.base_revision_id!=document.revision_id:raise DocumentError("The building revision changed; refresh before applying inputs.",409)
    if document.kind=="ifc":raise DocumentError("User refinement does not rewrite a supplied native IFC.",422)
    if document.description is None:raise DocumentError("Wait for source interpretation before refining scoped values.",409)
    source_ids={s["source_id"] for s in document.sources}
    if not set(request.supporting_source_ids)<=source_ids:raise DocumentError("A supporting source does not belong to this building.",422)
    candidate=document.snapshot();floors={f.persistent_id:f for f in candidate.description.floors}
    objects={item.persistent_id:(floor,item) for floor in candidate.description.floors for name in ("rooms","boundaries","openings","features","unresolved") for item in getattr(floor,name)}
    submitted=[];seen=set();conflicts=[];needs_model=False;transform_updates=[]
    for edit in request.edits:
        scope=edit.scope.model_dump(exclude_none=True);floor=floors.get(edit.scope.floor_id);item=None
        if edit.scope.object_id:
            pair=objects.get(edit.scope.object_id)
            if not pair or (floor and pair[0].persistent_id!=floor.persistent_id):raise DocumentError("Input scope references an unavailable object or another floor.",422)
            floor,item=pair;scope["floor_id"]=floor.persistent_id
        if floor is None:raise DocumentError("Choose the floor affected by this input.",422)
        key=(floor.persistent_id,edit.scope.object_id,edit.property)
        if key in seen:raise DocumentError("Submit one value per affected property and scope.",422)
        seen.add(key)
        if edit.source:resolve_reference(document,edit.source.page,edit.source.source_id,edit.source.source_page)
        value=deepcopy(edit.value)
        if edit.property in {"floor_height","display_height"}:
            value=_numeric(value)
            if edit.unit not in METRES and not (edit.property=="display_height" and edit.unit=="relative"):
                raise DocumentError("Height units must be m, mm, cm, ft or in; display height may use relative units.",422)
            if floor.height and floor.height.status=="observed" and floor.height.unit in METRES and edit.unit in METRES:
                if not math.isclose(value*METRES[edit.unit],floor.height.value*METRES[floor.height.unit],rel_tol=1e-8):
                    conflicts.append({"property":edit.property,"scope":scope,"source":floor.height.source.model_dump(mode="json"),
                        "message":"The supplied height conflicts with an observed source height. Both values retain their provenance."})
            if edit.unit in METRES:
                for observation in [*floor.measurements,*candidate.description.observations]:
                    if getattr(observation,"status",getattr(observation,"basis",None))!="observed":continue
                    category=f"{getattr(observation,'category','')} {observation.label}".replace('_',' ')
                    if not re.search(r"\b(height|ceiling|storey height|floor height|korkeus|hauteur|höhe)\b",category,re.I):continue
                    if not observation.source:continue
                    observed=observation.value;unit=observation.unit
                    try:known=float(observed) if not isinstance(observed,bool) else None
                    except (TypeError,ValueError):known=None
                    if known is not None and math.isfinite(known) and unit in METRES and math.isclose(value*METRES[edit.unit],known*METRES[unit],rel_tol=1e-8):continue
                    conflicts.append({"property":edit.property,"scope":scope,"source":observation.source.model_dump(mode="json"),
                        "observed_value":observed,"observed_unit":unit,"observation_label":observation.label,
                        "message":"An original height observation may apply to this floor and differs or cannot be compared. Resolve its scope before replacing display geometry; both inputs are retained."})
        elif edit.property=="calibration":
            if not isinstance(value,dict) or set(value)!={"length","segment"} or edit.unit not in METRES:
                raise DocumentError("Calibration needs {length,segment} and a physical length unit.",422)
            length=_numeric(value["length"]);segment=value["segment"]
            if (not isinstance(segment,list) or len(segment)!=2 or any(not isinstance(p,list) or len(p)!=2 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not 0<=v<=1 for v in p) for p in segment) or segment[0]==segment[1]):
                raise DocumentError("Calibration needs two distinct normalized original-page endpoints.",422)
            source=edit.source or floor.source
            if source.page!=floor.source.page:raise DocumentError("Calibration endpoints must refer to the selected floor's original page.",422)
            for point in segment:
                if not source.bbox[0]<=point[0]<=source.bbox[2] or not source.bbox[1]<=point[1]<=source.bbox[3]:
                    raise DocumentError("Calibration endpoints must lie in their cited source region.",422)
            prior=floor.calibration
            if prior and getattr(prior,"provenance","observed")=="observed":
                old_scale=_calibration_scale(document,prior.source.page,prior.segment,prior.length_m)
                new_scale=_calibration_scale(document,source.page,segment,length*METRES[edit.unit])
                if old_scale is not None and new_scale is not None and not math.isclose(old_scale,new_scale,rel_tol=1e-8):
                    conflicts.append({"property":"calibration","scope":scope,"source":prior.source.model_dump(mode="json"),
                        "observed_calibration":prior.model_dump(mode="json"),"proposed_value":value,"proposed_unit":edit.unit,
                        "message":"The supplied plan distance conflicts with the existing source-observed calibration scale. Original calibration and submitted value are retained separately."})
            fields={"length_m":length*METRES[edit.unit],"segment":segment,"source":source,"note":"Provided by user; not a dimension observed in the blueprint."}
            if "provenance" in Calibration.model_fields:fields["provenance"]="user_provided"
            floor.calibration=Calibration(**fields)
            candidate.frame_registry.pop(floor.persistent_id,None)
            transform_updates.append({"floor_id":floor.persistent_id,"reason":"User-provided calibration","evidence":source.model_dump(mode="json")})
        elif edit.property=="stair_connection":
            if not item or getattr(item,"kind",None)!="stairs" or not isinstance(value,dict) or not set(value)<={"target_floor_id","target_feature_id"}:
                raise DocumentError("Stair connection needs a selected stair and a target floor.",422)
            target=floors.get(value.get("target_floor_id"))
            if not target or target.persistent_id==floor.persistent_id:raise DocumentError("Choose a different known target storey.",422)
            target_feature=value.get("target_feature_id")
            if target_feature and not any(f.persistent_id==target_feature and f.kind=="stairs" for f in target.features):raise DocumentError("Target stair does not belong to the selected target storey.",422)
            item.connection=StairConnection(target_floor_id=target.persistent_id,target_feature_id=target_feature,source=edit.source or item.source,
                basis=edit.reason or "Connection provided by user; not independently observed.",status="supported",provenance="user_provided")
        else:
            if not isinstance(value,str) or not value.strip():raise DocumentError("Describe the interpretation correction as text.",422)
            value=value.strip();needs_model=True
        submitted.append({"id":uuid.uuid4().hex,"scope":scope,"property":edit.property,"value":value,"unit":edit.unit,
            "source":edit.source.model_dump(mode="json") if edit.source else None,"reason":edit.reason,
            "provenance":"user_provided","base_revision_id":document.revision_id,"submitted_at":time.time()})
    replacements={(json_key(v["scope"]),v["property"]) for v in submitted}
    candidate.user_values=[v for v in candidate.user_values if (json_key(v.get("scope",{})),v["property"]) not in replacements]+submitted
    candidate.reasoning=None
    return candidate,submitted,needs_model,conflicts,{"changed_ids":[v["scope"].get("object_id",v["scope"]["floor_id"]) for v in submitted],"transform_updates":transform_updates}


def json_key(value):
    return tuple(sorted((k,v) for k,v in value.items() if v is not None))


def _calibration_scale(document,page_number,segment,length_m):
    page=next((p for p in document.pages if p.number==page_number),None)
    if not page or len(segment)!=2 or any(len(point)!=2 for point in segment):return None
    dx=(segment[1][0]-segment[0][0])*page.width/page.height
    dy=segment[1][1]-segment[0][1]
    span=math.hypot(dx,dy)
    return length_m/span if span>0 and math.isfinite(span) and length_m>0 else None
