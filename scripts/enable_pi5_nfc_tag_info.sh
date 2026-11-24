#!/usr/bin/env bash
# Display verified NFC polling metadata in recovered PT35 GUI.
# Read-only UI patch: no changes to RF commands, I2C, or archive records.
set -Eeuo pipefail
[[ $(id -u) != 0 ]] || { echo "Run without sudo" >&2; exit 1; }
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
GUI="$HOME/pt35-old-recovery/pt35-nfc-bench/nfc/pt35_nfc_gui.py"
HELPER="$ROOT/nfc/pi5_tag_info.py"
[[ -f "$GUI" && -f "$HELPER" ]] || { echo "Recovered GUI or helper not found" >&2; exit 1; }
python3 -m py_compile "$HELPER"
GUI="$GUI" HELPER_DIR="$ROOT/nfc" python3 - <<'PY'
import ast
import os
from pathlib import Path
p = Path(os.environ["GUI"])
s = p.read_text(encoding="utf-8")
marker = "# PT35_PI5_NFC_TAG_INFO_V1"
if marker in s:
    print("NFC tag info GUI patch already installed")
    raise SystemExit(0)
needle = "from nfc_ndef import decode_message, extract_message, ndef_area\n"
if s.count(needle) != 1:
    raise SystemExit("Cannot find recovered GUI import anchor; no changes made")
replacement = (
    needle
    + "sys.path.insert(0, " + repr(os.environ["HELPER_DIR"]) + ")\n"
    + "from pi5_tag_info import describe as describe_nfc_tag\n"
    + marker + "\n"
)
s = s.replace(needle, replacement, 1)
summary_anchor = "    result.append('Classification: ' + str(record.get('classification', 'unknown')))\n"
if s.count(summary_anchor) != 1:
    raise SystemExit("Cannot identify summary anchor; no changes made")
s = s.replace(summary_anchor, "    result.extend(describe_nfc_tag(record))\n" + summary_anchor, 1)
# Make technology visible immediately in the live scan status, as well as
# in the existing tag details/summary panel.
status_anchor = "            self.status.set((comparison.replace('_', ' ') + ' · ' if comparison else '') + coverage(self.newest))\n"
if s.count(status_anchor) != 1:
    raise SystemExit("Cannot identify status anchor; no changes made")
s = s.replace(status_anchor,
    "            tag_info = describe_nfc_tag(self.newest)\n"
    "            heading = tag_info[0] + ' · ' if tag_info else ''\n"
    "            self.status.set(heading + (comparison.replace('_', ' ') + ' · ' if comparison else '') + coverage(self.newest))\n",
    1)
ast.parse(s, filename=str(p))
backup = p.with_name("pt35_nfc_gui.py.pre-tag-info.bak")
if backup.exists():
    raise SystemExit(f"Backup already exists at {backup}; no changes made")
backup.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
p.write_text(s, encoding="utf-8")
print("Updated NFC GUI; backup:", backup)
PY
python3 -m py_compile "$GUI"
echo "Restart the NFC GUI to see NFC-B PUPI / ATQB data and other protocol details."
