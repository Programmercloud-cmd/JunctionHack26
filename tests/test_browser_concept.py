"""Concept integration and atomic revisions; all inference in these tests is a fixture."""
import json
import os
import socket
import threading
import time

import pytest
from test_browser import ask, upload
from test_browser_3d import scene_page, snapshot
from test_browser_v3 import SemanticFixtureProvider, generate

pytestmark=pytest.mark.skipif(os.getenv('RUN_BROWSER_TESTS')!='1',reason='opt-in browser checks')


class ConceptFixtureProvider(SemanticFixtureProvider):
    legacy_fixture_without_review = True
    def reconstruct(self,document):
        from app.building import FeatureDescription
        d=super().reconstruct(document)
        d.floors[0].rooms[0].label='Prayer hall / worship space'
        d.floors[0].features.extend([
            FeatureDescription(kind='cabinet',label='Irregular source cabinet',polygon=[[.31,.50],[.43,.50],[.43,.54],[.35,.54],[.35,.62],[.31,.62]],source={'page':1,'bbox':[.30,.49,.44,.63]},basis='observed',note='Fixture concave source footprint'),
            FeatureDescription(kind='appliance',label='Unspecified equipment',polygon=[[.45,.60],[.55,.60],[.55,.67],[.45,.67]],source={'page':1,'bbox':[.44,.59,.56,.68]},basis='observed',note='Generic equipment; no appliance subtype established'),
            FeatureDescription(kind='chair',label='Rotated source chair',polygon=[[.35,.275],[.40,.35],[.35,.425],[.30,.35]],source={'page':1,'bbox':[.29,.27,.41,.43]},basis='observed',note='Fixture rotated rectangle'),
        ])
        return d


@pytest.fixture
def concept_server(tmp_path,monkeypatch):
    import uvicorn
    from app.main import create_app
    monkeypatch.setenv('AI_PROVIDER','gemini');monkeypatch.setenv('GEMINI_API_KEY','fixture-never-sent')
    ConceptFixtureProvider.unresolved_only=False
    app=create_app(provider_factory=ConceptFixtureProvider,storage_root=tmp_path/'uploads')
    sock=socket.socket();sock.bind(('127.0.0.1',0));server=uvicorn.Server(uvicorn.Config(app,log_level='error'))
    thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True);thread.start()
    deadline=time.monotonic()+5
    while not server.started and time.monotonic()<deadline:time.sleep(.02)
    assert server.started
    yield f'http://127.0.0.1:{sock.getsockname()[1]}'
    server.should_exit=True;thread.join(5);sock.close()


def click_concept_record(page,record_id):
    # Find a visible triangle of this exact record, then use a real pointer click.
    page.locator('#model-canvas-container').scroll_into_view_if_needed()
    point=page.evaluate("""async id=>{
      const THREE=await import('three'),v=window.blueprintViewer,c=v.concept;
      c.group.updateMatrixWorld(true);v.camera.updateMatrixWorld(true);
      const rect=v.renderer.domElement.getBoundingClientRect(),ray=new THREE.Raycaster();let result=null;
      c.group.traverse(m=>{if(result||!m.isMesh||m.userData.conceptRecord!==id)return;
        const p=m.geometry.attributes.position,ix=m.geometry.index;
        for(let i=0;i<(ix?ix.count:p.count);i+=3){
          const center=new THREE.Vector3();for(let j=0;j<3;j++)center.add(new THREE.Vector3().fromBufferAttribute(p,ix?ix.getX(i+j):i+j));center.multiplyScalar(1/3);m.localToWorld(center);center.project(v.camera);
          if(Math.abs(center.x)>1||Math.abs(center.y)>1)continue;ray.setFromCamera(center,v.camera);
          if(c.pick(ray)?.id===id){result={x:rect.x+(center.x+1)*rect.width/2,y:rect.y+(1-center.y)*rect.height/2};break;}
        }
      });return result;
    }""",record_id)
    assert point, f'No visible triangle found for {record_id}'
    page.mouse.click(point['x'],point['y'])


def test_concept_proposals_source_picking_footprints_and_export(concept_server,scene_page,tmp_path):
    from playwright.sync_api import expect
    page=scene_page;generate(page,concept_server)
    data=page.evaluate('window.blueprintViewer.data')
    requests=[];page.on('request',lambda r:requests.append(r.url)if '/api/'in r.url else None)
    page.locator('#show-concept').click()
    expect(page.locator('.concept-disclosure')).to_be_visible()
    expect(page.locator('#scene-badge')).to_contain_text('unscaled')
    expect(page.locator('#show-assumptions')).to_be_visible()
    records=snapshot(page)['concept_records']
    proposals=[r for r in records if r['kind']=='proposal']
    assert proposals
    hall=next(e for e in data['elements']if e['name']=='Prayer hall / worship space')
    assert not any(r['host_id']==hall['id']for r in proposals), 'Uncertain/nonresidential room use must not receive house furnishings'
    assert all(r['source_id']is None for r in proposals)
    cabinet=next(e for e in data['elements']if e['name']=='Irregular source cabinet')
    assert next(r for r in records if r['id']==cabinet['id'])['fallback']
    rotated=next(e for e in data['elements']if e['name']=='Rotated source chair')
    assert not next(r for r in records if r['id']==rotated['id'])['fallback'], page.evaluate('id=>window.blueprintViewer.concept.sourceRings.get(id)',rotated['id'])
    # Every styled source vertex remains within its actual projected source mesh,
    # including a rotated rectangle and a concave schematic fallback.
    check=page.evaluate('''() => {
      const v=window.blueprintViewer,c=v.concept,failures=[];c.group.updateMatrixWorld(true);
      for(const floor of c.floors.values())for(const item of floor.elements){
        if(!['furniture','fixture'].includes(item.element.kind))continue;
        floor.group.traverse(mesh=>{if(!mesh.isMesh||mesh.userData.conceptRecord!==item.element.id)return;
          const p=mesh.geometry.attributes.position;
          for(let i=0;i<p.count;i++){const q=v.camera.position.clone().fromBufferAttribute(p,i);mesh.localToWorld(q);q.z-=floor.group.position.z;if(!c.inside(item,q.x,q.y))failures.push(item.element.name);}
        });
      }
      return failures;
    }''')
    assert not check,check
    equipment=next(e for e in data['elements']if e['name']=='Unspecified equipment')
    # Generic styling is a box, not the circular burner pattern in the old renderer.
    xy=page.evaluate('''id=>{const pairs=new Set();window.blueprintViewer.concept.group.traverse(m=>{if(m.isMesh&&m.userData.conceptRecord===id){const p=m.geometry.attributes.position;for(let i=0;i<p.count;i++)pairs.add(p.getX(i).toFixed(4)+','+p.getY(i).toFixed(4));}});return pairs.size;}''',equipment['id'])
    assert xy<50
    page.locator('#show-assumptions').check()
    colors=page.evaluate('''id=>{const out=[];window.blueprintViewer.concept.group.traverse(m=>{if(m.isMesh&&m.userData.conceptRecord===id)out.push(m.material.color.getHex());});return out;}''',rotated['id'])
    assert colors and all(c==0xe4ae55 for c in colors)
    page.evaluate('id=>window.blueprintViewer.setHighlights([id],true)',rotated['id'])
    appearance=page.evaluate('''id=>{const out=[];window.blueprintViewer.concept.group.traverse(m=>{if(m.isMesh&&m.userData.conceptRecord)out.push({id:m.userData.conceptRecord,color:m.material.color.getHex(),opacity:m.material.opacity});});return out;}''',rotated['id'])
    assert all(m['color']==0xcce979 for m in appearance if m['id']==rotated['id'])
    assert all(m['opacity']==.1 for m in appearance if m['id']!=rotated['id'])
    page.locator('#show-assumptions').uncheck()
    assert snapshot(page)['highlight_ids']==[rotated['id']]
    page.evaluate('window.blueprintViewer.setHighlights([],true)')
    click_concept_record(page,proposals[0]['id'])
    expect(page.locator('#concept-selection-name')).to_contain_text('Proposal')
    expect(page.locator('#concept-selection-note')).to_contain_text('not depicted source evidence')
    page.locator('#concept-support-source').click();expect(page.locator('#evidence-overlay')).to_be_visible()
    page.locator('#show-concept').click()
    click_concept_record(page,rotated['id'])
    expect(page.locator('#element-inspector')).to_be_visible()
    page.locator('#element-source').click();expect(page.locator('#evidence-overlay')).to_be_visible()
    page.locator('#show-concept').click()
    page.locator('#concept-cutaway').uncheck()
    assert page.evaluate('window.blueprintViewer.concept.cuts.every(c=>c.material.clippingPlanes.length===0)')
    page.locator('#concept-cutaway').check()
    assert page.evaluate('window.blueprintViewer.concept.cuts.every(c=>c.material.clippingPlanes.length===1)')
    assert page.evaluate('window.blueprintViewer.data')==data
    assert snapshot(page)['concept_build_count']==1
    assert requests==[]
    with page.expect_download()as event:page.locator('#download-ifc').click()
    artifact=tmp_path/'concept.ifc';event.value.save_as(artifact)
    assert 'proposal:' not in artifact.read_text()
    ask(page,'What is the actual ceiling height?')
    expect(page.locator('#result-status')).to_have_text('Missing information')
    assert snapshot(page)['concept_build_count']==1
    page.screenshot(path='/tmp/product-concept-fixture.png',full_page=True)


def test_atomic_revision_preserves_view_and_discards_failed_stale_candidates(concept_server,scene_page):
    page=scene_page;generate(page,concept_server);page.locator('#show-concept').click()
    page.locator('#show-assumptions').check();page.locator('#concept-cutaway').uncheck()
    page.wait_for_timeout(250)
    result=page.evaluate('''() => {
      const v=window.blueprintViewer;v.data.building_id='fixture-building';v.data.revision_id='r1';v.data.revision_number=1;
      const source=v.data.elements.find(e=>e.kind==='furniture');v.select(source.id);
      v.setHighlights([source.id]);const before=v.getSnapshot(),beforeData=JSON.stringify(v.data),oldMesh=v.meshes.get(source.id);
      let retired=false;oldMesh.geometry.addEventListener('dispose',()=>retired=true);
      const next=structuredClone(v.data);next.revision_id='r2';next.revision_number=2;next.elements.reverse();
      const prepared=v.prepareRevision(next);
      const detached=!prepared.group.parent && (!prepared.concept||!prepared.concept.group.parent);
      const unchanged=JSON.stringify(v.data)===beforeData && !retired;
      v.commitRevision(prepared);const after=v.getSnapshot();
      const invalid=structuredClone(next);invalid.revision_id='bad';invalid.revision_number=3;invalid.elements.find(e=>e.geometry).geometry.positions=[NaN,0,0];
      let failed=false;try{v.prepareRevision(invalid);}catch{failed=true;}
      const currentMesh=v.meshes.get(source.id);let currentDisposed=false;currentMesh.geometry.addEventListener('dispose',()=>currentDisposed=true);
      const badConcept=structuredClone(next);badConcept.revision_id='bad-concept';badConcept.revision_number=3;badConcept.floors[0].transform=[[]];
      let failedConcept=false;try{v.prepareRevision(badConcept);}catch{failedConcept=true;}
      const retainedAfterConceptFailure=!currentDisposed && v.meshes.get(source.id)===currentMesh && v.data.revision_id==='r2';
      const a=structuredClone(next);a.revision_id='r3';a.revision_number=3;
      const b=structuredClone(next);b.revision_id='r4';b.revision_number=4;
      const stale=v.prepareRevision(a),fresh=v.prepareRevision(b);v.commitRevision(fresh);
      let rejected=false;try{v.commitRevision(stale);}catch{rejected=true;}
      const same=v.prepareRevision(v.data);v.commitRevision(same);
      return {before,after,detached,unchanged,retired,failed,failedConcept,retainedAfterConceptFailure,rejected,staleDisposed:stale.disposed,current:v.data.revision_id,sameNoop:same.noop};
    }''')
    assert all(result[k]for k in ('detached','unchanged','retired','failed','failedConcept','retainedAfterConceptFailure','rejected','staleDisposed','sameNoop'))
    assert result['current']=='r4'
    for field in ('camera_position','camera_target','floor_filter','exploded','mode','cutaway','show_assumptions','selected_id','highlight_ids','concept_placements'):
        assert result['after'][field]==result['before'][field],field


def test_revision_ui_keeps_selected_proposal_then_retains_removed_source(concept_server,scene_page):
    from playwright.sync_api import expect
    page=scene_page;generate(page,concept_server);page.locator('#show-concept').click()
    page.evaluate("Object.assign(window.blueprintViewer.data,{building_id:'fixture-building',revision_id:'r1',revision_number:1})")
    source=page.evaluate("window.blueprintViewer.data.elements.find(e=>e.kind==='furniture')")
    page.locator('#element-select').select_option(source['id'])
    proposal=next(r for r in snapshot(page)['concept_records']if r['kind']=='proposal')
    page.locator('#concept-proposal-select').select_option(proposal['id'])
    expect(page.locator('#element-inspector')).to_be_hidden()
    before=snapshot(page)
    page.evaluate("async()=>{const next=structuredClone(window.blueprintViewer.data);next.revision_id='r2';next.revision_number=2;await loadScene(next);}")
    expect(page.locator('#concept-selection')).to_be_visible()
    expect(page.locator('#concept-proposal-select')).to_have_value(proposal['id'])
    expect(page.locator('#element-inspector')).to_be_hidden()
    assert snapshot(page)['camera_position']==pytest.approx(before['camera_position'],abs=1e-10)
    page.locator('#element-select').select_option(source['id'])
    page.evaluate("async id=>{const next=structuredClone(window.blueprintViewer.data);next.revision_id='r3';next.revision_number=3;next.elements=next.elements.filter(e=>e.id!==id);await loadScene(next);}",source['id'])
    expect(page.locator('#concept-selection')).to_be_hidden()
    expect(page.locator('#element-inspector')).to_be_visible()
    expect(page.locator('#element-geometry-note')).to_contain_text('Removed in the current revision')
    expect(page.locator('#revision-notice')).to_contain_text('previous source evidence remains available')
    assert snapshot(page)['selected_id']is None
    page.locator('#element-source').click();expect(page.locator('#evidence-overlay')).to_be_visible()
