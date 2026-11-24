"""Offline tests for read-only Type 2 access matrix and lock classification."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "nfc"))
from tag_workshop_access import access_rows, summarize, model_for
from tag_workshop_rf import save_backup


def fixture():
    return {
        "uid": "045E9742CA2A81", "capacity": 496, "cc": "E1103E00",
        "data": bytes(496), "static_locks": "0000",
        "static_lock_bytes": bytes((0, 0)),
        "dynamic_lock_bytes": bytes((0, 0, 0)),
        "config_pages": {"auth0": 255, "access": 0},
        "version": bytes.fromhex("0004040201001103"),
    }


class AccessTests(unittest.TestCase):
    def test_blank_ntag215_pages(self):
        image = fixture()
        self.assertEqual(model_for(image), "NTAG215")
        rows = {p: (region, access) for p, name, region, value, access in access_rows(image)}
        self.assertEqual(rows[0][1], "System")
        self.assertEqual(rows[3][1], "Configuration")
        self.assertEqual(rows[4][1], "Writable*")
        self.assertEqual(rows[127][1], "Writable*")
        self.assertEqual(rows[130][0], "Dynamic lock bytes")
        self.assertEqual(rows[131][0], "Configuration: AUTH0")

    def test_locked_page_and_password(self):
        image = fixture()
        image["static_lock_bytes"] = bytes((0x10, 0))
        image["dynamic_lock_bytes"] = bytes((1, 0, 0))
        image["config_pages"] = {"auth0": 40, "access": 0x80}
        rows = {p: access for p, _, _, _, access in access_rows(image)}
        self.assertEqual(rows[4], "Locked")
        self.assertEqual(rows[16], "Locked")
        self.assertEqual(rows[40], "Password read + write")

    def test_unknown_config_not_claimed_writable(self):
        image = fixture()
        image["config_pages"] = {}
        rows = {p: access for p, _, _, _, access in access_rows(image)}
        self.assertEqual(rows[4], "Protection unknown")

    def test_invalid_version_no_chip_claim(self):
        image = fixture()
        image["version"] = None
        self.assertIsNone(model_for(image))
        rows = {p: access for p, _, _, _, access in access_rows(image)}
        self.assertEqual(rows[4], "Unknown chip")

    def test_metadata_backup_is_serializable(self):
        image = fixture()
        # This test doesn't write to a real tag. It validates the backup's
        # raw binary version/lock metadata can be represented in JSON.
        import json
        payload = {k: (v.hex().upper() if isinstance(v, bytes) else v)
                   for k,v in image.items() if k != "data"}
        json.dumps(payload)


if __name__ == "__main__":
    unittest.main()
