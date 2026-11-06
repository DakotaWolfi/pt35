#!/usr/bin/env bash
# PT35 NFC installer; no boot changes, no Proxmark firmware flashes.
set -euo pipefail
DEST="$HOME/pt35-nfc"
mkdir -p "$DEST" "$DEST/archive"
for f in pt35_nfc.py nfcv_scan.py nfcv_dump.py; do
  if [[ -f "$HOME/$f" ]]; then cp "$HOME/$f" "$DEST/$f"; fi
done
if [[ ! -f "$DEST/pt35_nfc.py" || ! -f "$DEST/nfcv_scan.py" || ! -f "$DEST/nfcv_dump.py" ]]; then
  echo 'ERROR: Upload pt35_nfc.py, nfcv_scan.py and nfcv_dump.py first.' >&2
  exit 1
fi
python3 -c 'import smbus2; print("smbus2 ready")'
chmod +x "$DEST/pt35_nfc.py"
cat > "$DEST/README.txt" <<'EOF'
Commands:
  python3 ~/pt35-nfc/pt35_nfc.py status
  python3 ~/pt35-nfc/pt35_nfc.py scan --backend internal --save
  python3 ~/pt35-nfc/pt35_nfc.py watch --auto-tonie
  python3 ~/pt35-nfc/pt35_nfc.py list
  python3 ~/pt35-nfc/pt35_nfc.py pm3-shell
NXP ISO15693 is only a Tonie *candidate*; verify tags manually.
Place confirmed Tonie UIDs in archive/known_tonies.txt (one per line).
EOF
printf 'Installed: %s\n' "$DEST/pt35_nfc.py"
python3 "$DEST/pt35_nfc.py" status
if [[ "${1:-}" == '--install-iceman' ]]; then
  echo 'Installing Debian dependencies for Iceman userspace client (not firmware).'
  sudo apt-get update
  sudo apt-get install -y --no-install-recommends git ca-certificates build-essential pkg-config \
    libreadline-dev libbz2-dev liblz4-dev zlib1g-dev libpython3-dev libssl-dev
  if [[ ! -d "$HOME/proxmark3/.git" ]]; then
    git clone --depth 1 --recurse-submodules https://github.com/RfidResearchGroup/proxmark3.git "$HOME/proxmark3"
  fi
  echo 'Compiling Iceman userspace client ONLY. No PM3 firmware flashing.'
  (cd "$HOME/proxmark3" && make client -j2 SKIPQT=1 SKIPBT=1)
  echo 'Iceman client built, check status with USB connected.'
fi
