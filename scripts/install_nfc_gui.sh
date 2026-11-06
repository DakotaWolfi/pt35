#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP="$ROOT/nfc/pt35_nfc_gui.py"
if [[ ! -f "$APP" ]]; then echo "Missing $APP" >&2; exit 1; fi
if ! python3 -c 'import tkinter' >/dev/null 2>&1; then
  echo "Tkinter not installed. Run: sudo apt install python3-tk" >&2
  exit 1
fi
mkdir -p "$HOME/.local/bin" "$HOME/.local/share/applications"
cat > "$HOME/.local/bin/pt35-nfc-gui" <<EOF
#!/bin/sh
exec /usr/bin/python3 "$APP" "\$@"
EOF
chmod +x "$HOME/.local/bin/pt35-nfc-gui"
cat > "$HOME/.local/share/applications/pt35-nfc.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=PT35 NFC Reader
Comment=Internal ST25R3916 and Proxmark3 tag reader and archive
Exec=$HOME/.local/bin/pt35-nfc-gui
Terminal=false
Icon=network-wireless
Categories=Utility;System;
EOF
echo "PT35 NFC GUI installed."
echo "Launch: $HOME/.local/bin/pt35-nfc-gui"
echo "Desktop shortcut: $HOME/.local/share/applications/pt35-nfc.desktop"
echo "This does not change or restart running services."
