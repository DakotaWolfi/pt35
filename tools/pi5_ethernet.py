#!/usr/bin/env python3
"""PT35 Ethernet diagnostic screen and optional NetworkManager settings.

'status' is read-only, never reconfigures an interface or starts DHCP.
'configure' opens the installed NetworkManager text UI (nmtui).
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def run(*argv, timeout=4):
    try:
        result = subprocess.run(argv, capture_output=True, text=True,
                                timeout=timeout, check=False)
        return result.stdout.strip() if result.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def ethernet_interfaces():
    raw = run("ip", "-j", "link", "show")
    try:
        links = json.loads(raw) if raw else []
    except ValueError:
        links = []
    results = []
    for item in links:
        name = item.get("ifname", "")
        kind = (Path("/sys/class/net") / name / "type")
        if (name.startswith(("eth", "en")) and name != "lo") or (
                kind.is_file() and kind.read_text().strip() == "1"
                and not name.startswith(("wl", "wlan", "veth", "br", "docker"))):
            results.append(item)
    return results


def report():
    print("PT35 Ethernet diagnostics (read-only)")
    print("=" * 54)
    all_addrs = run("ip", "-j", "address", "show")
    try:
        addresses = {it["ifname"]: it for it in json.loads(all_addrs)}
    except (ValueError, KeyError, TypeError):
        addresses = {}
    links = ethernet_interfaces()
    if not links:
        print("No physical Ethernet interface found.")
        print("Check 'ip link' and USB/Ethernet adapter connections.")
        return

    active = run("nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status")
    if active:
        print("NetworkManager devices:")
        print(active)
        print()

    for interface in links:
        name = interface["ifname"]
        state = interface.get("operstate", "UNKNOWN")
        sysdir = Path("/sys/class/net") / name
        try:
            carrier = (sysdir / "carrier").read_text().strip() == "1"
            link = "YES" if carrier else "NO"
        except OSError:
            link = "unknown"
        print(f"Interface: {name}")
        print(f"  Link carrier: {link}    Operating state: {state}")
        print(f"  MAC: {interface.get('address', 'unknown')}")
        for addr in addresses.get(name, {}).get("addr_info", []):
            scope = addr.get("scope", "?")
            print(f"  {addr.get('family', '?')}: {addr.get('local', '?')}/{addr.get('prefixlen', '?')} ({scope})")
        if not addresses.get(name, {}).get("addr_info"):
            print("  IP address: none")
        print("  NM device:")
        details = run("nmcli", "-g", "GENERAL.STATE,GENERAL.CONNECTION,IP4.GATEWAY,IP4.DNS",
                      "device", "show", name)
        if details:
            for entry in details.splitlines():
                print("    " + entry)
        else:
            print("    NetworkManager unavailable or device unmanaged")
        if shutil.which("ethtool"):
            speed = run("ethtool", name)
            for line in speed.splitlines():
                if any(label in line for label in ("Speed:", "Duplex:", "Link detected:")):
                    print("  " + line.strip())
        print()

    print("IPv4 routes:")
    print(run("ip", "-4", "route") or "(none)")
    print()
    print("DHCP service processes (does not prove serving this port):")
    print(run("systemctl", "is-active", "dnsmasq") or "dnsmasq: not active/unknown")
    print(run("systemctl", "is-active", "isc-dhcp-server") or "isc-dhcp-server: not active/unknown")
    print()
    print("Diagnosis:")
    for item in links:
        name = item["ifname"]
        addr = addresses.get(name, {}).get("addr_info", [])
        has_v4 = any(a.get("family") == "inet" for a in addr)
        if not has_v4:
            print(f"  {name}: no IPv4 assigned. Direct-connect printers may need")
            print("  a manually configured address or a separately enabled DHCP server.")
        else:
            print(f"  {name}: IPv4 address present; check the printer's IP/subnet.")
    print()
    print("This screen makes NO network changes.")
    print("Press Enter to close.")
    try:
        input()
    except EOFError:
        pass


def configure():
    app = shutil.which("nmtui")
    if not app:
        print("NetworkManager's nmtui is not installed.")
        print("Use 'nmcli' or install the NetworkManager text UI.")
        input("Press Enter to close.")
        return 1
    return subprocess.call([app])


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("status", "configure"):
        raise SystemExit("Usage: pi5_ethernet.py status|configure")
    raise SystemExit(configure() if sys.argv[1] == "configure" else report())
