#!/usr/bin/env bash
# PT35 custom launcher integration. Safe: leaves keyboard and old hardware services alone.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CONF="$HOME/.config/pt35/apps.toml"
mkdir -p "$HOME/.config/pt35" "$HOME/.local/bin" "$HOME/pt35-config-backups"
if [[ -f "$CONF" ]]; then cp -a "$CONF" "$HOME/pt35-config-backups/apps.toml.$(date +%Y%m%d-%H%M%S)"; fi
if ! command -v pt35ctl >/dev/null; then echo "PocketTerm35-OS not installed"; exit 1; fi
cat > "$HOME/.local/bin/fmi-pt35-tool" <<EOF
#!/bin/sh
case "\$1" in
 spectrum) exec python3 "$ROOT/tools/pt35_tools.py";;
 nfc) exec python3 "$ROOT/nfc/pt35_nfc_gui.py";;
 battery) exec python3 "$ROOT/tools/pi5_battery_status.py";;
 *) echo "Choose spectrum, nfc or battery"; exit 2;;
esac
EOF
chmod +x "$HOME/.local/bin/fmi-pt35-tool"
python3 - "$CONF" "$HOME/.local/bin/fmi-pt35-tool" <<'PY'
import sys
from pathlib import Path
p=Path(sys.argv[1]); tool=sys.argv[2]
s=p.read_text() if p.exists() else ""
a="# BEGIN FMI PT35 APPS"; b="# END FMI PT35 APPS"
if a in s and b in s:
    s=s[:s.index(a)]+s[s.index(b)+len(b):]
block=f'''
{a}
[app.fmi_spectrum]
label = "Spectral analyser"
glyph = "SP"
icon = "utilities-system-monitor"
exec = "foot -a fmi-spectrum {tool} spectrum"
match = {{ app_id = "fmi-spectrum" }}

[app.fmi_nfc]
label = "NFC reader"
glyph = "NF"
icon = "network-wireless"
exec = "{tool} nfc"
match = {{ app_id = "pt35-nfc" }}
scale = 0.75

[app.fmi_battery]
label = "Battery status"
glyph = "BT"
icon = "battery"
exec = "foot -a fmi-battery {tool} battery"
match = {{ app_id = "fmi-battery" }}
{b}
'''
p.write_text(s.rstrip()+"\n"+block)
print("PT35 launcher apps added. Existing system apps retained.")
PY
echo "Reload shell via Settings > Reload shell."
echo "For the built-in battery bar, the MAX17048 needs a Linux power_supply driver."
