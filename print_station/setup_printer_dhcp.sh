#!/usr/bin/env bash
# Opt-in DHCP for isolated direct Epson Ethernet. Does not route to Wi-Fi.
set -euo pipefail
IFACE=enx9cebe8ec46e1
if [[ "${1:-}" != "--apply" ]]; then
  echo "Preview: install dnsmasq, bind DHCP ONLY to $IFACE, add 10.88.77.1/24."
  echo "Pool: 10.88.77.20-40; Epson reserved 10.88.77.30. No Wi-Fi, DNS or NAT."
  echo "Run: sudo bash setup_printer_dhcp.sh --apply"
  exit 0
fi
[[ "$EUID" -eq 0 ]] || { echo "Use sudo"; exit 1; }
[[ -d "/sys/class/net/$IFACE" ]] || { echo "Missing interface $IFACE"; exit 1; }
command -v ip >/dev/null || { echo "Install iproute2"; exit 1; }
DEBIAN_FRONTEND=noninteractive apt-get install -y dnsmasq
systemctl stop dnsmasq.service || true
mkdir -p /etc/dnsmasq.d /usr/local/sbin
cat >/etc/dnsmasq.d/fmi-printer-lan.conf <<EOF
port=0
interface=$IFACE
bind-dynamic
dhcp-range=10.88.77.20,10.88.77.40,255.255.255.0,12h
dhcp-host=f8:25:51:79:eb:5f,10.88.77.30,infinite
dhcp-authoritative
dhcp-option=option:router
dhcp-option=option:dns-server
log-dhcp
EOF
cat >/usr/local/sbin/fmi-printer-ip <<EOF
#!/bin/sh
set -eu
if ! ip -4 address show dev "$IFACE" | grep -q "10.88.77.1/24"; then
  ip address add 10.88.77.1/24 dev "$IFACE"
fi
ip link set "$IFACE" up
EOF
chmod 755 /usr/local/sbin/fmi-printer-ip
cat >/etc/systemd/system/fmi-printer-lan.service <<EOF
[Unit]
Description=FMI isolated wired printer IP
After=network.target
Before=dnsmasq.service
[Service]
Type=oneshot
ExecStart=/usr/local/sbin/fmi-printer-ip
RemainAfterExit=yes
[Install]
WantedBy=multi-user.target
EOF
mkdir -p /etc/systemd/system/dnsmasq.service.d
cat >/etc/systemd/system/dnsmasq.service.d/fmi-printer-lan.conf <<EOF
[Unit]
Requires=fmi-printer-lan.service
After=fmi-printer-lan.service
EOF
dnsmasq --test
systemctl daemon-reload
systemctl enable --now fmi-printer-lan.service
systemctl enable --now dnsmasq.service
echo "Done. Epson MAC f8:25:51:79:eb:5f reserved 10.88.77.30. Restart printer for DHCP."
echo "Check: sudo journalctl -u dnsmasq -n 60 --no-pager"
