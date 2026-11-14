"""Install a hash-verified seed into stopped-app storage without overwriting existing data."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def install(seed,data):
    hashes=json.loads((seed/'seed-hashes.json').read_text())
    files=[]
    for name,expected in hashes.items():
        relative=Path(name)
        if relative.is_absolute() or '..'in relative.parts:raise ValueError('Invalid seed path.')
        source=seed/relative
        if source.is_symlink() or not source.is_file() or digest(source)!=expected:raise ValueError('Seed integrity failure.')
        # Deployment ledgers stay outside the public runtime.
        target=data/relative
        if target.exists() and (not target.is_file() or digest(target)!=expected):
            # Existing operational jobs/conversations aren't in this allowlist and remain untouched.
            raise ValueError('Destination conflict; existing state was not overwritten: '+name)
        files.append((source,target))
    for source,target in files:
        if target.exists():continue
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source,target)
    for building in (data/'runtime'/'buildings').iterdir():
        if building.is_dir():(building/'jobs').mkdir(exist_ok=True)
    return len(files)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed',type=Path,required=True)
    parser.add_argument('--data',type=Path,required=True)
    args=parser.parse_args()
    print('Verified seed files: '+str(install(args.seed,args.data))+'. Existing files were not overwritten.')
