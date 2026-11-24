"""Offline tests for exact-capacity Type 2 memory transfer and archive images."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "nfc"))
from tag_workshop_raw import transfer_plan, checked_image
from tag_workshop_library import load_archive_raw


class RawTransferTests(unittest.TestCase):
    def test_copy_opaque_bytes_without_ndef(self):
        old = bytes(496)
        data = b"\xFD\x06\xDE\xAD\xBE\xEF" + bytes(490)
        pages = transfer_plan(old, data)
        self.assertEqual(pages[0], (4, data[:4]))
        self.assertEqual(pages[1], (5, data[4:8]))
        self.assertTrue(all(4 <= page < 128 for page, _ in pages))

    def test_wrong_capacity_refused(self):
        with self.assertRaises(ValueError):
            transfer_plan(bytes(144), bytes(496))

    def test_exact_copy_no_writes(self):
        data = bytes(range(144))
        self.assertEqual(transfer_plan(data, data), [])

    def test_non_bytes_refused(self):
        with self.assertRaises(ValueError):
            checked_image("NOT A BYTE IMAGE", 144)

    def test_archive_full_verified_type2(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "NFC-A-530B82D0330001"
            folder.mkdir()
            data = b"\xFD\x06\xDE\xAD\xBE\xEF" + bytes(490)
            record = {
                "protocol": "NFC-A", "uid": "530B82D0330001",
                "cc": "E1103E00",
                "capture_format": 2, "requested_range_complete": True,
                "requested_range": {"start": 4, "count": 124},
                "geometry": {"start": 4, "blocks": 124, "size": 4},
                "read_errors": [],
                "blocks": [{"index": 4+i, "hex": data[i*4:i*4+4].hex().upper()}
                           for i in range(124)]
            }
            p = folder / "record.json"
            p.write_text(json.dumps(record))
            image = load_archive_raw(p, tmp)
            self.assertEqual(image["capacity"], 496)
            self.assertEqual(image["data"], data)
            self.assertEqual(image["uid"], "530B82D0330001")

    def test_partial_archive_not_importable(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "NFC-A-BADF00D"
            folder.mkdir()
            p = folder / "record.json"
            p.write_text(json.dumps({"protocol": "NFC-A", "cc": "E1103E00",
                                     "capture_format": 2, "requested_range_complete": False,
                                     "requested_range": {"start": 4, "count": 124},
                                     "blocks": []}))
            with self.assertRaises(ValueError):
                load_archive_raw(p, tmp)


if __name__ == "__main__":
    unittest.main()
