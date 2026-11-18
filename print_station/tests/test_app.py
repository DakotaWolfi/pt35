import json
import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app

class TestPrintStation(unittest.TestCase):
    def test_admin_cookie_expires_and_rejects_tampering(self):
        token=app.make_admin_session("test-secret",now=1000)
        self.assertTrue(app.valid_admin_session("test-secret",token,now=1001))
        self.assertFalse(app.valid_admin_session("test-secret",token,now=1001+app.ADMIN_SESSION_SECONDS))
        self.assertFalse(app.valid_admin_session("wrong-secret",token,now=1001))
        self.assertFalse(app.valid_admin_session("test-secret",token[:-1]+"0",now=1001))

    def test_interrupted_printer_stream_blocks_following_jobs(self):
        from unittest.mock import patch, Mock
        with tempfile.TemporaryDirectory() as folder:
            marker=Path(folder)/"printer-recovery-required"
            conf={**app.DEFAULT,"dry_run":False,"logo_enabled":False,"cut":False}
            socket_connection=Mock()
            socket_connection.__enter__=Mock(return_value=socket_connection)
            socket_connection.__exit__=Mock(return_value=False)
            socket_connection.sendall.side_effect=OSError("Printer disconnected during bitmap")
            with patch.object(app,"PRINTER_RECOVERY_PATH",marker), patch.object(app,"printer_destination",return_value=("10.88.77.30",9100)), patch.object(app.socket,"create_connection",return_value=socket_connection):
                with self.assertRaises(OSError):
                    app.send_printer(b"receipt",conf)
                self.assertTrue(marker.exists())
                with self.assertRaises(RuntimeError):
                    app.send_printer(b"next receipt",conf)
                app.clear_printer_uncertain()
                socket_connection.sendall.side_effect=None
                app.send_printer(b"after printer reset",conf)
                self.assertFalse(marker.exists())

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

    def test_custom_fine_layout(self):
        result=app.make_ticket(
            "Wolf", "Excessive cuddling", app.DEFAULT,
            {"custom_fine":True, "fine_title":"FLUFF VIOLATION",
             "fine_status":"PENDING CUDDLES", "offence":"Excessive cuddling",
             "amount":"CHF 35.00"},
            ticket_id=12, issued_at="2026-11-17T11:00:00+01:00").decode("ascii")
        self.assertIn("FLUFF VIOLATION",result)
        self.assertIn("Status: PENDING CUDDLES",result)
        self.assertIn("Ticket 00012",result)
        self.assertIn("NO LEGAL FORCE",result)
        self.assertNotIn("AWOO FINE\\n",result)

    def test_esc_pos_safety(self):
        b=app.make_ticket("Wolf\x1b", "AWOO!",app.DEFAULT)
        self.assertNotIn(bytes([27]),b)
        self.assertIn(b"AWOO!",b)

if __name__ == "__main__":
    unittest.main()
