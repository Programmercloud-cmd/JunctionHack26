"""Synthetic counterparts of retained failures; no uploaded responses in fixtures."""
from copy import deepcopy
import pytest
from pydantic import ValidationError
from app.bundles import BuildingStore
from app.documents import DocumentError
from app.review_schema import DescriptionPatch,ReconstructionReview,AuthorizationReview
from app.revisions import (apply_patch,PatchRejection,authorize_targets,validate_target_requests,SupplementalAuthorization,proposal_fingerprint)
from app.revision_delta import build_revision_delta,validate_candidate_review
from app.user_inputs import prepare_inputs,RefinementRequest
from app.ifc_generate import generate_ifc
from app.ifc_artifact import load_artifact
from test_backend import png
from test_bundles_revisions import build
from test_ifc_generate import description,floor,boundary,opening,region


@pytest.fixture
def document(tmp_path):
    store=BuildingStore(tmp_path);doc=build(store,store.add(png(),'fixture.png'),description(floor(boundaries=[boundary()],openings=[opening()])))
    yield doc
    store.close()


def review_for(doc,ids):
    return ReconstructionReview(candidate_supported=False,summary='Fixture baseline omissions',issues=[dict(id='issue',object_ids=ids,
        source=region(),category='extraction',discrepancy='Fixture inspected issue',evidence='Original region',proposed_action='Targeted correction',actionable=True)])


def metadata(doc,field='order_basis',value='Inspected order'):
    return dict(floor_id=doc.description.floors[0].persistent_id,changes=[dict(field=field,value=value)],evidence=region(),reason='Inspected metadata',issue_ids=['issue'])


def test_metadata_preserves_nested_records_and_explicit_null(document):
    f=document.description.floors[0];before=f.model_dump();update=metadata(document,'calibration',None)
    update['changes'].append(dict(field='order_basis',value='Inspected order'))
    patch=DescriptionPatch(base_revision_id=document.revision_id,floor_metadata_updates=[update])
    candidate,_=apply_patch(document,patch,review_for(document,[f.persistent_id]))
    for key in ('rooms','boundaries','openings','features','unresolved','height','source'):
        assert candidate.description.floors[0].model_dump()[key]==before[key]
    assert document.description.floors[0].model_dump()==before
    assert candidate.description.floors[0].calibration is None
    assert candidate.description.floors[0].order_basis=='Inspected order'


@pytest.mark.parametrize('change',[{'field':'rooms','value':[]},{'field':'label'},{'field':'label','value':None}])
def test_metadata_unknown_nested_or_missing_value_rejects(document,change):
    item=metadata(document);item['changes']=[change]
    with pytest.raises(ValidationError):DescriptionPatch(base_revision_id=document.revision_id,floor_metadata_updates=[item])


def test_church_legacy_empty_inventory_still_rejects(document):
    f=document.description.floors[0];broken=f.model_copy(deep=True);broken.boundaries=[];broken.rooms=[];broken.openings=[]
    patch=DescriptionPatch(base_revision_id=document.revision_id,operations=[dict(action='replace',collection='floors',target_id=f.persistent_id,
        record=broken,evidence=region(),reason='Bbox correction',issue_ids=['issue'])])
    before=document.description.model_dump()
    with pytest.raises(PatchRejection) as caught:apply_patch(document,patch,review_for(document,[f.persistent_id]))
    assert caught.value.feedback['code']=='nested_floor_edit' and caught.value.feedback['operation_index']==0
    assert document.description.model_dump()==before


def request_and_patch(doc):
    f=doc.description.floors[0];wall=f.boundaries[0];op=f.openings[0];review=review_for(doc,[op.persistent_id])
    request=dict(request_id='request',base_revision_id=doc.revision_id,issue_id='issue',target_id=wall.persistent_id,floor_id=f.persistent_id,
        collection='boundaries',evidence=region(),reason='Original drawing establishes host dependency')
    changed=wall.model_copy(deep=True);changed.note='Inspected host correction'
    patch=DescriptionPatch(base_revision_id=doc.revision_id,additional_target_requests=[request],operations=[dict(action='replace',collection='boundaries',floor_id=f.persistent_id,
        target_id=wall.persistent_id,record=changed,evidence=region(),reason='Supported wall correction',issue_ids=['issue'])])
    return request,patch,review


def decision(doc,request,result='approved'):
    return dict(base_revision_id=doc.revision_id,decisions=[dict(request_id=request['request_id'],issue_id=request['issue_id'],target_id=request['target_id'],
        decision=result,evidence=region(),reason='Inspected original supports this exact wall target')])


def test_3181_target_scope_expansion_requires_exact_reviewed_grant(document):
    request,patch,review=request_and_patch(document);original=review.model_dump()
    with pytest.raises(PatchRejection,match='not identified'):apply_patch(document,patch,review)
    grants=authorize_targets(document,review,[request],decision(document,request))
    candidate,_=apply_patch(document,patch,review,authorizations=grants)
    assert candidate.description.floors[0].boundaries[0].note=='Inspected host correction'
    assert review.model_dump()==original
    with pytest.raises(PatchRejection):apply_patch(document,patch,review,authorizations=[SupplementalAuthorization(**grants[0].model_dump())])
    modified=grants[0].model_copy(update={'reason':'tampered'})
    with pytest.raises(PatchRejection):apply_patch(document,patch,review,authorizations=[modified])


@pytest.mark.parametrize('result',['denied','unclear'])
def test_denied_unclear_cannot_authorize(document,result):
    request,patch,review=request_and_patch(document)
    grants=authorize_targets(document,review,[request],decision(document,request,result))
    assert grants==[]
    with pytest.raises(PatchRejection):apply_patch(document,patch,review,authorizations=grants)


@pytest.mark.parametrize('mutation',['duplicate','missing','foreign','wrongtarget','stale','wrongsource'])
def test_bad_authorization_decisions_reject(document,mutation):
    request,_,review=request_and_patch(document);result=decision(document,request)
    if mutation=='duplicate':result['decisions']*=2
    if mutation=='missing':result['decisions']=[]
    if mutation=='foreign':result['decisions'][0]['request_id']='foreign'
    if mutation=='wrongtarget':result['decisions'][0]['target_id']='foreign'
    if mutation=='stale':result['base_revision_id']='old'
    if mutation=='wrongsource':result['decisions'][0]['evidence']={**region(),'page':99}
    with pytest.raises(DocumentError):authorize_targets(document,review,[request],result)


@pytest.mark.parametrize('mutation',['unknown','crossfloor','badsource','emptyreason'])
def test_bad_requests_reject_before_review(document,mutation):
    request,_,review=request_and_patch(document)
    if mutation=='unknown':request['target_id']='unknown'
    if mutation=='crossfloor':request['floor_id']='another-floor'
    if mutation=='badsource':request['evidence']={**region(),'page':99}
    if mutation=='emptyreason':request['reason']=' '
    with pytest.raises(DocumentError):validate_target_requests(document,review,[request])


def height_candidate(document):
    request=RefinementRequest(base_revision_id=document.revision_id,edits=[dict(scope={'floor_id':document.description.floors[0].persistent_id},property='display_height',value=1.4,unit='relative')])
    candidate,submitted,_,conflicts,changes=prepare_inputs(document,request)
    assert not conflicts
    candidate.ifc_bytes=generate_ifc(candidate.description,candidate)
    candidate.scene,_,_=load_artifact(candidate.ifc_bytes,candidate.id)
    return candidate,deepcopy(submitted),changes


def supported_review():
    return ReconstructionReview(candidate_supported=True,summary='Only the supplied height changed',candidate_assessment=dict(delta_support='supported',source_conflicts=[],new_regressions=[],pre_existing_issue_ids=['old-omission'],unresolved=[]))


def test_34_attributed_height_delta_preserves_original_geometry(document):
    candidate,submitted,changes=height_candidate(document)
    delta=build_revision_delta(document,candidate,submitted,changes)
    assert delta['pure_height_change'] and not delta['local_failures']
    assert validate_candidate_review(supported_review(),delta)==[]
    review=supported_review();review.candidate_supported=False
    assert validate_candidate_review(review,delta)
    assert validate_candidate_review(ReconstructionReview(candidate_supported=True,summary='Missing assessment'),delta)


@pytest.mark.parametrize('damage',['xy','z','source','provenance','host','lost','uservalue'])
def test_height_delta_rejects_unrelated_damage_even_if_reviewer_agrees(document,damage):
    candidate,submitted,changes=height_candidate(document)
    mesh=next(e for e in candidate.scene.elements if e.geometry and e.geometry.type=='mesh')
    if damage=='xy':mesh.geometry.positions[0]+=.1
    if damage=='z':mesh.geometry.positions[2]+=.1
    if damage=='source':mesh.source.bbox[0]+=.001
    if damage=='provenance':mesh.evidence_basis='observed' if mesh.evidence_basis!='observed' else 'inferred'
    if damage=='host':candidate.description.floors[0].openings[0].host_wall='wrong-host'
    if damage=='lost':candidate.scene.elements.remove(mesh)
    if damage=='uservalue':candidate.user_values[0]['reason']='Unrequested attribution rewrite'
    delta=build_revision_delta(document,candidate,submitted,changes)
    assert delta['local_failures']
    assert validate_candidate_review(supported_review(),delta)


def test_fingerprint_ignores_request_ids_reason_and_metadata_order(document):
    a=DescriptionPatch(base_revision_id=document.revision_id,floor_metadata_updates=[metadata(document)])
    from app.review_schema import ChangeLabel
    a.floor_metadata_updates[0].changes.append(ChangeLabel(field='label',value='New label'))
    b=a.model_copy(deep=True);b.floor_metadata_updates[0].changes.reverse();b.floor_metadata_updates[0].reason='Paraphrase'
    assert proposal_fingerprint(a)==proposal_fingerprint(b)


def test_metadata_bbox_retains_frame_and_rotation_requires_explicit_transform(document):
    f=document.description.floors[0];source=f.source.model_dump();source['bbox']=[0,0,.99,1]
    patch=DescriptionPatch(base_revision_id=document.revision_id,floor_metadata_updates=[metadata(document,'source',source)])
    review=review_for(document,[f.persistent_id]);before=document.description.model_dump()
    candidate,_=apply_patch(document,patch,review)
    assert candidate.frame_registry==document.frame_registry
    rotated=DescriptionPatch(base_revision_id=document.revision_id,floor_metadata_updates=[metadata(document,'rotation_degrees',90)])
    with pytest.raises(DocumentError,match='transform update'):apply_patch(document,rotated,review)
    from app.review_schema import TransformUpdate
    rotated.transform_updates=[TransformUpdate(floor_id=f.persistent_id,evidence=region(),reason='Inspected rotation')]
    apply_patch(document,rotated,review)
    assert candidate.description.floors[0].boundaries==f.boundaries
    assert candidate.description.floors[0].openings==f.openings
    assert document.description.model_dump()==before


def test_metadata_conflicting_fields_and_late_failure_are_atomic(document):
    item=metadata(document);item['changes']*=2
    patch=DescriptionPatch(base_revision_id=document.revision_id,floor_metadata_updates=[item])
    with pytest.raises(PatchRejection,match='unique'):apply_patch(document,patch,review_for(document,[item['floor_id']]))
    request,patch,review=request_and_patch(document);grants=authorize_targets(document,review,[request],decision(document,request))
    invalid=patch.operations[0].model_copy(deep=True);invalid.evidence.page=99;patch.operations.append(invalid)
    before=document.description.model_dump()
    with pytest.raises(DocumentError):apply_patch(document,patch,review,authorizations=grants)
    assert document.description.model_dump()==before


def test_review_approved_delta_cannot_hide_explicit_conflict(document):
    candidate,submitted,changes=height_candidate(document);delta=build_revision_delta(document,candidate,submitted,changes)
    review=supported_review();review.candidate_assessment.source_conflicts=['Original measurement conflicts']
    assert validate_candidate_review(review,delta)
    review=supported_review();review.candidate_assessment.delta_support='unclear'
    assert validate_candidate_review(review,delta)


def test_actual_other_floor_target_is_not_authorized_by_shared_page_region(tmp_path):
    store=BuildingStore(tmp_path)
    try:
        doc=build(store,store.add(png(),'fixture.png'),description(
            floor('A',boundaries=[boundary()],openings=[opening()]),
            floor('B',boundaries=[boundary()],openings=[opening()])))
        a,b=doc.description.floors
        review=review_for(doc,[a.openings[0].persistent_id])
        request=dict(request_id='otherfloor',base_revision_id=doc.revision_id,issue_id='issue',target_id=b.boundaries[0].persistent_id,
            floor_id=b.persistent_id,collection='boundaries',evidence=region(),reason='Inspect related wall')
        with pytest.raises(PatchRejection) as caught:validate_target_requests(doc,review,[request])
        assert caught.value.feedback['code']=='cross_floor_target'
        with pytest.raises(PatchRejection):authorize_targets(doc,review,[request],decision(doc,request))
        # Explicit multi-floor evidence can establish the necessary wider scope.
        review.issues[0].object_ids.append(b.openings[0].persistent_id)
        assert authorize_targets(doc,review,[request],decision(doc,request))
        # A floor's own identity establishes its scope without requiring a nested ID.
        review.issues[0].object_ids=[b.persistent_id]
        assert authorize_targets(doc,review,[request],decision(doc,request))
    finally:store.close()


def test_region_only_issue_cannot_bridge_unrelated_target_with_broad_request(document):
    document.description.floors[0].boundaries[0].source.bbox=[.1,.19,.4,.21]
    request,_,review=request_and_patch(document)
    review.issues[0].object_ids=[]
    review.issues[0].source.bbox=[.7,.7,.9,.9]
    with pytest.raises(PatchRejection,match='source context'):validate_target_requests(document,review,[request])
    review.issues[0].source.bbox=[.1,.1,.4,.3]
    assert authorize_targets(document,review,[request],decision(document,request))


def test_unknown_issue_identity_cannot_establish_floor_scope(document):
    request,_,review=request_and_patch(document);review.issues[0].object_ids.append('unknown')
    with pytest.raises(PatchRejection,match='unavailable object'):validate_target_requests(document,review,[request])
