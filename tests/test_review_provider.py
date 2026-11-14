"""Exercise the Gemini SDK serializer against a mocked transport."""
import json
from time import monotonic
import httpx2
import pytest
from app.documents import DocumentStore
from app.providers.gemini import GeminiProvider, ProviderError
from app.schemas import DraftAnswer, GateResult
from app.reconstruction import reconstruct_scene
from app.review_render import overlay_views
from test_backend import png
from test_ifc_generate import description


@pytest.fixture
def setup(tmp_path,monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY','offline-fixture')
    provider=GeminiProvider()
    store=DocumentStore(tmp_path);document=store.add(png(),'source.png');document.revision_id='r1'
    document.description=description()
    class Extract:
        def reconstruct(self,*args):return document.description
    document.scene=reconstruct_scene(document,1,Extract())
    yield provider,document
    provider.close();store.close()


def transport(provider,output,calls):
    def handler(request):
        body=json.loads(request.content);calls.append((body,request.extensions['timeout']))
        if str(request.url).endswith('/decisions'):
            return httpx2.Response(200,json={'answers':{'support':{'type':'choice','choice':output['decision'],'confidence':.7,'probabilities':{'supported':.7,'unsupported':.1,'contradicted':.1,'unclear':.1}}}})
        return httpx2.Response(200,json={'candidates':[{'content':{'role':'model','parts':[{'text':json.dumps(output)}]},'finishReason':'STOP'}]})
    provider.client._api_client._httpx_client.close()
    provider.client._api_client._httpx_client=httpx2.Client(transport=httpx2.MockTransport(handler))


def test_reconstruction_review_uses_original_and_actual_overlay_and_typed_patch(setup):
    provider,document=setup;calls=[]
    output={'issues':[],'candidate_supported':True,'summary':'Fixture review only'}
    transport(provider,output,calls)
    result=provider.review_reconstruction(document,document.description,document.scene)
    assert result.candidate_supported
    body,timeout=calls[0];assert timeout['read']==120
    content=body['contents'][0]['parts']
    images=[p for p in content if 'inlineData'in p]
    assert len(images)==2  # one original, one actual reopened IFC overlay
    assert any('ACTUAL REOPENED IFC'in p.get('text','')for p in content)
    calls=[];transport(provider,{'base_revision_id':'r1','operations':[],'transform_updates':[]},calls)
    patch=provider.patch_reconstruction(document,document.description,document.scene,result)
    assert patch.base_revision_id=='r1'and patch.operations==[]
    wire=calls[0][0]['generationConfig']['responseJsonSchema']
    assert 'RecordPatch'in wire['$defs']and 'python'not in wire['properties']


def test_answer_review_receives_original_evidence_draft_and_findings_with_one_route(setup):
    provider,document=setup;calls=[]
    transport(provider,{'decision':'supported'},calls)
    provider.request_deadline=monotonic()+7
    draft=DraftAnswer(status='insufficient',answer='No actual height is established by this fixture drawing.')
    review=provider.review_answer(document,'Actual height?',draft,GateResult(decision='insufficient'),validation={'errors':[],'calculations':[]})
    assert review.decision=='supported'and len(calls)==1 and 0<calls[0][1]['read']<=7
    body=calls[0][0]
    assert set(body['questions'])=={'support'}
    assert set(body['questions']['support']['criteria'])=={'supported','contradicted','unsupported','unclear'}
    content=body['input'];assert any(p.get('type')=='image'for p in content)
    text=' '.join(p.get('text','')for p in content)
    assert 'No actual height'in text and 'validation'in text and 'Original pages are authoritative'in text
    provider.request_deadline=monotonic()-1
    with pytest.raises(ProviderError,match='budget'):provider.review_answer(document,'Actual height?',draft,GateResult(decision='insufficient'))
    assert len(calls)==1


def test_review_overlay_follows_reopened_geometry_not_description(setup):
    _,document=setup
    before=overlay_views(document,document.scene)[0][1]
    original_description=document.description.model_dump_json()
    assert document.scene.comparison
    document.scene.comparison=[]
    after=overlay_views(document,document.scene)[0][1]
    assert before!=after and document.description.model_dump_json()==original_description


def test_overlay_preserves_original_strokes_under_translucent_geometry(setup):
    from io import BytesIO
    from PIL import Image,ImageDraw
    from app.scene import PlanComparison
    _,document=setup
    page=document.pages[0]
    image=Image.new('RGB',(page.width,page.height),'white')
    ImageDraw.Draw(image).rectangle((30,30,35,35),fill='black')
    image.save(page.path)
    document.scene.comparison=[PlanComparison(element_id='fixture',floor_id='floor',page=1,layer='spaces',polygons=[[[.1,.1],[.9,.1],[.9,.9],[.1,.9]]],method='Test-only actual geometry region')]
    with Image.open(BytesIO(overlay_views(document,document.scene)[0][1]))as result:
        black=result.convert('RGB').getpixel((32,32));white=result.convert('RGB').getpixel((40,32))
        assert max(black)<40 and min(white)>200
    with Image.open(page.path)as source:assert source.getpixel((32,32))==(0,0,0)
