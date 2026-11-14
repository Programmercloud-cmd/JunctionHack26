"""Floor metadata copies never execute nested changes or bypass separate validation."""
from copy import deepcopy
import pytest
from app.bundles import BuildingStore
from app.documents import DocumentError
from app.review_schema import DescriptionPatch, ReconstructionReview
from app.revisions import apply_patch
from test_backend import png
from test_bundles_revisions import build
from test_ifc_generate import description, floor, boundary, opening, region


@pytest.fixture
def building(tmp_path):
    store=BuildingStore(tmp_path)
    source=store.add(png(),'fixture.png')
    current=build(store,source,description(floor(boundaries=[boundary()],openings=[opening()])))
    yield current
    store.close()


def operation_batch(document,*,floor_first,copy='replacement'):
    f=document.description.floors[0];wall=f.boundaries[0]
    changed=wall.model_copy(deep=True);changed.note='Explicit separately supported wall update'
    copied=f.model_copy(deep=True);copied.order_basis='Updated floor-order explanation'
    if copy=='replacement':copied.boundaries[0]=changed.model_copy(deep=True)
    wall_operation={'action':'replace','collection':'boundaries','floor_id':f.persistent_id,'target_id':wall.persistent_id,
        'record':changed.model_dump(),'evidence':region(),'reason':'Individually supported wall change','issue_ids':['wall']}
    floor_operation={'action':'replace','collection':'floors','target_id':f.persistent_id,'record':copied.model_dump(),
        'evidence':region(),'reason':'Supported floor metadata change','issue_ids':['floor']}
    operations=[floor_operation,wall_operation] if floor_first else [wall_operation,floor_operation]
    patch=DescriptionPatch(base_revision_id=document.revision_id,operations=operations)
    review=ReconstructionReview(candidate_supported=False,summary='Explicit fixture findings',issues=[
        {'id':name,'object_ids':[identity],'source':region(),'category':'extraction','discrepancy':'Fixture finding',
         'evidence':'Fixture original region','proposed_action':'Apply explicit replacement','actionable':True}
        for name,identity in [('floor',f.persistent_id),('wall',wall.persistent_id)]])
    return patch,review


@pytest.mark.parametrize('enrichment',[False,True])
@pytest.mark.parametrize('floor_first',[False,True])
@pytest.mark.parametrize('copy',['base','replacement'])
def test_redundant_base_staged_or_declared_copy_keeps_separate_update(building,enrichment,floor_first,copy):
    before=building.description.model_dump();registry=deepcopy(building.identity_registry)
    patch,review=operation_batch(building,floor_first=floor_first,copy=copy)
    candidate,changes=apply_patch(building,patch,review,enrichment=enrichment)
    original=building.description.floors[0];updated=candidate.description.floors[0]
    assert updated.order_basis=='Updated floor-order explanation'
    assert updated.boundaries[0].note=='Explicit separately supported wall update'
    assert updated.openings==original.openings
    assert updated.boundaries[0].persistent_id==original.boundaries[0].persistent_id
    assert set(changes['changed_ids'])=={original.persistent_id,original.boundaries[0].persistent_id}
    assert building.description.model_dump()==before and building.identity_registry==registry


@pytest.mark.parametrize('floor_first',[False,True])
def test_unrelated_nested_change_cannot_hide_in_floor_copy(building,floor_first):
    patch,review=operation_batch(building,floor_first=floor_first)
    floor_operation=next(op for op in patch.operations if op.collection=='floors')
    floor_operation.record.openings[0].note='Undeclared opening change'
    before=building.description.model_dump()
    with pytest.raises(DocumentError,match='unrelated nested'):
        apply_patch(building,patch,review)
    assert building.description.model_dump()==before


@pytest.mark.parametrize('floor_first',[False,True])
def test_matching_copy_does_not_bypass_invalid_separate_evidence(building,floor_first):
    patch,review=operation_batch(building,floor_first=floor_first)
    wall_operation=next(op for op in patch.operations if op.collection=='boundaries')
    wall_operation.evidence.page=2
    before=building.description.model_dump();registry=deepcopy(building.identity_registry)
    with pytest.raises(DocumentError,match='page|source|Source'):
        apply_patch(building,patch,review)
    assert building.description.model_dump()==before and building.identity_registry==registry


@pytest.mark.parametrize('mutation',['remove','duplicate','identity'])
def test_nested_membership_identity_and_length_stay_explicit(building,mutation):
    patch,review=operation_batch(building,floor_first=True)
    nested=patch.operations[0].record.boundaries
    if mutation=='remove':nested.clear()
    elif mutation=='duplicate':nested.append(nested[0].model_copy(deep=True))
    else:nested[0].persistent_id='unrelated-id'
    with pytest.raises(DocumentError,match='identity order or length'):
        apply_patch(building,patch,review)


def test_replacement_copy_must_match_its_floor_collection_and_target(building):
    patch,review=operation_batch(building,floor_first=True)
    patch.operations[1].floor_id='another-floor'
    with pytest.raises(DocumentError,match='unrelated nested'):
        apply_patch(building,patch,review)


def test_nested_order_cannot_change_even_when_records_are_unchanged(building):
    f=building.description.floors[0]
    # Two distinct existing collections entries are needed to test ordering alone.
    second=f.boundaries[0].model_copy(deep=True)
    from app.identities import new_identity
    second.persistent_id=new_identity(building.identity_registry);second.key='other-wall'
    building.identity_registry['objects'][second.persistent_id]={'collection':'boundaries','floor_id':f.persistent_id}
    f.boundaries.append(second)
    patch,review=operation_batch(building,floor_first=True,copy='base')
    patch.operations[0].record.boundaries.reverse()
    with pytest.raises(DocumentError,match='identity order or length'):
        apply_patch(building,patch,review)
