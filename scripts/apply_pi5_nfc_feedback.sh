#!/usr/bin/env bash
# Activate updated Pi 5 NFC feedback without touching RF wiring, archive, or scanner backend.
set -Eeuo pipefail
[[ $(id -u) != 0 ]] || { echo "Run as jenna, without sudo" >&2; exit 1; }
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
GUI="$HOME/pt35-old-recovery/pt35-nfc-bench/nfc/pt35_nfc_gui.py"
[[ -f "$GUI" ]] || { echo "Recovered NFC GUI not found: $GUI" >&2; exit 1; }
python3 -m py_compile "$ROOT/services/pi5_led_daemon.py" "$ROOT/nfc/pi5_nfc_feedback.py" "$ROOT/nfc/pi5_nfc_haptics.py" "$ROOT/nfc/pi5_nfc_haptic_settings.py" "$ROOT/scripts/patch_pi5_nfc_haptic_settings.py"
if ! grep -q 'PT35_PI5_NFC_FEEDBACK_V1' "$GUI"; then
  echo "Recovered GUI is not yet patched. Attempting SHA-checked Pi5 patch..."
  python3 "$ROOT/scripts/patch_recovered_pi5_nfc.py"
fi
python3 "$ROOT/scripts/patch_pi5_nfc_haptic_settings.py"
grep -q 'from pi5_nfc_feedback import NFCLeds' "$GUI" || {
  echo "NFC GUI does not import Pi5 LED adapter; not making changes." >&2; exit 1; }
python3 -m py_compile "$GUI"
echo "NFC GUI: Pi5 feedback import confirmed"
echo "Close the NFC GUI before relaunching so it imports the latest adapters."
if systemctl --user is-active --quiet pt35-leds-pi5; then
  systemctl --user restart pt35-leds-pi5
  echo "Pi5 LED daemon restarted."
else
  echo "LED daemon not active; leaving its prior state unchanged."
fi
CTL="$HOME/.local/bin/pt35-ledctl"
if [[ -x "$CTL" ]]; then
  "$CTL" status || true
else
  echo "Missing $CTL: install Pi5 shell launcher first."
fi
if command -v lra_ctl >/dev/null 2>&1; then
  echo "Haptic utility available at $(command -v lra_ctl)"
elif [[ -x /usr/local/bin/lra_ctl ]]; then
  echo "Haptic utility available at /usr/local/bin/lra_ctl"
else
  echo "WARNING: lra_ctl not found; NFC haptics cannot play. Check DRV2605L installation."
fi
echo "Haptic cues are configurable in NFC Reader > Settings > Configure NFC vibrations."
echo "New cyan fill mode: pt35-ledctl nfc ; restore with pt35-ledctl idle"
