#!/usr/bin/env bash
# Register the optional standalone Tag Workshop without touching the NFC GUI
# or changing any existing reader driver. Writes require tag-specific confirmation.
set -Eeuo pipefail
[[ $(id -u) != 0 ]] || { echo "Run without sudo" >&2; exit 1; }
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$HOME/as7341-env/bin/python3"
[[ -x "$PY" ]] || PY=/usr/bin/python3
"$PY" -m py_compile "$ROOT/nfc/tag_workshop_ndef.py" "$ROOT/nfc/tag_workshop_raw.py" "$ROOT/nfc/tag_workshop_rf.py" "$ROOT/nfc/tag_workshop_library.py" "$ROOT/nfc/tag_workshop_gui.py"
"$PY" -m unittest discover -s "$ROOT/tests" -p 'test_tag_workshop_ndef.py' -v
"$PY" -m unittest discover -s "$ROOT/tests" -p 'test_tag_workshop_library.py' -v
"$PY" -m unittest discover -s "$ROOT/tests" -p 'test_tag_workshop_raw.py' -v
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
echo "Tag Workshop desktop application installed. Writing requires confirmation per tag."
echo "Use only cheap test tags you own; physical WRITE/ACK handling is not yet hardware-verified."
# Register the app profile and menu entry together.
python3 "$ROOT/tools/merge_pi5_launcher.py" "$ROOT"
python3 - <<'PY'
from pathlib import Path
import tomllib
p = Path.home() / ".config/pt35"
apps = tomllib.loads((p / "apps.toml").read_text())
menu = tomllib.loads((p / "menu.toml").read_text())
assert "fmi_tag_workshop" in apps.get("app", {}), "Missing workshop app profile"
entries = menu.get("menu", {}).get("fmi", {}).get("entries", [])
assert any(e.get("app") == "fmi_tag_workshop" for e in entries), "Missing workshop menu entry"
assert (Path.home() / ".local/bin/pt35-tag-workshop").is_file()
print("PASS: Workshop profile, menu entry and executable installed.")
PY
echo "Reload the PT35 shell from Settings > Reload shell."
