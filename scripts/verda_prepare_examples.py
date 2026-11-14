"""Copy selected immutable bundles without inference, jobs, conversations or diagnostics."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.bundles import BuildingStore
from app.ifc_artifact import load_artifact


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def read(path):return json.loads(path.read_text())
def valid_id(value,size):return isinstance(value,str) and re.fullmatch('[0-9a-f]{'+str(size)+'}',value)


def copy_file(source,destination):
    if source.is_symlink() or not source.is_file():raise ValueError('Expected an ordinary immutable file: '+str(source))
    if destination.exists():
        if digest(source)!=digest(destination):raise ValueError('Conflicting immutable file: '+str(destination))
        return
    destination.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(source,destination)


def prepare(selection,output):
    items=read(selection)
    if isinstance(items,dict):items=items['examples']
    if not isinstance(items,list) or not items:raise ValueError('Choose explicit example revisions.')
    if output.exists():raise ValueError('Output already exists; do not overwrite prepared or visitor state.')
    identities=set();entries=[];reports=[]
    # This is a NEW private staging root. Never instantiate a store on source roots.
    runtime=output/'runtime';(runtime/'buildings').mkdir(parents=True);(runtime/'resources').mkdir()
    for item in items:
        root=Path(item['root']).resolve();bid=item['building_id'];rid=item['revision_id']
        if not valid_id(bid,64) or not valid_id(rid,32) or bid in identities:raise ValueError('Duplicate/invalid explicit example identity.')
        identities.add(bid);source=root/'buildings'/bid;destination=runtime/'buildings'/bid
        metadata=read(source/'building.json')
        if metadata['building_id']!=bid or digest(source/'source.original')!=metadata['content_sha256']:
            raise ValueError('Original bundle identity/hash mismatch.')
        for name in ('building.json','source.original'):copy_file(source/name,destination/name)
        for page in metadata['pages']:
            p=source/'pages'/f"{page['number']}.png"
            if digest(p)!=page['sha256']:raise ValueError('Original page integrity mismatch.')
            copy_file(p,destination/'pages'/p.name)
        (destination/'jobs').mkdir()
        current_id=rid;visited=set();source_ids=set()
        while current_id:
            if not valid_id(current_id,32) or current_id in visited:raise ValueError('Invalid/cyclic revision history.')
            visited.add(current_id);folder=source/'revisions'/current_id;info=read(folder/'revision.json')
            if info['revision_id']!=current_id or info['building_id']!=bid:raise ValueError('Revision identity mismatch.')
            # Revision hashes are the only artifact allowlist, plus revision metadata.
            for name,expected in info['hashes'].items():
                if Path(name).name!=name or name.startswith('.'):raise ValueError('Invalid revision member name.')
                p=folder/name
                if digest(p)!=expected:raise ValueError('Revision integrity mismatch: '+name)
                copy_file(p,destination/'revisions'/current_id/name)
            copy_file(folder/'revision.json',destination/'revisions'/current_id/'revision.json')
            if (folder/'sources.json').exists():source_ids.update(s['source_id']for s in read(folder/'sources.json'))
            current_id=info.get('parent_revision_id')
        for sid in source_ids:
            if not valid_id(sid,64):raise ValueError('Invalid source identity.')
            resource=root/'resources'/sid;target=runtime/'resources'/sid
            if digest(resource/'source.original')!=sid:raise ValueError('Source-resource hash mismatch.')
            for name in ('source.original','source.json','interpretation.json'):
                if (resource/name).exists():copy_file(resource/name,target/name)
            for page in (resource/'pages').glob('*.png'):copy_file(page,target/'pages'/page.name)
        info=read(source/'revisions'/rid/'revision.json')
        current={key:info[key]for key in ('revision_id','revision_number','status','updated_at')}
        (destination/'CURRENT.json').write_text(json.dumps(current,indent=2)+'\n')
        title=item.get('title') or metadata['filename']
        entries.append({'building_id':bid,'revision_id':rid,'title':title})
        report={'building_id':bid,'revision_id':rid,'title':title,'saved_status':info['status'],
                'original_sha256':metadata['content_sha256'],'revisions_preserved':len(visited),
                'known_limitations':item.get('known_limitations',[])}
        review=source/'revisions'/rid/'review.json'
        if review.exists():
            reviewed=read(review);report.update(review_present=True,candidate_supported=reviewed['candidate_supported'],review_issue_count=len(reviewed['issues']))
        else:report.update(review_present=False,candidate_supported=None)
        reports.append(report)
    store=BuildingStore(runtime)
    try:
        for entry,report in zip(entries,reports):
            document=store.revision(entry['building_id'],entry['revision_id'])
            if document.scene is None or not document.ifc_bytes:raise ValueError('Selected example lacks a cached IFC/model.')
            report.update(kind=document.kind,derived=document.scene.derived,stable_object_count=len(document.scene.elements),
                unresolved_count=sum(e.geometry is None for e in document.scene.elements),ifc_sha256=hashlib.sha256(document.ifc_bytes).hexdigest(),
                source_hashes=sorted(document.source_files),user_values=len(document.user_values))
            if document.scene.derived:
                restored,_,manifest=load_artifact(document.ifc_bytes,document.id)
                if not restored.derived or [e.id for e in restored.elements]!=[e.id for e in document.scene.elements]:
                    raise ValueError('Portable IFC identity/provenance mismatch.')
                if manifest.description!=document.description or manifest.user_values!=document.user_values:
                    raise ValueError('Portable IFC interpretation/assumptions mismatch.')
                if [e.source for e in restored.elements]!=[e.source for e in document.scene.elements]:
                    raise ValueError('Portable IFC original-source mapping mismatch.')
                report['portable_reopen']='passed'
            else:report['portable_reopen']='native IFC preserved; no drawing-derived assertion'
    finally:store.close()
    (output/'public-examples.json').write_text(json.dumps({'examples':entries},indent=2)+'\n')
    (output/'example-review-ledger.json').write_text(json.dumps(reports,indent=2)+'\n')
    hashes={str(p.relative_to(output)):digest(p)for p in output.rglob('*')if p.is_file()}
    (output/'seed-hashes.json').write_text(json.dumps(hashes,indent=2)+'\n')
    return {'examples':len(entries),'output':str(output.resolve()),'provider_calls':0,'bytes':sum(p.stat().st_size for p in output.rglob('*')if p.is_file())}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--selection',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(prepare(args.selection,args.output)))
