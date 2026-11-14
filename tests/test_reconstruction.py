"""All-source reconstruction, cached IFC and strict partial geometry behavior."""
import json
from fastapi.testclient import TestClient
import pytest
from app.building import BuildingDescription
from app.documents import DocumentError, DocumentStore
from app.highlights import validated_highlights
from app.main import create_app
from app.provider import ProviderError
from app.reconstruction import reconstruct_scene
from app.schemas import DraftAnswer
from app.source_context import source_context
from test_backend import png, pdf
from test_ifc_generate import description, floor, room, region


class ReconstructionProvider:
    def __init__(self, output=None):
        self.calls=[]
        self.output=output if output is not None else description()
    def reconstruct(self, document, page=None):
        self.calls.append([p.number for p in document.pages])
        return self.output
    def close(self):pass


def test_whole_document_cached_scene_source_refs_and_assumption_separation(tmp_path):
    provider=ReconstructionProvider(description(floor('Ground',source=region(1)),floor('Upper',source=region(2))))
    app=create_app(provider_factory=lambda:provider,storage_root=tmp_path)
    with TestClient(app) as client:
        doc=client.post('/api/documents',files={'file':('two.pdf',pdf(2))}).json()
        path=f"/api/documents/{doc['document_id']}/scene"
        assert client.get(path).status_code==404
        result=client.post(path,json={'page':2})
        assert result.status_code==200,result.text
        scene=result.json()
        assert scene['derived'] and scene['units']=='relative' and not scene['catalog_complete']
        assert {f['source']['page'] for f in scene['floors']}=={1,2}
        assert all(e['geometry_origin']=='inferred' and e['geometry']['type']=='mesh' for e in scene['elements'])
        assert client.post(path,json={'page':1}).json()==scene
        assert client.get(path).json()==scene and provider.calls==[[1,2]]
        context=json.loads(source_context(app.state.documents.get(doc['document_id'])))
        assert len(context['objects'])==2 and len(context['floors'])==2
        assert set(context['objects'][0])=={'id','kind','name','page','bbox','floor_id'}
        assert 'assumptions' not in json.dumps(context) and 'height' not in json.dumps(context)
        data=client.get(scene['ifc_url'])
        assert data.status_code==200 and data.content.startswith(b'ISO-10303-21;')


@pytest.mark.parametrize('output',[
    BuildingDescription(floors=[],limitations=['No depicted floor']),
    description(floor(rooms=[room(polygon=[[.1,.1],[.9,.9],[.1,.9],[.9,.1]])])),
    description(floor(rooms=[room(polygon=[[-.1,0],[.9,0],[.9,.9]])])),
    description(floor(rooms=[room(polygon=[[0,0,0],[.9,0],[.9,.9]])])),
    description(floor(rooms=[room('Outer',[[0,0],[1,0],[1,1],[0,1]]),room('Inner',[[.1,.1],[.9,.1],[.9,.9],[.1,.9]])])),
])
def test_no_usable_geometry_is_not_cached(tmp_path,output):
    provider=ReconstructionProvider(output)
    with TestClient(create_app(provider_factory=lambda:provider,storage_root=tmp_path)) as client:
        doc=client.post('/api/documents',files={'file':('plan.png',png())}).json()
        path=f"/api/documents/{doc['document_id']}/scene"
        assert client.post(path,json={}).status_code==422
        assert client.get(path).status_code==404
        assert client.get(f"/api/documents/{doc['document_id']}/model.ifc").status_code==404


@pytest.mark.parametrize('bad_polygon',[
    [[.1,.1],[.9,.9],[.1,.9],[.9,.1]], [[-.1,0],[.9,0],[.9,.9]], [[0,0,0],[.9,0],[.9,.9]],
])
def test_partial_model_retains_source_and_omitted_room_cannot_highlight(tmp_path,bad_polygon):
    store=DocumentStore(tmp_path)
    try:
        doc=store.add(png(),'plan.png')
        provider=ReconstructionProvider(description(floor(rooms=[room('Broken',bad_polygon),room('Bedroom',[[.6,.2],[.9,.2],[.9,.8],[.6,.8]])])))
        doc.scene=reconstruct_scene(doc,1,provider)
        rooms=[e for e in doc.scene.elements if e.kind=='room']
        assert len(rooms)==1 and rooms[0].name=='Bedroom'
        assert rooms[0].source.bbox==[.6,.2,.9,.8] and rooms[0].geometry.type=='mesh'
        assert any('omitted 1' in w.lower() for w in doc.scene.warnings)
        assert 'Broken' not in source_context(doc)
        answer=DraftAnswer(status='answered',answer='Original source remains available.',evidence=[{'page':1,'bbox':[.1,.1,.5,.5],'label':'Broken','observation':'Broken room region'}],highlight_ids=['omitted-id'])
        assert validated_highlights(answer,doc)==[] and answer.evidence
        second=store.add(doc.ifc_bytes,'derived.ifc')
        assert {e.id for e in second.scene.elements}=={e.id for e in doc.scene.elements}
    finally:store.close()


def test_reconstruction_provider_failure_sanitized(tmp_path):
    class Failing:
        def reconstruct(self,*args):raise RuntimeError('private response body')
    store=DocumentStore(tmp_path)
    try:
        with pytest.raises(ProviderError) as error:reconstruct_scene(store.add(png(),'plan.png'),1,Failing())
        assert 'private' not in error.value.message
    finally:store.close()


@pytest.mark.parametrize('provider_name',['gemini','openai'])
def test_actual_sdk_building_schema_sees_all_original_pages(tmp_path,monkeypatch,provider_name):
    import httpx2
    from app.provider import GeminiProvider
    from app.openai_provider import OpenAIProvider
    from test_openai_provider import intercept,response
    monkeypatch.setenv('GEMINI_API_KEY','offline-only');monkeypatch.setenv('OPENAI_API_KEY','offline-only')
    calls=[]
    output=description(floor('Ground',source=region(1)),floor('Upper',source=region(2)))
    def handler(request):
        body=json.loads(request.content);calls.append(body)
        if provider_name=='openai':
            content=body['input'][0]['content']
            assert len([p for p in content if p['type']=='input_image'])==2
            assert any('page 2' in p.get('text','') for p in content)
            assert body['text']['format']['strict'] is True
            return httpx2.Response(200,json=response(output.model_dump()))
        parts=body['contents'][0]['parts']
        assert len([p for p in parts if 'inlineData' in p])==2
        assert any('page 2' in p.get('text','') for p in parts)
        schema=body['generationConfig']['responseJsonSchema']
        assert schema['$defs']['RoomDescription']['properties']['polygon']['items']['type']=='object'
        return httpx2.Response(200,json={'candidates':[{'content':{'parts':[{'text':output.model_dump_json()}],'role':'model'},'finishReason':'STOP'}],'usageMetadata':{'promptTokenCount':1,'candidatesTokenCount':1}})
    provider=GeminiProvider() if provider_name=='gemini' else OpenAIProvider()
    if provider_name=='gemini':
        provider.client._api_client._httpx_client.close()
        provider.client._api_client._httpx_client=httpx2.Client(transport=httpx2.MockTransport(handler))
    else:intercept(provider,handler)
    store=DocumentStore(tmp_path)
    try:
        doc=store.add(pdf(2),'two.pdf')
        assert provider.reconstruct(doc,2)==output
        assert len(calls)==1 and doc.scene is None and len(doc.pages)==2
    finally:provider.close();store.close()
