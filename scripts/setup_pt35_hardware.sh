#!/bin/bash
set -e

if [ "$EUID" -ne 0 ]; then
    echo "Run with:"
    echo "  sudo ./setup_pt35_hardware.sh"
    exit 1
fi

BOOT="/boot/firmware"
OVERLAY_NAME="pt35-max17048"

echo "===================================="
echo " PT35 hardware integration installer"
echo "===================================="

echo
echo "[1/8] Installing packages..."

apt update
apt install -y \
    device-tree-compiler \
    i2c-tools \
    python3-smbus2 \
    python3-pip \
    python3-lgpio

# rpi_ws281x is not packaged consistently on every Raspberry Pi OS image
python3 -m pip install rpi_ws281x --break-system-packages

echo
echo "[2/8] Ensuring I2C is enabled..."

CONFIG="$BOOT/config.txt"

if ! grep -q '^dtparam=i2c_arm=on' "$CONFIG"; then
    echo 'dtparam=i2c_arm=on' >> "$CONFIG"
fi

echo
echo "[3/8] Installing MAX17048 Device Tree overlay..."

cat >/tmp/${OVERLAY_NAME}.dts <<'EOF'
/dts-v1/;
/plugin/;

/ {
    compatible = "brcm,bcm2711";

    fragment@0 {
        target = <&i2c1>;

        __overlay__ {
            status = "okay";

            max17048: fuel-gauge@36 {
                compatible = "maxim,max17048";
                reg = <0x36>;
                status = "okay";
            };
        };
    };
};
EOF

dtc -@ -I dts -O dtb \
    -o "$BOOT/overlays/${OVERLAY_NAME}.dtbo" \
    /tmp/${OVERLAY_NAME}.dts

if ! grep -q "^dtoverlay=${OVERLAY_NAME}$" "$CONFIG"; then
    echo "dtoverlay=${OVERLAY_NAME}" >> "$CONFIG"
fi

echo
echo "[4/8] Updating fan controller to GPIO17..."

if [ -f /usr/local/bin/fan_controller.py ]; then
    sed -i 's/^FAN_PIN *= *.*/FAN_PIN = 17/' \
        /usr/local/bin/fan_controller.py

    systemctl restart fan-controller.service 2>/dev/null || true
    echo "Fan GPIO changed to GPIO17."
else
    echo "Existing fan controller not found; skipping."
fi

echo
echo "[5/8] Creating LED daemon..."

cat >/usr/local/bin/pt35_led_daemon.py <<'PYEOF'
#!/usr/bin/env python3

import os
import time
import math
import socket
import threading
import subprocess

from rpi_ws281x import PixelStrip, Color

LED_COUNT = 16
LED_PIN = 12
LED_FREQ_HZ = 800000
LED_DMA = 10
LED_BRIGHTNESS = 64
LED_INVERT = False
LED_CHANNEL = 0

SOCKET_PATH = "/run/pt35-led.sock"

strip = PixelStrip(
    LED_COUNT,
    LED_PIN,
    LED_FREQ_HZ,
    LED_DMA,
    LED_INVERT,
    LED_BRIGHTNESS,
    LED_CHANNEL
)

strip.begin()

mode = "idle"
solid_color = (0, 0, 0)
running = True

def set_pixel(i, r, g, b):
    strip.setPixelColor(i, Color(int(r), int(g), int(b)))

def show():
    strip.show()

def clear():
    for i in range(LED_COUNT):
        set_pixel(i, 0, 0, 0)
    show()

def fill(r, g, b):
    for i in range(LED_COUNT):
        set_pixel(i, r, g, b)
    show()

def lra(effect):
    try:
        subprocess.run(
            ["/usr/local/bin/lra_ctl", "play", str(effect)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=2
        )
    except Exception:
        pass

def battery_sysfs():
    base = "/sys/class/power_supply"

    try:
        for dev in os.listdir(base):
            path = os.path.join(base, dev)

            cap = os.path.join(path, "capacity")
            volt = os.path.join(path, "voltage_now")

            if os.path.exists(cap):
                with open(cap) as f:
                    soc = float(f.read().strip())

                voltage = None

                if os.path.exists(volt):
                    with open(volt) as f:
                        voltage = float(f.read().strip()) / 1000000.0

                return soc, voltage

    except Exception:
        pass

    return None, None

def battery_direct():
    try:
        from smbus2 import SMBus

        bus = SMBus(1)

        msb = bus.read_byte_data(0x36, 0x04)
        lsb = bus.read_byte_data(0x36, 0x05)
        soc = msb + lsb / 256.0

        vm = bus.read_byte_data(0x36, 0x02)
        vl = bus.read_byte_data(0x36, 0x03)
        raw = (vm << 8) | vl
        voltage = (raw >> 4) * 0.00125

        bus.close()

        return soc, voltage

    except Exception:
        return None, None

def get_battery():
    soc, voltage = battery_sysfs()

    if soc is not None:
        return soc, voltage

    return battery_direct()

def battery_bar(seconds=3):
    soc, voltage = get_battery()

    if soc is None:
        for _ in range(3):
            fill(64, 0, 0)
            time.sleep(0.15)
            clear()
            time.sleep(0.15)
        return

    count = round((soc / 100.0) * LED_COUNT)
    count = max(0, min(LED_COUNT, count))

    clear()

    for i in range(LED_COUNT):
        if i < count:
            if soc < 15:
                set_pixel(i, 100, 0, 0)
            elif soc < 40:
                set_pixel(i, 80, 35, 0)
            else:
                set_pixel(i, 0, 80, 10)
        else:
            set_pixel(i, 0, 0, 0)

    show()

    print(
        f"Battery: {soc:.1f}%"
        + (f" {voltage:.3f}V" if voltage is not None else ""),
        flush=True
    )

    time.sleep(seconds)

def wheel(pos):
    pos = pos & 255

    if pos < 85:
        return pos * 3, 255 - pos * 3, 0

    if pos < 170:
        pos -= 85
        return 255 - pos * 3, 0, pos * 3

    pos -= 170
    return 0, pos * 3, 255 - pos * 3

def boot_animation():
    clear()

    # Slow blue sweep
    for i in range(LED_COUNT):
        set_pixel(i, 0, 0, 70)
        show()
        time.sleep(0.035)

    lra(1)

    time.sleep(0.15)

    # Fast second pass
    for i in range(LED_COUNT):
        set_pixel(i, 0, 50, 100)
        show()
        time.sleep(0.015)

    lra(10)

    time.sleep(0.3)

    battery_bar(2)

    # Fade out
    for level in range(50, -1, -2):
        fill(0, 0, level)
        time.sleep(0.02)

    clear()

def idle_animation():
    global mode

    phase = 0.0

    while running:
        if mode != "idle":
            time.sleep(0.05)
            continue

        # Slow, dim blue/purple breathing effect
        level = int((math.sin(phase) + 1.0) * 10)

        for i in range(LED_COUNT):
            offset = (i * 4) % 16
            set_pixel(
                i,
                level // 2,
                0,
                level + offset // 4
            )

        show()

        phase += 0.08
        time.sleep(0.05)

def rainbow_animation():
    global mode

    offset = 0

    while running:
        if mode != "rainbow":
            time.sleep(0.05)
            continue

        for i in range(LED_COUNT):
            r, g, b = wheel(
                (i * 256 // LED_COUNT + offset) & 255
            )

            # Keep default rainbow sane, not retina-removal mode
            set_pixel(i, r // 4, g // 4, b // 4)

        show()

        offset = (offset + 2) & 255
        time.sleep(0.03)

def solid_animation():
    global mode

    while running:
        if mode != "solid":
            time.sleep(0.05)
            continue

        r, g, b = solid_color
        fill(r, g, b)
        time.sleep(0.2)

def process_command(cmd):
    global mode, solid_color

    parts = cmd.strip().split()

    if not parts:
        return "ERR empty"

    command = parts[0].lower()

    if command == "off":
        mode = "off"
        clear()
        return "OK"

    if command == "idle":
        mode = "idle"
        return "OK"

    if command == "rainbow":
        mode = "rainbow"
        return "OK"

    if command == "battery":
        old = mode
        mode = "temporary"
        battery_bar(3)
        mode = old if old != "temporary" else "idle"
        return "OK"

    if command == "boot":
        old = mode
        mode = "temporary"
        boot_animation()
        mode = old if old != "temporary" else "idle"
        return "OK"

    if command == "color" and len(parts) == 4:
        try:
            r = max(0, min(255, int(parts[1])))
            g = max(0, min(255, int(parts[2])))
            b = max(0, min(255, int(parts[3])))

            solid_color = (r, g, b)
            mode = "solid"

            return "OK"

        except ValueError:
            return "ERR bad RGB"

    if command == "flash" and len(parts) >= 4:
        try:
            r = int(parts[1])
            g = int(parts[2])
            b = int(parts[3])

            old = mode
            mode = "temporary"

            fill(r, g, b)
            time.sleep(0.15)
            clear()
            time.sleep(0.08)
            fill(r, g, b)
            time.sleep(0.15)
            clear()

            mode = old if old != "temporary" else "idle"

            return "OK"

        except ValueError:
            return "ERR bad RGB"

    if command == "status":
        soc, voltage = get_battery()

        return (
            f"mode={mode} "
            f"soc={soc if soc is not None else 'unknown'} "
            f"voltage={voltage if voltage is not None else 'unknown'}"
        )

    return "ERR unknown command"

def socket_server():
    if os.path.exists(SOCKET_PATH):
        os.unlink(SOCKET_PATH)

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(SOCKET_PATH)

    os.chmod(SOCKET_PATH, 0o666)

    server.listen(5)

    while running:
        conn, _ = server.accept()

        try:
            data = conn.recv(1024).decode().strip()
            reply = process_command(data)
            conn.sendall((reply + "\n").encode())

        except Exception as e:
            try:
                conn.sendall(f"ERR {e}\n".encode())
            except Exception:
                pass

        finally:
            conn.close()

try:
    boot_animation()

    threading.Thread(
        target=idle_animation,
        daemon=True
    ).start()

    threading.Thread(
        target=rainbow_animation,
        daemon=True
    ).start()

    threading.Thread(
        target=solid_animation,
        daemon=True
    ).start()

    socket_server()

finally:
    clear()

    try:
        os.unlink(SOCKET_PATH)
    except Exception:
        pass
PYEOF

chmod +x /usr/local/bin/pt35_led_daemon.py

echo
echo "[6/8] Creating led_ctl..."

cat >/usr/local/bin/led_ctl <<'PYEOF'
#!/usr/bin/env python3

import socket
import sys

SOCKET = "/run/pt35-led.sock"

if len(sys.argv) < 2:
    print("""
Usage:
  led_ctl idle
  led_ctl off
  led_ctl rainbow
  led_ctl battery
  led_ctl boot
  led_ctl status
  led_ctl color R G B
  led_ctl flash R G B

Examples:
  led_ctl color 0 0 50
  led_ctl flash 100 0 80
  led_ctl battery
""".strip())
    sys.exit(1)

cmd = " ".join(sys.argv[1:])

sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

try:
    sock.connect(SOCKET)
    sock.sendall((cmd + "\n").encode())

    response = sock.recv(4096).decode().strip()

    if response:
        print(response)

except FileNotFoundError:
    print("PT35 LED service is not running.")
    sys.exit(2)

finally:
    sock.close()
PYEOF

chmod +x /usr/local/bin/led_ctl

echo
echo "[7/8] Creating LED systemd service..."

cat >/etc/systemd/system/pt35-leds.service <<'EOF'
[Unit]
Description=PT35 NeoPixel Hardware Service
After=local-fs.target
Wants=local-fs.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 /usr/local/bin/pt35_led_daemon.py
Restart=on-failure
RestartSec=2

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable pt35-leds.service

echo
echo "[8/8] Finishing..."

echo
echo "Installed:"
echo "  MAX17048 native Linux battery overlay"
echo "  NeoPixel daemon on GPIO12"
echo "  led_ctl command"
echo "  boot LED + LRA sequence"
echo "  battery bar"
echo "  idle animation"
echo "  fan moved to GPIO17"
echo
echo "A reboot is REQUIRED for the MAX17048 Device Tree overlay."
echo
echo "Reboot with:"
echo
echo "  sudo reboot"
echo
