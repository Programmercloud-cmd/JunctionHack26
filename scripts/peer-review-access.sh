#!/usr/bin/env bash
set -euo pipefail
usage() { echo 'Usage: bash scripts/peer-review-access.sh [status|open|require-code|schedule YYYY-MM-DD [HH:MM HH:MM]]' >&2; exit 2; }
mode="${1:-status}"
case "$mode" in
  status|open|require-code)
    [[ "$#" -le 1 ]] || usage
    remote_args="$mode"
    ;;
  schedule)
    [[ "$#" -eq 2 || "$#" -eq 4 ]] || usage
    [[ "$2" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || usage
    start="${3:-09:30}"; end="${4:-14:00}"
    [[ "$start" =~ ^[0-9]{2}:[0-9]{2}$ && "$end" =~ ^[0-9]{2}:[0-9]{2}$ ]] || usage
    remote_args="schedule --date $2 --start $start --end $end"
    ;;
  *) usage ;;
esac
ssh -i "${BLUEPRINT_DEMO_SSH_KEY:-$HOME/.ssh/junction-verda-demo-20261114}" \
  -o "UserKnownHostsFile=${BLUEPRINT_DEMO_KNOWN_HOSTS:-/tmp/junction-verda/known_hosts}" \
  -o BatchMode=yes -o StrictHostKeyChecking=yes root@95.133.254.90 \
  "/opt/blueprint-agentic/current/.venv/bin/python -B /opt/blueprint-agentic/current/deploy/verda-agentic/access_mode.py $remote_args"
