"""Evaluate administrator-owned access modes without timers, state or dependencies."""
from datetime import datetime, timezone
import json


def _aware_utc(value):
    if not isinstance(value,datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('Access window timestamps must include a timezone.')
    return value.astimezone(timezone.utc)


def evaluate_policy(text,now=None):
    """Return a closed policy for malformed input; window endpoints are UTC ISO strings."""
    closed={'required':True,'window':None}
    if not isinstance(text,str):return closed
    text=text.strip()
    if text=='open':return {'required':False,'window':None}
    if text=='code':return closed
    try:
        policy=json.loads(text)
        if not isinstance(policy,dict) or policy.get('mode')!='window':return closed
        start,end=policy.get('opens_at'),policy.get('closes_at')
        if not isinstance(start,str) or not isinstance(end,str):return closed
        start=_aware_utc(datetime.fromisoformat(start))
        end=_aware_utc(datetime.fromisoformat(end))
        if start>=end:return closed
        checked=_aware_utc(datetime.now(timezone.utc) if now is None else now)
        next_change=start if checked<start else end if checked<end else None
        return {'required':not start<=checked<end,'window':{
            'opens_at':start.isoformat(),'closes_at':end.isoformat(),'checked_at':checked.isoformat(),
            'next_change_at':next_change.isoformat() if next_change is not None else None}}
    except (ValueError,TypeError,OverflowError,RecursionError):
        return closed
