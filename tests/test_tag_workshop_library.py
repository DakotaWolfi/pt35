"""Offline coverage for presets and archive import; no NFC hardware required."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "nfc"))
from tag_workshop_ndef import tlv
from tag_workshop_library import (
    save_preset, list_presets, load_preset, list_archive, archive_entry,
    load_archive_ndef,
)


class TagWorkshopLibraryTests(unittest.TestCase):
    def test_save_load_without_tag(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            p = save_preset("hello test", "Text", "Hello! 🐺", root)
            self.assertEqual(list_presets(root), [p])
            self.assertEqual(load_preset(p, root), ("Text", "Hello! 🐺"))
            with self.assertRaises(FileExistsError):
                save_preset("hello test", "Text", "Don't overwrite", root)

    def test_url_template(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = save_preset("link", "URL", "https://example.org", tmp)
            self.assertEqual(load_preset(p, tmp), ("URL", "https://example.org"))

    def test_template_path_cannot_escape_library(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                load_preset(Path(tmp) / "../other.json", tmp)

    def test_import_verified_nfc_a(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp)
            folder = archive / "NFC-A-530B82D0330001"
            folder.mkdir()
            data = tlv("Text", "Saved text", 144)
            record = {
                "protocol": "NFC-A", "uid": "530B82D0330001",
                "dump_status": "addressable_memory_complete",
                "capture_format": 2, "requested_range_complete": True,
                "requested_range": {"start": 4, "count": 36},
                "geometry": {"start": 4, "blocks": 36, "size": 4},
                "cc": "E1101200", "read_errors": [],
                "blocks": [{"index": 4 + i, "size": 4,
                            "hex": data[i*4:(i+1)*4].hex().upper()}
                           for i in range(36)]
            }
            p = folder / "record.json"
            p.write_text(json.dumps(record))
            self.assertEqual(list_archive(archive), [p])
            self.assertIn("530B82D0330001", archive_entry(p))
            self.assertEqual(load_archive_ndef(p, archive), ("Text", "Saved text"))

    def test_refuse_discovery_only_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp)
            folder = archive / "NFC-B-065B5786"
            folder.mkdir()
            p = folder / "record.json"
            p.write_text(json.dumps({"protocol": "NFC-B", "uid": "065B5786",
                                     "dump_status": "not_requested", "blocks": []}))
            with self.assertRaises(ValueError):
                load_archive_ndef(p, archive)

    def test_refuse_partial_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp)
            folder = archive / "NFC-A-11111111"
            folder.mkdir()
            p = folder / "record.json"
            p.write_text(json.dumps({
                "protocol": "NFC-A", "uid": "11111111", "cc": "E1101200",
                "capture_format": 2, "requested_range_complete": False,
                "requested_range": {"start": 4, "count": 36},
                "blocks": [{"index": 4, "hex": "0300FE00"}]}))
            with self.assertRaises(ValueError):
                load_archive_ndef(p, archive)


if __name__ == "__main__":
    unittest.main()
