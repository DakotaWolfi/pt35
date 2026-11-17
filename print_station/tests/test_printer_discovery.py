import unittest
from unittest.mock import patch, Mock
from tempfile import TemporaryDirectory
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app

RESULT = """=;enx9cebe8ec46e1;IPv4;EPSON TM-T88VI (79EB5F);_printer._tcp;local;Printer-79EB5F.local;169.254.235.98;515;\"product=(EPSON TM-T88VI)\"
=;wlan0;IPv4;EPSON TM-T88VI (79EB5F);_printer._tcp;local;Printer-79EB5F.local;192.168.200.55;515;
=;enx9cebe8ec46e1;IPv4;other;_printer._tcp;local;wrong.local;169.254.235.20;515;
"""

class DiscoveryTests(unittest.TestCase):
    def test_dnsmasq_lease_pinned_by_mac_and_subnet(self):
        with TemporaryDirectory() as temp:
            lease=Path(temp)/"dnsmasq.leases"
            lease.write_text("0 aa:bb:cc:dd:ee:ff 10.88.77.21 Other *\n"
                             "0 f8:25:51:79:eb:5f 192.168.200.99 Bad *\n"
                             "0 f8:25:51:79:eb:5f 10.88.77.39 Epson *\n")
            self.assertEqual(app.printer_dhcp_address((lease,)),"10.88.77.39")
            lease.write_text("0 f8:25:51:79:eb:5f 192.168.200.99 Epson *\n")
            self.assertIsNone(app.printer_dhcp_address((lease,)))

    @patch("app.printer_dhcp_address",return_value="10.88.77.39")
    def test_dhcp_lease_overrides_stale_config_and_mdns(self, resolver):
        conf=dict(app.DEFAULT,printer_host="169.254.235.95",
                  printer_mdns_name="Printer-79EB5F.local",
                  printer_interface="enx9cebe8ec46e1")
        self.assertEqual(app.printer_destination(conf),("10.88.77.39",9100))

    def test_select_other_printer_mac(self):
        with TemporaryDirectory() as temp:
            lease=Path(temp)/"dnsmasq.leases"
            lease.write_text("0 f8:25:51:79:eb:5f 10.88.77.30 Epson *\n"
                             "0 64:eb:8c:f9:68:0a 10.88.77.36 Printer-7B0000 *\n")
            self.assertEqual(app.printer_dhcp_address((lease,), expected_mac="64:eb:8c:f9:68:0a"),"10.88.77.36")

    def test_pins_to_epson_and_ethernet(self):
        self.assertEqual(app.printer_mdns_candidates(RESULT, "Printer-79EB5F.local", "enx9cebe8ec46e1"), ["169.254.235.98"])
    def test_wrong_interface_or_name_is_rejected(self):
        self.assertEqual(app.printer_mdns_candidates(RESULT, "not-this-printer.local", "enx9cebe8ec46e1"), [])
    @patch("app.printer_dhcp_address",return_value=None)
    @patch("app.subprocess.run")
    def test_managed_dhcp_ip_preferred_when_two_are_advertised(self, run, lease):
        run.return_value=Mock(stdout=RESULT + "=;enx9cebe8ec46e1;IPv4;EPSON;_printer._tcp;local;Printer-79EB5F.local;10.88.77.20;515;\n",returncode=0)
        conf=dict(app.DEFAULT,printer_mdns_name="Printer-79EB5F.local",printer_interface="enx9cebe8ec46e1")
        self.assertEqual(app.printer_destination(conf),("10.88.77.20",9100))

    @patch("app.printer_dhcp_address",return_value=None)
    @patch("app.subprocess.run")
    def test_no_fallback_to_stale_ip(self, run, lease):
        run.return_value=Mock(stdout="",returncode=0)
        conf=dict(app.DEFAULT, printer_host="169.254.235.95",printer_mdns_name="Printer-79EB5F.local",printer_interface="enx9cebe8ec46e1")
        with self.assertRaises(RuntimeError):
            app.printer_destination(conf)
    @patch("app.printer_dhcp_address",return_value=None)
    @patch("app.subprocess.run")
    def test_resolves_changed_ip(self, run, lease):
        run.return_value=Mock(stdout=RESULT,returncode=0)
        conf=dict(app.DEFAULT, printer_mdns_name="Printer-79EB5F.local",printer_interface="enx9cebe8ec46e1")
        self.assertEqual(app.printer_destination(conf),("169.254.235.98",9100))

if __name__=="__main__": unittest.main()
