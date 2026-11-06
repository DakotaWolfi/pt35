#!/bin/bash
set -e

echo "=== CollarPet DRV2605L setup ==="

if [ "$EUID" -ne 0 ]; then
    echo "Run with sudo:"
    echo "  sudo ./setup_lra.sh"
    exit 1
fi

echo "[1/5] Installing I2C tools..."
apt update
apt install -y i2c-tools python3-smbus2

echo "[2/5] Enabling Raspberry Pi I2C..."
if command -v raspi-config >/dev/null 2>&1; then
    raspi-config nonint do_i2c 0
fi

echo "[3/5] Creating DRV2605L driver..."

cat >/usr/local/bin/lra_ctl.py <<'PYEOF'
#!/usr/bin/env python3

import sys
import time
from smbus2 import SMBus

BUS = 1
ADDR = 0x5A

REG_STATUS      = 0x00
REG_MODE        = 0x01
REG_RTP         = 0x02
REG_LIBRARY     = 0x03
REG_WAVESEQ1    = 0x04
REG_WAVESEQ2    = 0x05
REG_GO          = 0x0C
REG_FEEDBACK    = 0x1A

bus = SMBus(BUS)

def read(reg):
    return bus.read_byte_data(ADDR, reg)

def write(reg, value):
    bus.write_byte_data(ADDR, reg, value & 0xFF)

def init():
    # Internal trigger mode
    write(REG_MODE, 0x00)

    # Library 6 is normally appropriate for LRA operation
    write(REG_LIBRARY, 0x06)

    # Feedback Control bit 7 = 1 -> LRA mode
    fb = read(REG_FEEDBACK)
    write(REG_FEEDBACK, fb | 0x80)

def play(effect):
    effect = max(1, min(123, int(effect)))

    init()

    write(REG_WAVESEQ1, effect)
    write(REG_WAVESEQ2, 0)
    write(REG_GO, 1)

def stop():
    write(REG_GO, 0)
    write(REG_RTP, 0)

def rtp(level):
    level = max(-127, min(127, int(level)))

    # Real-time playback mode
    write(REG_MODE, 0x05)
    write(REG_RTP, level & 0xFF)

def status():
    s = read(REG_STATUS)
    mode = read(REG_MODE)
    lib = read(REG_LIBRARY)
    fb = read(REG_FEEDBACK)

    print(f"DRV2605L @ 0x{ADDR:02X}")
    print(f"STATUS   : 0x{s:02X}")
    print(f"MODE     : 0x{mode:02X}")
    print(f"LIBRARY  : {lib}")
    print(f"FEEDBACK : 0x{fb:02X}")
    print(f"LRA mode : {'YES' if fb & 0x80 else 'NO'}")

def test():
    print("DRV2605L test")
    init()

    # A few clearly distinguishable ROM effects
    for effect in (1, 10, 47):
        print(f"Effect {effect}")
        play(effect)
        time.sleep(0.8)

    stop()

def usage():
    print("""
Usage:
  lra_ctl status
  lra_ctl test
  lra_ctl play EFFECT
  lra_ctl stop
  lra_ctl rtp LEVEL

Examples:
  lra_ctl play 1
  lra_ctl play 47
  lra_ctl rtp 80
  lra_ctl rtp 0
""".strip())

try:
    if len(sys.argv) < 2:
        usage()
        sys.exit(1)

    cmd = sys.argv[1].lower()

    if cmd == "status":
        status()

    elif cmd == "test":
        test()

    elif cmd == "play" and len(sys.argv) >= 3:
        play(int(sys.argv[2]))

    elif cmd == "stop":
        stop()

    elif cmd == "rtp" and len(sys.argv) >= 3:
        rtp(int(sys.argv[2]))

    else:
        usage()
        sys.exit(1)

except OSError as e:
    print(f"I2C error: {e}")
    print("Is the DRV2605L visible at address 0x5A?")
    sys.exit(2)

finally:
    bus.close()
PYEOF

chmod +x /usr/local/bin/lra_ctl.py

ln -sf /usr/local/bin/lra_ctl.py /usr/local/bin/lra_ctl

echo "[4/5] Checking I2C bus..."

echo
i2cdetect -y 1
echo

if i2cdetect -y 1 | grep -q "5a"; then
    echo "DRV2605L found at 0x5A."
else
    echo "WARNING: 0x5A not detected."
    echo "A reboot may be required if I2C was just enabled."
fi

echo "[5/5] Done."
echo
echo "After reboot, try:"
echo "  lra_ctl status"
echo "  lra_ctl test"
echo
echo "Manual effect:"
echo "  lra_ctl play 47"
echo
echo "Stop:"
echo "  lra_ctl stop"
