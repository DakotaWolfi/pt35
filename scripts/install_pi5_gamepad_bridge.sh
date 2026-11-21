#!/usr/bin/env bash
# Install (not enable) a bridge for custom PT35 cafe:4011 keyboard+gamepad.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
[[ "$(id -u)" != 0 ]] || { echo "Run as login user, not root"; exit 1; }
if ! lsusb -d cafe:4011 | grep -q cafe:4011; then
    echo "ERROR: expected cafe:4011 custom PT35 Keyboard+Gamepad not found."
    exit 1
fi
if ! python3 -c "import evdev" >/dev/null 2>&1; then
    echo "Installing Debian python3-evdev for system Python."
    sudo apt-get install -y python3-evdev
fi
if [[ ! -e /dev/uinput ]]; then
    echo "/dev/uinput missing. Try: sudo modprobe uinput"
    exit 1
fi
echo "This bridge is for existing Pico SDK firmware and does not flash the RP2040."
echo "It maps gamepad A/B/X/Y/L/R/Start/Select into F18/F17/F15/F16/F13/F14/F22/F21."
echo "D-pad already emits arrow keys; it is intentionally not duplicated."
echo "Use the desktop's R button for mouse mode; avoid the firmware's Start+Select hold toggle."
sudo install -m755 "$ROOT/services/pi5_gamepad_bridge.py" /usr/local/bin/pt35-gamepad-bridge
sudo tee /etc/systemd/system/pt35-gamepad-bridge.service >/dev/null <<'UNIT'
[Unit]
Description=FMI PT35 custom cafe:4011 gamepad-to-shell input bridge
After=systemd-udev-settle.service

[Service]
Type=simple
ExecStart=/usr/bin/python3 /usr/local/bin/pt35-gamepad-bridge
Restart=on-failure
RestartSec=2
NoNewPrivileges=true
ProtectSystem=full
ProtectHome=true

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
echo "Installed but NOT started or enabled."
echo "First stop legacy user mapping, if present:"
echo "  systemctl --user disable --now pt35-buttons.service"
echo "Then bench-test bridge:"
echo "  sudo systemctl start pt35-gamepad-bridge"
echo "  sudo journalctl -u pt35-gamepad-bridge -n 20 --no-pager"
echo "If it works: sudo systemctl enable pt35-gamepad-bridge"
echo "To stop: sudo systemctl disable --now pt35-gamepad-bridge"
