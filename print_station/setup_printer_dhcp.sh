#!/usr/bin/env bash
# Opt-in DHCP for isolated direct Epson Ethernet. Does not route to Wi-Fi.
set -euo pipefail
IFACE=enx9cebe8ec46e1
if [[ "${1:-}" != "--apply" ]]; then
  echo "Preview: configure NetworkManager static 10.88.77.1/24, dnsmasq DHCP ONLY on $IFACE."
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
# NetworkManager owns this USB NIC. A one-shot 'ip address add' loses races
# against NM reactivation, cable reconnects, and USB device re-enumeration.
if ! command -v nmcli >/dev/null; then
  echo "NetworkManager/nmcli required for persistent printer Ethernet configuration" >&2
  exit 1
fi
CONN="$(nmcli -g GENERAL.CONNECTION device show "$IFACE" | head -n 1)"
if [[ -z "$CONN" || "$CONN" == "--" ]]; then
  echo "No active NetworkManager connection on $IFACE; configure it first" >&2
  exit 1
fi
echo "Configuring NetworkManager connection: $CONN"
nmcli connection modify "$CONN" \
  connection.interface-name "$IFACE" \
  connection.autoconnect yes \
  ipv4.method manual \
  ipv4.addresses 10.88.77.1/24 \
  ipv4.gateway "" \
  ipv4.dns "" \
  ipv4.never-default yes \
  ipv4.link-local disabled \
  ipv6.method disabled
# Remove obsolete one-shot assignment and dependency override from older installs.
systemctl disable --now fmi-printer-lan.service 2>/dev/null || true
rm -f /etc/systemd/system/dnsmasq.service.d/fmi-printer-lan.conf
# Restart of the wired NM connection does not touch Wi-Fi.
nmcli connection up "$CONN" ifname "$IFACE"
ip -4 addr show dev "$IFACE" | grep -q 'inet 10.88.77.1/24' || {
  echo "Static printer subnet is not active on $IFACE" >&2
  exit 1
}
systemctl daemon-reload
dnsmasq --test
systemctl daemon-reload
systemctl enable dnsmasq.service
systemctl restart dnsmasq.service
echo "Done. Epson MAC f8:25:51:79:eb:5f reserved 10.88.77.30. Restart printer for DHCP."
echo "Check: sudo journalctl -u dnsmasq -n 60 --no-pager"
