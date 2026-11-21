#!/usr/bin/env bash
# Copy old PT35 application SOURCE from a read-only Pi4 SD mount into a staging directory.
# Does NOT install services or overwrite current apps. Does NOT copy archives, keys or credentials.
set -Eeuo pipefail
OLD="${1:-/mnt/pt35-old}"
USER_HOME="$OLD/home/jenna"
SRC="$USER_HOME/pt35-nfc-bench"
DEST="$HOME/pt35-old-recovery"
[[ "$(id -u)" != 0 ]] || { echo "Run without sudo so recovered files belong to you"; exit 1; }
[[ -d "$SRC/nfc" && -d "$SRC/tools" ]] || { echo "Missing $SRC/nfc or $SRC/tools"; exit 1; }
if ! findmnt -n -o OPTIONS "$OLD" | grep -Eq "(^|,)ro(,|$)"; then
  echo "Old card is not mounted read-only at $OLD; aborting."; exit 1
fi
if [[ -e "$DEST" ]]; then
  echo "Recovery directory already exists: $DEST"
  echo "No overwrite attempted. Move it aside manually if you want a new copy."
  exit 1
fi
mkdir -p "$DEST/pt35-nfc-bench" "$DEST/old-home" "$DEST/desktop"
# Copy code from the bench snapshot; explicitly exclude NFC captures and all archives.
for part in nfc tools tests; do
  if [[ -d "$SRC/$part" ]]; then
    mkdir -p "$DEST/pt35-nfc-bench/$part"
    find "$SRC/$part" -maxdepth 1 -type f \( -name "*.py" -o -name "*.md" -o -name "*.toml" \) -exec cp --no-clobber -t "$DEST/pt35-nfc-bench/$part" -- {} +
  fi
done
# Preserve launchers for comparison, but do not execute them.
for f in "$USER_HOME/.local/share/applications/pt35-nfc.desktop" \
         "$USER_HOME/.local/share/applications/pt35-launcher.desktop" \
         "$USER_HOME/Desktop/pt35-nfc.desktop"; do
  [[ -f "$f" ]] && cp --no-clobber "$f" "$DEST/desktop/$(basename "${f%/*}")-$(basename "$f")" || true
done
for f in "$USER_HOME/pt35_tools.py" "$USER_HOME/test_as7341.py"; do
  [[ -f "$f" ]] && cp --no-clobber "$f" "$DEST/old-home/"
done
echo "Recovered source to: $DEST"
echo "No applications were installed or run. No NFC archives were copied."
echo "=== Source files ==="
find "$DEST" -maxdepth 3 -type f | sort
echo "=== Old NFC launch commands (from desktop files; check before sharing paths) ==="
grep -H "^\(Name\|Exec\|Icon\)=" "$DEST"/desktop/*.desktop 2>/dev/null || true
echo "=== NFC GUI sizes and key entrypoints ==="
grep -En "class |def (main|start|stop|close|scan)|geometry\(|title\(" "$DEST"/pt35-nfc-bench/nfc/pt35_nfc_gui.py "$DEST"/pt35-nfc-bench/nfc/nfc_touch.py "$DEST"/pt35-nfc-bench/tools/as7341_gui.py 2>/dev/null | head -90 || true

