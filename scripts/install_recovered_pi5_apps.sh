#!/usr/bin/env bash
# Activate RECOVERED Pi4 GUI source on Pi5 via local wrappers, without copying archives,
# touching I2C, launching scanners, or overwriting the recovered tree.
set -Eeuo pipefail
[[ "$(id -u)" != 0 ]] || { echo "Run without sudo"; exit 1; }
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OLD="$HOME/pt35-old-recovery/pt35-nfc-bench"
[[ -f "$OLD/nfc/pt35_nfc_gui.py" && -f "$OLD/tools/as7341_gui.py" ]] || {
 echo "Recover the original sources first: bash scripts/recover_old_pi4_apps.sh"; exit 1; }
python3 -m py_compile "$OLD"/nfc/*.py "$OLD"/tools/*.py
mkdir -p "$HOME/.local/bin" "$HOME/.local/state/pt35"
# Safety: make the recovered tree the canonical source, not a copy in the current repo.
# The GUI may still probe hardware at startup: running is a separate manual step.
cat > "$HOME/.local/bin/pt35-original-nfc" <<EOF
#!/usr/bin/env bash
set -e
export PYTHONPATH="$OLD/nfc:$ROOT/nfc:${PYTHONPATH:-}"
cd "$OLD/nfc"
# Match the original Pi4 desktop launcher interpreter exactly.
PY="\$HOME/as7341-env/bin/python3"
if [[ ! -x "\$PY" ]]; then
  echo "Missing original NFC Python environment: \$PY" >&2
  exit 1
fi
exec "\$PY" "$OLD/nfc/pt35_nfc_gui.py" "\$@" 2>> "$HOME/.local/state/pt35/old-nfc-errors.log"
EOF
cat > "$HOME/.local/bin/pt35-original-spectrum" <<EOF
#!/usr/bin/env bash
set -e
export PYTHONPATH="$OLD/tools:$OLD/nfc:${PYTHONPATH:-}"
cd "$OLD/tools"
exec "$HOME/as7341-env/bin/python" "$OLD/tools/as7341_gui.py" 2>> "$HOME/.local/state/pt35/old-spectrum-errors.log"
EOF
chmod 755 "$HOME/.local/bin/pt35-original-nfc" "$HOME/.local/bin/pt35-original-spectrum"
# Match the EXACT desktop launcher name on the original Pi 4.
# Use an absolute executable path: graphical launchers do not always inherit ~/.local/bin in PATH.
cat > "$HOME/.local/bin/pt35-nfc-gui" <<'EOF'
#!/usr/bin/env bash
exec "$HOME/.local/bin/pt35-original-nfc" "$@"
EOF
chmod 755 "$HOME/.local/bin/pt35-nfc-gui"
mkdir -p "$HOME/.local/share/applications" "$HOME/Desktop"
cat > "$HOME/.local/share/applications/pt35-nfc.desktop" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=PT35 NFC Reader
Comment=Original Pi 4 touch-friendly NFC reader and archive interface
Exec=$HOME/.local/bin/pt35-nfc-gui
Icon=network-wireless
Terminal=false
Categories=Utility;System;
StartupNotify=true
EOF
cp "$HOME/.local/share/applications/pt35-nfc.desktop" "$HOME/Desktop/pt35-nfc.desktop"
chmod +x "$HOME/Desktop/pt35-nfc.desktop"
echo "Pi4-style PT35 NFC Reader desktop icon and application entry installed."

echo "Recovered GUI wrappers created. No GUI launched and no RF commands sent."
echo "Original NFC: ~/.local/bin/pt35-nfc-gui (same name as Pi4)"
echo "Original spectrum: ~/.local/bin/pt35-original-spectrum"
echo "Preflight library check (safe):"
for lib in tkinter smbus2; do /usr/bin/python3 -c "import $lib" && echo "system Python: $lib OK" || true; done
echo "Run: bash scripts/install_pi5_shell.sh to update the FMI launcher entries."\necho "Pi5 NFC GUI patch: python3 scripts/patch_recovered_pi5_nfc.py (once, with original backup)."
echo "Do NOT initiate NFC scans until the reader lockup is diagnosed."

