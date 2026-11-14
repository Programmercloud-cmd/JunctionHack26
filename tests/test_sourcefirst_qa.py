"""Source-first QA control-flow regressions; fake outputs are not live inference."""
import pytest
from app.building import BuildingDescription
from app.documents import DocumentStore
from app.provider import GeminiProvider, ProviderError, INTERPRETATION_INSTRUCTIONS
from app.openai_provider import OpenAIProvider
from app.reasoning import build_reasoning, retrieve_context
from app.review_schema import DescriptionPatch
from app.schemas import (Clarification, CropRequest, DraftAnswer, Evidence, GateResult,
                         QuestionIntent, Usage)
from app.service import ask, validate_draft
from test_backend import png, evidence
from test_ifc_generate import description, floor, room
from test_reviewed_qa import ReviewedFixture


@pytest.fixture
def drawing(tmp_path):
    store=DocumentStore(tmp_path);document=store.add(png(),'floor.png')
    document.revision_id='source-only-revision'
    yield document
    store.close()


def test_interpretation_objects_and_floors_exist_without_scene(drawing):
    drawing.description=description(floor(rooms=[room(label='Laboratory')]))
    drawing.description.floors[0].persistent_id='floor-id'
    drawing.description.floors[0].rooms[0].persistent_id='room-id'
    result=build_reasoning(drawing)
    assert result['floors'][0]['id']=='floor-id'
    assert result['objects'][0]['name']=='Laboratory'
    assert result['objects'][0]['geometry_available'] is False
    assert result['coverage']['catalog_complete'] is False
    drawing.reasoning=result
    context=retrieve_context(drawing,'What spaces are depicted?')
    assert context['floors'][0]['id']=='floor-id' and context['objects'][0]['id']=='room-id'
    assert drawing.scene is None


def test_originals_available_before_extraction(drawing):
    result=retrieve_context(drawing,'How many doors are depicted?')
    assert result['objects']==[] and result['coverage']['inspected_pages']==[]
    assert result['sources']['pages'][0]['page']==1
    assert result['coverage']['available_pages']==[1]


def test_source_only_provider_stage_does_not_request_geometry_or_review(drawing):
    for cls in (GeminiProvider,OpenAIProvider):
        provider=cls.__new__(cls);provider.reconstruction_model='unchanged-model'
        calls=[]
        def generate(doc,question,instruction,schema,*args,**kwargs):
            calls.append((doc,question,instruction,schema,kwargs))
            return BuildingDescription(floors=[],limitations=[])
        if cls is GeminiProvider:provider._generate=generate
        else:provider._parse=generate
        output=provider.extract_interpretation(drawing)
        assert output.floors==[] and len(calls)==1
        assert calls[0][2]==INTERPRETATION_INSTRUCTIONS
        assert calls[0][0].scene is None and calls[0][0].description is None
        assert 'Do NOT trace' in calls[0][2]
        if cls is GeminiProvider:assert calls[0][4]['model']=='unchanged-model'


def test_geometry_enrichment_uses_typed_patch_and_exact_saved_interpretation(drawing):
    drawing.description=description(floor(rooms=[room()]))
    provider=GeminiProvider.__new__(GeminiProvider);provider.reconstruction_model='same-model'
    calls=[]
    def generate(doc,question,instruction,schema,**kwargs):
        calls.append((schema,kwargs))
        return DescriptionPatch(base_revision_id=doc.revision_id)
    provider._generate=generate
    assert provider.enrich_geometry(drawing).base_revision_id==drawing.revision_id
    assert calls[0][0] is DescriptionPatch
    assert calls[0][1]['extra_data']['description']==drawing.description.model_dump(mode='json')


def test_clarification_is_not_a_refusal_or_evidence_gate(drawing):
    class Clarifying:
        usage=Usage()
        def resolve_intent(self,document,question):
            assert document.pages[0].path.exists()
            return QuestionIntent(action='clarify',clarification=Clarification(message='Which floor?',suggestions=['Ground floor','Upper floor','Both']))
        def gate(self,*args):pytest.fail('Clarification must not invoke evidence gate')
    result=ask(drawing,'What about that floor?',Clarifying())
    assert result.status=='clarification' and result.gate is None
    assert result.inspection_passes==0 and result.review_passes==0
    assert result.clarification.free_text_allowed and result.missing_information==[]


def test_resolved_followup_still_inspects_originals_and_reviews(drawing):
    class Followup(ReviewedFixture):
        def resolve_intent(self,document,question):
            assert document.question_context['conversation_context']['messages'][0]['question']=='How many doors are depicted?'
            return QuestionIntent(action='answer',resolved_question='How many doors are depicted on the upper floor?')
        def gate(self,document,question,crop=None):
            assert question=='How many doors are depicted on the upper floor?'
            assert document.pages[0].path.exists() and document.scene is None
            return super().gate(document,question,crop)
    drawing.conversation_context={'messages':[{'question':'How many doors are depicted?','answer':'Earlier fallible answer'}]}
    provider=Followup(DraftAnswer(status='answered',answer='Two depicted doors.',evidence=[evidence()]))
    result=ask(drawing,'What about the upper floor?',provider)
    assert result.status=='answered' and result.review_passes==1
    assert result.resolved_question.endswith('upper floor?')


def test_visible_door_count_without_geometry_is_supported_and_reviewed(drawing):
    refs=[evidence(bbox=[.1,.1,.3,.3]),evidence(bbox=[.5,.5,.7,.7])]
    provider=ReviewedFixture(DraftAnswer(status='answered',answer='Two doors are depicted; the connecting door is counted once.',evidence=refs,
        support_summary='Two distinct door symbols in the cited regions.'))
    result=ask(drawing,'Count doors depicted in this plan.',provider)
    assert result.status=='answered' and len(result.evidence)==2
    assert result.support_summary and result.review_decision=='supported'
    assert not result.highlight_ids and drawing.scene is None


def test_individually_ambiguous_opening_stays_unclear(drawing):
    provider=ReviewedFixture(DraftAnswer(status='unclear',answer='One opening in the cited region may be a door or an open passage; it changes the total by one.',
        evidence=[evidence(bbox=[.4,.4,.6,.6])],missing_information=['Whether the marked opening is a door.']),gate='unclear')
    result=ask(drawing,'How many depicted doors?',provider)
    assert result.status=='unclear' and result.gate.decision=='unclear'
    assert result.missing_information==['Whether the marked opening is a door.']


def test_multisource_page_numbers_are_not_limited_to_five():
    assert Evidence(page=9,bbox=[0,0,1,1],label='Door',observation='Visible symbol').page==9
    assert CropRequest(page=9,bbox=[0,0,.5,.5],reason='Inspect symbol').page==9


def test_conflicting_source_identity_rejected(drawing):
    draft=DraftAnswer(status='answered',answer='One symbol',evidence=[{**evidence(),'source_id':'wrong-source'}])
    with pytest.raises(ProviderError,match='conflicting'):
        validate_draft(draft,drawing,GateResult(decision='sufficient'))


def test_user_value_cannot_become_drawing_evidence(drawing):
    drawing.user_values=[{'id':'height-1','property':'storey_height','value':3,'unit':'m'}]
    drawing.conversation_context={'evidence_scope':'sources_and_user'}
    assert retrieve_context(drawing,'What height does the drawing establish?')['user_values']==[]
    drawing.question_context=retrieve_context(drawing,'What height does the drawing establish?')
    draft=DraftAnswer(status='answered',answer='3 m',user_value_evidence=['height-1'])
    with pytest.raises(ProviderError,match='outside the permitted'):
        validate_draft(draft,drawing,GateResult(decision='sufficient'))


def test_explicit_user_value_answer_has_server_attribution(drawing):
    drawing.user_values=[{'id':'height-1','property':'storey_height','value':3,'unit':'m'}]
    class UserValue(ReviewedFixture):
        def resolve_intent(self,document,question):
            return QuestionIntent(action='answer',resolved_question=question,evidence_scope='sources_and_user')
    provider=UserValue(DraftAnswer(status='answered',answer='The supplied height is 3 m.',user_value_evidence=['height-1']))
    result=ask(drawing,'What height did I supply? Use the provided value.',provider)
    assert result.status=='answered' and 'Provided by user' in result.answer
    assert result.user_value_attributions[0]['provenance']=='user_provided'
    assert not result.evidence and result.review_passes==1


def test_drawing_only_guard_survives_intent_rewrite(drawing):
    drawing.user_values=[{'id':'height-1','property':'storey_height','value':3,'unit':'m'}]
    class BadIntent(ReviewedFixture):
        def resolve_intent(self,document,question):
            return QuestionIntent(action='answer',resolved_question='What is the height?',evidence_scope='sources_and_user')
        def gate(self,document,question,crop=None):
            assert document.question_context['user_values']==[]
            return super().gate(document,question,crop)
    provider=BadIntent(DraftAnswer(status='insufficient',answer='The drawing has no height dimension.',evidence=[evidence()]),gate='insufficient')
    result=ask(drawing,'What height does the drawing establish?',provider)
    assert result.status=='insufficient'


def test_integer_coordinate_convention_is_explicitly_rejected_and_retained(drawing):
    from pydantic import ValidationError
    from app.provider import INTERPRETATION_INSTRUCTIONS, GEOMETRY_ENRICHMENT_INSTRUCTIONS
    raw={"floors":[{"label":"Fixture floor","source":{"page":1,"bbox":{"left":100,"top":200,"right":800,"bottom":900}}}],"limitations":[]}
    with pytest.raises(ValidationError):BuildingDescription.model_validate(raw)
    assert raw["floors"][0]["source"]["bbox"]["left"]==100
    for prompt in (INTERPRETATION_INSTRUCTIONS,GEOMETRY_ENRICHMENT_INSTRUCTIONS):
        assert "[0,1]" in prompt and "0-1000" in prompt and "0.5" in prompt


def test_reviewed_drawing_calculation_keeps_operands_and_source_regions(drawing):
    from app.schemas import Calculation,Operand
    provider=ReviewedFixture(DraftAnswer(status='answered',answer='The supported total is {result} m.',
        evidence=[evidence(),evidence(bbox=[.2,.2,.6,.6])],calculation=Calculation(operation='sum',unit='m',
            operands=[Operand(value=2,unit='m',evidence_index=0),Operand(value=3,unit='m',evidence_index=1)])))
    result=ask(drawing,'Add the two depicted lengths.',provider)
    assert result.status=='answered' and result.calculation_results[0]['value']==5
    assert result.calculation_results[0]['operands'][1]['source']['bbox']==[.2,.2,.6,.6]


def test_sources_only_strips_user_calibration_registration_and_stair_connection(drawing):
    from app.building import Calibration,Registration,StairConnection,FeatureDescription
    from test_ifc_generate import feature,region
    f=floor(features=[feature()])
    drawing.description=description(f)
    floor_record=drawing.description.floors[0]
    floor_record.calibration=Calibration(length_m=17,segment=[[.1,.1],[.9,.1]],source=region(),note='User distance',provenance='user_provided')
    floor_record.registration=Registration(reference_floor_id='other',anchor=[.2,.2],reference_anchor=[.2,.2],source=region(),reference_source=region(),basis='User alignment',status='supported',provenance='user_provided')
    floor_record.features[0].connection=StairConnection(target_floor_id='other',source=region(),basis='User stair link',status='supported',provenance='user_provided')
    drawing.user_values=[{'id':'calibration-1','property':'calibration','value':17,'unit':'m'}]
    drawing.conversation_context={'evidence_scope':'sources_and_user'}
    only=retrieve_context(drawing,'What height and calibration does the drawing establish?')
    rendered=only['interpretation']['floors'][0]
    assert only['evidence_scope']=='sources_only' and only['user_values']==[]
    assert rendered['calibration'] is None and rendered['registration'] is None
    assert rendered['features'][0]['connection'] is None
    supplied=retrieve_context(drawing,'Use the calibration value I provided.')
    assert supplied['user_values'][0]['provenance']=='user_provided'
    assert supplied['interpretation']['floors'][0]['calibration']['provenance']=='user_provided'
    assert drawing.description.floors[0].calibration.length_m==17
    assert drawing.reasoning['interpretation']['floors'][0]['calibration']['length_m']==17
