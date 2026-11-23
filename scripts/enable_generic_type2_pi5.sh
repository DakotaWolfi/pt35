#!/usr/bin/env bash
# Enable the existing recovered Pi4 scanner's generic Type 2 read fallback.
# Never modifies RF initialization, GUI settings, tag archive, or hardware.
set -Eeuo pipefail
[[ $(id -u) != 0 ]] || { echo "Run as normal user, not sudo" >&2; exit 1; }
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="$HOME/pt35-old-recovery/pt35-nfc-bench/nfc/nfc_poll.py"
HELPER="$ROOT/nfc/pi5_type2_reader.py"
[[ -f "$TARGET" && -f "$HELPER" ]] || {
  echo "Missing recovered nfc_poll.py or generic Type 2 helper" >&2
  exit 1
}
python3 -m py_compile "$HELPER"
TARGET="$TARGET" python3 - <<'PY'
import ast
import os
from pathlib import Path

path = Path(os.environ["TARGET"])
source = path.read_text(encoding="utf-8")
marker = "# PT35_PI5_GENERIC_TYPE2_V1"
if marker in source:
    print("Generic NFC Type 2 fallback already installed")
    raise SystemExit(0)
module = ast.parse(source)
matches = [node for node in module.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "read_ntag"]
if len(matches) != 1:
    raise SystemExit("Cannot identify unique read_ntag function; no changes made")
node = matches[0]
lines = source.splitlines(keepends=True)
prior = "".join(lines[node.lineno - 1:node.end_lineno])
if "known NTAG21x" not in prior or "GET_VERSION" not in prior:
    raise SystemExit("Recovered scanner no longer matches expected Pi4 code; no changes made")

replacement = '''def read_ntag(chip, uid, details, *, progress=None):
    """Read generic NFC Forum Type 2 user memory, not only NXP NTAG21x."""
    from pi5_type2_reader import read_type2
    return read_type2(
        chip, uid, details, progress=progress, receive=receive,
        crc_a=crc_a, set_coverage=set_coverage, failure=failure,
        frame_error=FrameError,
    )  # PT35_PI5_GENERIC_TYPE2_V1
'''
updated = "".join(lines[:node.lineno - 1]) + replacement + "".join(lines[node.end_lineno:])
ast.parse(updated, filename=str(path))
backup = path.with_name("nfc_poll.py.pre-generic-type2.bak")
if backup.exists():
    raise SystemExit(f"Existing backup at {backup}; no changes made")
backup.write_text(source, encoding="utf-8")
path.write_text(updated, encoding="utf-8")
print("Generic Type 2 read-only fallback enabled in", path)
print("Original backed up to", backup)
PY
python3 -m py_compile "$TARGET"
echo "Close and reopen the graphical NFC Reader to pick up the update."
echo "Existing Auto / NFC-A / NFC-B / NFC-F / NFC-V selection remains unchanged."
