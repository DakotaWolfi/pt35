import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from mailbox_protocol import pack,unpack
import mailbox_host

class MailboxProtocolTests(unittest.TestCase):
    def test_status_roundtrip(self):
        data=pack("status","12ab56ff")
        self.assertEqual(unpack(data)["t"],"status")

    def test_print_roundtrip(self):
        req=pack("print","00aabbcc",name="PT35",message="AWOO",code="123456")
        self.assertEqual(unpack(req)["message"],"AWOO")

    def test_code_required(self):
        with self.assertRaises(ValueError):
            unpack(pack("print","00aabbcc",name="PT35",message="AWOO"))

    def test_size_limit(self):
        with self.assertRaises(ValueError):
            pack("reply","00aabbcc",message="X"*256)

    @patch("mailbox_host.http_json")
    def test_print_requires_challenge_enabled(self, http):
        http.return_value={"challenge_enabled":False}
        resp=mailbox_host.process(pack("print","00aabbcc",name="PT35",
                                     message="AWOO",code="123456"),"http://127.0.0.1:8767")
        self.assertFalse(unpack(resp)["ok"])
        self.assertEqual(http.call_count,1)

    @patch("mailbox_host.http_json")
    def test_nfc_print_is_not_direct_raw_printer(self,http):
        http.side_effect=[{"challenge_enabled":True},{"message":"Queued"}]
        response=mailbox_host.process(pack("print","00aabbcc",name="PT35",
                                          message="AWOO",code="123456"),
                                       "http://127.0.0.1:8767")
        self.assertTrue(unpack(response)["ok"])
        request=http.call_args.args[1]
        self.assertEqual(request["challenge_code"],"123456")
        self.assertEqual(request["message"],"AWOO")

if __name__=="__main__":
    unittest.main()
