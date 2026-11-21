#!/usr/bin/env bash
# Read-only inventory of old PT35 root filesystem. No archive data copied.
set -Eeuo pipefail
ROOT="${1:-/mnt/pt35-old}"
[[ -d "$ROOT/etc" && -d "$ROOT/home" ]] || { echo "No mounted Linux root at $ROOT" >&2; exit 1; }
echo "=== Old PT35 user homes ==="
find "$ROOT/home" -mindepth 1 -maxdepth 1 -type d -printf "%f\n" 2>/dev/null || true
echo "=== GUI / NFC / spectral Python scripts ==="
find "$ROOT/home" "$ROOT/usr/local" -type f \( -iname "*nfc*.py" -o -iname "*spectr*.py" -o -iname "*as7341*.py" -o -iname "*pt35*.py" -o -iname "*menu*.py" \) -not -path "*/site-packages/*" -not -path "*/node_modules/*" -not -path "*/archive/*" -not -path "*/.cache/*" -print 2>/dev/null | head -200
echo "=== GUI launchers ==="
find "$ROOT/home" "$ROOT/usr/local/share/applications" -type f -name "*.desktop" \( -iname "*pt35*" -o -iname "*nfc*" -o -iname "*spectr*" -o -iname "*collar*" \) -print 2>/dev/null | head -120
echo "=== Services mentioning NFC or PT35 ==="
find "$ROOT/etc/systemd" -type f \( -iname "*nfc*" -o -iname "*pt35*" \) -print 2>/dev/null | head -80
echo "=== Do not copy ~/.ssh, network settings or NFC archives to public GitHub ==="

