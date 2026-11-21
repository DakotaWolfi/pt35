#!/usr/bin/env bash
# Rename Pi5 host to pt35, replace old VisionPi login banner; no storage relabelling.
set -Eeuo pipefail
[[ "$(id -u)" != 0 ]] || { echo "Run as your login user without sudo"; exit 1; }
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
echo "This changes the network hostname from $(hostname) to pt35 and the login banner."
echo "It does NOT change partition UUIDs, mountpoints, disk labels, or boot configuration."
read -r -p "Type PT35 to continue: " CONFIRM
[[ "$CONFIRM" = "PT35" ]] || { echo "Cancelled"; exit 1; }
OLD="$(hostname)"
STAMP="$(date +%Y%m%d-%H%M%S)"
sudo cp -a /etc/hosts "/etc/hosts.pt35-$STAMP.bak"
sudo hostnamectl set-hostname pt35
sudo python3 - "$OLD" <<'PY'
from pathlib import Path
import sys,re
p=Path("/etc/hosts"); s=p.read_text(); old=sys.argv[1]
# Only replace an exact hostname token on the 127.0.1.1 host mapping.
lines=[]
for line in s.splitlines(keepends=True):
    if line.lstrip().startswith("#"): lines.append(line); continue
    m=re.match(r"^(\s*127\.0\.1\.1\s+)(.*)$",line)
    if m:
        tail=re.sub(rf"(?<![A-Za-z0-9_.-]){re.escape(old)}(?![A-Za-z0-9_.-])","pt35",m.group(2))
        lines.append(m.group(1)+tail)
    else: lines.append(line)
p.write_text("".join(lines))
PY
# Never delete the original banner: use a run-parts-ignored extension backup.
if [[ -f /etc/update-motd.d/10-visionpi && -x /etc/update-motd.d/10-visionpi ]]; then
    sudo mv /etc/update-motd.d/10-visionpi "/etc/update-motd.d/10-visionpi.disabled-$STAMP"
fi
sudo install -m755 "$ROOT/scripts/motd/10-pt35" /etc/update-motd.d/10-pt35
echo "Hostname now $(hostname); MOTD updated. Start a NEW SSH session to see the PT35 branding."
echo "If DHCP/mDNS or SSH uses the old host name, use the current IP until clients update."
echo "Current SD card filesystem labels were intentionally left unchanged."

