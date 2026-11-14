"""Portable derived IFC must reopen as source drawings, never as new factual evidence."""
import hashlib
import json

import ifcopenshell
import pytest

from app.artifact_schema import MANIFEST_PROPERTY, PSET_NAME
from app.documents import DocumentError, DocumentStore
from app.highlights import validated_highlights
from app.ifc_generate import generate_ifc
from app.ifc_import import import_ifc
from app.providers.gemini import ProviderError
from app.scene import Property
from app.schemas import CropRequest, DraftAnswer, GateResult, Usage
from app.service import ask, validate_draft
from app.source_context import source_context
from test_backend import pdf
from test_ifc_generate import description, floor, manifest, region, room
from test_ifc_import import encode, fixture_model


@pytest.fixture
def artifact_bundle(tmp_path):
    store=DocumentStore(tmp_path/"original")
    try:
        document=store.add(pdf(2),"original-drawings.pdf")
        measurement={"label":"TRANSCRIBED_HEIGHT_MARKER","status":"observed","value":9876,"unit":"mm",
                     "source":region(bbox=[.1,.1,.2,.2]),"note":"Source observation, not derived geometry"}
        data=generate_ifc(description(floor("Ground",rooms=[room("Bedroom")],measurements=[measurement]),
            floor("Upper",source=region(page=2),rooms=[room("Bedroom")])),document)
        original_manifest=manifest(ifcopenshell.file.from_string(data.decode()))
        return data,[p.path.read_bytes() for p in document.pages],original_manifest,document.id
    finally:
        # Reopening must work after the original store and all source files are gone.
        store.close()


def property_for(model, entity, name):
    for relation in model.by_type("IfcRelDefinesByProperties"):
        if entity in relation.RelatedObjects and relation.RelatingPropertyDefinition.Name==PSET_NAME:
            return next(p for p in relation.RelatingPropertyDefinition.HasProperties if p.Name==name)
    raise AssertionError("Fixture property missing")


def corrupted(data,kind):
    model=ifcopenshell.file.from_string(data.decode())
    project=model.by_type("IfcProject")[0]
    prop=property_for(model,project,MANIFEST_PROPERTY)
    values=json.loads(prop.NominalValue.wrappedValue)
    if kind=="missing_manifest":
        prop.Name="RemovedManifest"
    elif kind=="malformed_manifest":
        prop.NominalValue=model.create_entity("IfcText","not valid JSON")
    elif kind=="wrong_unit":
        model.by_type("IfcContextDependentUnit")[0].Name="METRES_WITHOUT_CALIBRATION"
    elif kind=="changed_identity":
        model.by_type("IfcSpace")[0].GlobalId=ifcopenshell.guid.new()
    elif kind in {"element_source","element_assumptions","element_basis","missing_element_source"}:
        element=model.by_type("IfcSpace")[0]
        name={"element_source":"Source","element_assumptions":"Assumptions","element_basis":"EvidenceBasis",
              "missing_element_source":"Source"}[kind]
        target=property_for(model,element,name)
        if kind=="missing_element_source":
            target.Name="RemovedSource"
        else:
            changed={"element_source":json.dumps({"kind":"image","page":2,"bbox":[.2,.2,.3,.3]}),
                     "element_assumptions":"[]","element_basis":"inferred"}[kind]
            target.NominalValue=model.create_entity("IfcText",changed)
    else:
        if kind=="bad_source_hash":
            values["pages"][0]["sha256"]="0"*64
        elif kind=="no_original_pages":
            values["pages"]=[]
        elif kind=="launder_classification":
            values["scene"]["derived"]=False
        elif kind=="bad_source_region":
            values["scene"]["elements"][0]["source"]["bbox"]=[-1,0,1,1]
        elif kind=="manifest_type":
            values["scene"]["elements"][0]["ifc_type"]="IfcDoor"
            values["scene"]["elements"][0]["kind"]="door"
        else:
            raise AssertionError(kind)
        prop.NominalValue=model.create_entity("IfcText",json.dumps(values))
    return model.to_string().encode()


def test_fresh_store_reopens_original_pixels_and_global_ids_after_original_closed(tmp_path,artifact_bundle):
    data,pages,original,old_id=artifact_bundle
    store=DocumentStore(tmp_path/"new")
    try:
        document=store.add(data,"downloaded.ifc")
        assert document.id!=old_id and document.kind=="drawing" and document.ifc_bytes==data
        assert document.scene.derived and document.scene.source_kind=="image" and not document.scene.catalog_complete
        assert document.scene.units=="relative" and document.scene.document_id==document.id
        assert [p.path.read_bytes() for p in document.pages]==pages
        assert [hashlib.sha256(p.path.read_bytes()).hexdigest() for p in document.pages]==[p.sha256 for p in original.pages]
        assert [e.id for e in document.scene.elements]==[e.id for e in original.scene.elements]
        assert [f.source.page for f in document.scene.floors]==[1,2]
        assert all(e.geometry is not None and e.geometry_origin=="inferred" and e.source.kind=="image" for e in document.scene.elements)
        direct=import_ifc(data,"direct-id")
        assert direct.derived and direct.source_kind=="image" and direct.units=="relative"
        assert [e.id for e in direct.elements]==[e.id for e in original.scene.elements]
    finally:
        store.close()


@pytest.mark.parametrize("path",["store","direct"])
@pytest.mark.parametrize("kind",["missing_manifest","malformed_manifest","bad_source_hash","no_original_pages",
    "wrong_unit","changed_identity","launder_classification","bad_source_region","manifest_type",
    "element_source","element_assumptions","element_basis","missing_element_source"])
def test_corrupted_provenance_never_falls_back_to_native_ifc(tmp_path,artifact_bundle,path,kind):
    broken=corrupted(artifact_bundle[0],kind)
    store=DocumentStore(tmp_path/"rejected")
    try:
        with pytest.raises(DocumentError) as error:
            if path=="store":
                store.add(broken,"derived.ifc")
            else:
                import_ifc(broken,"direct")
        assert error.value.status==422
        assert not store.documents
    finally:
        store.close()


def test_genuine_native_ifc_stays_native_through_store_and_direct_import(tmp_path):
    model,wall,window,space=fixture_model()
    data=encode(model)
    store=DocumentStore(tmp_path)
    try:
        document=store.add(data,"native.ifc")
        assert document.kind=="ifc" and document.pages==[]
        for scene in [document.scene,import_ifc(data,"direct")]:
            assert not scene.derived and scene.source_kind=="ifc" and scene.catalog_complete and scene.units=="m"
            assert {e.id for e in scene.elements}=={wall.GlobalId,window.GlobalId,space.GlobalId}
            assert all(e.geometry_origin=="extracted" and e.source.kind=="ifc" for e in scene.elements)
    finally:
        store.close()


class DrawingProvider:
    # This legacy fixture tests pre-review behavior; reviewed QA has dedicated fixtures.
    legacy_fixture_without_review = True
    def __init__(self, decisions=("sufficient",)):
        self.decisions=iter(decisions)
        self.calls=[]
        self.usage=Usage()

    def gate(self,document,question,crop=None):
        assert document.pages and all(p.path.exists() for p in document.pages)
        assert json.loads(source_context(document))["source_kind"]=="drawing"
        self.calls.append("gate")
        return GateResult(decision=next(self.decisions))

    def choose_crop(self,document,question):
        self.calls.append("crop")
        return CropRequest(page=2,bbox=[.1,.2,.4,.6],reason="Inspect the original upper-floor region")

    def answer(self,document,question,gate,crop=None):
        self.calls.append("answer")
        return DraftAnswer(status="answered",answer="The original drawing was inspected by the fixture provider.",
            evidence=[{"page":2,"bbox":[.1,.2,.7,.8],"label":"Bedroom","observation":"The upper source diagram region"}])


@pytest.mark.parametrize("decisions",[("sufficient",),("unclear","sufficient")])
def test_derived_qa_cannot_enter_native_count_path_even_with_wrong_document_kind(tmp_path,artifact_bundle,monkeypatch,decisions):
    store=DocumentStore(tmp_path/"qa")
    try:
        document=store.add(artifact_bundle[0],"derived.ifc")
        document.kind="ifc"  # Defense in depth: derived status overrides a stale document tag.
        document.scene.catalog_complete=True
        def forbidden(*args):
            raise AssertionError("Derived inventory was used as factual evidence")
        monkeypatch.setattr("app.service.ifc_count",forbidden)
        provider=DrawingProvider(decisions)
        result=ask(document,"How many rooms are in this model?",provider)
        assert result.answer.startswith("The original drawing") and not result.model_evidence
        assert provider.calls==(["gate","answer"] if len(decisions)==1 else ["gate","crop","gate","answer"])
        assert result.inspected_pages==[1,2]
    finally:
        store.close()


def test_reopened_context_excludes_generated_dimensions_properties_and_measurements(tmp_path,artifact_bundle):
    store=DocumentStore(tmp_path/"context")
    try:
        document=store.add(artifact_bundle[0],"derived.ifc")
        document.kind="ifc"
        document.scene.elements[0].properties.append(Property(name="INVENTED_DIMENSION",value=123456,origin="derived"))
        context=source_context(document)
        # Restored descriptions remain explicitly fallible source interpretations;
        # neither their measurements nor generated IFC are independent evidence.
        assert "TRANSCRIBED_HEIGHT_MARKER" in context and "9876" in context
        assert "INVENTED_DIMENSION" not in context and "123456" not in context
        parsed=json.loads(context)
        assert parsed["source_kind"]=="drawing"
        assert "Original pages are authoritative" in parsed["evidence_rule"]
        assert all({"id","label","page","bbox"} <= set(f) for f in parsed["floors"])
        assert all(e["provenance"]=="interpretation" and {"page","bbox"} <= set(e["source"]) and not e["source"].get("global_id") for e in parsed["objects"])
        assert all("geometry" not in e and "properties" not in e and "assumptions" not in e for e in parsed["objects"])
        bad=DraftAnswer(status="answered",answer="Height from generated IFC",model_evidence=[{
            "element_id":document.scene.elements[0].id,"label":"IFC height","observation":"Assumed height"}])
        with pytest.raises(ProviderError,match="IFC evidence for a drawing"):
            validate_draft(bad,document,GateResult(decision="sufficient"))
        document.pages=[]
        provider=DrawingProvider()
        with pytest.raises(ProviderError,match="Original drawing pages are required"):
            ask(document,"What is the height?",provider)
        assert provider.calls==[]
    finally:
        store.close()


@pytest.mark.parametrize("same_page",[False,True])
def test_same_room_label_highlights_only_matching_original_floor_region(tmp_path,artifact_bundle,same_page):
    store=DocumentStore(tmp_path/"highlight")
    try:
        if same_page:
            original=store.add(pdf(1),"two-panels.pdf")
            first=floor("Ground",source=region(bbox=[0,0,.49,1]),rooms=[room("Bedroom",[[.1,.2],[.4,.2],[.4,.8],[.1,.8]])])
            second=floor("Upper",source=region(bbox=[.51,0,1,1]),rooms=[room("Bedroom",[[.6,.2],[.9,.2],[.9,.8],[.6,.8]])])
            data=generate_ifc(description(first,second),original)
        else:
            data=artifact_bundle[0]
        document=store.add(data,"derived.ifc")
        rooms=[e for e in document.scene.elements if e.kind=="room"]
        selected=rooms[1]
        draft=DraftAnswer(status="answered",answer="See the upper Bedroom",evidence=[{
            "page":selected.source.page,"bbox":selected.source.bbox,"label":"Bedroom","observation":"Original upper-floor region"}],
            highlight_ids=[r.id for r in rooms]+["unknown"])
        assert validated_highlights(draft,document)==[selected.id]
        assert selected.storey_id==document.scene.floors[1].id
        draft.evidence[0].label="Kitchen"
        assert validated_highlights(draft,document)==[]
        assert len(draft.evidence)==1
    finally:
        store.close()


@pytest.mark.parametrize("path",["store","direct"])
def test_actual_same_page_storey_membership_must_match_manifest(tmp_path,path):
    store=DocumentStore(tmp_path)
    try:
        original=store.add(pdf(1),"two-panels.pdf")
        first=floor("Ground",source=region(bbox=[0,0,.49,1]),rooms=[room("Bedroom",[[.1,.2],[.4,.2],[.4,.8],[.1,.8]])])
        second=floor("Upper",source=region(bbox=[.51,0,1,1]),rooms=[room("Bedroom",[[.6,.2],[.9,.2],[.9,.8],[.6,.8]])])
        model=ifcopenshell.file.from_string(generate_ifc(description(first,second),original).decode())
        space=model.by_type("IfcSpace")[0]
        space.Decomposes[0].RelatingObject=model.by_type("IfcBuildingStorey")[1]
        data=model.to_string().encode()
        with pytest.raises(DocumentError) as error:
            if path=="store":
                store.add(data,"wrong-floor.ifc")
            else:
                import_ifc(data,"direct")
        assert error.value.status==422
    finally:
        store.close()
