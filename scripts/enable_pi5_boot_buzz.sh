#!/usr/bin/env bash
# Enable the original Pi4 boot buzz on the Pi5 LED daemon (DRV2605L).
# Keeps the 24 LED setup and idle animation unchanged.
set -Eeuo pipefail
[[ "$(id -u)" != 0 ]] || { echo "Run as PT35 user, not sudo"; exit 1; }
UNIT="$HOME/.config/systemd/user/pt35-leds-pi5.service"
[[ -f "$UNIT" ]] || { echo "Pi5 LED service not installed."; exit 1; }
CTL="/usr/local/bin/lra_ctl"
if [[ ! -x "$CTL" ]]; then
  echo "DRV2605L controller not installed at $CTL."
  echo "Inspect the I2C 0x5A device before using scripts/setup_lra.sh."
  exit 1
fi
echo "Checking DRV2605L (will not trigger buzz yet)..."
if ! "$CTL" status; then
  echo "DRV2605L unavailable for current user; fix I2C permissions/wiring before enabling."
  exit 1
fi
printf '\nTesting original first buzz (effect 1)...\n'
"$CTL" play 1
sleep 0.4
printf 'Testing original second buzz (effect 10)...\n'
"$CTL" play 10
printf '\nIf both pulses felt correct, type BUZZ to enable on LED daemon startup: '
read -r reply
[[ "$reply" == BUZZ ]] || { echo "No configuration changed."; exit 0; }
DROP="$HOME/.config/systemd/user/pt35-leds-pi5.service.d"
mkdir -p "$DROP"
printf '[Service]\nEnvironment=PT35_LED_BOOT_HAPTIC=1\n' > "$DROP/30-boot-haptic.conf"
systemctl --user daemon-reload
systemctl --user restart pt35-leds-pi5
echo "Startup haptic enabled; existing LED count and animation preserved."
echo "On next login/service startup, effect 1 then 10 will play once."
echo "Check: journalctl --user -u pt35-leds-pi5 -n 25 --no-pager"
