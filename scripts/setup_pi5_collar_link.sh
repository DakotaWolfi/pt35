#!/usr/bin/env bash
# Minimal, non-destructive Collar Pet LAN link for a fresh PT35.
set -Eeuo pipefail
[[ "$EUID" -ne 0 ]] || { echo "Run as desktop user." >&2; exit 1; }
BASE="$HOME/.local/share/collarpet-link"
BIN="$HOME/.local/bin"
CFG="$HOME/.config/collarpet/link.conf"
mkdir -p "$BASE" "$BIN" "$(dirname "$CFG")"
if [[ ! -e "$CFG" ]]; then
  cat > "$CFG" <<'EOF'
COLLARPET_NAME="CollarPet"
COLLARPET_USER="jenna"
COLLARPET_SSH_PORT="22"
HELLO_PORT="47842"
DISCOVERY_SECONDS="3"
EOF
  chmod 600 "$CFG"
fi
cat > "$BASE/discover.py" <<'PY'
#!/usr/bin/env python3
import json, socket, sys, time
port=int(sys.argv[1]) if len(sys.argv)>1 else 47842
timeout=float(sys.argv[2]) if len(sys.argv)>2 else 3
s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
s.setsockopt(socket.SOL_SOCKET,socket.SO_BROADCAST,1)
s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
s.settimeout(0.35)
deadline=time.time()+timeout
next_send=0
while time.time()<deadline:
    if time.time() >= next_send:
        s.sendto(b"COLLARPET_HELLO v4",("255.255.255.255",port))
        next_send=time.time()+0.6
    try:
        raw,addr=s.recvfrom(8192)
        obj=json.loads(raw)
        if isinstance(obj,dict) and obj.get("name")=="CollarPet":
            obj["_source_ip"]=addr[0]
            print(json.dumps(obj))
            sys.exit(0)
    except (socket.timeout, ValueError, OSError):
        pass
sys.exit(1)
PY
cat > "$BIN/cp-discover" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
source "$HOME/.config/collarpet/link.conf"
exec python3 "$HOME/.local/share/collarpet-link/discover.py" "${HELLO_PORT:-47842}" "${DISCOVERY_SECONDS:-3}"
SH
cat > "$BIN/cp-connect" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
source "$HOME/.config/collarpet/link.conf"
ip="$(cp-discover | python3 -c 'import sys,json; x=json.load(sys.stdin); print(x.get("_source_ip",""))')" || {
  echo "Collar Pet not discovered. Pair when it is available."; exit 1;
}
args=(-p "${COLLARPET_SSH_PORT:-22}")
key="$HOME/.ssh/id_ed25519_collarpet"
[[ -f "$key" ]] && args+=(-i "$key")
exec ssh "${args[@]}" "${COLLARPET_USER:-jenna}@$ip"
SH
cat > "$BIN/cp-pair-ssh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
source "$HOME/.config/collarpet/link.conf"
key="$HOME/.ssh/id_ed25519_collarpet"
[[ -f "$key" ]] || ssh-keygen -t ed25519 -f "$key" -N "" -C "PT35 -> CollarPet"
ip="$(cp-discover | python3 -c 'import sys,json; x=json.load(sys.stdin); print(x.get("_source_ip",""))')" || {
  read -r -p "Collar Pet hostname/IP: " ip;
}
ssh-copy-id -i "$key.pub" -p "${COLLARPET_SSH_PORT:-22}" "${COLLARPET_USER:-jenna}@$ip"
SH
chmod 0755 "$BIN/cp-discover" "$BIN/cp-connect" "$BIN/cp-pair-ssh" "$BASE/discover.py"
echo "LAN link utilities installed without replacing existing connection settings."
