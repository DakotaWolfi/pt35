#!/usr/bin/env python3
"""Add PT35 hardware A/B controls to the verified Pi4 NFC and spectrum GUIs.

PT35 custom cafe:4011 gamepad bridge maps A to F18 and B to F17.
Do not bind letter a/b: they are necessary in entry fields. No firmware changes.
Run on Pi5 after the original GUI has been recovered.
"""
import ast
from pathlib import Path
import shutil

base = Path.home() / "pt35-old-recovery/pt35-nfc-bench"
MARKER = "# PT35_PI5_AB_BUTTONS_V1"


def patch(path, anchor, replacement):
    if not path.is_file():
        raise SystemExit(f"Missing original application: {path}")
    text = path.read_text(encoding="utf-8")
    if MARKER in text:
        print(f"Already patched: {path}")
        return
    if text.count(anchor) != 1:
        raise SystemExit(f"Expected exactly one button-insertion anchor in {path}; refusing changes")
    updated = text.replace(anchor, replacement + "\n" + anchor, 1)
    ast.parse(updated, str(path))
    backup = path.with_name(path.name + ".before-ab.bak")
    if backup.exists():
        raise SystemExit(f"Refusing overwrite of existing backup: {backup}")
    shutil.copy2(path, backup)
    path.write_text(updated, encoding="utf-8")
    print(f"Patched {path}; backup {backup}")


nfc = base / "nfc/pt35_nfc_gui.py"
nfc_anchor = "        self.bind('<Configure>', self.resize_ui, add='+')"
nfc_keys = """        # PT35 hardware: A=F18 and B=F17 through cafe:4011 bridge.
        # PT35_PI5_AB_BUTTONS_V1
        self.bind('<F18>', self.pt35_a_button, add='+')
        self.bind('<F17>', self.pt35_b_button, add='+')
"""
patch(nfc, nfc_anchor, nfc_keys)

# Methods must be at class indentation, not inside __init__.
nfc_methods_anchor = "    def resize_ui(self, event):"
nfc_methods = """    def pt35_a_button(self, _event):
        # Only start/stop on the home screen; avoid accidental scanner starts
        # during archive, settings, and text editing.
        if not self.closing and self.screen == 'home' and self.ready and not self.stopping:
            self.toggle_scan()
        return 'break'

    def pt35_b_button(self, _event):
        if not self.closing:
            self.close()
        return 'break'

"""
nfc_source = nfc.read_text(encoding="utf-8")
if "    def pt35_a_button(" not in nfc_source:
    if nfc_source.count(nfc_methods_anchor) != 1:
        raise SystemExit("Could not locate original NFC resize_ui method; inspect manual backup")
    updated_nfc = nfc_source.replace(nfc_methods_anchor, nfc_methods + nfc_methods_anchor, 1)
    ast.parse(updated_nfc, str(nfc))
    nfc.write_text(updated_nfc, encoding="utf-8")

spectrum = base / "tools/as7341_gui.py"
spectrum_anchor = '        self.bind("<Escape>", lambda _: self.close())'
spectrum_keys = """        # PT35 hardware: A=F18 toggles spectral sampling, B=F17 exits.
        # PT35_PI5_AB_BUTTONS_V1
        self.bind("<F18>", lambda _: (self.toggle_pause(), "break")[1], add="+")
        self.bind("<F17>", lambda _: (self.close(), "break")[1], add="+")
"""
patch(spectrum, spectrum_anchor, spectrum_keys)
print("No keyboard firmware, system button mapping or UI layout changed.")
