#!/usr/bin/env bash
# Fetch only Collar Pet display expression PNGs, no Collar Pet runtime.
set -euo pipefail
APP="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="$APP/assets/wolves"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
command -v git >/dev/null || { echo "git is required"; exit 1; }
git clone --depth 1 --filter=blob:none --sparse https://github.com/DakotaWolfi/collar-pet.git "$TMP/collar-pet"
git -C "$TMP/collar-pet" sparse-checkout set pi/assets/wolves
TEST="$TMP/collar-pet/pi/assets/wolves/wolf_idle.png"
test -s "$TEST" || { echo "Missing Collar Pet wolf_idle.png in upstream source"; exit 1; }
mkdir -p "$DEST"
count=0
for file in "$TMP/collar-pet/pi/assets/wolves"/wolf_*.png; do
    [[ -f "$file" ]] || continue
    cp "$file" "$DEST/"
    count=$((count+1))
done
echo "Installed $count actual Collar Pet expression PNGs in $DEST"
echo "Restart display: sudo systemctl restart fmi-print-display"
