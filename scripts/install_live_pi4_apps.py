#!/usr/bin/env python3
"""Install exact Pi4 application bundle on Pi5 with backups and no private config.

Input: ~/pt35-pi4-apps/ (extracted using export_live_pi4_apps.py)
No services started, no credentials migrated, no system paths overwritten.
The existing working NFC reader is deliberately untouched.
"""
from pathlib import Path
import ast
import hashlib
import os
import shutil
import subprocess
import sys
from datetime import datetime

home = Path.home()
source = home / "pt35-pi4-apps"
state = home / ".local/state/pt35"
backup = home / "pt35-pi4-apps-backup" / datetime.now().strftime("%Y%m%d-%H%M%S")
bin_dir = home / ".local/bin"
app_dir = home / ".local/share/collarpet-link"
repo = Path(__file__).resolve().parents[1]

expected = {
    ".local/bin/cp-petmind-training": "6efa70e0a4bc3c0c66dc76280c5daadeca923e172ad9c5ceb3e61312225025b4",
    ".local/bin/pt35-eye-control": "6ea3100676c399b15e63de65e28d44bef55250d5987026ae64ac2cb1b180511b",
    ".local/share/collarpet-link/dashboard.py": "061a984dba41b34ca9ebd2bb04e4e6569dc4c84d8f2f34265a7cf99ab8d91215",
    "pt35-nfc-bench/tools/as7341_gui.py": "fccfcc9b053fee8b9978769bb4bf5195ccdb5166d9cf7bc2b338697fb44efd10",
}
missing = []
for relative, checksum in expected.items():
    path = source / relative
    if not path.is_file():
        missing.append(relative)
        continue
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    if sha != checksum:
        raise SystemExit(f"Checksum differs from Pi4 inventory: {relative} {sha}")
if missing:
    raise SystemExit("Missing original Pi4 files:\n  " + "\n  ".join(missing))
if os.geteuid() == 0:
    raise SystemExit("Run as regular PT35 user, not sudo.")

def install_file(src, dest):
    if not src.is_file() or src.is_symlink():
        return False
    # Never install arbitrary files: only allow the expected source's code/assets.
    data = src.read_bytes()
    if dest.exists() and dest.is_symlink():
        raise SystemExit(f"Refusing overwrite of symlink: {dest}")
    if dest.exists() and dest.read_bytes() == data:
        return True
    if dest.exists():
        old = backup / dest.relative_to(home)
        old.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(dest, old)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return True

# Copy required Collar Pet helper scripts to the original, expected runtime path.
# Do not copy any settings, SSH keys, archives or recorded captures.
helpers = source / ".local/share/collarpet-link"
for item in sorted(helpers.iterdir()):
    if item.is_file() and not item.is_symlink() and (item.suffix == ".py" or item.name == "collarpet-icon.png"):
        install_file(item, app_dir / item.name)

# Preserve original launcher semantics: the original Pi4 dashboard is a
# special launcher, and the original trainer is a standalone Python program.
for name in ("cp-dashboard", "cp-petmind-training", "pt35-eye-control"):
    install_file(source / ".local/bin" / name, bin_dir / name)
    (bin_dir / name).chmod(0o755)

# Spectrum launcher uses the newly recovered exact Pi4 file and helper modules
# from the bundle without replacing the already-working NFC sources.
spectrum = source / "pt35-nfc-bench/tools/as7341_gui.py"
wrapper = bin_dir / "pt35-original-spectrum"
script = f"""#!/usr/bin/env bash
set -e
export PYTHONPATH="{source}/pt35-nfc-bench/tools:{source}/pt35-nfc-bench/nfc:${{PYTHONPATH:-}}"
exec "$HOME/as7341-env/bin/python3" "{spectrum}" "$@"
"""
# Wrapper is not an untrusted SSH or shell command: generated from fixed local paths.
if wrapper.exists():
    old = backup / wrapper.relative_to(home)
    old.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(wrapper, old)
wrapper.write_text(script, encoding="utf-8")
wrapper.chmod(0o755)

print("Pi4 source installed locally, with backups when previous files differed.")
print(f"Previous files backed up under: {backup}")
print("No private config, SSH keys or credentials migrated.")
conf = home / ".config/collarpet/link.conf"
if not conf.is_file():
    print("WARNING: Collar Pet link.conf missing. Dashboard and trainer will not fully work until paired.")
if not (home / ".ssh/id_ed25519_collarpet").is_file():
    print("WARNING: Collar Pet pairing key absent. SSH controls need pairing before they work.")
print("Checking basic imports (does NOT start GUI, reader, BLE or Wi-Fi):")
for cmd in (
    ["/usr/bin/python3", "-c", "import tkinter, PIL; print('Tk/PIL OK')"],
    [str(home / "as7341-env/bin/python3"), "-c", "import tkinter; print('Spectrum Tk OK')"],
):
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
        print(" ", (result.stdout or result.stderr).strip().split("\n")[0], "exit", result.returncode)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(" ", exc)
print("Refresh FMI launcher with: bash scripts/install_pi5_shell.sh")
print("Start apps from PT35 graphical desktop, not from a DISPLAY-less SSH session.")
