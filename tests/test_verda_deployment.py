"""Deployment packaging contracts; these synthetic fixtures make no cloud/provider calls."""
import importlib.util
import json
from pathlib import Path
import stat

import pytest
from dotenv import dotenv_values
from app.bundles import BuildingStore
from app.review_schema import ReconstructionReview
from test_backend import png
from test_bundles_revisions import build
from test_ifc_generate import description

ROOT=Path(__file__).resolve().parents[1]


def module(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/(name+'.py'))
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value


def test_private_configuration_uses_shared_hash_helper_and_excludes_other_credentials(tmp_path,capsys):
    secrets=module('verda_prepare_secrets')
    source=tmp_path/'input.env';source.write_text('GEMINI_API_KEY=fixture-only-key\nGEMINI_MODEL=fixture-model\nOPENAI_API_KEY=fixture-other-key\nVERDA_CLIENT_SECRET=fixture-cloud-secret\n')
    destination=tmp_path/'private';secrets.prepare(source,destination)
    values=dotenv_values(destination/'application.env');code=(destination/'demo-access-code.txt').read_text().strip()
    assert values['AI_PROVIDER']=='gemini' and values['GEMINI_MODEL']=='fixture-model'
    assert values['BLUEPRINT_PUBLIC_DEMO']=='1' and values['GEMINI_API_KEY']=='fixture-only-key'
    assert values['BLUEPRINT_DEMO_ACCESS_CODE_HASH'].startswith('scrypt:')
    assert code not in (destination/'application.env').read_text()
    assert len(code)>=32 and len(values['BLUEPRINT_DEMO_SESSION_SECRET'])>=64
    assert not {'OPENAI_API_KEY','VERDA_CLIENT_SECRET'}&values.keys()
    assert stat.S_IMODE(destination.stat().st_mode)==0o700
    assert all(stat.S_IMODE(p.stat().st_mode)==0o600 for p in destination.iterdir())
    assert capsys.readouterr().out==''
    before=(destination/'application.env').read_bytes()
    with pytest.raises(FileExistsError):secrets.prepare(source,destination)
    assert (destination/'application.env').read_bytes()==before


def test_missing_gemini_configuration_creates_no_private_directory(tmp_path):
    source=tmp_path/'input.env';source.write_text('OPENAI_API_KEY=fixture-only\n')
    with pytest.raises(ValueError,match='no Gemini credential'):
        module('verda_prepare_secrets').prepare(source,tmp_path/'private')
    assert not (tmp_path/'private').exists()


def test_seed_retains_exact_revisions_sources_and_negative_review_without_copying_private_jobs(tmp_path):
    pack=module('verda_prepare_examples');installer=module('verda_install_seed')
    origin=tmp_path/'origin';store=BuildingStore(origin);doc=store.add(png(),'fixture.png')
    document=build(store,doc,description())
    review=ReconstructionReview(candidate_supported=False,summary='Explicit fixture with unresolved concerns')
    document=store.commit(store.prepare(document),document.revision_id,status='reviewed_issues',review=review)
    folder=store.directory(document.id)
    (folder/'jobs'/'private-job.json').write_text(json.dumps({'status':'running','private':'fixture'}))
    (folder/'conversation.json').write_text('[{"private":"fixture"}]')
    (folder/'diagnostics').mkdir();(folder/'diagnostics'/'response.json').write_text('{"private":"fixture"}')
    selection=tmp_path/'selection.json';selection.write_text(json.dumps([{'root':str(origin),'building_id':document.id,'revision_id':document.revision_id,'title':'Partial fixture'}]))
    output=tmp_path/'seed';result=pack.prepare(selection,output)
    assert result['examples']==1 and result['provider_calls']==0
    assert json.loads((folder/'jobs'/'private-job.json').read_text())['status']=='running'
    copied=output/'runtime'/'buildings'/document.id
    assert not list((copied/'jobs').iterdir())
    assert not (copied/'conversation.json').exists() and not (copied/'diagnostics').exists()
    ledger=json.loads((output/'example-review-ledger.json').read_text())[0]
    assert ledger['candidate_supported'] is False and ledger['review_present']
    assert ledger['portable_reopen']=='passed' and ledger['saved_status']=='reviewed_issues'
    target=tmp_path/'data';installer.install(output,target)
    restored=BuildingStore(target/'runtime')
    current=restored.get(document.id)
    assert current.revision_id==document.revision_id and current.source_bytes==document.source_bytes
    assert current.description==document.description and current.ifc_bytes==document.ifc_bytes
    assert current.frame_registry==document.frame_registry
    assert [e.id for e in current.scene.elements]==[e.id for e in document.scene.elements]
    restored.close();store.close()
    visitor=target/'runtime'/'buildings'/document.id/'conversation.json';visitor.write_text('[{"new":"visitor"}]')
    installer.install(output,target)
    assert visitor.read_text()=='[{"new":"visitor"}]'
    currentfile=target/'runtime'/'buildings'/document.id/'CURRENT.json';currentfile.write_text('{"new":"revision"}')
    with pytest.raises(ValueError,match='Destination conflict'):installer.install(output,target)
    assert currentfile.read_text()=='{"new":"revision"}'


def test_seed_integrity_rejects_tampering_before_copy(tmp_path):
    installer=module('verda_install_seed');seed=tmp_path/'seed';seed.mkdir()
    (seed/'public-examples.json').write_text('changed')
    (seed/'seed-hashes.json').write_text(json.dumps({'public-examples.json':'0'*64}))
    with pytest.raises(ValueError,match='integrity'):installer.install(seed,tmp_path/'target')
    assert not (tmp_path/'target').exists()
