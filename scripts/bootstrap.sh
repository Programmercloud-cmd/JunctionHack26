#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m venv --without-pip .venv
if ! .venv/bin/python -m pip --version >/dev/null 2>&1; then
  bootstrap_file=$(mktemp)
  trap 'rm -f "$bootstrap_file"' EXIT
  curl --fail --silent --show-error https://bootstrap.pypa.io/get-pip.py -o "$bootstrap_file"
  .venv/bin/python "$bootstrap_file"
fi
if [ -f requirements.txt ]; then
  .venv/bin/python -m pip install -r requirements.txt
else
  .venv/bin/python -m pip install -r requirements.in
fi
