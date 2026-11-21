#!/usr/bin/env python3
"""Report PT35 battery status without changing sensor configuration.

Prefer Linux power_supply (used by the PocketTerm35-OS taskbar).
Fallback is the MAX17048 at I2C address 0x36, which is *not* a kernel bar feed.
"""
from pathlib import Path

def power_supply():
    root = Path("/sys/class/power_supply")
    for item in sorted(root.glob("*")):
        kind = item / "type"
        if not kind.is_file() or kind.read_text().strip() != "Battery":
            continue
        def get(key):
            f = item / key
            return f.read_text().strip() if f.exists() else None
        cap = get("capacity")
        raw = get("voltage_now")
        voltage = f"{int(raw)/1000000:.3f} V" if raw and raw.isdigit() else "unknown"
        print(f"Linux battery: {item.name}, {cap or '?'}%, {voltage}, status={get('status') or 'unknown'}")
        return True
    return False

def fallback_max17048():
    try:
        from smbus2 import SMBus
        with SMBus(1) as bus:
            # MAX17048 VCELL (0x02/03) LSB 78.125 uV.
            v = (bus.read_byte_data(0x36, 0x02) << 8) | bus.read_byte_data(0x36, 0x03)
            # SOC (0x04/05) 1/256 percent per LSB.
            s = (bus.read_byte_data(0x36, 0x04) << 8) | bus.read_byte_data(0x36, 0x05)
        print(f"MAX17048 I2C (diagnostic only): {s/256:.1f}%  {v*78.125/1000000:.3f} V")
        print("This is not connected to the desktop battery bar yet.")
    except Exception as exc:
        print(f"No readable gauge: {exc}")
        print("Install python3-smbus2 for direct diagnostics; check wiring and device variant.")

if __name__ == "__main__":
    if not power_supply():
        fallback_max17048()
