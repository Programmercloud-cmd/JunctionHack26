"""Native semantic coverage and calculations use actual source records, including meshless ones."""
import json
import ifcopenshell
import pytest
from app.documents import DocumentStore
from app.reasoning import build_reasoning,retrieve_context,execute_native_calculation
from app.schemas import NativeCalculation,NativeOperand
from test_ifc_import import fixture_model,encode


def document_for(tmp_path,model):
    store=DocumentStore(tmp_path)
    document=store.add(encode(model),'source.ifc')
    document.source_bytes=encode(model)
    return store,document


def test_complete_native_properties_relationships_meshless_and_units(tmp_path):
    model,wall,window,space=fixture_model()
    pset=model.create_entity('IfcPropertySet',GlobalId=ifcopenshell.guid.new(),Name='Many',HasProperties=[model.create_entity('IfcPropertySingleValue',Name=f'P{i}',NominalValue=model.create_entity('IfcReal',float(i)))for i in range(60)])
    model.create_entity('IfcRelDefinesByProperties',GlobalId=ifcopenshell.guid.new(),RelatedObjects=[window],RelatingPropertyDefinition=pset)
    opening=model.create_entity('IfcOpeningElement',GlobalId=ifcopenshell.guid.new(),Name='Opening')
    void=model.create_entity('IfcRelVoidsElement',GlobalId=ifcopenshell.guid.new(),RelatingBuildingElement=wall,RelatedOpeningElement=opening)
    fill=model.create_entity('IfcRelFillsElement',GlobalId=ifcopenshell.guid.new(),RelatingOpeningElement=opening,RelatedBuildingElement=window)
    store,doc=document_for(tmp_path,model)
    try:
        reasoning=build_reasoning(doc);records={r['id']:r for r in reasoning['objects']}
        assert records[window.GlobalId]['values']['Many.P59']['value']==59
        assert records[window.GlobalId]['values']['OverallHeight']['unit']=='mm'
        assert records[window.GlobalId]['values']['Dimensions.SpecifiedHeight']['unit']=='m'
        assert not records[window.GlobalId]['geometry_available']
        assert records[window.GlobalId]['source']['step_id']==window.id()
        assert opening.GlobalId in records
        assert {void.GlobalId,fill.GlobalId}<={r['id']for r in reasoning['relationships']}
        assert records[wall.GlobalId]['values']['geometry.volume']['value']==pytest.approx(.6)
        result=execute_native_calculation(reasoning,NativeCalculation(operation='count',scope='model',entity_type='IfcWindow'))
        assert result['value']==1 and result['status']=='complete'
        summed=execute_native_calculation(reasoning,NativeCalculation(operation='sum',scope='objects',object_ids=[window.GlobalId],operands=[NativeOperand(object_id=window.GlobalId,property_name='OverallHeight'),NativeOperand(object_id=window.GlobalId,property_name='Dimensions.SpecifiedHeight')]))
        assert summed['value']==pytest.approx(3.5)and summed['unit']=='m'
        assert all(x['source']['step_id']for x in summed['contributing_records'])
    finally:store.close()


def test_partial_scope_or_missing_numeric_input_never_yields_complete_total(tmp_path):
    model,wall,window,_=fixture_model();orphan=model.create_entity('IfcWindow',GlobalId=ifcopenshell.guid.new(),Name='Uncontained window')
    store,doc=document_for(tmp_path,model)
    try:
        r=build_reasoning(doc);floor=model.by_type('IfcBuildingStorey')[0].GlobalId
        result=execute_native_calculation(r,NativeCalculation(operation='count',scope='storey',entity_type='IfcWindow',storey_id=floor))
        assert result['status']=='incomplete'and result['value']is None
        result=execute_native_calculation(r,NativeCalculation(operation='sum',scope='model',entity_type='IfcWindow',property_name='OverallHeight'))
        assert result['status']=='incomplete'and result['value']is None
        r['coverage']['catalog_complete']=False
        result=execute_native_calculation(r,NativeCalculation(operation='count',scope='model',entity_type='IfcWindow'))
        assert result['status']=='incomplete'and result['value']is None
    finally:store.close()


def test_retrieval_reports_subset_and_all_original_catalog_ids(tmp_path):
    model,wall,window,space=fixture_model();store,doc=document_for(tmp_path,model)
    try:
        context=retrieve_context(doc,'What is the window height?')
        assert context['source_kind']=='native_ifc'
        assert {wall.GlobalId,window.GlobalId,space.GlobalId}<={r['id']for r in context['catalog']}
        assert not context['retrieval']['all_records_selected']
        record=next(r for r in context['objects']if r['id']==window.GlobalId)
        assert record['values']['OverallHeight']['provenance']=='supplied'
        assert 'property_view_complete'in context['retrieval']
    finally:store.close()


def test_explicit_operands_cannot_disguise_partial_aggregate(tmp_path):
    model,wall,window,_=fixture_model()
    second=model.create_entity('IfcWindow',GlobalId=ifcopenshell.guid.new(),Name='Missing-height window')
    store,doc=document_for(tmp_path,model)
    try:
        r=build_reasoning(doc)
        partial=NativeCalculation(operation='sum',scope='model',entity_type='IfcWindow',property_name='OverallHeight',operands=[NativeOperand(object_id=window.GlobalId,property_name='OverallHeight')])
        result=execute_native_calculation(r,partial)
        assert result['status']=='incomplete' and result['value']is None
        assert any('aggregate'in item for item in result['missing_inputs'])
        partial.scope='objects';partial.object_ids=[window.GlobalId]
        assert execute_native_calculation(r,partial)['status']=='complete'
        partial.object_ids=[wall.GlobalId]
        assert execute_native_calculation(r,partial)['status']=='incomplete'
        unsupported=NativeCalculation(operation='count',scope='model',entity_type='IfcMaterial')
        assert execute_native_calculation(r,unsupported)['status']=='incomplete'
    finally:store.close()


def test_calculated_volume_does_not_cancel_disconnected_opposite_shells(tmp_path):
    from app.ifc_reasoning import _geometry
    from app.scene import Geometry
    model,wall,_,_=fixture_model();store,doc=document_for(tmp_path,model)
    try:
        mesh=next(e.geometry for e in doc.scene.elements if e.id==wall.GlobalId)
        n=len(mesh.positions)//3
        shifted=[v+(10 if i%3==0 else 0)for i,v in enumerate(mesh.positions)]
        flipped=[]
        for i in range(0,len(mesh.indices),3):
            a,b,c=mesh.indices[i:i+3];flipped.extend([n+a,n+c,n+b])
        values,missing=_geometry(Geometry(type='mesh',positions=mesh.positions+shifted,indices=mesh.indices+flipped))
        assert 'geometry.surface_area'in values and 'geometry.volume'not in values
        assert any('shell'in message for message in missing)
    finally:store.close()


def test_predefined_type_properties_and_complex_scalar_leaves_keep_original_units(tmp_path):
    model,_,window,_=fixture_model()
    lining=model.create_entity('IfcWindowLiningProperties',GlobalId=ifcopenshell.guid.new(),Name='Lining',LiningDepth=125.,FirstTransomOffset=.4)
    window_type=model.create_entity('IfcWindowType',GlobalId=ifcopenshell.guid.new(),Name='Typed window',PredefinedType='WINDOW',PartitioningType='SINGLE_PANEL',HasPropertySets=[lining])
    model.create_entity('IfcRelDefinesByType',GlobalId=ifcopenshell.guid.new(),RelatedObjects=[window],RelatingType=window_type)
    child=model.create_entity('IfcPropertySingleValue',Name='Depth',NominalValue=model.create_entity('IfcLengthMeasure',200.))
    parent=model.create_entity('IfcComplexProperty',Name='Nested',UsageName='Source group',HasProperties=[child])
    pset=model.create_entity('IfcPropertySet',GlobalId=ifcopenshell.guid.new(),Name='Source',HasProperties=[parent])
    model.create_entity('IfcRelDefinesByProperties',GlobalId=ifcopenshell.guid.new(),RelatedObjects=[window],RelatingPropertyDefinition=pset)
    store,doc=document_for(tmp_path,model)
    try:
        r=build_reasoning(doc);record=next(x for x in r['objects']if x['id']==window.GlobalId)
        assert record['values']['Type::Lining.LiningDepth']['value']==125
        assert record['values']['Type::Lining.LiningDepth']['unit']=='mm'
        assert record['values']['Type::Lining.LiningDepth']['source']['step_id']==lining.id()
        assert record['values']['Type::Lining.FirstTransomOffset']['unit']=='1'
        leaf=record['values']['Source.Nested.Depth']
        assert leaf['value']==200 and leaf['unit']=='mm' and leaf['source']['step_id']==child.id()
        assert leaf['owner']['global_id']==window.GlobalId
    finally:store.close()


def test_entity_type_retrieval_does_not_expand_for_grammatical_substrings(tmp_path):
    model,wall,window,space=fixture_model()
    wall.Name='As built wall on site';space.Name='Installation area'
    store,doc=document_for(tmp_path,model)
    try:
        context=retrieve_context(doc,'What was the date of the last on-site inspection confirming that the windows were installed as built?')
        assert {r['id']for r in context['objects']}=={window.GlobalId}
        assert {wall.GlobalId,space.GlobalId}<={r['id']for r in context['catalog']}
        assert context['retrieval']['selected_records']==1 and not context['retrieval']['all_records_selected']
    finally:store.close()
