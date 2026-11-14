"""Create private deployment env/code files; never emit secrets or request input in chat."""
import argparse
import os
from pathlib import Path
import secrets
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import dotenv_values
from app.public_access import hash_access_code

# These are configuration, not a full copy of development environment credentials.
ALLOWED = {
    'GEMINI_API_KEY', 'GEMINI_MODEL', 'GEMINI_RECONSTRUCTION_MODEL', 'GEMINI_DECISION_MODEL',
    'RECONSTRUCTION_CALL_SECONDS', 'RECONSTRUCTION_MAX_TOKENS',
    'RECONSTRUCTION_REVIEW_SECONDS', 'RECONSTRUCTION_REVIEW_TOKENS',
    'RECONSTRUCTION_JOB_SECONDS', 'RECONSTRUCTION_PATCH_ATTEMPTS',
}


def private_write(path, value):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        stream.write(value)


def prepare(source, destination):
    source_values = dotenv_values(source)
    values = {key: value for key, value in source_values.items() if key in ALLOWED and value is not None}
    if not values.get('GEMINI_API_KEY'):
        raise ValueError('The selected local env file has no Gemini credential; no files created.')
    if any('\n' in value or '\r' in value or '\0' in value for value in values.values()):
        raise ValueError('A selected setting contains unsupported line breaks; no files created.')
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    code = secrets.token_urlsafe(24)
    values.update(AI_PROVIDER='gemini', BLUEPRINT_PUBLIC_DEMO='1',
                  BLUEPRINT_STORAGE_ROOT='/srv/blueprint-data/runtime',
                  BLUEPRINT_PUBLIC_EXAMPLES_FILE='/srv/blueprint-data/public-examples.json',
                  BLUEPRINT_DEMO_ACCESS_CODE_HASH=hash_access_code(code),
                  BLUEPRINT_DEMO_SESSION_SECRET=secrets.token_urlsafe(48))
    def quote(value):
        return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'
    private_write(destination / 'application.env', ''.join(key+'='+quote(value)+'\n' for key, value in sorted(values.items())))
    private_write(destination / 'demo-access-code.txt', code+'\n')
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-env', type=Path, default=ROOT/'.env.local')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        result = prepare(args.source_env, args.output)
    except (ValueError, FileExistsError) as error:
        parser.exit(1, str(error)+'\n')
    print('Private deployment files created at '+str(result.resolve())+'. Read the access code locally; do not paste it into chat.')
