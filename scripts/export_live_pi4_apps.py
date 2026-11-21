#!/usr/bin/env python3
"""Bundle exact LIVE Pi4 PT35 application sources for local transfer.

Does not include secrets, pairing keys, user settings, archives, recordings,
NFC tag dumps or wireless credentials. Does not execute any captured scripts.
The resulting tarball stays on the Pi4; it is NOT uploaded to GitHub.
"""
from pathlib import Path
import hashlib
import json
import tarfile

home = Path.home()
output = home / "pt35-pi4-apps-recovery.tar.gz"
paths = [
    ".local/bin/cp-dashboard",
    ".local/bin/cp-petmind-training",
    ".local/bin/pt35-eye-control",
    ".local/bin/pt35-launcher",
    ".local/bin/pt35-nfc-gui",
    "pt35-nfc-bench/tools/as7341_gui.py",
    "pt35-nfc-bench/tools/pt35_launcher.py",
    "pt35-nfc-bench/tools/pt35_tools.py",
    "pt35-nfc-bench/nfc/nfc_touch.py",
    ".local/share/collarpet-link/dashboard.py",
    ".local/share/collarpet-link/discover.py",
    ".local/share/collarpet-link/cp_ble_scan.py",
    ".local/share/collarpet-link/ble_scan.py",
    ".local/share/collarpet-link/collarpet-icon.png",
]
# No arbitrary directory traversal, no private config or hidden credentials.
# Include the app's helper Python code, if present.
helpers = home / ".local/share/collarpet-link"
if helpers.is_dir():
    for item in helpers.iterdir():
        if item.is_file() and item.suffix == ".py":
            rel = item.relative_to(home).as_posix()
            if rel not in paths:
                paths.append(rel)

checksums = {}
with tarfile.open(output, "w:gz", format=tarfile.PAX_FORMAT) as archive:
    for rel in sorted(paths):
        path = home / rel
        if not path.is_file() or path.is_symlink():
            continue
        if path.stat().st_size > 3_000_000:
            print("Skipped unusually large file:", rel)
            continue
        raw = path.read_bytes()
        checksums[rel] = hashlib.sha256(raw).hexdigest()
        archive.add(path, arcname=rel, recursive=False)
        print(f"{rel}   {len(raw)} bytes  {checksums[rel][:12]}")
    manifest = output.with_suffix(".manifest.json")
    manifest.write_text(json.dumps(checksums, indent=2) + "\n", encoding="utf-8")

print(f"\nBundle: {output}")
print(f"Manifest: {manifest}")
print("Private config (~/.config/collarpet), pairing keys and captures NOT included.")
print("Transfer bundle manually to Pi5 for inspection; do NOT extract over your live home.")
