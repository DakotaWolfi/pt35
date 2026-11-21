#!/usr/bin/env bash
# Read-only Pi5 PT35 validation. Does not start services, change boot files or flash keyboard.
set -u
echo "=== PT35 desktop ==="
command -v pt35ctl || true
systemctl --user is-active pt35-buttons.service 2>/dev/null || true
echo "=== Board / kernel ==="
uname -a
echo "=== I2C ==="
if command -v i2cdetect >/dev/null; then sudo i2cdetect -y 1; else echo "i2c-tools missing"; fi
echo "=== AS7341 Python dependencies ==="
for p in "$HOME/as7341-env/bin/python" /usr/bin/python3; do
  if [[ -x "$p" ]]; then
    "$p" -c 'import importlib.util; print("python:",__import__("sys").executable, "board:",bool(importlib.util.find_spec("board")), "adafruit_as7341:",bool(importlib.util.find_spec("adafruit_as7341")), "smbus2:",bool(importlib.util.find_spec("smbus2")))' 2>&1 || true
  fi
done
echo "=== Touch/display ==="
ls /dev/input/by-id/ 2>/dev/null | head -20 || true
echo "=== Input firmware status ==="
command -v pt35-kbd || true
if command -v pt35-kbd >/dev/null; then echo "Use sudo pt35-kbd files / dump code.py to inspect before flash"; fi
echo "=== LED ==="
ls -l /dev/pio0 2>&1 || true
id -nG
systemctl is-active pt35-leds.service 2>/dev/null || true
systemctl --user is-active pt35-leds-pi5.service 2>/dev/null || true
systemctl --user status pt35-leds-pi5.service --no-pager -n 12 2>/dev/null || true
echo "=== Battery ==="
find /sys/class/power_supply/ -maxdepth 2 -name capacity -exec sh -c 'echo "$1"; cat "$1"' _ {} \; 2>/dev/null || true
echo "=== Control shortcuts ==="
command -v foot || true
echo "=== End read-only diagnostics ==="
