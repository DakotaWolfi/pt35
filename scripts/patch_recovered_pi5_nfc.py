#!/usr/bin/env python3
"""Reversibly patch the recovered, SHA-verified original PT35 NFC GUI for Pi5.

The original Pi4 GUI remains recognizable: touch layout, archives, navigation,
RF backend and other functionality are unchanged. No RF hardware accessed.
"""
from pathlib import Path
import hashlib
import shutil
import sys

path = Path.home() / "pt35-old-recovery/pt35-nfc-bench/nfc/pt35_nfc_gui.py"
original_sha = "02b0670fc089c5fb6c7734f4d451b6c7544b4e1bd46466b1f61e9912092f4ff3"
marker = "# PT35_PI5_NFC_FEEDBACK_V1"
if not path.is_file():
    raise SystemExit(f"Missing recovered original GUI: {path}")

original = path.read_bytes()
if marker.encode() in original:
    print("Pi5 NFC settings/feedback already applied; no changes made.")
    raise SystemExit(0)
actual = hashlib.sha256(original).hexdigest()
if actual != original_sha:
    raise SystemExit(
        f"Recovered GUI differs from confirmed Pi4 original ({actual}); "
        "refusing an uncertain patch. No files changed."
    )

s = original.decode("utf-8")
def swap(old, new, *, count=1):
    global s
    found = s.count(old)
    if found != count:
        raise SystemExit(f"Patch anchor mismatch: expected {count}, got {found}: {old[:120]!r}")
    s = s.replace(old, new, count)

swap("from nfc_led import NFCLeds",
     "from pi5_nfc_feedback import NFCLeds\n"
     "from pi5_nfc_haptics import notify as notify_haptic, new_scan as reset_haptic\n"
     + marker)

swap("led_effect='sweep', led_brightness='12')",
     "led_effect='sweep', led_brightness='12', haptic_enabled=False, haptic_effect='47')")

# Backward compatible JSON settings: new keys get defaults.
swap("        self.setting_edit(body, 'Onboard ST25DV UID', 'exclude_uid')\n"
     "        if self.latest_st:\n"
     "            Button(body, 'Use latest ST tag as onboard UID', lambda: self.change('exclude_uid', self.latest_st)).pack(fill='x', pady=3)\n", "")

swap("for title, key in (('Include onboard ST25DV', 'include_st'), ('Save all tags', 'save_all'),",
     "for title, key in (('Save all tags', 'save_all'),")

swap("        self.setting_edit(body, 'LED brightness', 'led_brightness')\n",
     "        self.setting_edit(body, 'LED brightness', 'led_brightness')\n"
     "        enabled = self.draft['haptic_enabled']\n"
     "        Button(body, f\"New tag vibration   {'ON' if enabled else 'OFF'}\",\n"
     "               lambda: self.change('haptic_enabled', not enabled), selected=enabled, anchor='w').pack(fill='x', pady=3)\n"
     "        self.options(body, 'Vibration pattern', 'haptic_effect',\n"
     "                     {'1': 'Strong click', '10': 'Sharp click', '47': 'Soft pulse'})\n")

# The old settings may remember include_st=True or an obsolete excluded onboard UID.
# Neither setting is passed to the scanner on this Pi5.
swap("        cmd.append(f\"--exclude-uid={values['exclude_uid']}\")\n", "")
swap("('save_all', '--save'), ('include_st', '--include-st')):",
     "('save_all', '--save')):")

swap("        if action == 'watch':\n            self.last_rf_bits = None",
     "        if action == 'watch':\n            reset_haptic()\n            self.last_rf_bits = None")

swap("        elif kind == 'tag':\n            self.read_progress = None\n            self.newest = item['record']",
     "        elif kind == 'tag':\n            self.read_progress = None\n"
     "            self.newest = item['record']\n"
     "            if not self.stopping:\n"
     "                notify_haptic(self.newest.get('uid'), self.settings.get('haptic_enabled', False),\n"
     "                              self.settings.get('haptic_effect', '47'))")

# Do not add I2C accesses on Tk thread. Existing GUI's calls to NFCLeds
# are redirected to the Pi5 Unix-socket adapter from the PT35 repository.
backup = path.with_name(path.name + ".pi4-original.bak")
if backup.exists():
    raise SystemExit(f"Backup already exists; inspect before overwriting: {backup}")
backup.write_bytes(original)
path.write_text(s, encoding="utf-8")
try:
    import ast
    ast.parse(s, filename=str(path))
except Exception:
    path.write_bytes(original)
    raise
print(f"Pi5 adapter patched: {path}")
print(f"Original backed up: {backup}")
print("Onboard-tag UI removed; optional new-tag haptics and Pi5 LED IPC added.")
