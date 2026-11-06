#!/bin/bash
set -e

FAN_SCRIPT="/usr/local/bin/fan_controller.py"
SERVICE_FILE="/etc/systemd/system/fan-controller.service"

echo "Installing dependencies..."
apt update
apt install -y python3-gpiozero python3-lgpio

echo "Creating fan controller..."

cat > "$FAN_SCRIPT" <<'PYEOF'
#!/usr/bin/env python3

import time
from gpiozero import PWMOutputDevice

FAN_PIN = 18

# Some 2-wire fans dislike very high-frequency PWM.
# 500 Hz is a reasonable starting point.
PWM_FREQ = 500

fan = PWMOutputDevice(
    FAN_PIN,
    frequency=PWM_FREQ,
    initial_value=0
)

def cpu_temp():
    with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
        return int(f.read().strip()) / 1000.0

def fan_speed(temp):
    if temp < 45:
        return 0.00
    elif temp < 50:
        return 0.30
    elif temp < 55:
        return 0.40
    elif temp < 60:
        return 0.50
    elif temp < 65:
        return 0.65
    elif temp < 70:
        return 0.80
    else:
        return 1.00

last_duty = 0.0

while True:
    try:
        temp = cpu_temp()
        duty = fan_speed(temp)

        # Give the fan a short full-power kick when starting.
        if last_duty == 0 and duty > 0:
            fan.value = 1.0
            time.sleep(0.35)

        fan.value = duty
        last_duty = duty

        print(
            f"CPU {temp:.1f} C | Fan {duty * 100:.0f}%",
            flush=True
        )

        time.sleep(2)

    except Exception as e:
        print(f"Fan controller error: {e}", flush=True)

        # Fail-safe: run fan at full speed.
        fan.value = 1.0
        time.sleep(5)
PYEOF

chmod +x "$FAN_SCRIPT"

echo "Creating systemd service..."

cat > "$SERVICE_FILE" <<'EOF'
[Unit]
Description=Raspberry Pi PWM Fan Controller
After=multi-user.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 /usr/local/bin/fan_controller.py
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
EOF

echo "Enabling service..."

systemctl daemon-reload
systemctl enable fan-controller.service
systemctl restart fan-controller.service

echo
echo "Fan controller installed."
echo
echo "Status:"
systemctl --no-pager --full status fan-controller.service || true
echo
echo "Useful commands:"
echo "  sudo systemctl status fan-controller"
echo "  sudo systemctl restart fan-controller"
echo "  sudo systemctl stop fan-controller"
echo "  journalctl -u fan-controller -f"
