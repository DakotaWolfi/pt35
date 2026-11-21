#!/usr/bin/env bash
# Install AS7341 Python dependencies into a dedicated Pi5 virtual environment.
set -Eeuo pipefail
if [[ "$(id -u)" == 0 ]]; then echo "Run as login user, without sudo"; exit 1; fi
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$HOME/as7341-env"
if ! python3 -m venv --help >/dev/null 2>&1; then
  echo "Install python3-venv first: sudo apt install python3-venv"
  exit 1
fi
if [[ ! -x "$VENV/bin/python" ]]; then
  python3 -m venv --system-site-packages "$VENV"
fi
"$VENV/bin/python" -m pip install --upgrade pip
"$VENV/bin/python" -m pip install Adafruit-Blinka adafruit-circuitpython-as7341 smbus2
echo "=== AS7341 Python import test ==="
"$VENV/bin/python" - <<'PY'
import sys
import board
import adafruit_as7341
from smbus2 import SMBus
print("Python:", sys.executable)
print("Blinka board import: OK")
print("AS7341 driver import: OK")
with SMBus(1) as bus:
    for a in (0x39,):
        try:
            v=bus.read_byte_data(a, 0x92)
            print(f"AS7341 device at 0x{a:02x}, chip ID register 0x92 -> 0x{v:02x}")
        except OSError as exc:
            print("I2C chip ID check failed:", exc)
            raise
PY
echo "Ready. Run: $VENV/bin/python $ROOT/tools/pt35_tools.py --device as7341"
