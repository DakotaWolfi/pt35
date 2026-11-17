#!/usr/bin/env bash
# Install standalone PT35 Print Pet GUI without changing existing R launcher.
set -Eeuo pipefail
[[ $EUID -ne 0 ]] || { echo "Run as desktop user, not sudo"; exit 1; }
REPO="$HOME/pt35"
[[ -f "$REPO/nfc/print_pet_gui.py" && -f "$REPO/nfc/print_pet_mailbox.py" ]] || {
  echo "Fetch the Print Pet GUI and mailbox scripts first"; exit 1;
}
/usr/bin/python3 -c 'from PIL import Image, ImageTk; import tkinter; import smbus2' || {
  echo "Missing dependencies: python3-pil python3-pil.imagetk python3-tk python3-smbus2"; exit 1;
}
mkdir -p "$HOME/.local/bin" "$HOME/.local/share/applications"
printf '#!/usr/bin/env bash\nexec /usr/bin/python3 "%s/nfc/print_pet_gui.py" "$@"\n' "$REPO" > "$HOME/.local/bin/pt35-print-pet"
chmod 755 "$HOME/.local/bin/pt35-print-pet"
cat >"$HOME/.local/share/applications/pt35-print-pet.desktop" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=Print Pet (NFC)
Comment=Offline NFC print and status for FMI Print Pet
Exec=$HOME/.local/bin/pt35-print-pet
Icon=printer
Terminal=false
Categories=Utility;
EOF
echo "Installed ~/.local/bin/pt35-print-pet; test: ~/.local/bin/pt35-print-pet"
echo "Preserved existing R launcher: ~/.local/bin/pt35-nfc-menu"
