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
export PYTHONPATH="$OLD/nfc:${PYTHONPATH:-}"
cd "$OLD/nfc"
exec /usr/bin/python3 "$OLD/nfc/pt35_nfc_gui.py" 2>> "$HOME/.local/state/pt35/old-nfc-errors.log"
EOF
cat > "$HOME/.local/bin/pt35-original-spectrum" <<EOF
#!/usr/bin/env bash
set -e
export PYTHONPATH="$OLD/tools:$OLD/nfc:${PYTHONPATH:-}"
cd "$OLD/tools"
exec "$HOME/as7341-env/bin/python" "$OLD/tools/as7341_gui.py" 2>> "$HOME/.local/state/pt35/old-spectrum-errors.log"
EOF
chmod 755 "$HOME/.local/bin/pt35-original-nfc" "$HOME/.local/bin/pt35-original-spectrum"
echo "Recovered GUI wrappers created. No GUI launched and no RF commands sent."
echo "Original NFC: ~/.local/bin/pt35-original-nfc"
echo "Original spectrum: ~/.local/bin/pt35-original-spectrum"
echo "Preflight library check (safe):"
for lib in tkinter smbus2; do /usr/bin/python3 -c "import $lib" && echo "system Python: $lib OK" || true; done
echo "Run: bash scripts/install_pi5_shell.sh to update the FMI launcher entries."
echo "Do NOT initiate NFC scans until the reader lockup is diagnosed."

