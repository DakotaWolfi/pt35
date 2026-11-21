#!/usr/bin/env bash
# Launch NFC GUI; capture Python errors only (not tag/stdout records).
set -Eeuo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MODE="${1:-classic}"
case "$MODE" in
  classic) APP="$ROOT/nfc/pt35_nfc_gui_legacy.py";;
  new) APP="$ROOT/nfc/pt35_nfc_gui.py";;
  *) echo "Usage: $0 classic|new" >&2; exit 2;;
esac
mkdir -p "$HOME/.local/state/pt35"
LOG="$HOME/.local/state/pt35/nfc-${MODE}-errors.log"
echo "=== $(date -Is) $MODE GUI starting ===" >> "$LOG"
if /usr/bin/python3 "$APP" 2>> "$LOG"; then
  echo "=== exited normally ===" >> "$LOG"
else
  CODE=$?
  echo "=== exit code $CODE ===" >> "$LOG"
  echo "NFC GUI exited with code $CODE; see $LOG" >&2
  exit "$CODE"
fi
