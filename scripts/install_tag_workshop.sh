#!/usr/bin/env bash
# Register the optional standalone Tag Workshop without touching the NFC GUI
# or changing any existing reader driver. Writes require tag-specific confirmation.
set -Eeuo pipefail
[[ $(id -u) != 0 ]] || { echo "Run without sudo" >&2; exit 1; }
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$HOME/as7341-env/bin/python3"
[[ -x "$PY" ]] || PY=/usr/bin/python3
"$PY" -m py_compile "$ROOT/nfc/tag_workshop_ndef.py" "$ROOT/nfc/tag_workshop_raw.py" "$ROOT/nfc/tag_workshop_access.py" "$ROOT/nfc/tag_workshop_rf.py" "$ROOT/nfc/tag_workshop_library.py" "$ROOT/nfc/tag_workshop_gui.py" "$ROOT/nfc/tag_workshop_batch.py" "$ROOT/nfc/tag_workshop_batch_gui.py" "$ROOT/nfc/tag_workshop_erase_gui.py" "$ROOT/nfc/pt35_nfc_tools_hub.py"
"$PY" -m unittest discover -s "$ROOT/tests" -p 'test_tag_workshop_ndef.py' -v
"$PY" -m unittest discover -s "$ROOT/tests" -p 'test_tag_workshop_library.py' -v
"$PY" -m unittest discover -s "$ROOT/tests" -p 'test_tag_workshop_raw.py' -v
"$PY" -m unittest discover -s "$ROOT/tests" -p 'test_tag_workshop_rf.py' -v
"$PY" -m unittest discover -s "$ROOT/tests" -p 'test_tag_workshop_access.py' -v
"$PY" -m unittest discover -s "$ROOT/tests" -p 'test_tag_workshop_batch.py' -v
mkdir -p "$HOME/.local/bin" "$HOME/.local/share/applications" "$HOME/.local/state/pt35"
cat > "$HOME/.local/bin/pt35-tag-workshop" <<EOF
#!/usr/bin/env bash
set -e
export PYTHONPATH="$ROOT/nfc:${PYTHONPATH:-}"
exec "$PY" "$ROOT/nfc/tag_workshop_gui.py" "\$@" 2>> "\$HOME/.local/state/pt35/tag-workshop-errors.log"
EOF
chmod +x "$HOME/.local/bin/pt35-tag-workshop"
cat > "$HOME/.local/bin/pt35-nfc-tools" <<EOF
#!/usr/bin/env bash
set -e
exec "$PY" "$ROOT/nfc/pt35_nfc_tools_hub.py" "\$@" 2>> "\$HOME/.local/state/pt35/nfc-tools-errors.log"
EOF
cat > "$HOME/.local/bin/pt35-nfc-infinite-copy" <<EOF
#!/usr/bin/env bash
set -e
exec "$PY" "$ROOT/nfc/tag_workshop_batch_gui.py" "\$@" 2>> "\$HOME/.local/state/pt35/nfc-copy-errors.log"
EOF
chmod +x "$HOME/.local/bin/pt35-nfc-tools" "$HOME/.local/bin/pt35-nfc-infinite-copy"
cat > "$HOME/.local/share/applications/pt35-nfc-tools.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=PT35 NFC Tools
Exec=$HOME/.local/bin/pt35-nfc-tools
Icon=applications-science
Terminal=false
Categories=Utility;System;
EOF
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
echo "Batch writing uses source UID checks, readback verification and per-tag backup."
# Register the app profile and menu entry together.
python3 "$ROOT/tools/merge_pi5_launcher.py" "$ROOT"
python3 - <<'PY'
from pathlib import Path
import tomllib
p = Path.home() / ".config/pt35"
apps = tomllib.loads((p / "apps.toml").read_text())
menu = tomllib.loads((p / "menu.toml").read_text())
assert "fmi_nfc_tools" in apps.get("app", {}), "Missing NFC Tools app profile"
entries = menu.get("menu", {}).get("fmi", {}).get("entries", [])
assert any(e.get("app") == "fmi_nfc_tools" for e in entries), "Missing NFC Tools menu entry"
assert (Path.home() / ".local/bin/pt35-tag-workshop").is_file()
assert (Path.home() / ".local/bin/pt35-nfc-tools").is_file()
print("PASS: NFC Tools hub, Workshop, batch copy and FMI menu profile installed.")
PY
echo "Reload the PT35 shell from Settings > Reload shell."
