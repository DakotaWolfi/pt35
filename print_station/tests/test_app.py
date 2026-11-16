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
    def test_esc_pos_safety(self):
        b=app.make_ticket("Wolf\x1b", "AWOO!",app.DEFAULT)
        self.assertNotIn(bytes([27]),b)
        self.assertIn(b"AWOO!",b)

if __name__ == "__main__":
    unittest.main()
