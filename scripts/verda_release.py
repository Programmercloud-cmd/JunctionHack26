"""Archive an immutable committed app release without secrets, datasets or runtime files."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PATHS = ['app', 'requirements.txt', 'requirements.in', 'deploy/verda']


def prepare(ref, output):
    commit = subprocess.check_output(['git', 'rev-parse', '--verify', ref+'^{commit}'], cwd=ROOT, text=True).strip()
    output = output.resolve()
    if output.exists():
        raise ValueError('Output already exists; choose a new release directory.')
    output.mkdir(parents=True)
    archive = output/'application.tar'
    subprocess.run(['git', 'archive', '--format=tar', '--output', str(archive), commit, '--', *PATHS], cwd=ROOT, check=True)
    metadata = {'commit':commit, 'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),
                'archive':archive.name, 'included_paths':PATHS}
    (output/'release.json').write_text(json.dumps(metadata, indent=2)+'\n')
    return metadata


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ref', default='HEAD')
    parser.add_argument('--output', type=Path, required=True)
    args=parser.parse_args()
    print(json.dumps(prepare(args.ref,args.output)))
