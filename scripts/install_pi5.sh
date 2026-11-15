#!/usr/bin/env bash
# PT35 Raspberry Pi 5 staged install. Run as the normal desktop user.
# Deliberately does not install the Pi 4 WS281x daemon, legacy PWM fan,
# or a custom MAX17048 overlay until each has been verified on hardware.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[[ "${EUID}" -ne 0 ]] || { echo "Run as your normal user (not sudo)." >&2; exit 1; }
[[ -r /proc/device-tree/model ]] || { echo "Cannot detect board" >&2; exit 1; }
MODEL="$(tr -d '\0' </proc/device-tree/model)"
[[ "$MODEL" == *"Raspberry Pi 5"* ]] || { echo "This installer requires Raspberry Pi 5, found: $MODEL" >&2; exit 1; }
[[ -f /etc/os-release ]] && source /etc/os-release
[[ "${VERSION_CODENAME:-}" == "trixie" ]] || { echo "Use a clean Raspberry Pi OS Trixie 64-bit image." >&2; exit 1; }
[[ "$(dpkg --print-architecture)" == "arm64" ]] || { echo "64-bit arm64 OS required." >&2; exit 1; }
echo "PT35 Pi 5 staged install on $MODEL"
sudo apt-get update
sudo apt-get install -y git python3 python3-evdev python3-smbus2 python3-lgpio python3-gpiozero python3-tk i2c-tools raspi-utils xdotool wtype
CONFIG=/boot/firmware/config.txt
[[ -f "$CONFIG" ]] || { echo "Missing $CONFIG" >&2; exit 1; }
if ! grep -Eq '^[[:space:]]*dtparam=i2c_arm=on([[:space:]]*(#.*)?)?$' "$CONFIG"; then
  sudo cp -a "$CONFIG" "$CONFIG.pt35-backup-$(date +%Y%m%d-%H%M%S)"
  echo 'dtparam=i2c_arm=on' | sudo tee -a "$CONFIG" >/dev/null
  echo "Enabled I2C in boot config; reboot before hardware tests."
fi
mkdir -p "$HOME/.local/bin" "$HOME/.config/systemd/user" "$HOME/pt35-nfc/archive"
install -m 0755 "$ROOT/services/pt35-buttons.py" "$HOME/.local/bin/pt35-buttons.py"
install -m 0644 "$ROOT/systemd/user/pt35-buttons.service" "$HOME/.config/systemd/user/pt35-buttons.service"
# Copy tools without clobbering any local archives/known-tag records.
for file in pt35_nfc.py nfcv_scan.py nfcv_dump.py; do
  [[ -e "$HOME/pt35-nfc/$file" ]] || cp "$ROOT/nfc/$file" "$HOME/pt35-nfc/$file"
done
bash "$ROOT/scripts/install_nfc_gui.sh"
systemctl --user daemon-reload
echo
echo "STAGED, not automatically started:"
echo "  systemctl --user enable --now pt35-buttons.service"
echo "  (Run only after USB gamepad and UI have been checked.)"
echo
echo "Not installed: Pi 4 LED DMA service, custom MAX17048 overlay, legacy fan"
echo "Not installed: Remote Eye controller (owned by vision_pi repo)"
echo "Not enabled: USB/I2C-dependent daemons, until peripherals are connected"
echo "Official Pi 5 Active Cooler remains firmware controlled."
echo "Reboot, then check: i2cdetect -y 1; ls /dev/input/by-id/; vcgencmd get_throttled"
