import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "nfc"))
from tag_workshop_ndef import message, tlv, parse, plan


class WorkshopNDEFTests(unittest.TestCase):
    def test_text_roundtrip(self):
        area = tlv("Text", "Hello from PT35", 144)
        self.assertEqual(parse(area), ("Text", "Hello from PT35"))
        self.assertEqual(area[0], 3)

    def test_url_roundtrip(self):
        area = tlv("URL", "https://www.example.org/hello", 144)
        self.assertEqual(parse(area), ("URL", "https://www.example.org/hello"))

    def test_empty_format(self):
        self.assertEqual(parse(tlv("Empty", "", 144)), ("Empty", ""))

    def test_plan_never_touches_uid_lock_or_cc(self):
        before = tlv("Text", "Before", 144)
        changes = plan(before, "Text", "After")
        self.assertTrue(changes)
        self.assertTrue(all(4 <= page <= 39 and len(data) == 4
                            for page, data in changes))

    def test_unrecognized_tlv_is_not_erased(self):
        with self.assertRaises(ValueError):
            plan(b"\xFD\x00" + bytes(142), "Text", "Nope")

    def test_excess_data_refused(self):
        with self.assertRaises(ValueError):
            tlv("Text", "A" * 144, 144)

    def test_496_byte_ntag215_blank_and_text(self):
        area = bytes(496)
        self.assertEqual(parse(area), ("Empty", ""))
        changes = plan(area, "Text", "Hello from PT35")
        self.assertTrue(changes)
        self.assertTrue(all(4 <= page <= 127 for page, _ in changes))
        self.assertEqual(parse(tlv("Text", "Hello from PT35", 496)),
                         ("Text", "Hello from PT35"))

    def test_496_byte_long_ndef_extended_tlv(self):
        content = "X" * 300
        data = tlv("Text", content, 496)
        self.assertEqual(data[0:2], bytes((3, 255)))
        self.assertEqual(parse(data), ("Text", content))

    def test_872_byte_ntag216_area(self):
        data = tlv("URL", "https://example.org", 872)
        self.assertEqual(len(data), 872)
        self.assertEqual(parse(data), ("URL", "https://example.org"))

    def test_unknown_protocol_refused(self):
        with self.assertRaises(ValueError):
            message("Raw", "00")


if __name__ == "__main__":
    unittest.main()
