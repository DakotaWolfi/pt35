import unittest
from unittest.mock import patch, Mock
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app

RESULT = """=;enx9cebe8ec46e1;IPv4;EPSON TM-T88VI (79EB5F);_printer._tcp;local;Printer-79EB5F.local;169.254.235.98;515;\"product=(EPSON TM-T88VI)\"
=;wlan0;IPv4;EPSON TM-T88VI (79EB5F);_printer._tcp;local;Printer-79EB5F.local;192.168.200.55;515;
=;enx9cebe8ec46e1;IPv4;other;_printer._tcp;local;wrong.local;169.254.235.20;515;
"""

class DiscoveryTests(unittest.TestCase):
    def test_pins_to_epson_and_ethernet(self):
        self.assertEqual(app.printer_mdns_candidates(RESULT, "Printer-79EB5F.local", "enx9cebe8ec46e1"), ["169.254.235.98"])
    def test_wrong_interface_or_name_is_rejected(self):
        self.assertEqual(app.printer_mdns_candidates(RESULT, "not-this-printer.local", "enx9cebe8ec46e1"), [])
    @patch("app.subprocess.run")
    def test_no_fallback_to_stale_ip(self, run):
        run.return_value=Mock(stdout="",returncode=0)
        conf=dict(app.DEFAULT, printer_host="169.254.235.95",printer_mdns_name="Printer-79EB5F.local",printer_interface="enx9cebe8ec46e1")
        with self.assertRaises(RuntimeError):
            app.printer_destination(conf)
    @patch("app.subprocess.run")
    def test_resolves_changed_ip(self, run):
        run.return_value=Mock(stdout=RESULT,returncode=0)
        conf=dict(app.DEFAULT, printer_mdns_name="Printer-79EB5F.local",printer_interface="enx9cebe8ec46e1")
        self.assertEqual(app.printer_destination(conf),("169.254.235.98",9100))

if __name__=="__main__": unittest.main()
