#!/usr/bin/env bash
# Register the optional standalone Tag Workshop without touching the NFC GUI
# or changing any existing reader driver. Write mode is OFF by default.
set -Eeuo pipefail
[[ $(id -u) != 0 ]] || { echo "Run without sudo" >&2; exit 1; }
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$HOME/as7341-env/bin/python3"
[[ -x "$PY" ]] || PY=/usr/bin/python3
"$PY" -m py_compile "$ROOT/nfc/tag_workshop_ndef.py" "$ROOT/nfc/tag_workshop_rf.py" "$ROOT/nfc/tag_workshop_gui.py"
"$PY" -m unittest discover -s "$ROOT/tests" -p 'test_tag_workshop_ndef.py' -v
mkdir -p "$HOME/.local/bin" "$HOME/.local/share/applications" "$HOME/.local/state/pt35"
cat > "$HOME/.local/bin/pt35-tag-workshop" <<EOF
#!/usr/bin/env bash
set -e
export PYTHONPATH="$ROOT/nfc:${PYTHONPATH:-}"
exec "$PY" "$ROOT/nfc/tag_workshop_gui.py" "\$@" 2>> "\$HOME/.local/state/pt35/tag-workshop-errors.log"
EOF
chmod +x "$HOME/.local/bin/pt35-tag-workshop"
cat > "$HOME/.local/share/applications/pt35-tag-workshop.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=PT35 Tag Workshop
Comment=NFC Type 2 NDEF editor and experimental writer
Exec=$HOME/.local/bin/pt35-tag-workshop
Icon=applications-science
Terminal=false
Categories=Utility;System;
StartupNotify=true
EOF
echo "Tag Workshop desktop application installed (write mode disabled)."
echo "You can enable optional experimental writing for one launch with:"
echo "PT35_TAG_WORKSHOP_WRITE=YES ~/.local/bin/pt35-tag-workshop"
echo "To add the app to FMI Tools, run: python3 tools/merge_pi5_launcher.py \"$ROOT\""
