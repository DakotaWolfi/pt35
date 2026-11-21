#!/usr/bin/env python3
"""Inspect ACTUAL Pi4 launchers for Collar Pet, PetMind, Remote Eye and spectrum.
Read-only. Only reports executable paths and source checksums; no config, tokens,
network keys, archives or NFC dumps are opened or included.
"""
import hashlib
import os
from pathlib import Path
import re
import shlex

home = Path.home()
roots = [home / "Desktop", home / ".local/share/applications", home / ".local/bin",
         home / "pt35-nfc-bench/tools"]
keywords = ("collar", "petmind", "training", "trainer", "eye", "remote", "vision",
            "spectrum", "spectral", "as7341", "camera", "pt35-launcher")
seen = set()
def show(path):
    try:
        if not path.is_file() or path.is_symlink() and not path.resolve().is_relative_to(home):
            return
        if path in seen:
            return
        seen.add(path)
        data = path.read_bytes()
        # Avoid dumping code, comments, configs or secrets: only explicit desktop Exec
        if path.suffix == ".desktop":
            lines = data.decode(errors="replace").splitlines()
            name = next((x[5:] for x in lines if x.startswith("Name=")), "?")
            command = next((x[5:] for x in lines if x.startswith("Exec=")), "?")
            print(f"DESKTOP  {path}: {name}")
            print(f"  Exec: {command}")
            return
        if len(data) > 2_000_000:
            return
        print(f"SOURCE   {path}  {len(data)} bytes  sha256={hashlib.sha256(data).hexdigest()}")
        if path.parent == home / ".local/bin" and data.startswith(b"#!"):
            for line in data.decode(errors="replace").splitlines()[:30]:
                if re.search(r"\b(exec|python3?|source)\b", line) and not re.search(
                    r"(password|secret|token|key|private|ssh)", line, re.I):
                    print("  launcher: " + line.strip()[:180])
    except (OSError, ValueError):
        pass

for root in roots:
    if not root.exists():
        continue
    for path in sorted(root.iterdir()):
        if any(k in path.name.lower() for k in keywords):
            show(path)
    if root.name == "Desktop":
        for folder in sorted(root.iterdir()):
            if folder.is_dir() and any(k in folder.name.lower() for k in keywords):
                for path in sorted(folder.glob("*.desktop")):
                    show(path)

# Verify candidate source paths, but do not infer an executable from filename alone.
for relative in ("pt35-nfc-bench/tools/as7341_gui.py",
                 "pt35-nfc-bench/tools/pt35_launcher.py",
                 ".local/bin/cp-petmind-training",
                 ".local/bin/cp-dashboard",
                 ".local/bin/pt35-eye-control",
                 ".local/share/collarpet-link/dashboard.py",
                 "pt35-legacy-collarpet/pt35/training/cp-petmind-training",
                 "pt35-legacy-collarpet/pt35/link/dashboard.py"):
    show(home / relative)
print("Inspection only. No files copied, services started or settings changed.")
