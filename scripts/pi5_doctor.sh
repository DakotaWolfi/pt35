#!/usr/bin/env bash
# Safe, read-only PT35 Pi 5 setup report.
set -u
status=0
say() { printf '%-30s %s\n' "$1" "$2"; }
check_file() { if [[ -e "$2" ]]; then say "$1" "OK"; else say "$1" "MISSING ($2)"; status=1; fi; }
echo "===== PT35 Pi 5 installation report ====="
if [[ -r /proc/device-tree/model ]]; then
  say "Board" "$(tr -d '\0' < /proc/device-tree/model)"
else
  say "Board" "Not detectable (non-Pi host)"
fi
say "OS" "$(. /etc/os-release; echo "${PRETTY_NAME:-unknown}")"
say "Kernel" "$(uname -r)"
if command -v vcgencmd >/dev/null 2>&1; then
  say "Throttle flags" "$(vcgencmd get_throttled 2>&1)"
else say "Throttle flags" "vcgencmd unavailable"; fi
check_file "Button daemon" "$HOME/.local/bin/pt35-buttons.py"
check_file "NFC scanner" "$HOME/pt35-nfc/pt35_nfc.py"
check_file "NFC GUI" "$HOME/.local/bin/pt35-nfc-gui"
check_file "Collar Pet dashboard" "$HOME/.local/bin/cp-dashboard"
check_file "PetMind training UI" "$HOME/.local/bin/cp-petmind-training"
check_file "Collar Pet source" "$HOME/src/collar-pet/.git"
check_file "Vision source" "$HOME/src/vision_pi/.git"
if command -v i2cdetect >/dev/null 2>&1 && [[ -e /dev/i2c-1 ]]; then
  echo
  echo "I2C bus 1 (address scan; only run on connected, stable 3.3 V hardware):"
  i2cdetect -y 1 || status=1
else
  say "I2C bus 1" "NOT READY (enable I2C and reboot)"
  status=1
fi
echo
if systemctl --user is-enabled pt35-buttons.service >/dev/null 2>&1; then
  say "Buttons user service" "$(systemctl --user is-active pt35-buttons.service)"
else
  say "Buttons user service" "STAGED, NOT ENABLED"
fi
if systemctl is-enabled pt35-leds.service >/dev/null 2>&1; then
  say "Pi4 legacy LEDs" "WARNING: enabled; Pi 5 backend not validated"
  status=1
else
  say "Pi5 LEDs" "NOT YET IMPLEMENTED"
fi
say "MAX17048 Pi5 overlay" "NOT YET VALIDATED"
say "Pi5 Active Cooler" "Uses firmware fan control"
say "Remote Eye integration" "Requires existing local controller inventory"
echo
echo "NOTE: Missing optional hardware integrations are not installed automatically."
exit "$status"
