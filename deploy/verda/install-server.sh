#!/usr/bin/env bash
# Run on the new VM after mounting the approved persistent volume and transferring files.
set -euo pipefail
if [[ "$EUID" != 0 || "$#" != 2 ]]; then
  echo 'Usage as root: install-server.sh /opt/blueprint/releases/COMMIT PUBLIC_HOSTNAME' >&2
  exit 2
fi
release_dir="$1"
demo_host="$2"
if [[ ! "$release_dir" =~ ^/opt/blueprint/releases/[0-9a-f]{40}$ || ! "$demo_host" =~ ^[a-zA-Z0-9.-]+$ ]]; then
  echo 'Invalid release path or hostname' >&2
  exit 2
fi
mountpoint -q /srv/blueprint-data
[[ -f "$release_dir/app/main.py" && -f /etc/blueprint/application.env && -f /srv/blueprint-data/public-examples.json ]]
# Configured public mode and Gemini are mandatory. Do not dump the environment.
python3 - <<'PY'
from pathlib import Path
values={line.split('=',1)[0]:line.split('=',1)[1].strip().strip('"') for line in Path('/etc/blueprint/application.env').read_text().splitlines() if '=' in line and not line.startswith('#')}
assert values.get('BLUEPRINT_PUBLIC_DEMO')=='1' and values.get('AI_PROVIDER')=='gemini', 'Public-demo mode and Gemini are required'
assert values.get('GEMINI_API_KEY') and values.get('BLUEPRINT_DEMO_ACCESS_CODE_HASH') and values.get('BLUEPRINT_DEMO_SESSION_SECRET'), 'Server credentials/access controls are incomplete'
PY
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y python3-venv python3-pip libgomp1 libcairo2 curl gpg debian-keyring debian-archive-keyring apt-transport-https
if ! command -v caddy >/dev/null 2>&1; then
  curl --fail --silent --show-error --location https://dl.cloudsmith.io/public/caddy/stable/gpg.key -o /tmp/caddy-key.asc
  gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg /tmp/caddy-key.asc
  curl --fail --silent --show-error --location https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt -o /etc/apt/sources.list.d/caddy-stable.list
  chmod 644 /usr/share/keyrings/caddy-stable-archive-keyring.gpg /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y caddy
fi
id blueprint >/dev/null 2>&1 || useradd --system --home-dir /nonexistent --shell /usr/sbin/nologin blueprint
python3 -m venv "$release_dir/.venv"
"$release_dir/.venv/bin/python" -m pip install --disable-pip-version-check -r "$release_dir/requirements.txt"
chown -R root:root "$release_dir"
chown -R blueprint:blueprint /srv/blueprint-data/runtime
chmod 600 /etc/blueprint/application.env
chmod 644 /srv/blueprint-data/public-examples.json
install -m 644 "$release_dir/deploy/verda/blueprint-qa.service" /etc/systemd/system/blueprint-qa.service
sed "s/DEMO_HOST/$demo_host/g" "$release_dir/deploy/verda/Caddyfile" > /etc/caddy/Caddyfile
caddy validate --config /etc/caddy/Caddyfile
# Existing process must be stopped before switching versions. Data is never replaced here.
systemctl stop blueprint-qa.service 2>/dev/null || true
if [[ -L /opt/blueprint/current ]]; then
  readlink /opt/blueprint/current > /opt/blueprint/previous-release.txt
fi
ln -s "$release_dir" /opt/blueprint/current.next
mv -Tf /opt/blueprint/current.next /opt/blueprint/current
systemctl daemon-reload
systemctl enable --now blueprint-qa.service
systemctl enable caddy.service
systemctl reload-or-restart caddy.service
# Print no environment, credentials or application response bodies.
systemctl is-active --quiet blueprint-qa.service
curl --fail --silent --show-error --retry 30 --retry-connrefused --retry-delay 1 --retry-max-time 60 --output /dev/null http://127.0.0.1:8000/api/health
echo 'Service installed. Verify public HTTPS, access controls and persistent state before sharing the URL.'
