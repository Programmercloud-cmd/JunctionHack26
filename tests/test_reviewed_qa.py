"""Explicit review fixtures verify routing/progress; these are not live inference claims."""
from app.documents import DocumentStore
from app.providers.gemini import ProviderError
from app.schemas import DraftAnswer,GateResult,Usage,CropRequest,AnswerClaim
from app.review_schema import AnswerReview
from app.service import ask
from test_backend import png,evidence
from test_ifc_import import fixture_model,encode
import pytest
import ifcopenshell


class ReviewedFixture:
    def __init__(self,draft,revised=None,decisions=('supported',),gate='sufficient',crop=None):
        self.draft=draft;self.revised=revised or draft;self.decisions=iter(decisions);self.gate_value=gate
        self.crop=crop or CropRequest(page=1,bbox=[0,0,1,1],reason='No additional detail')
        self.usage=Usage();self.calls=[];self.seen=[]
    def gate(self,d,q,crop=None):self.calls.append('gate');return GateResult(decision=self.gate_value)
    def answer(self,d,q,g,crop=None):self.calls.append('draft');return self.draft.model_copy(deep=True)
    def choose_crop(self,d,q):self.calls.append('crop');return self.crop
    def review_answer(self,d,q,draft,g,crop=None,validation=None):
        self.calls.append('review');self.seen.append((d.snapshot(),draft.model_copy(deep=True),validation))
        return AnswerReview(decision=next(self.decisions))
    def revise_answer(self,d,q,draft,g,review,crop=None,validation=None):self.calls.append('repair');return self.revised.model_copy(deep=True)


@pytest.fixture
def drawing(tmp_path):
    store=DocumentStore(tmp_path);doc=store.add(png(),'drawing.png');doc.revision_id='revision-one'
    yield doc
    store.close()


def test_supported_answer_and_refusal_are_both_reviewed(drawing):
    for status,gate in [('answered','sufficient'),('insufficient','insufficient')]:
        provider=ReviewedFixture(DraftAnswer(status=status,answer='Fixture result',evidence=[evidence()]),gate=gate)
        stages=[];result=ask(drawing,'Fixture question',provider,progress=stages.append)
        assert result.status==status and result.review_passes==1 and result.review_decision=='supported'
        assert 'Checking answer'in stages and provider.calls==['gate','draft','review']
        assert result.answered_revision_id=='revision-one'
        assert provider.seen[0][0].pages[0].path.read_bytes()==drawing.pages[0].path.read_bytes()


def test_same_unsupported_claim_rephrased_is_not_progress(drawing):
    provider=ReviewedFixture(DraftAnswer(status='answered',answer='The actual height is 3 metres.',evidence=[evidence()]),
        revised=DraftAnswer(status='answered',answer='This building has a 3 m actual height.',evidence=[evidence()]),decisions=('unsupported',))
    result=ask(drawing,'Actual height?',provider)
    assert result.status=='unclear'and '3 m'not in result.answer and result.review_passes==1
    assert provider.calls.count('review')==1


def test_new_source_inspection_allows_corrected_draft(drawing):
    provider=ReviewedFixture(DraftAnswer(status='answered',answer='Fixture: 3 windows',evidence=[evidence()]),
        revised=DraftAnswer(status='answered',answer='Fixture: 2 windows',evidence=[evidence(bbox=[.1,.1,.5,.5])]),decisions=('contradicted','supported'),
        crop=CropRequest(page=1,bbox=[.1,.1,.5,.5],reason='Inspect fixture window symbols'))
    result=ask(drawing,'How many windows?',provider)
    assert result.answer=='Fixture: 2 windows'and result.review_passes==2 and result.inspection_passes==2


def test_unsupported_actual_height_narrows_to_refusal(drawing):
    provider=ReviewedFixture(DraftAnswer(status='answered',answer='Height is 2.6m',evidence=[evidence()]),
        revised=DraftAnswer(status='insufficient',answer='The inspected drawing does not establish actual height.',evidence=[evidence()],missing_information=['A height dimension or section']),decisions=('unsupported','supported'))
    result=ask(drawing,'What is the actual height?',provider)
    assert result.status=='insufficient'and not result.highlight_ids


def test_claim_removal_uses_existing_claim_text_not_rephrased_free_prose(drawing):
    first=DraftAnswer(status='answered',answer='Unused',evidence=[evidence()],claims=[AnswerClaim(text='Fixture room label A is present.'),AnswerClaim(text='Actual height is 3m.')])
    revised=DraftAnswer(status='answered',answer='Actual height is three metres.',evidence=[evidence()],retained_claim_ids=['claim:0'])
    provider=ReviewedFixture(first,revised,('unsupported','supported'))
    result=ask(drawing,'Describe supported information',provider)
    assert result.answer=='Fixture room label A is present.'
    assert provider.seen[-1][1].answer==result.answer


def test_missing_review_hook_fails_instead_of_publishing(drawing):
    provider=ReviewedFixture(DraftAnswer(status='answered',answer='Fixture',evidence=[evidence()]))
    provider.review_answer=None
    with pytest.raises(ProviderError,match='required answer review'):ask(drawing,'Question',provider)


@pytest.mark.parametrize("question", [
    "How many windows are in this IFC model?",
    "how many windows are in the building?",
])
def test_native_wrong_count_is_replaced_by_source_bound_count_including_meshless(tmp_path, question):
    model,wall,window,space=fixture_model();store=DocumentStore(tmp_path)
    model.create_entity("IfcBuilding", GlobalId=ifcopenshell.guid.new())
    try:
        doc=store.add(encode(model),'native.ifc');doc.source_bytes=encode(model)
        provider=ReviewedFixture(DraftAnswer(status='answered',answer='999 windows',model_evidence=[{'element_id':window.GlobalId,'label':'Window','observation':'Fixture wrong count'}]))
        result=ask(doc,question,provider)
        assert result.answer.startswith('1 windows')and result.calculation_results[0]['value']==1
        assert result.model_evidence[0].element_id==window.GlobalId
        assert not next(e for e in doc.scene.elements if e.id==window.GlobalId).geometry
        assert provider.seen[0][1].answer.startswith('1 windows')
    finally:store.close()


def test_initial_false_abstention_can_recover_after_new_inspection(drawing):
    class Reconsidered(ReviewedFixture):
        def gate(self,d,q,crop=None):
            self.calls.append('gate')
            return GateResult(decision='sufficient' if crop else 'insufficient')
    provider=Reconsidered(DraftAnswer(status='insufficient',answer='Fixture initial missed label.'),
        revised=DraftAnswer(status='answered',answer='Fixture label is Kitchen.',evidence=[evidence(bbox=[.1,.1,.5,.5])]),
        decisions=('contradicted','supported'),crop=CropRequest(page=1,bbox=[.1,.1,.5,.5],reason='Inspect previously missed label'))
    result=ask(drawing,'What is the room label?',provider)
    assert result.status=='answered'and result.gate.decision=='sufficient'and result.review_passes==2
    assert provider.calls.count('gate')==2
