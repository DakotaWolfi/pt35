#!/bin/bash
# Switch Print Station to HTTPS-proxy-only mode AFTER Caddy HTTPS is working.
# Run as jenna, not root. Changes only the ignored local config.json.
set -euo pipefail
cd "$(dirname "$0")"
if [[ ${1:-} != https://* ]]; then
  echo 'Usage: bash enable_https_proxy.sh https://your-real-hostname.example'
  echo 'Configure and verify Caddy TLS first. Do not use the placeholder.'
  exit 2
fi
if [[ ${1} == *example* ]]; then echo 'Replace example hostname' >&2; exit 2; fi
python3 - "$1" <<'PY'
import json, pathlib, sys, urllib.parse
url=sys.argv[1].rstrip("/")
p=urllib.parse.urlsplit(url)
if p.scheme!='https' or not p.hostname or p.username or p.password or p.path or p.query or p.fragment:
    raise SystemExit("Provide only HTTPS scheme and hostname; no path/query/credentials")
path=pathlib.Path("config.json")
data=json.loads(path.read_text())
backup=path.with_name("config.before-https.json")
backup.write_text(json.dumps(data, indent=2)+"\n")
backup.chmod(0o600)
data["listen"]="127.0.0.1"
data["require_https_proxy"]=True
data["access_mode"]="both"
data["public_base_url"]=url
tmp=path.with_suffix(".tmp")
tmp.write_text(json.dumps(data,indent=2)+"\n")
tmp.replace(path)
path.chmod(0o600)
print("Saved HTTPS-only proxy config. Local backup:",backup)
print("Restart web server after Caddy is working: sudo systemctl restart fmi-print-station")
PY
