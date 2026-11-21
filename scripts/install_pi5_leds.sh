#!/usr/bin/env bash
# Pi 5 RP1 PIO WS2812 installer. Install only; NEVER enable LEDs at boot.
# Intended 16 LEDs on BCM GPIO18; verify real wiring first!
set -Eeuo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [[ "$(id -u)" == 0 ]]; then echo "Run as your login user, without sudo"; exit 1; fi
echo "RP1 PIO status:"
if [[ ! -c /dev/pio0 ]]; then
  echo "ERROR: /dev/pio0 absent. Do not use the old Pi4 rpi_ws281x daemon here."
  echo "See Adafruit Pi5 NeoPixel instructions; confirm kernel/firmware support first."
  exit 1
fi
ls -l /dev/pio0
if [[ ! -r /dev/pio0 || ! -w /dev/pio0 ]]; then
  echo "ERROR: current user cannot access /dev/pio0."
  echo "Add udev rule per Adafruit instructions: SUBSYSTEM==\"*-pio\", GROUP=\"gpio\", MODE=\"0660\""
  echo "and ensure current user is in gpio group. Reload rules/reboot before retrying."
  exit 1
fi
if [[ "$(find /etc/systemd/system /etc/systemd/user "$HOME/.config/systemd/user" -name '*pt35*led*.service' -print 2>/dev/null | head -n1)" != "" ]]; then
 echo "Existing PT35 LED services found; inspect for conflicts before starting two LED owners:"
 find /etc/systemd/system /etc/systemd/user "$HOME/.config/systemd/user" -name '*pt35*led*.service' -print 2>/dev/null || true
fi
printf '\nOnly use this if LED DIN is wired to BCM GPIO18 (physical pin 12), 16 WS2812s.\n'
printf 'LED 5 V supply must have a common GND with the Pi; level shifting may be needed.\n'
read -r -p 'Type GPIO18-VERIFIED to install the user service (not start): ' CONFIRM
[[ "$CONFIRM" == "GPIO18-VERIFIED" ]] || { echo "Cancelled"; exit 1; }
command -v python3 >/dev/null
if ! python3 -m venv --help >/dev/null 2>&1; then
 echo "Install python3-venv: sudo apt install python3-venv"; exit 1
fi
VENV="$HOME/.local/share/pt35/led-venv"
mkdir -p "$(dirname "$VENV")" "$HOME/.config/systemd/user"
python3 -m venv --system-site-packages "$VENV"
"$VENV/bin/python" -m pip install --upgrade pip
"$VENV/bin/python" -m pip install Adafruit-Blinka Adafruit-Blinka-Raspberry-Pi5-Neopixel
SERVICE="$HOME/.config/systemd/user/pt35-leds-pi5.service"
cat > "$SERVICE" <<EOF
[Unit]
Description=PT35 Pi5 NeoPixels via RP1 PIO
After=graphical-session.target

[Service]
Type=simple
Environment=PT35_LED_COUNT=16
Environment=PT35_LED_GPIO=18
Environment=PT35_LED_BRIGHTNESS=0.15
ExecStart=$VENV/bin/python $ROOT/services/pi5_led_daemon.py
Restart=on-failure
RestartSec=2

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
echo "Service INSTALLED but NOT started or enabled."
echo "To start a bench test: systemctl --user start pt35-leds-pi5"
echo "Then: ~/.local/bin/pt35-ledctl status"
echo "      ~/.local/bin/pt35-ledctl color 0 10 0"
echo "      ~/.local/bin/pt35-ledctl off"
echo "Stop: systemctl --user stop pt35-leds-pi5"
echo "Only after a good test: systemctl --user enable pt35-leds-pi5"
