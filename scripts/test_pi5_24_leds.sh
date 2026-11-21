#!/usr/bin/env bash
# Bench-test 3 x 8 WS2812 on Pi5 before mounting. Uses existing LED daemon.
set -Eeuo pipefail
[[ "$(id -u)" != 0 ]] || { echo "Run as PT35 user (no sudo)"; exit 1; }
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DROP="$HOME/.config/systemd/user/pt35-leds-pi5.service.d"
UNIT="$HOME/.config/systemd/user/pt35-leds-pi5.service"
LED="$HOME/.local/bin/pt35-ledctl"
[[ -f "$UNIT" && -x "$LED" ]] || { echo "LED service or controller missing. No changes made."; exit 1; }
[[ -c /dev/pio0 ]] || { echo "/dev/pio0 missing. Do not attempt Pi4 ws281x driver."; exit 1; }
echo "Test assumes 24 LEDs in a SINGLE serial chain, DIN on GPIO18, shared ground."
echo "Only run after checking power and DIN/DOUT arrows; unplug power before rewiring."
read -r -p 'Type 24-VERIFIED to reconfigure the daemon for 24 LEDs: ' ANSWER
[[ "$ANSWER" == 24-VERIFIED ]] || exit 1
mkdir -p "$DROP"
printf '[Service]\nEnvironment=PT35_LED_COUNT=24\n' > "$DROP/20-count.conf"
systemctl --user daemon-reload
systemctl --user restart pt35-leds-pi5
ready=0
for _ in {1..40}; do
  if output="$("$LED" status 2>/dev/null)" && [[ "$output" == *"count=24"* ]]; then
    ready=1
    break
  fi
  if ! systemctl --user is-active --quiet pt35-leds-pi5; then break; fi
  sleep 0.25
done
if [[ "$ready" != 1 ]]; then
  echo "ERROR: Pi5 LED daemon is not responding with count=24." >&2
  systemctl --user status pt35-leds-pi5 --no-pager -l || true
  journalctl --user -u pt35-leds-pi5 -n 35 --no-pager || true
  exit 1
fi
echo "$output"
echo "Each row of eight LEDs should light separately: first RED, second GREEN, third BLUE."
for n in 1 2 3; do
  echo "Row $n:"
  "$LED" segment "$n"
  sleep 2
done
echo "Now walking through pixels 1..24 (one LED at a time)"
for n in $(seq 1 24); do
  printf 'LED %2d of 24\n' "$n"
  "$LED" pixel "$n" 0 0 95
  sleep 0.35
done
echo "Switching back to original Pi4 breathing animation."
"$LED" idle
echo "If the test stops at LED 8 or 16, check the DATA OUT -> DATA IN junction of that row."
echo "The display proves command delivery; inspect the LEDs visually for actual function."
