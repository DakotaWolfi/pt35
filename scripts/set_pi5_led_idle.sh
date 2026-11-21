#!/usr/bin/env bash
# Configure existing Pi5 LED service for gentle idle animation at startup.
# Does not reinstall packages, touch GPIO assignments, or alter NFC.
set -Eeuo pipefail
[[ $(id -u) != 0 ]] || { echo "Run as jenna, without sudo."; exit 1; }
service="$HOME/.config/systemd/user/pt35-leds-pi5.service"
[[ -f "$service" ]] || { echo "LED service not installed; no changes made."; exit 1; }
mode="${1:-idle}"
case "$mode" in idle|rainbow|off) ;; *) echo "Usage: bash scripts/set_pi5_led_idle.sh idle|rainbow|off"; exit 2;; esac
mkdir -p "$HOME/.config/systemd/user/pt35-leds-pi5.service.d"
cat > "$HOME/.config/systemd/user/pt35-leds-pi5.service.d/10-idle.conf" <<EOF
[Service]
Environment=PT35_LED_IDLE_MODE=$mode
EOF
systemctl --user daemon-reload
systemctl --user enable pt35-leds-pi5
systemctl --user restart pt35-leds-pi5
# A socket file may exist before listen() or may be stale. Check a real reply,
# not just the presence of the filesystem entry.
ready=0
for _ in {1..30}; do
    if "$HOME/.local/bin/pt35-ledctl" status >/dev/null 2>&1; then
        ready=1
        break
    fi
    if ! systemctl --user is-active --quiet pt35-leds-pi5; then
        break
    fi
    sleep 0.2
done
if [[ "$ready" != 1 ]]; then
    echo "LED daemon did not become responsive; startup mode is configured but hardware is NOT confirmed." >&2
    systemctl --user status pt35-leds-pi5 --no-pager -l || true
    journalctl --user -u pt35-leds-pi5 -n 35 --no-pager || true
    exit 1
fi
"$HOME/.local/bin/pt35-ledctl" status
echo "Startup LED default: $mode; service enabled for user login."
echo "NFC reader temporary LED effects can override this while scanning."
