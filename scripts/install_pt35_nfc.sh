#!/usr/bin/env bash
# Use the Git checkout as the source of truth. Keep existing live scripts and data.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ $# -gt 0 ]]; then
  echo "Run without arguments to install the NFC launcher." >&2
  exit 2
fi
python3 -c 'import smbus2' || { echo "Install python3-smbus2 first." >&2; exit 1; }
bash "$ROOT/scripts/install_nfc_gui.sh"
