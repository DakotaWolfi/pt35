#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP="$ROOT/nfc/pt35_nfc_gui.py"
case "${1:-}" in
  ''|--autostart|--no-autostart) ;;
  *) echo "Usage: $0 [--autostart|--no-autostart]" >&2; exit 2 ;;
esac
if [[ $# -gt 1 ]]; then exit 2; fi
AUTOSTART="${XDG_CONFIG_HOME:-$HOME/.config}/autostart/pt35-nfc.desktop"
if [[ ! -f "$APP" ]]; then echo "Missing $APP" >&2; exit 1; fi
PYTHON="$(command -v python3)"
if ! "$PYTHON" -c 'import tkinter' >/dev/null 2>&1; then
  echo "Tkinter not installed. Run: sudo apt install python3-tk" >&2
  exit 1
fi
mkdir -p "$HOME/.local/bin" "$HOME/.local/share/applications"
printf '#!/usr/bin/env bash\nexec %q %q "$@"\n' "$PYTHON" "$APP" > "$HOME/.local/bin/pt35-nfc-gui"
chmod +x "$HOME/.local/bin/pt35-nfc-gui"
DESKTOP_EXEC="$HOME/.local/bin/pt35-nfc-gui"
DESKTOP_EXEC="${DESKTOP_EXEC//%/%%}"
cat > "$HOME/.local/share/applications/pt35-nfc.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=PT35 NFC Reader
Comment=Internal ST25R3916 and Proxmark3 tag reader and archive
Exec="$DESKTOP_EXEC"
Terminal=false
Icon=network-wireless
Categories=Utility;
EOF
if [[ "${1:-}" == --autostart ]]; then
  mkdir -p "$(dirname "$AUTOSTART")"
  cp "$HOME/.local/share/applications/pt35-nfc.desktop" "$AUTOSTART"
elif [[ "${1:-}" == --no-autostart ]]; then
  rm -f -- "$AUTOSTART"
fi
echo "PT35 NFC GUI installed."
echo "Launch: $HOME/.local/bin/pt35-nfc-gui"
echo "Desktop application menu entry: $HOME/.local/share/applications/pt35-nfc.desktop"
echo "This does not change or restart running services."
