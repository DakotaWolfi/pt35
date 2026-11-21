import unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import nfc_tag

class NdefUrlTests(unittest.TestCase):
    def test_uri_record(self):
        data=nfc_tag.format_ndef("http://192.168.200.7:8767/")
        self.assertEqual(data[0],3)
        self.assertEqual(data[2:4],bytes([0xD1,0x01]))
        self.assertEqual(data[5:7],bytes([0x55,0]))
        self.assertTrue(data.endswith(b"\xfe"))
    def test_reject_admin_https_and_password(self):
        for u in ("https://192.168.200.7/","http://bob:pw@192.168.1.4:8767/"):
            with self.assertRaises(ValueError):
                nfc_tag.format_ndef(u)

if __name__=="__main__":unittest.main()
