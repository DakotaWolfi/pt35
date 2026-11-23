#!/usr/bin/env bash
set -euo pipefail
if [[ $(id -u) != 0 ]]; then echo 'Run with sudo bash install.sh'; exit 1; fi
SRC="$(cd "$(dirname "$0")" && pwd)"
OWNER="${SUDO_USER:-$(logname 2>/dev/null || echo pi)}"
apt-get update
apt-get install -y cups cups-client cups-filters python3-venv python3-pip fonts-dejavu-core dnsmasq-base sudo
install -d -m755 /opt/pt35-receipt-host/templates
install -m644 "$SRC/app.py" "$SRC/requirements.txt" /opt/pt35-receipt-host/
install -o root -g root -m755 "$SRC/printer-ethernet.sh" /usr/local/sbin/pt35-printer-ethernet
install -m644 "$SRC/templates/index.html" /opt/pt35-receipt-host/templates/
python3 -m venv /opt/pt35-receipt-host/.venv
/opt/pt35-receipt-host/.venv/bin/pip install -r /opt/pt35-receipt-host/requirements.txt
if [[ ! -f /etc/pt35-receipt-host.conf ]]; then
  cat > /etc/pt35-receipt-host.conf <<'CONF'
PT35_BIND=127.0.0.1
PT35_PORT=8765
PT35_PRINTER=
PT35_WIDTH_DOTS=576
# LAN access: use PT35_BIND=0.0.0.0 AND set a strong PT35_PASSWORD.
PT35_PASSWORD=
CONF
  chmod 600 /etc/pt35-receipt-host.conf
fi
# Install per-user system service; do not touch existing PT35 services.
sed "s/^User=%i$/User=$OWNER/" "$SRC/systemd/pt35-receipt-host.service" >/etc/systemd/system/pt35-receipt-host.service
# Permit the web service user to run only these two predefined root operations.
# The helper itself has no arbitrary command arguments.
SUDOERS_TMP="$(mktemp)"
printf '%s\n' "$OWNER ALL=(root) NOPASSWD: /usr/local/sbin/pt35-printer-ethernet on, /usr/local/sbin/pt35-printer-ethernet off" > "$SUDOERS_TMP"
visudo -cf "$SUDOERS_TMP"
install -o root -g root -m440 "$SUDOERS_TMP" /etc/sudoers.d/pt35-receipt-host
rm -f "$SUDOERS_TMP"
systemctl daemon-reload
systemctl enable --now cups.service
systemctl enable --now pt35-receipt-host.service
printf '\nInstalled. Local UI: http://127.0.0.1:8765\nSet printer and LAN settings in /etc/pt35-receipt-host.conf\nThen sudo systemctl restart pt35-receipt-host\n'
