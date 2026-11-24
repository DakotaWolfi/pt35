#!/usr/bin/env bash
# Safe, idempotent V2 NFC tag-information installer.
# Never prepends migration/nfc to sys.path: doing so shadows the recovered RF reader.
set -Eeuo pipefail
[[ "$(id -u)" != 0 ]] || { echo "Run as normal user (not sudo)" >&2; exit 1; }
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
GUI="$HOME/pt35-old-recovery/pt35-nfc-bench/nfc/pt35_nfc_gui.py"
[[ -f "$GUI" ]] || { echo "Recovered NFC GUI missing: $GUI" >&2; exit 1; }
python3 -m py_compile "$ROOT/nfc/pi5_tag_info.py" "$ROOT/scripts/repair_pi5_nfc_tag_info.py"
python3 "$ROOT/scripts/repair_pi5_nfc_tag_info.py"
python3 -m py_compile "$GUI"
# Check RF module resolution as the launcher would see it, without creating a GUI.
NFC_GUI_DIR="$(dirname "$GUI")" ROOT="$ROOT" python3 - <<'PY'
import os
import subprocess
import sys
from pathlib import Path
directory = os.environ["NFC_GUI_DIR"]
env = dict(os.environ)
env["PYTHONPATH"] = directory + os.pathsep + str(Path(os.environ["ROOT"]) / "nfc")
code = (
    "import nfcv_scan; from nfcv_scan import FrameError; "
    "print('NFC FrameError imported from', nfcv_scan.__file__)"
)
py = Path.home() / "as7341-env/bin/python3"
interpreter = str(py) if py.is_file() else sys.executable
proc = subprocess.run([interpreter, "-c", code], cwd=directory, env=env,
                      text=True, capture_output=True)
if proc.returncode != 0:
    print(proc.stderr, file=sys.stderr)
    raise SystemExit("Recovered NFC import preflight FAILED; do not launch GUI")
if not str(Path(directory).resolve()) in proc.stdout:
    raise SystemExit("Unexpected NFC driver import path: " + proc.stdout)
print(proc.stdout.strip())
print("Import preflight passed.")
PY
echo "NFC tag info V2 installed, safe to reopen graphical PT35 NFC Reader."
