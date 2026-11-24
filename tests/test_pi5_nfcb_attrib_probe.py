"""Offline checks for PT35 NFC-B ATTRIB request/response formatting."""
import importlib.util
import unittest
from pathlib import Path

path = Path(__file__).resolve().parents[1] / "tools/pi5_nfcb_attrib_probe.py"
spec = importlib.util.spec_from_file_location("pi5_nfcb_attrib_probe", path)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class AttribTests(unittest.TestCase):
    def test_known_pupi(self):
        self.assertEqual(
            probe.attrib_command(bytes.fromhex("065B5786")).hex().upper(),
            "1D065B578600050100",
        )

    def test_reject_wrong_pupi_length(self):
        with self.assertRaises(ValueError):
            probe.attrib_command(bytes.fromhex("065B57"))

    def test_response_mblication_and_cid(self):
        self.assertEqual(
            probe.parse_attrib_reply(bytes.fromhex("200102")),
            {"mbli": 2, "cid": 0, "higher_layer_response": "0102"},
        )

    def test_empty_response_rejected(self):
        with self.assertRaises(ValueError):
            probe.parse_attrib_reply(b"")


if __name__ == "__main__":
    unittest.main()
