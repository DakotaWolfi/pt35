#!/usr/bin/env python3
"""Bounded discovery of ST25DV16K on available Linux I2C adapters.

Default checks only 0x53 (user EEPROM) and 0x57 (system interface).
A positive i2cdetect response is NOT proof of device identity.
No writes to device memory. HDMI/DDC adapters excluded by default.
"""
import argparse
from pathlib import Path
import re
import subprocess
import sys
import time

SYSFS = Path("/sys/class/i2c-dev")
TARGETS = (0x53, 0x57)

def list_buses(root=SYSFS):
    result = []
    for entry in root.glob("i2c-*"):
        try:
            bus = int(entry.name.split("-")[1])
            name = (entry / "name").read_text().strip()
            dev = (entry / "device").resolve()
            result.append((bus, name, str(dev)))
        except (OSError, ValueError, IndexError):
            continue
    return sorted(result)

def scan_range(bus, start, end, timeout):
    # SMBus read-byte (not write quick). A kernel timeout is still possible.
    cmd = ["i2cdetect", "-y", "-r", str(bus), f"0x{start:02x}", f"0x{end:02x}"]
    try:
        proc = subprocess.run(cmd, text=True, capture_output=True,
                              timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return "TIMEOUT", []
    except FileNotFoundError:
        return "MISSING_TOOL", []
    if proc.returncode != 0:
        return "ERROR: " + proc.stderr.strip()[:180], []
    # i2cdetect table entries may be --, UU, or a two-hex-digit address.
    found = []
    for row in proc.stdout.splitlines():
        if not re.match(r"^[0-7]0:", row.strip()):
            continue
        for part in row.split(":", 1)[1].split():
            if part == "UU":
                found.append("UU")
                continue
            if re.fullmatch(r"[0-7][0-9a-f]", part):
                address = int(part,16)
                if start <= address <= end:
                    found.append(f"0x{address:02X}")
    return "OK", found

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--full", action="store_true",
                    help="Dangerous/broad scan 0x08-0x77 (not recommended on unstable bus)")
    ap.add_argument("--include-hdmi", action="store_true",
                    help="Also probe HDMI/DDC adapters (usually unnecessary)")
    ap.add_argument("--timeout",type=float,default=3.0,
                    help="Per probe timeout in seconds (default: 3)")
    args=ap.parse_args()
    if args.timeout <= 0 or args.timeout > 15:
        ap.error("timeout must be between 0 and 15 seconds")
    buses=list_buses()
    if not buses:
        print("No I2C adapters listed under /sys/class/i2c-dev")
        return 1
    print(f"Found {len(buses)} I2C adapter(s). Read-byte probes; no EEPROM writes.")
    if args.full:
        print("WARNING: full scans may disrupt devices or flood kernel logs.")
    for bus,name,controller in buses:
        print(f"\nBus {bus}: {name}\n  Controller: {controller}",flush=True)
        if ("hdmi" in name.lower() or "hdmi" in controller.lower()) and not args.include_hdmi:
            print("  SKIPPED: HDMI/DDC controller")
            continue
        ranges=[(0x08,0x77)] if args.full else [(a,a) for a in TARGETS]
        for lo,hi in ranges:
            print(f"  Probing 0x{lo:02X}-0x{hi:02X}...",end=" ",flush=True)
            status,found=scan_range(bus,lo,hi,args.timeout)
            print(f"{status}; response(s): {', '.join(found) if found else 'none'}",flush=True)
        if bus == 9:
            print("  NOTE: bus 9 is 0x2519000.twi, previously logged SCL errors")
    print("\nST25DV16K usually responds at 0x53 and 0x57. "
          "Confirm physical wiring and bus mapping before attempting writes.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
