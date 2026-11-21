#!/usr/bin/env bash
# Install FMI PT35 launchers and submenu, without touching keyboard or hardware.
set -Eeuo pipefail
if [[ "$(id -u)" == 0 ]]; then echo "Run without sudo."; exit 1; fi
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
command -v pt35ctl >/dev/null || { echo "PocketTerm35-OS not installed"; exit 1; }
mkdir -p "$HOME/.local/bin"
cat > "$HOME/.local/bin/fmi-pt35-tool" <<EOF
#!/usr/bin/env bash
set -e
case "\$1" in
  spectrum)
    if [[ -x "\$HOME/as7341-env/bin/python" ]]; then
      exec "\$HOME/as7341-env/bin/python" "$ROOT/tools/pt35_tools.py"
    fi
    exec python3 "$ROOT/tools/pt35_tools.py" ;;
  nfc) exec /usr/bin/python3 "$ROOT/nfc/pt35_nfc_gui.py" ;;
  battery) exec /usr/bin/python3 "$ROOT/tools/pi5_battery_status.py" ;;
  *) echo "Usage: fmi-pt35-tool spectrum|nfc|battery"; exit 2 ;;
esac
EOF
cat > "$HOME/.local/bin/pt35-ledctl" <<EOF
#!/bin/sh
exec /usr/bin/python3 "$ROOT/tools/pi5_ledctl.py" "\$@"
EOF
chmod +x "$HOME/.local/bin/fmi-pt35-tool" "$HOME/.local/bin/pt35-ledctl"
python3 "$ROOT/tools/merge_pi5_launcher.py" "$ROOT"
echo "FMI launchers installed. Settings > Reload shell (or log out/in)."
echo "LED controls only work after the optional Pi5 LED daemon is started."
echo "Wolf choice only works after: bash $ROOT/scripts/patch_wolf_taskbar.sh --install"
