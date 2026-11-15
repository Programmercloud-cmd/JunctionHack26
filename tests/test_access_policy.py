"""Timezone-aware peer-review windows use the runtime clock, never a restart timer."""
from datetime import datetime, timedelta, timezone
import json

import pytest
from fastapi.testclient import TestClient

from app.access_policy import evaluate_policy
from app.main import create_app
from app.public_access import PublicAccess
from test_peer_access import configured_access, verifier
from test_public_access import request
from test_public_access_integration import prepared


WINDOW={'mode':'window','opens_at':'2026-11-15T09:30:00+02:00','closes_at':'2026-11-15T14:00:00+02:00'}
START='2026-11-15T07:30:00+00:00'
END='2026-11-15T12:00:00+00:00'


@pytest.mark.parametrize('instant,required,next_change',[
    ('2026-11-15T07:29:59.999999+00:00',True,START),
    (START,False,END),
    ('2026-11-15T09:00:00+00:00',False,END),
    ('2026-11-15T11:59:59.999999+00:00',False,END),
    (END,True,None),
    ('2026-11-15T12:00:00.000001+00:00',True,None),
])
def test_window_start_inclusive_end_exclusive(instant,required,next_change):
    assert evaluate_policy(json.dumps(WINDOW),datetime.fromisoformat(instant))=={
        'required':required,'window':{'opens_at':START,'closes_at':END,
                                    'checked_at':instant,'next_change_at':next_change}}


def test_offsets_and_utc_z_are_normalized():
    value={'mode':'window','opens_at':'2026-11-15T07:30:00Z','closes_at':'2026-11-15T21:00:00+09:00','operator_note':'Fixture metadata'}
    result=evaluate_policy(json.dumps(value),datetime.fromisoformat('2026-11-15T04:00:00-05:00'))
    assert result=={'required':False,'window':{'opens_at':START,'closes_at':END,
        'checked_at':'2026-11-15T09:00:00+00:00','next_change_at':END}}


@pytest.mark.parametrize('value',[
    '', 'unknown', 'false', '{', 'null', '[]', '"open"', '{"mode":"open"}',
    {'mode':'window'}, WINDOW|{'opens_at':None},WINDOW|{'closes_at':123},
    WINDOW|{'opens_at':'2026-11-15T07:30:00'},
    WINDOW|{'closes_at':'2026-11-15T12:00:00'},
    WINDOW|{'opens_at':'not a date'},WINDOW|{'closes_at':'2026-11-15T12:00:00+25:00'},
    WINDOW|{'opens_at':END},WINDOW|{'opens_at':'2026-11-15T12:01:00+00:00'},
])
def test_invalid_or_naive_window_requires_code(value):
    text=json.dumps(value) if isinstance(value,dict) else value
    assert evaluate_policy(text,datetime.fromisoformat(START))=={'required':True,'window':None}


def test_naive_injected_clock_does_not_open_window():
    assert evaluate_policy(json.dumps(WINDOW),datetime(2026,11,15,9))=={'required':True,'window':None}


def test_default_clock_is_aware_utc_and_sampled_once():
    before=datetime.now(timezone.utc)
    value={'mode':'window','opens_at':(before-timedelta(hours=1)).isoformat(),
        'closes_at':(before+timedelta(hours=1)).isoformat()}
    result=evaluate_policy(json.dumps(value))
    after=datetime.now(timezone.utc)
    assert result['required'] is False
    checked=datetime.fromisoformat(result['window']['checked_at'])
    assert checked.utcoffset()==timedelta(0) and before<=checked<=after


def test_window_file_is_reread_after_recreation_and_explicit_modes_override(tmp_path,verifier,monkeypatch):
    mode=tmp_path/'access-mode';text=json.dumps(WINDOW);mode.write_text(text)
    monkeypatch.setattr('app.public_access.evaluate_policy',lambda value:evaluate_policy(value,datetime.fromisoformat(START)))
    access=configured_access(tmp_path,verifier,BLUEPRINT_DEMO_ACCESS_MODE_FILE=str(mode))
    assert access.is_editor(request())
    again=configured_access(tmp_path,verifier,BLUEPRINT_DEMO_ACCESS_MODE_FILE=str(mode))
    assert again.status(request())==access.status(request())
    mode.write_text('code\n')
    assert access.status(request())['access_code_required'] and 'access_window' not in access.status(request())
    mode.write_text('open\n')
    assert access.is_editor(request()) and 'access_window' not in access.status(request())
    mode.write_text(text);assert access.is_editor(request())
    mode.unlink();assert not access.is_editor(request())


def test_access_status_uses_one_policy_snapshot_at_a_boundary(tmp_path,verifier,monkeypatch):
    mode=tmp_path/'access-mode';mode.write_text(json.dumps(WINDOW))
    access=configured_access(tmp_path,verifier,BLUEPRINT_DEMO_ACCESS_MODE_FILE=str(mode))
    calls=[]
    def at_boundary(value):
        calls.append(True)
        return evaluate_policy(value,datetime.fromisoformat(START if len(calls)==1 else END))
    monkeypatch.setattr('app.public_access.evaluate_policy',at_boundary)
    result=access.status(request())
    assert len(calls)==1 and result['can_work'] and not result['access_code_required']
    assert result['shared_workspace'] and result['access_window']['checked_at']==START
    result=access.status(request())
    assert len(calls)==2 and not result['can_work'] and result['access_code_required']
    assert not result['shared_workspace'] and result['access_window']['checked_at']==END


def test_same_app_opens_and_relocks_by_clock_without_modefile_rewrite(prepared,tmp_path,monkeypatch):
    root,document,private=prepared;mode=tmp_path/'access-mode';text=json.dumps(WINDOW);mode.write_text(text)
    monkeypatch.setenv('BLUEPRINT_DEMO_ACCESS_MODE_FILE',str(mode))
    clock={'now':datetime.fromisoformat(START)-timedelta(microseconds=1)}
    monkeypatch.setattr('app.public_access.evaluate_policy',lambda value:evaluate_policy(value,clock['now']))
    calls=[]
    def forbidden():calls.append(True);raise AssertionError('Window access checks must not infer')
    with TestClient(create_app(storage_root=root,provider_factory=forbidden),base_url='https://demo.test') as client:
        assert client.get('/api/access').json()['access_window']['next_change_at']==START
        assert client.get('/api/buildings/'+private.id).status_code==404
        assert client.post('/api/projects',json={'name':'Before fixture'}).status_code==401
        clock['now']=datetime.fromisoformat(START)
        status=client.get('/api/access').json();assert status['can_work'] and status['access_window']['next_change_at']==END
        assert client.get('/api/buildings/'+private.id).status_code==200
        assert client.post('/api/projects',json={'name':'During fixture'}).status_code==201
        assert client.post('/api/access/unlock',json={'code':''}).json()['access_window']==status['access_window']
        assert client.post('/api/access/lock').json()['access_window']==status['access_window']
        assert not client.cookies
        assert client.post(f'/api/buildings/{document.id}/render',json={'base_revision_id':document.revision_id}).status_code==409
        assert client.post('/api/projects',json={'name':'Cross-site fixture'},headers={'Origin':'https://other.example'}).status_code==403
        clock['now']=datetime.fromisoformat(END)
        status=client.get('/api/access').json();assert not status['can_work'] and status['access_window']['next_change_at'] is None
        assert client.get('/api/buildings/'+private.id).status_code==404
        assert client.post('/api/projects',json={'name':'After fixture'}).status_code==401
        assert mode.read_text()==text and not calls
