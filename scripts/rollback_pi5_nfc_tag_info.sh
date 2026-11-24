#!/usr/bin/env bash
# Restore recovered NFC GUI to its exact state before the optional tag-info patch.
# Does not alter RF driver, Type 2 reader, archive, settings or LED/haptic services.
set -Eeuo pipefail
[[ $(id -u) != 0 ]] || { echo "Run without sudo" >&2; exit 1; }
GUI="$HOME/pt35-old-recovery/pt35-nfc-bench/nfc/pt35_nfc_gui.py"
BACKUP="$HOME/pt35-old-recovery/pt35-nfc-bench/nfc/pt35_nfc_gui.py.pre-tag-info.bak"
if [[ ! -f "$GUI" || ! -f "$BACKUP" ]]; then
  echo "Expected GUI / tag-info backup not found. No changes made." >&2
  exit 1
fi
if ! grep -q 'PT35_PI5_NFC_TAG_INFO_V1' "$GUI"; then
  echo "Tag-info patch is not present; no changes made."
  exit 0
fi
if grep -q 'PT35_PI5_NFC_TAG_INFO_V1' "$BACKUP"; then
  echo "Backup unexpectedly contains tag-info patch; refusing restoration" >&2
  exit 1
fi
python3 -m py_compile "$BACKUP"
SNAPSHOT="$GUI.pre-tag-info-rollback.$(date +%Y%m%d-%H%M%S).bak"
cp -p "$GUI" "$SNAPSHOT"
cp -p "$BACKUP" "$GUI"
python3 -m py_compile "$GUI"
echo "Restored NFC GUI from pre-tag-info backup."
echo "Copy of crashed GUI: $SNAPSHOT"
echo "Archive, reader, haptic and Type 2 modifications untouched."
echo "Close and reopen NFC Reader."
