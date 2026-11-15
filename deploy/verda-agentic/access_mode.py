"""Operator-only access-code switch for the separate agentic demo; no restart."""
import argparse
from datetime import date, datetime, time
import fcntl
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
from urllib.request import urlopen
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.access_policy import evaluate_policy

MODE_FILE = Path('/etc/blueprint-agentic/access-mode')
STATUS_URL = 'http://127.0.0.1:8001/api/access'


class AccessModeError(Exception):
    pass


def runtime_status():
    try:
        with urlopen(STATUS_URL, timeout=5) as response:
            return json.load(response)
    except Exception:
        raise AccessModeError('The agentic application access status could not be checked.') from None


def verify_status(status, policy):
    expected = evaluate_policy(policy)
    window = expected['window']
    actual = status.get('access_window')
    if window is not None:
        if not (isinstance(actual, dict) and actual.get('opens_at') == window['opens_at']
                and actual.get('closes_at') == window['closes_at']):
            raise AccessModeError('The running application does not match the requested access window.')
        try:
            checked = datetime.fromisoformat(actual['checked_at'])
            if checked.utcoffset() is None:raise ValueError()
        except (KeyError, TypeError, ValueError):
            raise AccessModeError('The application access-window check time is invalid.') from None
        expected = evaluate_policy(policy, now=checked)
        if actual.get('next_change_at') != expected['window']['next_change_at']:
            raise AccessModeError('The application next access change does not match its window.')
    elif actual is not None:
        raise AccessModeError('The application still reports a different scheduled access window.')
    required = expected['required']
    if not (status.get('public_demo') is True
            and status.get('access_code_required') is required
            and status.get('can_work') is (not required)
            and status.get('shared_workspace') is (not required)):
        raise AccessModeError('The running application does not match the requested access mode.')


def scheduled_policy(day, start='09:30', end='14:00'):
    try:
        local_day = date.fromisoformat(day)
        start_time, end_time = time.fromisoformat(start), time.fromisoformat(end)
        if start_time.tzinfo is not None or end_time.tzinfo is not None:raise ValueError()
        zone = ZoneInfo('Europe/Helsinki')
        opens = datetime.combine(local_day, start_time, zone)
        closes = datetime.combine(local_day, end_time, zone)
        if opens >= closes:raise ValueError()
    except (TypeError, ValueError):
        raise AccessModeError('Provide an ISO date and increasing Helsinki start/end times on that date.') from None
    return json.dumps({'mode': 'window', 'opens_at': opens.isoformat(), 'closes_at': closes.isoformat()}, sort_keys=True)


def _regular(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode):
        raise AccessModeError('The access-mode path must be an ordinary file, not a link.')
    return info


def _sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _replace(path, content, permissions=0o644):
    descriptor, name = tempfile.mkstemp(prefix='.access-mode-', dir=path.parent)
    temporary = Path(name)
    try:
        os.fchmod(descriptor, permissions)
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        _sync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def change_policy(policy, *, path=MODE_FILE, read_status=runtime_status):
    """Serialize operator changes and restore exact prior bytes on failed checks."""
    if policy not in {'code', 'open'} and evaluate_policy(policy)['window'] is None:
        raise AccessModeError('Choose code, open, or a valid scheduled access window.')
    lock_path = path.with_name('.access-mode.lock')
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'rb') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        info = _regular(path)
        previous = path.read_bytes() if info else None
        if previous is not None and previous.strip() == policy.encode():
            verify_status(read_status(), policy)
            return False
        try:
            _replace(path, (policy + '\n').encode())
            verify_status(read_status(), policy)
        except Exception:
            try:
                if previous is None:
                    path.unlink(missing_ok=True)
                    _sync_directory(path.parent)
                else:
                    _replace(path, previous, stat.S_IMODE(info.st_mode))
            except Exception:
                raise AccessModeError('Access change failed and the previous mode could not be restored. Check access status on the server.') from None
            raise AccessModeError('Access change was not verified; the previous access-mode file was restored.') from None
        return True


def change_mode(mode, *, path=MODE_FILE, read_status=runtime_status):
    if mode not in {'code', 'open'}:
        raise AccessModeError('Choose code or open access.')
    return change_policy(mode, path=path, read_status=read_status)


def inspect_mode(*, path=MODE_FILE, read_status=runtime_status):
    info = _regular(path)
    policy = 'code'
    if info:
        try:
            value = path.read_text().strip()
        except (OSError, UnicodeError):
            value = ''
        if value == 'open' or evaluate_policy(value)['window'] is not None:
            policy = value
    verify_status(read_status(), policy)
    return policy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['status', 'open', 'require-code', 'schedule'], nargs='?', default='status')
    parser.add_argument('--date', help='Local Helsinki date, YYYY-MM-DD, required for schedule.')
    parser.add_argument('--start', default='09:30', help='Helsinki local opening time (default 09:30).')
    parser.add_argument('--end', default='14:00', help='Helsinki local closing time (default 14:00).')
    args = parser.parse_args()
    try:
        if os.geteuid() != 0:
            raise AccessModeError('Run this operator command as root on the agentic server.')
        parent = MODE_FILE.parent
        if parent.is_symlink() or parent.stat().st_uid != 0 or parent.stat().st_mode & 0o022:
            raise AccessModeError('The agentic configuration directory must be root-owned and not writable by others.')
        info = _regular(MODE_FILE)
        if info and (info.st_uid != 0 or info.st_mode & 0o022):
            raise AccessModeError('The access-mode file must be root-owned and not writable by others.')
        if args.action == 'status':
            policy = inspect_mode()
        else:
            policy = (scheduled_policy(args.date, args.start, args.end) if args.action == 'schedule'
                      else 'open' if args.action == 'open' else 'code')
            change_policy(policy)
        expected = evaluate_policy(policy)
        print('Access code: REQUIRED' if expected['required'] else 'Peer review: OPEN shared workspace')
        if expected['window'] is not None:
            zone = ZoneInfo('Europe/Helsinki')
            opens = datetime.fromisoformat(expected['window']['opens_at']).astimezone(zone)
            closes = datetime.fromisoformat(expected['window']['closes_at']).astimezone(zone)
            print(f'Scheduled: {opens:%Y-%m-%d %H:%M} to {closes:%H:%M} Europe/Helsinki')
        print('Runtime verified. No restart or job interruption.')
    except (AccessModeError, OSError) as error:
        parser.exit(1, (str(error) if isinstance(error, AccessModeError) else 'The access-mode file could not be updated.') + '\n')


if __name__ == '__main__':
    main()
