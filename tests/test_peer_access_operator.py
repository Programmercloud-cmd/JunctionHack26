"""The operator switch changes one file; failed verification restores its state."""
import importlib.util
from pathlib import Path
import stat
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('peer_access_operator', ROOT / 'deploy/verda-agentic/access_mode.py')
operator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(operator)


def status(mode):
    required = mode == 'code'
    return {'public_demo': True, 'access_code_required': required,
            'can_work': not required, 'shared_workspace': not required}


def test_live_toggle_preserves_other_config_and_needs_no_restart(tmp_path):
    path = tmp_path / 'access-mode'
    path.write_text('code\n')
    env = tmp_path / 'application.env'
    env.write_bytes(b'PRIVATE_FIXTURE=unchanged\n')
    assert operator.change_mode('open', path=path, read_status=lambda: status(path.read_text().strip()))
    assert path.read_text() == 'open\n'
    assert stat.S_IMODE(path.stat().st_mode) == 0o644
    assert operator.change_mode('code', path=path, read_status=lambda: status(path.read_text().strip()))
    assert path.read_text() == 'code\n' and env.read_bytes() == b'PRIVATE_FIXTURE=unchanged\n'


def test_status_is_read_only_and_already_requested_mode_is_not_rewritten(tmp_path):
    path = tmp_path / 'access-mode'
    path.write_text('code\n');before = path.stat()
    assert operator.inspect_mode(path=path, read_status=lambda: status('code')) == 'code'
    assert set(tmp_path.iterdir()) == {path}
    assert not operator.change_mode('code', path=path, read_status=lambda: status('code'))
    assert path.stat().st_mtime_ns == before.st_mtime_ns


@pytest.mark.parametrize('previous', [None, b'code\n', b'invalid fixture mode\n'])
def test_failed_runtime_verification_restores_exact_previous_state(tmp_path, previous):
    path = tmp_path / 'access-mode'
    if previous is not None:
        path.write_bytes(previous);path.chmod(0o640)
    with pytest.raises(operator.AccessModeError, match='previous access-mode file was restored'):
        operator.change_mode('open', path=path, read_status=lambda: status('code'))
    assert path.read_bytes() == previous if previous is not None else not path.exists()
    if previous is not None:assert stat.S_IMODE(path.stat().st_mode) == 0o640


def test_failure_after_atomic_replace_also_rolls_back(tmp_path, monkeypatch):
    path = tmp_path / 'access-mode';path.write_text('code\n')
    replace = operator._replace
    def fail_once(path, content, permissions=0o644):
        replace(path, content, permissions)
        if content == b'open\n':raise OSError('private fixture write failure')
    monkeypatch.setattr(operator, '_replace', fail_once)
    with pytest.raises(operator.AccessModeError, match='restored'):
        operator.change_mode('open', path=path, read_status=lambda: status('open'))
    assert path.read_text() == 'code\n'


def test_symlink_is_never_followed_or_changed(tmp_path):
    target = tmp_path / 'other';target.write_text('retained')
    path = tmp_path / 'access-mode';path.symlink_to(target)
    with pytest.raises(operator.AccessModeError, match='ordinary file'):
        operator.change_mode('open', path=path, read_status=lambda: status('open'))
    assert path.is_symlink() and target.read_text() == 'retained'


def test_unknown_or_legacy_runtime_status_cannot_confirm_an_open_gate(tmp_path):
    path = tmp_path / 'access-mode';path.write_text('code\n')
    with pytest.raises(operator.AccessModeError):
        operator.change_mode('open', path=path, read_status=lambda: {'public_demo': True, 'can_work': True})
    assert path.read_text() == 'code\n'


@pytest.mark.parametrize('args', [['invalid'], ['open', 'extra'], ['open; false']])
def test_local_wrapper_rejects_bad_arguments_before_ssh(args):
    result = subprocess.run(['bash', str(ROOT / 'scripts/peer-review-access.sh'), *args], capture_output=True, text=True)
    assert result.returncode == 2 and 'Usage:' in result.stderr


def test_rollback_failure_is_reported_without_claiming_restoration(tmp_path, monkeypatch):
    path = tmp_path / 'access-mode';path.write_text('code\n')
    replace = operator._replace
    def fail_restore(path, content, permissions=0o644):
        if content == b'code\n':raise OSError('private fixture rollback failure')
        replace(path, content, permissions)
    monkeypatch.setattr(operator, '_replace', fail_restore)
    with pytest.raises(operator.AccessModeError, match='previous mode could not be restored'):
        operator.change_mode('open', path=path, read_status=lambda: status('code'))


def test_directory_sync_failure_after_replace_rolls_back(tmp_path, monkeypatch):
    path = tmp_path / 'access-mode';path.write_text('code\n')
    sync = operator._sync_directory
    calls = []
    def fail_once(parent):
        calls.append(True)
        if len(calls) == 1:raise OSError('private fixture directory sync failure')
        sync(parent)
    monkeypatch.setattr(operator, '_sync_directory', fail_once)
    with pytest.raises(operator.AccessModeError, match='file was restored'):
        operator.change_mode('open', path=path, read_status=lambda: status('open'))
    assert path.read_text() == 'code\n'


def test_scheduled_policy_uses_helsinki_offsets_for_the_requested_clock_times():
    import json
    november = json.loads(operator.scheduled_policy('2026-11-15'))
    summer = json.loads(operator.scheduled_policy('2026-07-15'))
    assert november == {'mode': 'window', 'opens_at': '2026-11-15T09:30:00+02:00', 'closes_at': '2026-11-15T14:00:00+02:00'}
    assert summer['opens_at'] == '2026-07-15T09:30:00+03:00'
    assert summer['closes_at'] == '2026-07-15T14:00:00+03:00'


def window_status(policy, now):
    from datetime import datetime
    result = operator.evaluate_policy(policy, now=datetime.fromisoformat(now))
    return {**status('code' if result['required'] else 'open'), 'access_window': result['window']}


@pytest.mark.parametrize('now', ['2026-11-15T07:29:59+00:00', '2026-11-15T07:30:00+00:00', '2026-11-15T12:00:00+00:00'])
def test_scheduled_policy_is_verified_before_inside_and_after_window(tmp_path, now):
    path = tmp_path / 'access-mode';path.write_text('code\n')
    policy = operator.scheduled_policy('2026-11-15')
    assert operator.change_policy(policy, path=path, read_status=lambda: window_status(policy, now))
    assert operator.inspect_mode(path=path, read_status=lambda: window_status(policy, now)) == policy


def test_wrong_window_identity_restores_previous_gate(tmp_path):
    path = tmp_path / 'access-mode';path.write_text('code\n')
    policy = operator.scheduled_policy('2026-11-15')
    wrong = operator.scheduled_policy('2026-11-16')
    with pytest.raises(operator.AccessModeError, match='restored'):
        operator.change_policy(policy, path=path, read_status=lambda: window_status(wrong, '2026-11-15T06:00:00+00:00'))
    assert path.read_text() == 'code\n'


@pytest.mark.parametrize('day,start,end', [('bad', '09:30', '14:00'), ('2026-11-15', '14:00', '09:30'), ('2026-11-15', '09:30+02:00', '14:00'), ('2026-11-15', '99:00', '14:00')])
def test_invalid_scheduled_clock_inputs_are_rejected(day, start, end):
    with pytest.raises(operator.AccessModeError):operator.scheduled_policy(day, start, end)


@pytest.mark.parametrize('args', [['schedule'], ['schedule', '2026-11-15; false'], ['schedule', '2026-11-15', '09:30;false', '14:00']])
def test_wrapper_rejects_bad_schedule_arguments_before_ssh(args):
    result = subprocess.run(['bash', str(ROOT / 'scripts/peer-review-access.sh'), *args], capture_output=True, text=True)
    assert result.returncode == 2 and 'Usage:' in result.stderr
