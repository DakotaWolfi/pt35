#!/bin/bash
# Configure hybrid mode: HTTP guest printing + separate HTTPS administrator backend.
# Run as jenna after Caddy and its publicly trusted HTTPS endpoint are working.
set -euo pipefail
cd "$(dirname "$0")"
if [[ ${1:-} != https://* || ${1:-} == *example* ]]; then
  echo 'Usage: bash enable_https_proxy.sh https://YOUR-REAL-HOSTNAME'
  echo 'This does NOT remove HTTP guest printing on port 8767.'
  exit 2
fi
python3 - "$1" <<'PY'
import json, pathlib, sys, urllib.parse
url=sys.argv[1].rstrip("/")
p=urllib.parse.urlsplit(url)
if p.scheme!="https" or not p.hostname or p.username or p.password or p.path or p.query or p.fragment:
    raise SystemExit("Provide only a real HTTPS hostname")
path=pathlib.Path("config.json")
data=json.loads(path.read_text())
backup=path.with_name("config.before-https.json")
backup.write_text(json.dumps(data,indent=2)+"\n")
backup.chmod(0o600)
data["listen"]="0.0.0.0"
data["admin_port"]=8768
data["require_https_proxy"]=False
data["access_mode"]="both"
data["public_base_url"]=url
tmp=path.with_suffix(".tmp")
tmp.write_text(json.dumps(data,indent=2)+"\n")
tmp.replace(path)
path.chmod(0o600)
print("Hybrid configuration saved. HTTP guest port 8767 remains available.")
print("HTTPS Caddy upstream: 127.0.0.1:8768.")
print("Local backup:",backup)
PY
