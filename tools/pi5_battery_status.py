#!/usr/bin/env python3
"""Read-only battery diagnostics for the PT35 MAX17048 kernel driver."""
from pathlib import Path
from datetime import datetime

ROOT = Path("/sys/class/power_supply")


def read(path, name):
    try:
        return (path / name).read_text().strip()
    except (FileNotFoundError, OSError):
        return None


def detail(path):
    print(f"Device: {path.name}")
    print(f"Type: {read(path, 'type') or '?'}")
    for attr in ("model_name", "manufacturer", "capacity", "capacity_level", "status",
                 "voltage_now", "voltage_min_design", "voltage_max_design",
                 "charge_now", "current_now", "online"):
        raw = read(path, attr)
        if raw is None:
            continue
        if attr.startswith("voltage_") and raw.lstrip("-").isdigit():
            print(f"  {attr}: {int(raw) / 1_000_000:.4f} V  (raw {raw} µV)")
        elif attr == "current_now" and raw.lstrip("-").isdigit():
            print(f"  {attr}: {int(raw) / 1_000_000:.3f} A")
        else:
            print(f"  {attr}: {raw}")


def main():
    print(f"PT35 Battery Diagnostics — {datetime.now().astimezone():%Y-%m-%d %H:%M:%S %Z}")
    print("=" * 59)
    if not ROOT.is_dir():
        print("/sys/class/power_supply not present")
        return
    found = False
    for p in sorted(ROOT.iterdir()):
        if p.is_dir() and read(p, "type") in ("Battery", "Mains", "USB", "USB_C", "USB_PD"):
            found = True
            detail(p)
            print()
    if not found:
        print("No battery/charger power_supply devices exposed by Linux.")
    print("MAX17048 SOC is a model-based estimate, not a charger termination signal.")
    print("If the charger says full at 89%, measure cell voltage and identify the pack/charger.")
    print("A MAX17048 is intended for one cell. Do not attach it across a 2S pack.")


if __name__ == "__main__":
    main()
