#!/usr/bin/env python3
"""Repair the optional NFC tag-information GUI patch safely.

Supports either original unpatched recovered GUI, V1-patched GUI, or GUI
restored with rollback script. Never changes RF drivers, archives or settings.
"""
import ast
import datetime
import os
import sys
from pathlib import Path

TARGET = Path.home() / "pt35-old-recovery/pt35-nfc-bench/nfc/pt35_nfc_gui.py"
MARKER_V1 = "# PT35_PI5_NFC_TAG_INFO_V1"
MARKER_V2 = "# PT35_PI5_NFC_TAG_INFO_V2"
IMPORT_ANCHOR = "from nfc_ndef import decode_message, extract_message, ndef_area\n"
SUMMARY_ANCHOR = "    result.append('Classification: ' + str(record.get('classification', 'unknown')))\n"
SUMMARY_V1 = "    result.extend(describe_nfc_tag(record))\n"
STATUS_ANCHOR = "            self.status.set((comparison.replace('_', ' ') + ' · ' if comparison else '') + coverage(self.newest))\n"
STATUS_V1 = (
    "            tag_info = describe_nfc_tag(self.newest)\n"
    "            heading = tag_info[0] + ' · ' if tag_info else ''\n"
    "            self.status.set(heading + (comparison.replace('_', ' ') + ' · ' if comparison else '') + coverage(self.newest))\n"
)
IMPORT_V1 = (
    "sys.path.insert(0, " + repr(str(Path(__file__).resolve().parents[1] / 'nfc')) + ")\n"
    "from pi5_tag_info import describe as describe_nfc_tag\n"
    + MARKER_V1 + "\n"
)

# This version avoids an unconditional import at GUI startup and isolates
# unexpected capture formats, so optional metadata cannot crash a scan.
IMPORT_V2 = '''
# PT35_PI5_NFC_TAG_INFO_V2
def describe_nfc_tag(record):
    """Optional metadata: never interrupt scanning due to invalid old records."""
    try:
        if not isinstance(record, dict):
            return []
        from pi5_tag_info import describe
        result = describe(record)
        return [str(line) for line in result if isinstance(line, str)] if isinstance(result, (list, tuple)) else []
    except Exception:
        return []
'''

def exactly_once(s, old, new, label):
    count = s.count(old)
    if count != 1:
        raise RuntimeError(f"Expected one {label} location, found {count}; no changes made.")
    return s.replace(old, new, 1)


def main():
    if not TARGET.exists():
        raise RuntimeError(f"Recovered NFC GUI missing: {TARGET}")
    original = TARGET.read_text(encoding="utf-8")
    if MARKER_V2 in original:
        if "sys.path.insert(0, " in original and "from pi5_tag_info import describe" in original:
            raise RuntimeError("Unexpected mixed V1/V2 imports. No changes made.")
        print("NFC tag-info v2 already installed. No changes.")
        return

    source = original
    if MARKER_V1 in source:
        # Remove only our V1 import, retaining any unrelated GUI modifications.
        start = source.find("sys.path.insert(0, ", source.find(IMPORT_ANCHOR))
        end = source.find(MARKER_V1 + "\n", start)
        if start < 0 or end < 0 or source[start:end].count("from pi5_tag_info import describe as describe_nfc_tag") != 1:
            raise RuntimeError("Unexpected tag-info V1 import layout; no changes made.")
        source = source[:start] + source[end + len(MARKER_V1) + 1:]
        source = exactly_once(source, SUMMARY_V1, "", "V1 summary")
        source = exactly_once(source, STATUS_V1, STATUS_ANCHOR, "V1 live status")

    # The original GUI imports sys already. Add a controlled helper path for
    # the regular launcher AND the direct 'python3 pt35_nfc_gui.py' case.
    import_path = repr(str(Path(__file__).resolve().parents[1] / "nfc"))
    # Append, NEVER prepend: nfcv_scan in the recovered Pi4 directory must\n    # win over the unrelated simplified migration copy.\n    block = ("sys.path.append(" + import_path + ")\n" + IMPORT_V2)
    source = exactly_once(source, IMPORT_ANCHOR, IMPORT_ANCHOR + block, "GUI imports")
    source = exactly_once(source, SUMMARY_ANCHOR,
        SUMMARY_V1 + SUMMARY_ANCHOR, "GUI summary")
    source = exactly_once(source, STATUS_ANCHOR,
        STATUS_V1, "GUI live status")
    ast.parse(source, filename=str(TARGET))
    import py_compile
    # Snapshot first, atomically replace only after validation.
    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = TARGET.with_name(TARGET.name + f".pre-tag-info-v2.{timestamp}.bak")
    backup.write_text(original, encoding="utf-8")
    try:
        TARGET.write_text(source, encoding="utf-8")
        py_compile.compile(str(TARGET), doraise=True)
    except Exception:
        TARGET.write_text(original, encoding="utf-8")
        raise
    print("Installed NFC tag-info v2. Previous GUI backed up to:", backup)
    print("No NFC hardware, archive, LED or haptic configuration changed.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        raise SystemExit("NFC GUI repair refused: " + str(exc))
