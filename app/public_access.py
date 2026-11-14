"""Pinned public examples and shared-code access; no inference or storage writes."""
from dataclasses import dataclass, field
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets

from fastapi import HTTPException
from fastapi.responses import JSONResponse

COOKIE_NAME='__Host-blueprint_demo'
ID=r'[0-9a-f]{64}'
REV=r'[0-9a-f]{32}'


def hash_access_code(code):
    """Administrative helper. Obtain and store the code privately, never in logs."""
    if not isinstance(code,str) or not code:raise ValueError('An access code is required.')
    salt=secrets.token_bytes(16)
    digest=hashlib.scrypt(code.encode(),salt=salt,n=16384,r=8,p=1,dklen=32)
    return f'scrypt:{salt.hex()}:{digest.hex()}'


def _verifier(value):
    try:
        tag,salt,digest=value.split(':')
        if tag!='scrypt' or len(salt)!=32 or len(digest)!=64:raise ValueError()
        return bytes.fromhex(salt),bytes.fromhex(digest)
    except (AttributeError,ValueError):raise RuntimeError('Public demo access-code verifier is missing or invalid.') from None


@dataclass
class PublicAccess:
    enabled: bool=False
    examples: dict=field(default_factory=dict)
    titles: dict=field(default_factory=dict)
    verifier: str=field(default='',repr=False)
    session_secret: str=field(default='',repr=False)
    protected_source_ids: set=field(default_factory=set)

    @classmethod
    def from_environment(cls,environ=None):
        env=os.environ if environ is None else environ
        flag=env.get('BLUEPRINT_PUBLIC_DEMO','0')
        if flag not in ('0','1'):raise RuntimeError('BLUEPRINT_PUBLIC_DEMO must explicitly be 0 or 1.')
        if flag=='0':return cls()
        verifier=env.get('BLUEPRINT_DEMO_ACCESS_CODE_HASH','');_verifier(verifier)
        secret=env.get('BLUEPRINT_DEMO_SESSION_SECRET','')
        if not secret:raise RuntimeError('Public demo session secret is required.')
        try:
            data=json.loads(Path(env['BLUEPRINT_PUBLIC_EXAMPLES_FILE']).read_text())
            items=data['examples'] if isinstance(data,dict) else data
            if not isinstance(items,list) or not items:raise ValueError()
            examples={};titles={}
            for item in items:
                identity,revision=item['building_id'],item['revision_id']
                if (not re.fullmatch(ID,identity) or not re.fullmatch(REV,revision) or identity in examples
                        or not isinstance(item.get('title',''),str)):raise ValueError()
                examples[identity]=revision;titles[identity]=item.get('title','')
        except (KeyError,TypeError,ValueError,OSError):
            raise RuntimeError('Public example manifest is missing or invalid.') from None
        return cls(True,examples,titles,verifier,secret)

    def validate_store(self,store):
        if not self.enabled:return
        sources=set(self.examples)
        try:
            for identity,revision in self.examples.items():
                document=store.revision(identity,revision)
                if document.id!=identity or document.revision_id!=revision:raise ValueError()
                sources.update(source['source_id'] for source in document.sources)
        except Exception:
            raise RuntimeError('A configured public example revision is unavailable or invalid.') from None
        self.protected_source_ids=sources

    def _signature(self,nonce):
        return hmac.new(self.session_secret.encode(),f'editor:{self.verifier}:{nonce}'.encode(),hashlib.sha256).hexdigest()

    def is_editor(self,request):
        if not self.enabled:return True
        parts=request.cookies.get(COOKIE_NAME,'').split('.')
        return (len(parts)==2 and re.fullmatch(r'[0-9a-f]{64}',parts[0]) is not None
            and re.fullmatch(r'[0-9a-f]{64}',parts[1]) is not None
            and hmac.compare_digest(parts[1],self._signature(parts[0])))

    def require_editor(self,request):
        if not self.is_editor(request):raise HTTPException(401,'Enter the access code to use paid or private features.')

    def status(self,request):
        return {'public_demo':self.enabled,'can_work':self.is_editor(request),
            'shared_workspace':self.enabled and self.is_editor(request)}

    def _same_origin(self,request):
        if not self.enabled:return
        origin=request.headers.get('origin')
        expected=f'{request.url.scheme}://{request.url.netloc}'
        if ((origin is not None and origin!=expected)
                or request.headers.get('sec-fetch-site') in {'cross-site','same-site'}):
            raise HTTPException(403,'Use this application directly for state-changing requests.')

    def unlock(self,request,code):
        self._same_origin(request)
        if not self.enabled:return JSONResponse(self.status(request),headers={'Cache-Control':'no-store'})
        salt,expected=_verifier(self.verifier)
        supplied=hashlib.scrypt((code if isinstance(code,str) else '').encode(),salt=salt,n=16384,r=8,p=1,dklen=32)
        if not hmac.compare_digest(supplied,expected):raise HTTPException(401,'Access code not accepted.')
        nonce=secrets.token_hex(32)
        response=JSONResponse({'public_demo':True,'can_work':True,'shared_workspace':True},headers={'Cache-Control':'no-store'})
        response.set_cookie(COOKIE_NAME,f'{nonce}.{self._signature(nonce)}',secure=True,httponly=True,samesite='strict',path='/')
        return response

    def lock(self,request):
        self._same_origin(request)
        response=JSONResponse({'public_demo':self.enabled,'can_work':not self.enabled,'shared_workspace':False},headers={'Cache-Control':'no-store'})
        response.delete_cookie(COOKIE_NAME,path='/',secure=True,httponly=True,samesite='strict')
        return response

    def document(self,store,request,building_id,revision_id=None):
        if self.enabled and building_id in self.examples:
            pinned=self.examples[building_id]
            if revision_id is not None and revision_id!=pinned:raise HTTPException(404,'Building revision not available.')
            return store.revision(building_id,pinned)
        if not self.is_editor(request):raise HTTPException(404,'Building not available.')
        return store.revision(building_id,revision_id) if revision_id else store.get(building_id)

    def question_document(self,store,request,building_id,revision_id=None):
        self.require_editor(request)
        if self.enabled and building_id in self.examples:
            return self.document(store,request,building_id,revision_id)
        document=store.get(building_id)
        if revision_id and revision_id!=document.revision_id:
            raise HTTPException(409,'The building revision changed; refresh before asking.')
        return document

    def require_editable(self,request,building_id):
        self.require_editor(request)
        if self.enabled and building_id in self.examples:
            raise HTTPException(409,'This shared example model is read-only. Upload another blueprint to edit.')

    def require_uploadable(self,request,payloads):
        """Preflight the entire multipart batch before alias/resource/store writes."""
        self.require_editor(request)
        if self.enabled:
            for payload in payloads:
                data=payload[0] if isinstance(payload,tuple) else payload
                if hashlib.sha256(data).hexdigest() in self.protected_source_ids:
                    raise HTTPException(409,'This upload contains a shared example source. Select its read-only example to ask questions; upload another blueprint to edit.')

    def descriptor(self,document):
        public_example=self.enabled and document.id in self.examples
        result={**document.public(),'public_example':public_example,'read_only_model':public_example,
            'pinned_revision_id':self.examples.get(document.id) if public_example else None}
        if public_example and self.titles.get(document.id):result['example_title']=self.titles[document.id]
        return result

    def public_buildings(self,store):
        return [self.descriptor(store.revision(identity,revision)) for identity,revision in self.examples.items()]

    def authorize_http(self,request):
        """Default-deny anonymous routes; no request body or provider is touched."""
        if not self.enabled:return
        path=request.url.path;method=request.method
        if method not in {'GET','HEAD','OPTIONS'}:self._same_origin(request)
        if path in {'/api/access/unlock','/api/access/lock'} and method=='POST':return
        if self.is_editor(request):return
        if method not in {'GET','HEAD'}:self.require_editor(request)
        if path in {'/','/chat','/api/health','/api/access'} or path.startswith('/static/'):return
        if path=='/api/buildings':return
        patterns=(
            rf'/api/buildings/({ID})(?:/assumptions)?',
            rf'/api/documents/({ID})/(?:scene|model\.ifc|pages/[1-9][0-9]*)',
            rf'/api/buildings/({ID})/revisions/({REV})/(?:pages/[1-9][0-9]*|evidence/[^/]+)',
        )
        for pattern in patterns:
            match=re.fullmatch(pattern,path)
            if match and match[1] in self.examples and (len(match.groups())==1 or match[2]==self.examples[match[1]]):return
        raise HTTPException(404,'Resource not available.')
