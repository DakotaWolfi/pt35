"""Offline decisions for automated NFC Type 2 copying."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "nfc"))
from tag_workshop_batch import image_for, is_empty, destination_decision
from tag_workshop_ndef import tlv


def tag(uid, data):
    return {"uid": uid, "capacity": len(data), "data": data}


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.source = tag("SOURCE", tlv("Text", "PT35", 496))
        self.empty = tag("DEST", bytes(496))

    def test_empty_only_writes_blank(self):
        what, data = destination_decision(self.source, self.empty, "ndef", "empty", set())
        self.assertEqual(what, "write")
        self.assertEqual(data, self.source["data"])

    def test_empty_only_refuses_existing_data(self):
        dest = tag("DEST", tlv("URL", "https://example.org", 496))
        self.assertEqual(destination_decision(
            self.source, dest, "ndef", "empty", set())[0], "skip")

    def test_overwrite_allows_existing_data(self):
        dest = tag("DEST", tlv("URL", "https://example.org", 496))
        self.assertEqual(destination_decision(
            self.source, dest, "ndef", "overwrite", set())[0], "write")

    def test_skip_original_source(self):
        self.assertEqual(destination_decision(
            self.source, tag("SOURCE", bytes(496)), "raw", "overwrite", set())[0], "skip")

    def test_skip_uid_already_written(self):
        self.assertEqual(destination_decision(
            self.source, self.empty, "raw", "overwrite", {"DEST"})[0], "skip")

    def test_ndef_can_fit_smaller_destination(self):
        short = tag("DEST", bytes(144))
        self.assertEqual(len(image_for(self.source, short, "ndef")), 144)

    def test_raw_requires_equal_capacity(self):
        with self.assertRaises(ValueError):
            image_for(self.source, tag("DEST", bytes(144)), "raw")

    def test_unrecognized_data_is_not_empty(self):
        self.assertFalse(is_empty(b"\xFD\x04" + bytes(494)))

    def test_known_empty_ndef(self):
        self.assertTrue(is_empty(tlv("Empty", "", 496)))

    def test_data_already_matches(self):
        self.assertEqual(destination_decision(
            self.source, tag("DEST", self.source["data"]), "raw", "overwrite", set())[0], "same")


if __name__ == "__main__":
    unittest.main()
