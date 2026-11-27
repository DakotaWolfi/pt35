#!/usr/bin/env bash
# Restricted root helper for the PT35's dedicated printer Ethernet port.
set -euo pipefail
export LC_ALL=C
ACTION="${1:-}"
IFACE="eth0"
PROFILE="PT35 Printer Ethernet"
ADDRESS="192.168.77.1/24"

[[ "$#" -eq 1 && ( "$ACTION" == "on" || "$ACTION" == "off" || "$ACTION" == "status" ) ]] || {
  echo "Usage: pt35-printer-ethernet {on|off|status}" >&2; exit 2;
}

command -v nmcli >/dev/null || { echo "NetworkManager/nmcli missing" >&2; exit 1; }
systemctl is-active --quiet NetworkManager || { echo "NetworkManager is not active" >&2; exit 1; }
nmcli -g GENERAL.TYPE device show "$IFACE" 2>/dev/null | grep -qx ethernet || {
  echo "$IFACE is not an Ethernet interface managed by NetworkManager" >&2; exit 1;
}
active() {
  nmcli -t -f NAME connection show --active | grep -Fxq "$PROFILE"
}
case "$ACTION" in
  status)
    if active; then echo on; else echo off; fi
    exit 0 ;;
  off)
    if active; then nmcli connection down "$PROFILE"; fi
    echo "Printer Ethernet DHCP off on $IFACE"
    exit 0 ;;
  on)
    if active; then echo "Printer Ethernet DHCP already on ($ADDRESS)"; exit 0; fi
    # Never replace an existing usable Ethernet address or connection by surprise.
    if ip -4 -o address show dev "$IFACE" scope global | grep -q .; then
      echo "Refusing: $IFACE already has an IPv4 address. Disconnect its current profile first." >&2
      exit 1
    fi
    current="$(nmcli -g GENERAL.CONNECTION device show "$IFACE" 2>/dev/null || true)"
    if [[ -n "$current" && "$current" != "--" && "$current" != "$PROFILE" ]]; then
      echo "Refusing: $IFACE already uses connection '$current'. Disconnect it first." >&2
      exit 1
    fi
    if ! nmcli -g connection.id connection show "$PROFILE" >/dev/null 2>&1; then
      nmcli connection add type ethernet ifname "$IFACE" con-name "$PROFILE" \
        connection.autoconnect no ipv4.method shared ipv4.addresses "$ADDRESS" \
        ipv4.never-default yes ipv6.method disabled
    fi
    # Profile is application-owned: keep autoconnect disabled even after a reboot.
    nmcli connection modify "$PROFILE" connection.autoconnect no \
      connection.interface-name "$IFACE" ipv4.method shared ipv4.addresses "$ADDRESS" \
      ipv4.never-default yes ipv6.method disabled
    nmcli connection up "$PROFILE" ifname "$IFACE"
    echo "Printer Ethernet DHCP on: $IFACE = $ADDRESS"
    ;;
esac
