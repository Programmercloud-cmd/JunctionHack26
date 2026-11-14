"""Deterministic candidate context; model agreement never overrides local failures."""
from copy import deepcopy
import math
from .revisions import regression_findings


def _dump(value):
    return value.model_dump(mode="json") if hasattr(value,"model_dump") else value


def _xy(geometry):
    if geometry is None:return None
    if geometry.type=="mesh":return sorted(set((round(geometry.positions[i],9),round(geometry.positions[i+1],9)) for i in range(0,len(geometry.positions),3)))
    return {"center":geometry.center[:2] if geometry.center else None,"size":geometry.size[:2] if geometry.size else None,"polygon":geometry.polygon,"rotation":geometry.rotation_z}


def build_revision_delta(before,after,submitted,changes):
    submitted=[_dump(item) for item in submitted]
    failures=regression_findings(before,after,changes) if before.scene else []
    old={e.id:e for e in before.scene.elements} if before.scene else {}
    new={e.id:e for e in after.scene.elements} if after.scene else {}
    object_changes=[]
    pure_height=bool(submitted) and all(x.get('property') in {'display_height','floor_height'} for x in submitted)
    for identity in sorted(set(old)|set(new)):
        a,b=old.get(identity),new.get(identity)
        changed=[key for key in (_dump(a) or {}) if _dump(a)[key]!=(_dump(b) or {}).get(key)] if a else ['added']
        if changed:object_changes.append({'id':identity,'fields':changed,'xy_changed':_xy(a.geometry) != _xy(b.geometry) if a and b else True,
            'before_has_geometry':bool(a and a.geometry),'after_has_geometry':bool(b and b.geometry)})
        if pure_height and a and b:
            for key in ('source','properties','geometry_origin','evidence_basis','storey_id','name','semantic_type','environment'):
                if getattr(a,key)!=getattr(b,key):failures.append(f'Height-only refinement changed unrelated {key}: {identity}')
            if _xy(a.geometry)!=_xy(b.geometry):failures.append(f'Height-only refinement changed horizontal geometry: {identity}')
    before_floors={f.id:f for f in before.scene.floors} if before.scene else {}
    after_floors={f.id:f for f in after.scene.floors} if after.scene else {}
    frame_changes=[{'floor_id':identity,'fields':[key for key in _dump(floor) if _dump(floor)[key]!=(_dump(before_floors.get(identity)) or {}).get(key)]}
        for identity,floor in after_floors.items() if floor!=before_floors.get(identity)]
    if pure_height:
        if before.description!=after.description:failures.append('Height-only refinement changed source description, hosts or provenance.')
        if set(old)!=set(new):failures.append('Height-only refinement changed the object inventory.')
        from .user_inputs import json_key
        replacements={(json_key(v["scope"]),v["property"]) for v in submitted}
        expected_values=[deepcopy(v) for v in before.user_values if (json_key(v.get("scope",{})),v["property"]) not in replacements]+deepcopy(submitted)
        if after.user_values!=expected_values:failures.append('Refinement changed unrelated supplied values or their attribution.')
        if any(item.get('provenance')!='user_provided' for item in submitted):failures.append('Submitted height is missing explicit user attribution.')
        from .user_inputs import prepare_inputs, RefinementRequest
        try:
            edits=[{k:v for k,v in item.items() if k in {'scope','property','value','unit','source','reason'}} for item in submitted]
            _,_,_,source_conflicts,_=prepare_inputs(before,RefinementRequest(base_revision_id=before.revision_id,edits=edits))
            if source_conflicts:failures.append('Supplied height conflicts with an existing source observation.')
        except Exception:
            failures.append('Submitted height cannot be validated against the baseline input contract.')
        from .ifc_generate import _floor_height
        for floor in before.description.floors:
            rendered=after_floors.get(floor.persistent_id)
            if rendered:
                expected,_,_=_floor_height(floor,rendered.scale_status=='known',after)
                if rendered.reference_height is None or not math.isclose(rendered.reference_height,expected,rel_tol=1e-8,abs_tol=1e-9):
                    failures.append(f'Rendered height does not match the attributed input/conversion: {floor.persistent_id}')
        # Compare against the deterministic baseline + supplied values, including
        # dependent storey/stair placement. This is local IFC validation, no inference.
        from .ifc_generate import generate_ifc
        from .ifc_artifact import load_artifact
        expected=before.snapshot();expected.user_values=expected_values
        try:
            expected_scene,_,_=load_artifact(generate_ifc(expected.description,expected),expected.id)
            expected_elements={e.id:e for e in expected_scene.elements}
            for identity,element in new.items():
                target=expected_elements.get(identity)
                if target is None or element.geometry!=target.geometry:
                    failures.append(f'Geometry differs from deterministic attributed-height result: {identity}')
        except Exception:
            failures.append('Could not verify deterministic attributed-height geometry.')
    return {'base_revision_id':before.revision_id,'candidate_revision_id':after.revision_id,
        'requested_inputs':submitted,'previous_user_values':deepcopy(before.user_values),'current_user_values':deepcopy(after.user_values),
        'changes':deepcopy(changes),'object_changes':object_changes,'frame_changes':frame_changes,
        'local_failures':sorted(set(failures)),'pure_height_change':pure_height}


def validate_candidate_review(review,context):
    failures=list(context.get('local_failures',[]))
    if not review.candidate_supported:failures.append('Source reviewer did not support the candidate change.')
    assessment=review.candidate_assessment
    if assessment is None:return failures+['Candidate review omitted the required change assessment.']
    if assessment.delta_support!='supported':failures.append('Requested change remains unsupported or unclear.')
    if assessment.source_conflicts:failures.append('Candidate review reports source conflicts.')
    if assessment.new_regressions:failures.append('Candidate review reports newly introduced regressions.')
    if assessment.unresolved_delta is None:
        failures.append('Candidate review omitted explicit uncertainty assessment for the requested change.')
    elif assessment.unresolved_delta:
        failures.append('Candidate change attribution or causality remains unresolved.')
    return failures
