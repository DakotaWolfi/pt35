#!/usr/bin/env bash
# PT35 Pi 5 migration helper. No firmware flash, automatic reboot or legacy GPIO install.
set -Eeuo pipefail
case "${1:-}" in
  --check|--install-desktop) MODE="$1";;
  *) echo "Usage: bash scripts/migrate_pi5_desktop.sh --check|--install-desktop"; exit 2;;
esac
if [[ "$(id -u)" == 0 ]]; then echo "Run as your normal user, not sudo"; exit 1; fi
. /etc/os-release
echo "OS: ${PRETTY_NAME:-unknown} | $(uname -m) | $(uname -r)"
if [[ "${VERSION_CODENAME:-}" != trixie || "$(uname -m)" != aarch64 ]]; then
  echo "ERROR: PocketTerm35-OS requires Trixie 64-bit"; exit 1
fi
DIR="$HOME/pt35-migration-backups/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$DIR"
for p in /boot/firmware/config.txt /boot/firmware/cmdline.txt \
  /etc/motd /etc/update-motd.d /etc/lightdm \
  "$HOME/.config/autostart" "$HOME/.config/visionpi" \
  "$HOME/start-vision.sh" "$HOME/.config/labwc"; do
  [[ -e "$p" ]] || continue
  mkdir -p "$DIR/files$(dirname "$p")"
  cp -a "$p" "$DIR/files$p" 2>/dev/null || echo "Could not copy $p"
done
uname -a > "$DIR/kernel.txt"
dpkg-query -W > "$DIR/apt-packages.txt" 2>&1 || true
python3 -m pip freeze > "$DIR/python-packages.txt" 2>&1 || true
systemctl list-unit-files > "$DIR/system-services.txt" 2>&1 || true
systemctl --user list-unit-files > "$DIR/user-services.txt" 2>&1 || true
wlr-randr > "$DIR/display.txt" 2>&1 || true
lsusb > "$DIR/usb.txt" 2>&1 || true
cat /proc/bus/input/devices > "$DIR/input.txt" 2>&1 || true
echo "=== Display ==="; cat "$DIR/display.txt"
echo "=== Touch and keyboard ==="
grep -Ei 'pico|keyboard|goodix|touch|gt911' "$DIR/usb.txt" "$DIR/input.txt" || true
echo "=== Boot options ==="
grep -nE 'i2c_arm|waveshare|dwc2|vc4-kms' /boot/firmware/config.txt || true
echo "=== I2C bus ==="
if [[ -e /dev/i2c-1 ]]; then
  echo "I2C-1 present"
  if command -v i2cdetect >/dev/null; then
    echo "Driver-bound touchscreen may appear as UU"
    i2cdetect -y 1 || true
  fi
else
  echo "I2C-1 missing; touchscreen may need overlay/I2C setup"
fi
echo "=== Display managers ==="
systemctl is-active lightdm 2>/dev/null || true
systemctl is-active greetd 2>/dev/null || true
echo "Saved local configuration snapshot to $DIR"
echo "WARNING: This is NOT a full SD-card image and is stored on the same SD card."
if [[ "$MODE" == --check ]]; then echo "No system settings were changed."; exit 0; fi
echo "=== Download and dry-run third-party PocketTerm35-OS installer ==="
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
curl -fsSL https://raw.githubusercontent.com/therezor/PocketTerm35-OS/main/install.sh -o "$TMP/install.sh"
[[ -s "$TMP/install.sh" ]] || { echo "Download failed"; exit 1; }
sudo bash "$TMP/install.sh" --dry-run --no-ai
echo "The installer may modify the display manager, touchscreen overlay and login."
echo "No keyboard firmware will be flashed by this migration script."
read -r -p "Full SD-card image saved OFF this Pi? Type IMAGE-BACKED-UP: " ANSWER
[[ "$ANSWER" == IMAGE-BACKED-UP ]] || { echo "Cancelled"; exit 1; }
read -r -p "Proceed with desktop installation? Type INSTALL: " ANSWER
[[ "$ANSWER" == INSTALL ]] || { echo "Cancelled"; exit 1; }
sudo bash "$TMP/install.sh" --no-ai
echo "Done. Do not flash keyboard firmware yet. Check greetd/lightdm, then reboot manually."
