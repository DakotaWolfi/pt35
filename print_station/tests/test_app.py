import json
import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app

class TestPrintStation(unittest.TestCase):
    def test_config_default(self):
        with tempfile.TemporaryDirectory() as d:
            c=app.load_config(Path(d)/"missing.json")
            self.assertEqual(c["access_mode"],"local")
            self.assertTrue(c["dry_run"])
    def test_public_requires_https(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"test.json"
            path.write_text(json.dumps({"access_mode":"public","public_base_url":"http://example.test/print"}))
            with self.assertRaises(ValueError):
                app.load_config(path)
    def test_network_modes(self):
        c=app.DEFAULT.copy()
        self.assertTrue(app.allowed("192.168.1.42",c))
        self.assertFalse(app.allowed("8.8.8.8",c))
        c["access_mode"]="both"
        self.assertTrue(app.allowed("8.8.8.8",c))
    def test_detailed_fine_layout(self):
        result=app.make_ticket("Philipp", "Being suspiciously fluffy", app.DEFAULT,
            {"issuer":"Jenna","location":"FMI Labs","offence":"Being suspiciously fluffy",
             "amount":"CHF 350.00"},
            ticket_id=3, issued_at="2026-11-17T09:00:00+01:00").decode("ascii")
        self.assertIn("AWOO FINE",result)
        self.assertIn("Ticket 00003",result)
        self.assertIn("Issued: 2026-11-17T09:00:00+01:00",result)
        self.assertIn("Offender: Philipp",result)
        self.assertIn("FINE: CHF 350.00",result)
        self.assertIn("Status: UNPAID",result)
        self.assertIn("NO LEGAL FORCE",result)

    def test_esc_pos_safety(self):
        b=app.make_ticket("Wolf\x1b", "AWOO!",app.DEFAULT)
        self.assertNotIn(bytes([27]),b)
        self.assertIn(b"AWOO!",b)

if __name__ == "__main__":
    unittest.main()
